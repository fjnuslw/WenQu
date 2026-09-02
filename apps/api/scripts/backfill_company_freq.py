"""面经频率榜事实校准（F7 二期 · 第二梯队）。

背景：question_companies.freq 此前全部是 LLM 推断值（source='ai'），F2 验收要求
「频率榜数据可追溯到面经条目」。面经问题 ↔ 题库题干的精确匹配只有 0.9%
（口语化 vs 规范题干），题→题直接匹配不可行，故走**词级双向匹配**：

    面经条目文本 --提取--> 词集 W(item)
    题库题干     --提取--> 词集 W(q)（倒排索引）
    若 W(item) ∩ W(q) ≠ ∅ 且 IDF 加权覆盖度 ≥ 阈值 → 落 evidence（可追溯到条目）
    → 聚合 (公司, 题) 的独立条目数 → 回灌 question_companies.freq

**为什么必须是双向匹配**（2026-09-01 验收修正）：
初版走「标签级代理」——面经命中标签即关联该标签下**全部**题，实测导致
company_id=3 下 1293 道题共享 freq=2，且「卷积操作参数」的证据是
「二叉树层序遍历」（同属“算法”标签）——数字看似精确实为摊薄的假象，
比 AI 推断值更误导。双向匹配要求**题干本身包含同一个词**才关联：
「二叉树层序遍历」→ 12 道二叉树题（而非 429 道算法题）。

口径（写死，防拍脑袋漂移）：
- 只统计有公司归属的面经条目（3150/5745）；
- score = Σ idf(交集词) / Σ idf(面经条目词集)，仅 ≥ MIN_SCORE 的关联落库；
- freq(C,q) = 公司 C 面经中与题 q 关联的独立条目数（evidence 按 experience_item
  去重，同一场追问多轮只记一次）；
- 合并：freq = max(已有 freq, 实证条目数)；有实证时 source='experience'，
  无实证保持 source='ai'（实证不被推断值覆盖，推断兜底不丢）；
- 幂等：evidence 唯一约束 (question_id, experience_item_id)，重复执行不翻倍。

用法（apps/api 目录）：
    python scripts/backfill_company_freq.py                  # dry-run 预览
    python scripts/backfill_company_freq.py --apply           # 写库
    python scripts/backfill_company_freq.py --reset --apply   # 清空旧证据并重置 freq=1（换算法时用）
"""

from __future__ import annotations

import argparse
import asyncio
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

from sqlalchemy import func, select, text

API_SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(API_SRC))

from sqlalchemy.dialects.postgresql import insert as pg_insert  # noqa: E402

from getoffer.config import load_settings  # noqa: E402
from getoffer.db import make_engine, make_sessionmaker  # noqa: E402
from getoffer.ingest.tag_vocab import CANONICAL_TAGS  # noqa: E402
from getoffer.models import (  # noqa: E402
    Company,
    Experience,
    ExperienceItem,
    Question,
    QuestionCompany,
    QuestionCompanyEvidence,
    QuestionTag,
    Tag,
)

# 低于此覆盖度的关联视为噪音（单词命中但词很宽泛时不采信）
MIN_SCORE = 0.30
# 关联扇出门槛：交集中「最窄的那个词」若仍对应超过这么多题，说明整组都太宽泛，
# 关联了也只会在几百道题上刷同一个 +1（摊薄），不予采信。
WIDE_FANOUT = 150

# 面经高频术语：题库标签体系之外的细粒度词，双向匹配下词越多召回越好
# （不再有摊薄风险，因为要求题干本身也含该词）
TECH_TERMS = [
    "kv cache",
    "flash attention",
    "pagedattention",
    "vllm",
    "deepspeed",
    "rope",
    "gqa",
    "mha",
    "多头注意力",
    "注意力机制",
    "自注意力",
    "softmax",
    "mlp",
    "layer norm",
    "残差连接",
    "位置编码",
    "归一化",
    "微调",
    "lora",
    "qlora",
    "预训练",
    "sft",
    "dpo",
    "grpo",
    "ppo",
    "rlhf",
    "dapo",
    "simpo",
    "rloo",
    "rlvr",
    "对齐",
    "奖励模型",
    "量化",
    "蒸馏",
    "剪枝",
    "稀疏",
    "instructgpt",
    "思维链",
    "cot",
    "function calling",
    "function call",
    "工具调用",
    "langchain",
    "langgraph",
    "llamaindex",
    "mcp",
    "prompt",
    " hallucination",
    "幻觉",
    "embedding",
    "向量检索",
    "召回",
    "重排",
    "rerank",
    "切分",
    "chunk",
    "动态规划",
    "二分",
    "滑动窗口",
    "回溯",
    "并查集",
    "堆",
    "链表",
    "红黑树",
    "二叉树",
    "层序",
    "bfs",
    "dfs",
    "贪心",
    "排序算法",
    "哈希表",
    "栈与队列",
    "拓扑排序",
    "最短路径",
    "岛屿",
    "lru",
    "快排",
    "卷积",
    "池化",
    "感受野",
    "cnn",
    "rnn",
    "lstm",
    "bert",
    "gpt",
    "过拟合",
    "dropout",
    "batchnorm",
    "学习率",
    "优化器",
    "adam",
    "梯度消失",
    "梯度",
    "loss",
    "正则",
    "auc",
    "f1",
    "准确率",
    "召回率",
    "cuda",
    "分布式训练",
    "数据并行",
    "张量并行",
    "流水线并行",
    "显存",
    "batch",
    "epoch",
    "过采样",
    "数据增强",
    "sql",
    "索引",
    "事务",
    "redis",
    "缓存",
    "消息队列",
    "kafka",
    "http",
    "tcp",
    "进程",
    "线程",
    "协程",
    "锁",
    "并发",
    "git",
    "docker",
    "k8s",
    "kubernetes",
    "ci",
    "监控",
    "日志",
]

# 通用工程词：在题干与面经里都高频出现，但「同时提到」不代表同一考点
# （如「并发」会让「Agent 线程安全」关联到「asyncio 高并发」，score 0.5 的弱相关）。
# 撤掉它们会损失一些召回，但符合宁缺毋滥——频率榜宁可少标，不可错标。
STOPWORDS = {
    "并发",
    "线程",
    "进程",
    "协程",
    "锁",
    "调度",
    "异步",
    "同步",
    "阻塞",
    "优化",
    "设计",
    "实现",
    "方案",
    "方法",
    "技术",
    "使用",
    "处理",
    "支持",
    "问题",
    "场景",
    "性能",
    "架构",
    "系统",
    "服务",
    "部署",
    "监控",
    "日志",
    "测试",
    "上线",
    "成本",
    "效率",
    "优势",
    "区别",
    "原理",
    "流程",
    "步骤",
    "基础",
    "应用",
    "数据",
    "模型",
    "训练",
    "推理",
    "接口",
    "请求",
    "响应",
    "参数",
    "配置",
    "工具",
    "框架",
    "平台",
    "业务",
    "需求",
    "效果",
    "评估",
}


def build_word_index(
    vocabulary: list[str],
    stems: list[tuple[int, str]],
) -> tuple[dict[str, set[int]], dict[int, set[str]], dict[str, float]]:
    """词 → 题 id 倒排索引；题 id → 词集；词 → IDF。

    IDF = log(N / df)：含该词的题越多（如 agent 556 题）权重越低，
    窄词（如 kv cache 91 题）权重越高——让「具体到考点」的关联胜出。
    """
    total = max(len(stems), 1)
    index: dict[str, set[int]] = defaultdict(set)
    q_words: dict[int, set[str]] = defaultdict(set)

    for qid, stem in stems:
        low = (stem or "").lower()
        for word in vocabulary:
            if word in low:
                index[word].add(qid)
                q_words[qid].add(word)

    # 空词的题不进索引（没有任何区分信息）
    idf = {word: math.log(total / max(len(qids), 1)) for word, qids in index.items()}
    return dict(index), {q: ws for q, ws in q_words.items() if ws}, idf


def extract_words(text: str, vocabulary: list[str]) -> set[str]:
    return {word for word in vocabulary if word in (text or "").lower()}


async def load_vocabulary(session) -> list[str]:
    """词表 = 题库标签（canonical）+ 技术术语；只保留题库里真能命中的词。"""
    rows = (
        await session.execute(
            select(Tag.name, func.count(QuestionTag.question_id))
            .join(QuestionTag, QuestionTag.tag_id == Tag.id)
            .group_by(Tag.name)
        )
    ).all()
    tag_names = [name for name, _ in rows]
    vocab = list(CANONICAL_TAGS) + [t for t in tag_names if t not in CANONICAL_TAGS]
    vocab += [t for t in TECH_TERMS if t not in vocab]
    lowered = [v.lower() for v in vocab]
    kept = [w for w in lowered if w not in STOPWORDS]
    print(f"词表 {len(lowered)} 词，剔除通用词 {len(lowered) - len(kept)} 个后剩 {len(kept)} 词")
    return kept


async def dry_run(session, vocab: list[str]) -> None:
    stems = (await session.execute(select(Question.id, Question.stem))).all()
    stems = [(qid, stem) for qid, stem in stems]
    _index, q_words, idf = build_word_index(vocab, stems)
    df = {word: len(qids) for word, qids in _index.items()}

    rows = (
        await session.execute(
            select(
                Experience.id,
                ExperienceItem.id,
                Company.id,
                Company.name,
                ExperienceItem.question_text,
            )
            .join(Experience, Experience.id == ExperienceItem.experience_id)
            .join(Company, Company.id == Experience.company_id)
        )
    ).all()

    matched = 0
    no_match = 0
    evidence_total = 0
    score_hist: Counter[str] = Counter()
    pairs: set[tuple[int, int]] = set()
    samples: list[tuple[str, str, float, str]] = []

    for _exp_id, _item_id, cid, _cname, item_text in rows:
        words = extract_words(item_text, vocab)
        if not words:
            no_match += 1
            continue
        idf_sum = sum(idf.get(w, 0.0) for w in words) or 1.0
        # 候选题：任一命中词倒排出的题
        candidates: set[int] = set()
        for w in words:
            candidates.update(_index.get(w, set()))
        kept = 0
        for qid in candidates:
            common = words & q_words.get(qid, set())
            if not common:
                continue
            # 扇出门槛：最窄的共现词都超过阈值 → 整组太宽泛，关联等于摊薄
            if min(df.get(w, 0) for w in common) > WIDE_FANOUT:
                continue
            score = sum(idf.get(w, 0.0) for w in common) / idf_sum
            if score < MIN_SCORE:
                continue
            kept += 1
            pairs.add((cid, qid))
            bucket = "1.0" if score >= 0.999 else ("0.6-1.0" if score >= 0.6 else "0.3-0.6")
            score_hist[bucket] += 1
            if len(samples) < 6 and score >= 0.9:
                stem = next((s for q, s in stems if q == qid), "")
                samples.append((item_text, stem, round(score, 2), w_display(common)))
        if kept:
            matched += 1
        else:
            no_match += 1
        evidence_total += kept

    print(f"挂公司面经条目 {len(rows)}；词表 {len(vocab)} 词（题库命中 {len(_index)} 词）")
    print(f"产生关联 {matched} 条 / 无关联 {no_match} 条（宁缺毋滥）")
    print(f"证据行 ≈ {evidence_total:,}，覆盖 (公司,题) 对 {len(pairs):,}")
    print(f"score 分布: {dict(score_hist)}")
    print("\n高置信样本（面经 → 题）：")
    for item_text, stem, score, common in samples:
        print(f"   [{score}] {item_text[:38]}")
        print(f"           → {stem[:44]}   (共现词: {common})")


def w_display(words: set[str]) -> str:
    return ",".join(sorted(words)[:3])


async def apply(session, vocab: list[str], reset: bool) -> dict:
    stems = (await session.execute(select(Question.id, Question.stem))).all()
    stems = [(qid, stem) for qid, stem in stems]
    index, q_words, idf = build_word_index(vocab, stems)
    df = {word: len(qids) for word, qids in index.items()}

    if reset:
        # 换算法后旧证据与旧 freq 都不可信：清空重来
        await session.execute(text("DELETE FROM question_company_evidence"))
        await session.execute(
            text("UPDATE question_companies SET freq = 1, source = 'ai' WHERE source = 'experience'")
        )
        await session.commit()
        print("[reset] 已清空 evidence 表，并把 source=experience 的行重置为 freq=1 / source=ai")

    rows = (
        await session.execute(
            select(
                Experience.id,
                ExperienceItem.id,
                Company.id,
                ExperienceItem.question_text,
            )
            .join(Experience, Experience.id == ExperienceItem.experience_id)
            .join(Company, Company.id == Experience.company_id)
        )
    ).all()

    evidence: list[dict] = []
    seen: set[tuple[int, int]] = set()
    for exp_id, item_id, cid, item_text in rows:
        words = extract_words(item_text, vocab)
        if not words:
            continue
        idf_sum = sum(idf.get(w, 0.0) for w in words) or 1.0
        candidates: set[int] = set()
        for w in words:
            candidates.update(index.get(w, set()))
        for qid in candidates:
            common = words & q_words.get(qid, set())
            if not common:
                continue
            if min(df.get(w, 0) for w in common) > WIDE_FANOUT:
                continue
            score = sum(idf.get(w, 0.0) for w in common) / idf_sum
            if score < MIN_SCORE:
                continue
            key = (qid, item_id)
            if key in seen:
                continue
            seen.add(key)
            evidence.append(
                {
                    "question_id": qid,
                    "company_id": cid,
                    "experience_id": exp_id,
                    "experience_item_id": item_id,
                    "score": round(min(score, 1.0), 4),
                }
            )

    for i in range(0, len(evidence), 1000):
        chunk = evidence[i : i + 1000]
        stmt = (
            pg_insert(QuestionCompanyEvidence)
            .values(chunk)
            .on_conflict_do_nothing(index_elements=["question_id", "experience_item_id"])
        )
        await session.execute(stmt)
    await session.commit()

    agg = (
        await session.execute(
            select(
                QuestionCompanyEvidence.question_id,
                QuestionCompanyEvidence.company_id,
                func.count(func.distinct(QuestionCompanyEvidence.experience_item_id)),
            ).group_by(
                QuestionCompanyEvidence.question_id,
                QuestionCompanyEvidence.company_id,
            )
        )
    ).all()
    freq_map: dict[tuple[int, int], int] = {(q, c): n for q, c, n in agg}

    existing = (await session.scalars(select(QuestionCompany))).all()
    updated, inserted, kept = 0, 0, 0
    seen_qc: set[tuple[int, int]] = set()
    for qc in existing:
        key = (qc.question_id, qc.company_id)
        if key not in freq_map:
            continue
        seen_qc.add(key)
        n = freq_map[key]
        if n > qc.freq:
            qc.freq = n
            updated += 1
        if qc.source != "experience":
            qc.source = "experience"
            kept += 1
    for (qid, cid), n in freq_map.items():
        if (qid, cid) in seen_qc:
            continue
        session.add(
            QuestionCompany(
                question_id=qid,
                company_id=cid,
                role="default",
                freq=n,
                source="experience",
            )
        )
        inserted += 1
    await session.commit()
    return {
        "evidence": len(evidence),
        "pairs": len(freq_map),
        "updated": updated,
        "inserted": inserted,
        "kept": kept,
    }


async def main() -> int:
    parser = argparse.ArgumentParser(description="面经频率榜事实校准（词级双向匹配）")
    parser.add_argument("--apply", action="store_true", help="写库；缺省为 dry-run")
    parser.add_argument("--reset", action="store_true", help="先清空旧证据并把 experience 行重置为 freq=1")
    args = parser.parse_args()

    settings = load_settings()
    engine = make_engine(settings)
    sm = make_sessionmaker(engine)
    async with sm() as session:
        vocab = await load_vocabulary(session)
        if not args.apply:
            await dry_run(session, vocab)
            print("\n[dry-run] 未写库。加 --apply 执行；换算法时加 --reset。")
            return 0
        stats = await apply(session, vocab, args.reset)
        print(f"\n[apply] 证据 {stats['evidence']:,} 行；(公司,题) 对 {stats['pairs']:,}")
        print(f"   回灌：freq 提升 {stats['updated']} · 新增 {stats['inserted']} · 标记实证 {stats['kept']}")
    await engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

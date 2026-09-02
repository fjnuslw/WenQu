"""探测：面经条目 ↔ 题库题干 的 n-gram 相似度匹配可行性与阈值。

已被证伪的两条路：
1. 严格字符串/题干匹配 → 命中率 0.9%（面经口语化 vs 题库规范题干）
2. 标签级共现 → 24 个宽标签把 191 条面经放大成 14.5 万证据对，毫无区分度

第三条路：混合 token（中文二元组 + 英文单词）的 Dice 相似度 + 倒排索引剪枝。
本脚本只做**测量与人工判读**，不写库。
"""

from __future__ import annotations

import random
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parents[1] / "apps" / "api" / "src"))

import asyncio  # noqa: E402

from sqlalchemy import select  # noqa: E402

from getoffer.config import load_settings  # noqa: E402
from getoffer.db import make_engine, make_sessionmaker  # noqa: E402
from getoffer.models import Experience, ExperienceItem, Question  # noqa: E402

CJK = re.compile(r"[\u4e00-\u9fff]+")
WORD = re.compile(r"[a-zA-Z][a-zA-Z0-9+#.]{1,}")


def tokens(text: str) -> set[str]:
    """中文切二元组、英文取整词——中文无空格，二元组是唯一可行的切分。"""
    out: set[str] = set()
    for seg in CJK.findall(text):
        if len(seg) == 1:
            out.add(seg)
        for i in range(len(seg) - 1):
            out.add(seg[i : i + 2])
    out.update(w.lower() for w in WORD.findall(text))
    return out


def dice(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return 2 * inter / (len(a) + len(b))


async def main() -> None:
    settings = load_settings()
    engine = make_engine(settings)
    sm = make_sessionmaker(engine)

    async with sm() as session:
        questions = (await session.execute(select(Question.id, Question.stem))).all()
        items = (await session.execute(
            select(ExperienceItem.id, ExperienceItem.experience_id, ExperienceItem.question_text)
        )).all()
        exps = {e.id: e.company_id for e in (await session.scalars(select(Experience))).all()}

    print(f"题目 {len(questions)}，面经条目 {len(items)}")

    q_tokens = {qid: tokens(stem) for qid, stem in questions}
    q_stem = dict(questions)

    # 倒排索引：token -> 题 id，避免 5745 × 22812 的全量比对
    index: dict[str, list[int]] = defaultdict(list)
    for qid, toks in q_tokens.items():
        for t in toks:
            index[t].append(qid)
    print(f"倒排索引 {len(index)} 个 token")

    # 只保留出现在较少题目里的 token（高频 token 如「如何」「什么」无区分度）
    MAX_DF = 4000
    score_buckets: dict[float, int] = defaultdict(int)
    best_samples: list[tuple[float, str, str]] = []

    sampled = random.Random(7).sample(items, min(600, len(items)))
    for item_id, exp_id, text in sampled:
        toks = tokens(text or "")
        if len(toks) < 3:
            continue
        cand: dict[int, int] = defaultdict(int)
        for t in toks:
            postings = index.get(t)
            if not postings or len(postings) > MAX_DF:
                continue
            for qid in postings:
                cand[qid] += 1
        # 至少共享 3 个 token 才可能是同一道题
        for qid, shared in cand.items():
            if shared < 3:
                continue
            score = dice(toks, q_tokens[qid])
            if score < 0.2:
                continue
            score_buckets[round(score, 1)] += 1
            if score >= 0.4:
                best_samples.append((score, text or "", q_stem.get(qid, "?")))

    print("\nDice 分数分布（600 条抽样）：")
    for k in sorted(score_buckets, reverse=True):
        print(f"  {k:.1f}  {score_buckets[k]}")

    print(f"\n≥0.4 的样本 {len(best_samples)} 条，随机抽 18 条人工判读：")
    random.Random(11).shuffle(best_samples)
    for score, item_text, stem in best_samples[:18]:
        print(f"\n  [{score:.2f}] 面经: {item_text[:70]}")
        print(f"         题目: {stem[:70]}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

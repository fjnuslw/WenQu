"""探测：面经条目 × 标签 共现，能覆盖多少（题目, 公司）对。

上一轮已证伪「面经问题 ↔ 题库题干」的字符串匹配（命中率 0.9%——
面经是口语化追问「训练时为什么要 mask」，题库是规范题干）。
本脚本验证替代方案：以标签为桥梁做共现。
"""

from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parents[1] / "apps" / "api" / "src"))

import asyncio  # noqa: E402

from sqlalchemy import select  # noqa: E402

from getoffer.config import load_settings  # noqa: E402
from getoffer.db import make_engine, make_sessionmaker  # noqa: E402
from getoffer.models import (  # noqa: E402
    Company,
    Experience,
    ExperienceItem,
    Question,
    QuestionCompany,
    QuestionTag,
    Tag,
)


async def main() -> None:
    settings = load_settings()
    engine = make_engine(settings)
    sm = make_sessionmaker(engine)

    async with sm() as session:
        tags = (await session.scalars(select(Tag))).all()
        print(f"标签数 {len(tags)}")
        name_len = Counter(len(t.name) for t in tags)
        print("标签长度分布(前8):", sorted(name_len.items())[:8])

        # 题库侧：tag -> question_ids
        qt = (await session.execute(select(QuestionTag.tag_id, QuestionTag.question_id))).all()
        q_by_tag: dict[int, set[int]] = defaultdict(set)
        for tag_id, qid in qt:
            q_by_tag[tag_id].add(qid)
        print(f"question_tags 关联 {len(qt)} 条，覆盖题目 {len({q for _, q in qt})}")

        # 面经侧
        exps = (await session.scalars(select(Experience))).all()
        with_company = [e for e in exps if e.company_id]
        print(f"面经 {len(exps)} 条，其中带公司 {len(with_company)} 条")

        items = (await session.scalars(select(ExperienceItem))).all()
        text_by_exp: dict[int, str] = defaultdict(str)
        for it in items:
            text_by_exp[it.experience_id] += f"\n{it.question_text}\n{it.note or ''}"
        print(f"面经条目 {len(items)} 条")

        # 标签命中：用小写文本做子串匹配（中文无空格，子串是唯一可行手段）
        pairs: Counter[tuple[int, int]] = Counter()  # (qid, company_id) -> n_experiences
        hit_stats: Counter[str] = Counter()
        for exp in with_company:
            text = text_by_exp.get(exp.id, "").lower()
            if not text:
                continue
            hit_tags = [t for t in tags if t.name.lower() in text]
            hit_stats["有命中标签的面经"] += 1 if hit_tags else 0
            if not hit_tags:
                continue
            qids: set[int] = set()
            for t in hit_tags:
                qids |= q_by_tag.get(t.id, set())
            # 一条面经对同一题只计一次，避免"大段追问"刷高频率
            for qid in qids:
                pairs[(qid, exp.company_id)] += 1

        print(f"\n有标签命中的面经 {hit_stats['有命中标签的面经']}/{len(with_company)}")
        print(f"产生 (题目,公司) 证据对 {len(pairs)} 个")
        freq_dist = Counter(pairs.values())
        print("freq 分布(前10):", sorted(freq_dist.items())[:10])

        # 与既有 AI 推断行的重合度
        existing = (await session.execute(
            select(QuestionCompany.question_id, QuestionCompany.company_id, QuestionCompany.freq)
        )).all()
        exist_set = {(q, c) for q, c, _ in existing}
        print(f"\n既有 question_companies 行 {len(existing)}，去重对 {len(exist_set)}")
        overlap = sum(1 for pair in pairs if pair in exist_set)
        print(f"证据对中已有 AI 行的 {overlap}（{overlap / max(1, len(pairs)):.1%}）→ 这些是「校准」")
        new_pairs = len(pairs) - overlap
        print(f"证据对中全新的 {new_pairs} → 这些是「补充」")

        # 最常出现的证据对
        print("\nTop 12 证据对：")
        comp_name = {c.id: c.name for c in (await session.scalars(select(Company))).all()}
        q_stem = dict((await session.execute(select(Question.id, Question.stem))).all())
        for (qid, cid), n in pairs.most_common(12):
            print(f"  {n:>3}× {comp_name.get(cid, '?')} | {q_stem.get(qid, '?')[:52]}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

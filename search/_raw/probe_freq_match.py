"""调研：面经问题 ↔ 题库题干 的匹配可行性（决定频率榜校准策略）。

比较三种匹配口径在同一批数据上的命中率：
  A. 归一化后完全相等
  B. 归一化后一方包含另一方（长度差限制）
  C. 核心术语命中（从题库标签词表派生的关键词）

只有真实命中率能决定该用哪层，不能拍脑袋。
"""

from __future__ import annotations

import asyncio
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "api" / "src"))

from sqlalchemy import func, select, text  # noqa: E402

from getoffer.config import load_settings  # noqa: E402
from getoffer.db import make_engine, make_sessionmaker  # noqa: E402
from getoffer.models import Company, Experience, ExperienceItem, Question  # noqa: E402

PUNCT = re.compile(r"[\s，。？?！!、；;：:（）()【】\[\]“”\"'’‘,.\-—_/\\|]+")


def norm(value: str) -> str:
    return PUNCT.sub("", (value or "").strip().lower())


async def main() -> None:
    settings = load_settings()
    engine = make_engine(settings)
    sm = make_sessionmaker(engine)

    async with sm() as session:
        n_items = await session.scalar(select(func.count()).select_from(ExperienceItem))
        n_questions = await session.scalar(select(func.count()).select_from(Question))
        # 有公司归属的面经条目数（只有这些能参与频率榜）
        n_with_company = await session.scalar(
            select(func.count())
            .select_from(ExperienceItem)
            .join(Experience, Experience.id == ExperienceItem.experience_id)
            .where(Experience.company_id.is_not(None))
        )
        print(f"面经条目 {n_items}，其中挂公司 {n_with_company}；题库题目 {n_questions}")

        print("\n--- 面经问题文本样例（前 12）---")
        rows = (
            await session.execute(
                select(ExperienceItem.question_text)
                .join(Experience, Experience.id == ExperienceItem.experience_id)
                .where(Experience.company_id.is_not(None))
                .limit(12)
            )
        ).all()
        for (text_value,) in rows:
            print("   ", text_value[:70])

        print("\n--- 题库题干样例（前 8）---")
        qrows = (await session.scalars(select(Question.stem).limit(8))).all()
        for stem in qrows:
            print("   ", stem[:70])

        # 长度分布
        lens = (
            await session.execute(
                select(func.length(ExperienceItem.question_text))
                .join(Experience, Experience.id == ExperienceItem.experience_id)
                .where(Experience.company_id.is_not(None))
                .limit(3000)
            )
        ).all()
        qlens = (await session.execute(select(func.length(Question.stem)).limit(3000))).all()
        print(f"\n面经问题长度中位数 {sorted(x for (x,) in lens)[len(lens)//2]}")
        print(f"题库题干长度中位数 {sorted(x for (x,) in qlens)[len(qlens)//2]}")

        # A. 归一化精确匹配：把题库题干做成集合，看多少面经问题能命中
        stems = [norm(s) for s in (await session.scalars(select(Question.stem))).all()]
        stem_set = {s for s in stems if len(s) >= 6}
        items = (
            await session.scalars(
                select(ExperienceItem.question_text)
                .join(Experience, Experience.id == ExperienceItem.experience_id)
                .where(Experience.company_id.is_not(None))
            )
        ).all()
        exact = sum(1 for t in items if norm(t) in stem_set)
        print(f"\nA. 归一化精确匹配：{exact}/{len(items)} = {exact/max(len(items),1):.2%}")

        # B. 包含匹配（题库题干较短且被面经问题包含，或反之）
        short_stems = [s for s in stems if 8 <= len(s) <= 40]
        sample = short_stems[:800]
        contain = 0
        for t in items[:1500]:
            nt = norm(t)
            if not nt:
                continue
            if any(s in nt or nt in s for s in sample):
                contain += 1
        print(f"B. 包含匹配（题干 8-40 字，抽样 800 × 面经 1500）：{contain}/1500 = {contain/1500:.2%}")

        # C. 术语命中：用题库标签 + 高频技术词做词典
        tag_rows = (
            await session.execute(
                text(
                    "select t.name, count(*) c from question_tags qt "
                    "join tags t on t.id = qt.tag_id group by t.name order by c desc"
                )
            )
        ).all()
        print("\n--- 题库标签分布（前 15）---")
        print("   ", [(name, count) for name, count in tag_rows[:15]])

        terms = [
            "lora", "qlora", "rag", "agent", "mcp", "kv cache", "flash attention",
            "pagedattention", "RoPE", "GQA", "MHA", "多头注意力", "transformer",
            "微调", "预训练", "量化", "蒸馏", "rlhf", "dpo", "grpo", "ppo",
            "langchain", "llamaindex", "langgraph", "vllm", "deepspeed",
            "动态规划", "二分", "滑动窗口", "回溯", "并查集", "堆", "链表", "红黑树",
        ]
        hit_counter: Counter[str] = Counter()
        any_hit = 0
        for t in items:
            low = (t or "").lower()
            hits = [term for term in terms if term.lower() in low]
            if hits:
                any_hit += 1
                for h in hits:
                    hit_counter[h] += 1
        print(f"\nC. 术语命中：{any_hit}/{len(items)} = {any_hit/max(len(items),1):.2%}")
        print("   命中最多的术语：", hit_counter.most_common(12))

        # 公司分布（面经侧）
        comp_rows = (
            await session.execute(
                select(Company.name, func.count(ExperienceItem.id))
                .join(Experience, Experience.company_id == Company.id)
                .join(ExperienceItem, ExperienceItem.experience_id == Experience.id)
                .group_by(Company.name)
                .order_by(func.count(ExperienceItem.id).desc())
                .limit(15)
            )
        ).all()
        print("\n--- 面经条目按公司分布（前 15）---")
        print("   ", [(name, count) for name, count in comp_rows])

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

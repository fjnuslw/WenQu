"""LeetCode Hot 100 种子装载：data/seeds/leetcode_hot100.json → questions + Meili 索引。

幂等：content_hash 用稳定键 lc-hot100:{slug}。用法：
    .venv/Scripts/python scripts/seed_leetcode.py
"""

import asyncio
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sqlalchemy import select  # noqa: E402

from getoffer.config import load_settings  # noqa: E402
from getoffer.db import make_engine, make_sessionmaker  # noqa: E402
from getoffer.models import Question, Tag  # noqa: E402
from getoffer.search.meili import MeiliIndexer, QUESTIONS_INDEX  # noqa: E402

DIFFICULTY_MAP = {"E": 1, "M": 3, "H": 4}
SEED_PATH = Path(__file__).resolve().parents[3] / "data" / "seeds" / "leetcode_hot100.json"


async def main() -> None:
    settings = load_settings()
    entries = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    print(f"seed entries: {len(entries)}")

    engine = make_engine(settings)
    sessionmaker = make_sessionmaker(engine)
    indexer = MeiliIndexer(settings)
    await indexer.ensure_index(QUESTIONS_INDEX)

    inserted = 0
    documents = []
    async with sessionmaker() as session:
        algo_tag = await session.scalar(select(Tag).where(Tag.name == "算法"))
        if algo_tag is None:
            algo_tag = Tag(name="算法")
            session.add(algo_tag)
            await session.flush()

        for entry in entries:
            # 稳定幂等键的 sha256（content_hash 列宽 64，统一走 hex 摘要）
            content_hash = hashlib.sha256(f"lc-hot100:{entry['slug']}".encode("utf-8")).hexdigest()
            exists = await session.scalar(select(Question).where(Question.content_hash == content_hash))
            if exists is not None:
                continue
            question = Question(
                stem=f"[算法·手撕] LeetCode {entry['lc_id']}. {entry['title']}"
                     f"（{('、'.join(entry['topics']))}）—— 请现场手写参考实现",
                kind="algorithm",
                difficulty=DIFFICULTY_MAP.get(entry["difficulty"], 3),
                answer=entry["approach"],
                answer_provenance="manual",
                source_id=None,
                source_ref=f"leetcode/{entry['slug']}",
                content_hash=content_hash,
                meta={"lc_id": entry["lc_id"], "lc_slug": entry["slug"], "topics": entry["topics"]},
            )
            question.tags = [algo_tag]
            session.add(question)
            await session.flush()
            inserted += 1
        await session.commit()

        # 索引全部 algorithm 题（含历史）
        rows = (
            await session.scalars(
                select(Question).where(Question.kind == "algorithm")
            )
        ).all()
        documents = [
            {
                "id": q.id,
                "stem": q.stem,
                "answer": q.answer or "",
                "kind": q.kind,
                "difficulty": q.difficulty,
                "tags": [t.name for t in q.tags],
                "companies": [],
            }
            for q in rows
        ]

    if documents:
        await indexer.upsert_documents(QUESTIONS_INDEX, documents, wait=True)
    await indexer.aclose()
    await engine.dispose()
    print(f"inserted={inserted}, algorithm questions indexed={len(documents)}")


if __name__ == "__main__":
    asyncio.run(main())

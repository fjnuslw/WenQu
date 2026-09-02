"""标签归一迁移：把存量标签按 canonical 词表合并（rag→RAG、agent→Agent 等），清理孤儿。

用法：.venv/Scripts/python scripts/normalize_tags.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sqlalchemy import delete, select  # noqa: E402

from getoffer.config import load_settings  # noqa: E402
from getoffer.db import make_engine, make_sessionmaker  # noqa: E402
from getoffer.ingest.tag_vocab import canonical_tag_name  # noqa: E402
from getoffer.models import Question, Tag  # noqa: E402


async def main() -> None:
    settings = load_settings()
    engine = make_engine(settings)
    sessionmaker = make_sessionmaker(engine)

    async with sessionmaker() as session:
        tags = (await session.scalars(select(Tag))).all()
        merged = 0
        renamed = 0
        for tag in tags:
            canonical = canonical_tag_name(tag.name)
            if canonical == tag.name:
                continue
            target = await session.scalar(select(Tag).where(Tag.name == canonical))
            if target is None:
                # 没有同名词：直接改名
                old_name = tag.name
                tag.name = canonical
                renamed += 1
                print(f"rename: {old_name} -> {canonical}")
                continue
            # 有同名词：把引用迁到 target，再删除旧标签
            ids = (
                await session.scalars(
                    select(Question.id).where(Question.tags.any(Tag.id == tag.id))
                )
            ).all()
            for question_id in ids:
                question = await session.get(Question, question_id)
                question.tags = [t for t in question.tags if t.id != tag.id]
                if all(t.id != target.id for t in question.tags):
                    question.tags.append(target)
            await session.flush()
            await session.execute(delete(Tag).where(Tag.id == tag.id))
            merged += 1
            print(f"merge: {tag.name} -> {canonical} ({len(ids)} 题)")
        await session.commit()

        total_tags = (await session.scalars(select(Tag))).all()
        names = [tag.name for tag in total_tags]
        print(f"done. renamed={renamed} merged={merged} tags_now={len(total_tags)}: {names}")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

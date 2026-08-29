"""一次性迁移：questions.source_ref 的 Windows 反斜杠 → posix 斜杠（增量跳过逻辑依赖 posix 匹配）。"""

import asyncio

from sqlalchemy import text

from getoffer.config import load_settings
from getoffer.db import make_engine


async def main() -> None:
    engine = make_engine(load_settings())
    async with engine.begin() as conn:
        before = (
            await conn.execute(text("SELECT count(*) FROM questions WHERE strpos(source_ref, chr(92)) > 0"))
        ).scalar_one()
        await conn.execute(
            text("UPDATE questions SET source_ref = translate(source_ref, chr(92), '/') "
                 "WHERE strpos(source_ref, chr(92)) > 0")
        )
        after = (
            await conn.execute(text("SELECT count(*) FROM questions WHERE strpos(source_ref, chr(92)) > 0"))
        ).scalar_one()
        total = (await conn.execute(text("SELECT count(*) FROM questions"))).scalar_one()
    await engine.dispose()
    print(f"total={total} backslash_refs_before={before} after={after}")


if __name__ == "__main__":
    asyncio.run(main())

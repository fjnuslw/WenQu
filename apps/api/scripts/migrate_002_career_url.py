"""一次性迁移：companies.career_url / career_note 列（Postgres IF NOT EXISTS，可重复执行）。"""

import asyncio

from sqlalchemy import text

from getoffer.config import load_settings
from getoffer.db import make_engine

STATEMENTS = [
    "ALTER TABLE companies ADD COLUMN IF NOT EXISTS career_url VARCHAR(512)",
    "ALTER TABLE companies ADD COLUMN IF NOT EXISTS career_note VARCHAR(255)",
]


async def main() -> None:
    engine = make_engine(load_settings())
    async with engine.begin() as conn:
        for statement in STATEMENTS:
            await conn.execute(text(statement))
            print("ok:", statement[:60])
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

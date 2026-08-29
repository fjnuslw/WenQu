"""一次性迁移：questions.track 与 companies.logo 列（Postgres IF NOT EXISTS，可重复执行）。"""

import asyncio

from sqlalchemy import text

from getoffer.config import load_settings
from getoffer.db import make_engine

STATEMENTS = [
    "ALTER TABLE questions ADD COLUMN IF NOT EXISTS track VARCHAR(32)",
    "CREATE INDEX IF NOT EXISTS ix_questions_track ON questions (track)",
    "ALTER TABLE companies ADD COLUMN IF NOT EXISTS logo VARCHAR(255)",
    "ALTER TABLE questions ADD COLUMN IF NOT EXISTS classify_attempted_at TIMESTAMPTZ",
    "CREATE INDEX IF NOT EXISTS ix_questions_classify_attempted ON questions (classify_attempted_at)",
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

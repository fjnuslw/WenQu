"""学习路径（F7）冒烟测试。

在进程内直接驱动 router 的处理函数，连接本机开发库，验证：
  1. 目录加载与交叉引用校验通过（5 路径 / 26 阶段 / 109 节点 / 141 资源）
  2. 新增的两张表能建出来
  3. 列表与详情的进度聚合算得对（完成度分母剔除 skipped）
  4. 订阅与节点进度是幂等 upsert
  5. 节点可生成复习卡接入 F6（source=path），且按节点去重

测试数据（一个订阅 + 两个节点进度 + 一张复习卡）在结束时全部删除，不留残留。

用法：apps/api/.venv/Scripts/python.exe scripts/smoke_paths.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sqlalchemy import select, text  # noqa: E402

from getoffer.config import load_settings  # noqa: E402
from getoffer.db import Base, make_engine, make_sessionmaker  # noqa: E402
from getoffer.models import (  # noqa: E402
    LearningEnrollment,
    LearningNodeProgress,
    ReviewItem,
)
from getoffer.paths import router as paths_router  # noqa: E402

SLUG = "llm-app"
NODE_A = "app-3-1"
NODE_B = "app-3-2"

checks: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    checks.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f" — {detail}" if detail else ""))


async def main() -> int:
    settings = load_settings()
    engine = make_engine(settings)
    sessionmaker = make_sessionmaker(engine)

    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)

    async with sessionmaker() as session:
        table_rows = await session.execute(
            text(
                "select table_name from information_schema.tables "
                "where table_schema='public' and table_name in "
                "('learning_enrollments','learning_node_progress')"
            )
        )
        tables = {row[0] for row in table_rows}
        check(
            "新增两张表已建立",
            tables == {"learning_enrollments", "learning_node_progress"},
            ",".join(sorted(tables)),
        )

        listing = await paths_router.list_paths(session=session)
        check("目录总量", (listing["node_count"], listing["resource_count"]) == (109, 141),
              f"节点 {listing['node_count']} / 资源 {listing['resource_count']}")
        check("路径数", len(listing["items"]) == 5, f"{len(listing['items'])} 条")

        detail = await paths_router.get_path(SLUG, session=session)
        node_count = sum(stage["node_count"] for stage in detail["stages"])
        check("详情页节点数", node_count == 27, f"{node_count} 个")
        check("初始完成度", detail["summary"]["percent"] == 0, f"{detail['summary']['percent']}%")

        # ---- 幂等写入 ----
        await paths_router.enroll_path(
            SLUG, paths_router.EnrollIn(target_role="冒烟测试岗", daily_minutes=90), session=session
        )
        await paths_router.enroll_path(
            SLUG, paths_router.EnrollIn(target_role="冒烟测试岗2", daily_minutes=120), session=session
        )
        rows = await session.scalars(
            select(LearningEnrollment).where(LearningEnrollment.path_slug == SLUG)
        )
        check("订阅 upsert 幂等", len(rows.all()) == 1, "重复订阅未产生第二行")

        await paths_router.set_node_progress(
            NODE_A, paths_router.ProgressIn(status="done"), session=session
        )
        await paths_router.set_node_progress(
            NODE_A, paths_router.ProgressIn(status="done"), session=session
        )
        rows = await session.scalars(
            select(LearningNodeProgress).where(LearningNodeProgress.node_id == NODE_A)
        )
        check("节点进度 upsert 幂等", len(rows.all()) == 1, "重复写入未产生第二行")

        await paths_router.set_node_progress(
            NODE_B, paths_router.ProgressIn(status="skipped"), session=session
        )

        detail = await paths_router.get_path(SLUG, session=session)
        summary = detail["summary"]
        # 27 个节点，1 done + 1 skipped，分母 = 27 - 1 = 26
        check(
            "完成度分母剔除 skipped",
            summary["done_nodes"] == 1 and summary["skipped_nodes"] == 1 and summary["percent"] == 4,
            f"done={summary['done_nodes']} skipped={summary['skipped_nodes']} percent={summary['percent']}",
        )

        plan = await paths_router.today_plan(session=session)
        check(
            "今日计划取到下一个未完成节点",
            len(plan["items"]) == 1 and plan["items"][0]["node"]["id"] != NODE_A,
            plan["items"][0]["node"]["id"] if plan["items"] else "空",
        )

        # ---- 生成复习卡（接入 F6）----
        first = await paths_router.node_to_review(NODE_A, session=session)
        second = await paths_router.node_to_review(NODE_A, session=session)
        check(
            "复习卡按节点去重",
            first["created"] is True and second["created"] is False,
            f"first={first['created']} second={second['created']}",
        )

        # ---- 清理测试数据 ----
        await session.execute(
            select(ReviewItem).where(ReviewItem.source == "path").exists().select()
        )
        created_item = await session.scalars(
            select(ReviewItem).where(ReviewItem.source == "path", ReviewItem.source_ref == NODE_A)
        )
        item = created_item.first()
        if item is not None:
            await session.delete(item)
        await session.execute(
            LearningNodeProgress.__table__.delete().where(
                LearningNodeProgress.node_id.in_([NODE_A, NODE_B])
            )
        )
        await session.execute(
            LearningEnrollment.__table__.delete().where(LearningEnrollment.path_slug == SLUG)
        )
        await session.commit()

        remaining = await session.scalars(
            select(LearningNodeProgress).where(LearningNodeProgress.node_id.in_([NODE_A, NODE_B]))
        )
        check("测试数据已清理", len(remaining.all()) == 0, "无残留")

    await engine.dispose()
    failed = [name for name, ok, _ in checks if not ok]
    print(f"\n{len(checks) - len(failed)}/{len(checks)} 通过")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

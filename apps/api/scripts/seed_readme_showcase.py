"""Seed an idempotent, privacy-safe resume used only for README screenshots.

This deliberately bypasses PDF parsing so documentation can be regenerated
without exposing a contributor's real resume to screenshots or external models.
"""

from __future__ import annotations

import asyncio
from datetime import date

from sqlalchemy import delete, select

from getoffer.config import load_settings
from getoffer.db import make_engine, make_sessionmaker
from getoffer.models import Resume, ResumeClaim, ReviewItem

SHOWCASE_FILE = "README_SHOWCASE_SYNTHETIC_RESUME.pdf"
SHOWCASE_SESSION = "README_SHOWCASE_SYNTHETIC_SESSION"

SHOWCASE_PROFILE = {
    "candidate_name": "林星河（合成示例）",
    "role_target": "大模型应用 / AI Agent 开发实习",
    "tech_stack": [
        "Python",
        "FastAPI",
        "LangGraph",
        "PostgreSQL",
        "pgvector",
        "RAG",
        "Reranker",
        "Docker",
    ],
    "experiences": [
        {
            "organization": "某科技公司（合成）",
            "role": "AI 应用研发实习生",
            "points": [
                "负责企业知识问答的检索评测与失败样本回流，离线命中率由 71% 提升到 84%",
                "将长任务改造成可恢复状态图，补齐超时、重试与人工审核分支",
            ],
            "stack": ["FastAPI", "LangGraph", "RAG"],
        }
    ],
    "projects": [
        {
            "name": "TraceRAG（合成项目）",
            "points": [
                "实现 Dense + BM25 + RRF + Reranker 的混合检索链路",
                "为每条回答保留来源片段、文件路径和版本号，支持证据回放",
                "建立 120 条合成 Golden Set，并按召回、重排、生成阶段归因失败",
            ],
            "stack": ["pgvector", "RAG", "Reranker"],
        },
        {
            "name": "FlowPilot（合成项目）",
            "points": [
                "用状态机编排工具调用、人工确认、异常恢复与会话持久化",
                "通过结构化输出与确定性校验减少工具参数错误",
            ],
            "stack": ["LangGraph", "Pydantic", "Docker"],
        },
    ],
    "highlights": [
        "能用数据解释检索方案取舍，而不是只罗列框架",
        "有真实的失败归因、评测集建设与线上恢复经验",
        "项目覆盖 RAG、Agent 编排和工程化交付三个面试高频面",
    ],
    "exam_tags": ["RAG", "Agent", "评测", "MCP与工具调用"],
}


async def seed() -> None:
    settings = load_settings()
    engine = make_engine(settings)
    sessions = make_sessionmaker(engine)
    try:
        async with sessions() as session:
            existing = await session.scalar(select(Resume).where(Resume.file_path == SHOWCASE_FILE))
            if existing is None:
                existing = Resume(file_path=SHOWCASE_FILE, parsed=SHOWCASE_PROFILE)
                session.add(existing)
                await session.flush()
            else:
                existing.parsed = SHOWCASE_PROFILE
                await session.execute(delete(ResumeClaim).where(ResumeClaim.resume_id == existing.id))

            for experience in SHOWCASE_PROFILE["experiences"]:
                hint = f"{experience['organization']} · {experience['role']}"
                for point in experience["points"]:
                    session.add(
                        ResumeClaim(
                            resume_id=existing.id,
                            kind="experience",
                            claim_text=point,
                            project_hint=hint,
                        )
                    )
            for project in SHOWCASE_PROFILE["projects"]:
                for point in project["points"]:
                    session.add(
                        ResumeClaim(
                            resume_id=existing.id,
                            kind="project",
                            claim_text=point,
                            project_hint=project["name"],
                        )
                    )

            await session.execute(delete(ReviewItem).where(ReviewItem.source_ref == SHOWCASE_SESSION))
            for index, item in enumerate(
                [
                    {
                        "question": "如何证明混合检索优于单路召回？",
                        "weakness": (
                            "回答了 Dense + BM25 + RRF，但没有给出消融实验、Recall@K 与失败样本分桶。"
                        ),
                        "tag": "RAG",
                    },
                    {
                        "question": "Agent 工具失败时，怎样避免无效重试和死循环？",
                        "weakness": "需要补充最大步数、错误分类、幂等重试、人工确认和可恢复 checkpoint。",
                        "tag": "Agent",
                    },
                    {
                        "question": "上线前怎样验证一次状态机改动没有破坏旧路径？",
                        "weakness": "应说明状态转移契约测试、长会话回放、异常分支覆盖和发布门禁指标。",
                        "tag": "评测",
                    },
                ]
            ):
                session.add(
                    ReviewItem(
                        source="interview",
                        source_ref=SHOWCASE_SESSION,
                        content_hash=f"readme-showcase-{index}",
                        question_text=item["question"],
                        weakness=item["weakness"],
                        tag=item["tag"],
                        due_on=date.today(),
                    )
                )

            await session.commit()
            print(f"showcase resume ready: id={existing.id}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())

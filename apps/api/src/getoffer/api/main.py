"""FastAPI 应用工厂（spec §5.1）。"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from getoffer.config import load_settings
from getoffer.db import Base, make_engine, make_sessionmaker
from getoffer.errors import UpstreamError, install_error_handlers
from getoffer.llm.gateway import LLMGateway
from getoffer.models import LLMCall
from getoffer.search.meili import QUESTIONS_INDEX, MeiliIndexer

logger = logging.getLogger("getoffer.api")


async def _record_llm_usage(sessionmaker, usage: dict) -> None:
    async with sessionmaker() as session:
        session.add(LLMCall(**usage))
        await session.commit()


def create_app() -> FastAPI:
    settings = load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.engine = make_engine(settings)
        app.state.sessionmaker = make_sessionmaker(app.state.engine)
        app.state.settings = settings
        app.state.gateway = LLMGateway(
            settings.llm,
            usage_sink=lambda usage: _record_llm_usage(app.state.sessionmaker, usage),
        )
        app.state.meili = MeiliIndexer(settings)
        try:
            await app.state.meili.ensure_index(QUESTIONS_INDEX)
        except UpstreamError as exc:
            # 显式降级（有日志、检索端点会用 502 提示），不影响知识库其余功能
            logger.warning("Meilisearch 索引初始化失败，检索端点将显式报错: %s", exc)
        if settings.auto_create_tables:
            # 开发便利；正式迁移用 alembic upgrade head（README）
            # pgvector 扩展必须先启用（镜像内置扩展但不会自动 CREATE EXTENSION）
            async with app.state.engine.begin() as conn:
                from sqlalchemy import text

                await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                await conn.run_sync(Base.metadata.create_all)
        yield
        await app.state.gateway.aclose()
        await app.state.meili.aclose()
        await app.state.engine.dispose()

    app = FastAPI(title="get_offer api", version="0.1.0", lifespan=lifespan)
    install_error_handlers(app)

    # dev 前端跨源访问 api：允许本地任意端口（web 端口会因占用自动顺延）；公开化时收敛到正式域名
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^http://(localhost|127\.0\.0\.1):\d+$",
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from getoffer.api.routers import (
        companies,
        experiences,
        grill,
        ingest,
        interview,
        questions,
        resumes,
        review,
        sessions,
        stats,
    )

    app.include_router(ingest.router)
    app.include_router(questions.router)
    app.include_router(companies.router)
    app.include_router(interview.router)
    app.include_router(sessions.router)
    app.include_router(experiences.router)
    app.include_router(resumes.router)
    app.include_router(review.router)
    app.include_router(grill.router)
    app.include_router(stats.router)

    @app.get("/api/health")
    async def health() -> dict:
        return {"status": "ok", "service": "api", "version": app.version}

    return app

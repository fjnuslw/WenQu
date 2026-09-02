"""API 路由共享依赖。"""

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from getoffer.config import Settings
from getoffer.llm.gateway import LLMGateway
from getoffer.search.meili import MeiliIndexer
from getoffer.voice import VoiceGateway


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    """请求级会话：异常回滚（spec §7，不吞异常）。"""
    async with request.app.state.sessionmaker() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


def get_gateway(request: Request) -> LLMGateway:
    return request.app.state.gateway


def get_indexer(request: Request) -> MeiliIndexer:
    return request.app.state.meili


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_voice_gateway(request: Request) -> VoiceGateway:
    return request.app.state.voice_gateway

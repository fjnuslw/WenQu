"""Persistence and exact pgvector retrieval for repository syntax chunks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import and_, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from getoffer.errors import Conflict, NotConfigured, UpstreamError
from getoffer.grill.chunks import IndexedChunk
from getoffer.grill.embeddings import EmbeddingBatch, EmbeddingGateway
from getoffer.models import Embedding, RepoArtifact, RepoChunk


@dataclass(frozen=True)
class SemanticHit:
    path: str
    start_line: int
    end_line: int
    content: str
    symbols: list[str]
    score: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "content": self.content,
            "symbols": self.symbols,
            "score": round(self.score, 6),
        }


async def replace_project_chunks(
    session: AsyncSession,
    *,
    project_id: int,
    chunks: list[IndexedChunk],
    embeddings: EmbeddingBatch | None,
) -> list[RepoChunk]:
    """Atomically replace one project's chunks and their vector rows in the caller transaction."""
    if embeddings is not None and len(embeddings.vectors) != len(chunks):
        raise ValueError("chunk 与 embedding 数量不一致")

    old_chunk_ids = select(RepoChunk.id).where(RepoChunk.project_id == project_id)
    await session.execute(
        delete(Embedding).where(
            Embedding.kind == "repo_chunk",
            Embedding.ref_id.in_(old_chunk_ids),
        )
    )
    await session.execute(delete(RepoChunk).where(RepoChunk.project_id == project_id))
    rows = [
        RepoChunk(
            project_id=project_id,
            path=chunk.path,
            language=chunk.language,
            start_line=chunk.start_line,
            end_line=chunk.end_line,
            content=chunk.content,
            content_hash=chunk.content_hash,
            symbols=list(chunk.symbols),
            meta=chunk.meta,
        )
        for chunk in chunks
    ]
    session.add_all(rows)
    await session.flush()
    if embeddings is not None:
        session.add_all(
            [
                Embedding(
                    kind="repo_chunk",
                    ref_id=row.id,
                    model=embeddings.model,
                    dim=embeddings.dimension,
                    embedding=vector,
                )
                for row, vector in zip(rows, embeddings.vectors, strict=True)
            ]
        )
        await session.flush()
    return rows


async def semantic_search(
    session: AsyncSession,
    gateway: EmbeddingGateway,
    *,
    project_id: int,
    query: str,
    limit: int = 6,
) -> dict[str, Any]:
    query = query.strip()
    if not query:
        raise ValueError("semantic query 不能为空")
    if not gateway.configured:
        raise NotConfigured("代码语义检索未配置 embedding Provider")

    artifact = await session.scalar(
        select(RepoArtifact).where(
            RepoArtifact.project_id == project_id,
            RepoArtifact.kind == "semantic_index",
        )
    )
    metadata = artifact.meta if artifact is not None else {}
    if metadata.get("status") != "ready":
        raise NotConfigured(
            "该项目没有可用的语义索引",
            details={"status": metadata.get("status", "missing")},
        )
    indexed_model = str(metadata.get("model") or "")
    indexed_dimension = int(metadata.get("dimension") or 0)
    if indexed_model != gateway.model:
        raise Conflict(
            "当前 embedding 模型与项目索引不一致，需要重新备课",
            details={"indexed_model": indexed_model, "configured_model": gateway.model},
        )

    query_batch = await gateway.embed([query])
    if query_batch.dimension != indexed_dimension:
        raise Conflict(
            "查询向量维度与项目索引不一致，需要重新备课",
            details={"indexed_dimension": indexed_dimension, "query_dimension": query_batch.dimension},
        )
    query_vector = query_batch.vectors[0]
    distance = Embedding.embedding.cosine_distance(query_vector).label("distance")
    statement = (
        select(RepoChunk, distance)
        .join(
            Embedding,
            and_(Embedding.kind == "repo_chunk", Embedding.ref_id == RepoChunk.id),
        )
        .where(
            RepoChunk.project_id == project_id,
            Embedding.model == indexed_model,
            Embedding.dim == indexed_dimension,
        )
        .order_by(distance)
        .limit(max(1, min(limit, 12)))
    )
    try:
        rows = (await session.execute(statement)).all()
    except Exception as exc:
        raise UpstreamError("pgvector 语义查询失败", details={"type": type(exc).__name__}) from exc
    hits = [
        SemanticHit(
            path=chunk.path,
            start_line=chunk.start_line,
            end_line=chunk.end_line,
            content=chunk.content,
            symbols=list(chunk.symbols or []),
            score=max(-1.0, min(1.0, 1.0 - float(distance_value))),
        )
        for chunk, distance_value in rows
    ]
    return {
        "mode": "semantic",
        "model": indexed_model,
        "dimension": indexed_dimension,
        "hits": [hit.as_dict() for hit in hits],
    }

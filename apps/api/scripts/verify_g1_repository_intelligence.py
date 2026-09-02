"""G1 v2 repository-intelligence acceptance smoke.

The default run validates a real repository snapshot and a real PostgreSQL/pgvector
distance query.  When no embedding Provider is configured, vectors come from a small,
deterministic test encoder: this proves persistence/query wiring only and is deliberately
reported as ``providerVerified=false``.  Pass ``--require-provider`` for the release gate.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select, text

API_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = API_ROOT.parents[1]
sys.path.insert(0, str(API_ROOT / "src"))

from getoffer.config import Settings, load_settings  # noqa: E402
from getoffer.db import Base, make_engine, make_sessionmaker  # noqa: E402
from getoffer.grill.chunks import IndexedChunk, normalize_chunks  # noqa: E402
from getoffer.grill.embeddings import EmbeddingBatch, EmbeddingGateway  # noqa: E402
from getoffer.grill.ownership import analyze_git_ownership  # noqa: E402
from getoffer.grill.prep import collect_files  # noqa: E402
from getoffer.grill.repomap import build_repo_map  # noqa: E402
from getoffer.grill.retrieval import replace_project_chunks, semantic_search  # noqa: E402
from getoffer.grill.syntax import analyze_files  # noqa: E402
from getoffer.models import Embedding, Project, RepoArtifact, RepoChunk  # noqa: E402

QUERY = "代码语义检索和 pgvector 余弦距离查询在哪里实现？"
EXPECTED_PATH = "apps/api/src/getoffer/grill/retrieval.py"
FIXTURE_MODEL = "g1-pgvector-wiring-fixture-v1"


class DeterministicFixtureGateway:
    """Test-only encoder; never exported to application configuration or runtime."""

    configured = True
    model = FIXTURE_MODEL

    async def embed(self, values: list[str]) -> EmbeddingBatch:
        vectors = [_fixture_vector(value) for value in values]
        return EmbeddingBatch(vectors=vectors, model=self.model, dimension=len(vectors[0]))


def _fixture_vector(value: str) -> list[float]:
    lowered = value.casefold()
    groups = (
        ("semantic", "语义", "pgvector", "cosine", "retrieval", "检索", "embedding"),
        ("tree-sitter", "syntax", "parser", "语法", "symbol", "chunk"),
        ("git", "ownership", "author", "commit", "归属"),
        ("api", "router", "endpoint", "fastapi"),
        ("agent", "tool", "harness", "能力"),
        ("web", "react", "ui", "页面"),
        ("config", "settings", "provider", "配置"),
        ("error", "failure", "disabled", "失败"),
    )
    vector = [float(sum(lowered.count(token) for token in tokens)) for tokens in groups]
    if not any(vector):
        vector[-1] = 0.25
    norm = math.sqrt(sum(item * item for item in vector)) or 1.0
    return [item / norm for item in vector]


def inspect_repository(settings: Settings) -> tuple[dict[str, Any], list[IndexedChunk]]:
    snapshot = collect_files(PROJECT_ROOT)
    analysis = analyze_files(snapshot.files, cache_dir=settings.data_dir / "tree-sitter-cache")
    repo_map = build_repo_map(snapshot.files, analysis)
    chunks = normalize_chunks(analysis.chunks)
    ownership = analyze_git_ownership(PROJECT_ROOT)
    return (
        {
            "root": str(PROJECT_ROOT),
            "headCommit": ownership.get("head_commit"),
            "snapshotFiles": len(snapshot.files),
            "supportedFiles": analysis.supported_files,
            "parsedFiles": analysis.parsed_files,
            "parseCoverage": round(analysis.coverage, 6),
            "parseFailures": analysis.failures,
            "syntaxChunks": len(chunks),
            "repoMapChars": len(repo_map.text),
            "repoMapEdges": repo_map.edge_count,
            "repoMapTopFiles": [item.path for item in repo_map.files[:8]],
            "gitHistory": ownership.get("history_scope"),
        },
        chunks,
    )


async def pgvector_smoke(
    settings: Settings,
    chunks: list[IndexedChunk],
    *,
    require_provider: bool,
) -> dict[str, Any]:
    real_gateway = EmbeddingGateway(settings.embedding)
    provider_verified = real_gateway.configured
    if require_provider and not provider_verified:
        await real_gateway.aclose()
        raise RuntimeError("embedding Provider 未配置；release gate 不允许 fixture 向量")
    gateway: Any = real_gateway if provider_verified else DeterministicFixtureGateway()
    # Current MVP repositories are small enough for exact cosine search. Keep the whole
    # analyzed snapshot (with a generous safety cap) so acceptance cannot accidentally
    # exclude the manually labelled relevant file by alphabetical truncation.
    selected = chunks[:500]
    if len(selected) < 20:
        await real_gateway.aclose()
        raise RuntimeError(f"真实代码块不足 20 个: {len(selected)}")

    engine = make_engine(settings)
    maker = make_sessionmaker(engine)
    project_id: int | None = None
    try:
        async with engine.begin() as connection:
            await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await connection.run_sync(Base.metadata.create_all)
        batch = await gateway.embed([item.embedding_input() for item in selected])
        async with maker() as session:
            project = Project(
                name="__g1_pgvector_acceptance__",
                repo_path=str(PROJECT_ROOT),
                meta={"temporary": True, "purpose": "G1 acceptance"},
            )
            session.add(project)
            await session.flush()
            project_id = project.id
            session.add(
                RepoArtifact(
                    project_id=project_id,
                    kind="semantic_index",
                    meta={
                        "status": "ready",
                        "model": batch.model,
                        "dimension": batch.dimension,
                        "vector_count": len(batch.vectors),
                    },
                )
            )
            await replace_project_chunks(
                session,
                project_id=project_id,
                chunks=selected,
                embeddings=batch,
            )
            await session.commit()

        async with maker() as session:
            result = await semantic_search(
                session,
                gateway,
                project_id=project_id,
                query=QUERY,
                limit=5,
            )
        hit_paths = [item["path"] for item in result["hits"]]
        expected_hit = EXPECTED_PATH in hit_paths
        return {
            "database": "postgresql+pgvector",
            "queryMode": result["mode"],
            "model": result["model"],
            "dimension": result["dimension"],
            "indexedChunks": len(selected),
            "query": QUERY,
            "top5": [
                {
                    "anchor": f'{item["path"]}:{item["start_line"]}-{item["end_line"]}',
                    "score": item["score"],
                }
                for item in result["hits"]
            ],
            "expectedPath": EXPECTED_PATH,
            "expectedPathHit": expected_hit,
            "providerVerified": provider_verified and expected_hit,
            "wiringVerified": expected_hit,
            "evidenceClass": "configured_embedding_provider" if provider_verified else "fixture_vector",
        }
    finally:
        if project_id is not None:
            async with maker() as session:
                chunk_ids = select(RepoChunk.id).where(RepoChunk.project_id == project_id)
                await session.execute(
                    delete(Embedding).where(
                        Embedding.kind == "repo_chunk",
                        Embedding.ref_id.in_(chunk_ids),
                    )
                )
                await session.execute(delete(RepoChunk).where(RepoChunk.project_id == project_id))
                await session.execute(
                    delete(RepoArtifact).where(RepoArtifact.project_id == project_id)
                )
                await session.execute(delete(Project).where(Project.id == project_id))
                await session.commit()
        await real_gateway.aclose()
        await engine.dispose()


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--require-provider",
        action="store_true",
        help="fail unless a configured embedding Provider passes the natural-query Top-5 gate",
    )
    arguments = parser.parse_args()
    settings = load_settings()
    repository, chunks = await asyncio.to_thread(inspect_repository, settings)
    vector = await pgvector_smoke(settings, chunks, require_provider=arguments.require_provider)
    passed = (
        repository["supportedFiles"] > 0
        and repository["parseCoverage"] >= 0.9
        and vector["wiringVerified"]
        and (not arguments.require_provider or vector["providerVerified"])
    )
    print(
        json.dumps(
            {
                "passed": passed,
                "releaseGate": arguments.require_provider,
                "repository": repository,
                "pgvector": vector,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

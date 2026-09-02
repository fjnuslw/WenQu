import json
import os
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import httpx
import pytest

from getoffer.config import DATA_ROOT, EmbeddingProviderConfig
from getoffer.errors import NotConfigured, UpstreamError, ValidationFailed
from getoffer.grill.chunks import normalize_chunks
from getoffer.grill.embeddings import EmbeddingGateway
from getoffer.grill.ownership import analyze_git_ownership
from getoffer.grill.repomap import build_repo_map
from getoffer.grill.source import (
    derive_repository_name,
    enumerate_repository_files,
    remove_owned_repository,
    validate_public_git_url,
)
from getoffer.grill.syntax import (
    FileAnalysis,
    RepositoryAnalysis,
    SymbolDefinition,
    SyntaxChunk,
    analyze_files,
    identifier_counts,
    language_for_path,
)


@dataclass
class SourceFile:
    rel_path: str
    text: str
    importance: int = 100


LANGUAGE_FIXTURES = [
    ("core.py", "python", "def calculate(value: int) -> int:\n    return value + 1\n", "calculate"),
    (
        "core.ts",
        "typescript",
        "export function calculate(value: number): number { return value + 1; }\n",
        "calculate",
    ),
    ("card.tsx", "tsx", "export function Card() { return <section>ok</section>; }\n", "Card"),
    ("core.js", "javascript", "export function calculate(value) { return value + 1; }\n", "calculate"),
    (
        "Core.java",
        "java",
        "public class Core { public int calculate(int value) { return value + 1; } }\n",
        "Core",
    ),
    ("core.go", "go", "package core\nfunc Calculate(value int) int { return value + 1 }\n", "Calculate"),
    ("core.rs", "rust", "pub fn calculate(value: i32) -> i32 { value + 1 }\n", "calculate"),
]


@pytest.mark.parametrize(("path", "language", "source", "symbol"), LANGUAGE_FIXTURES)
def test_six_primary_languages_produce_symbols_and_syntax_chunks(
    path: str, language: str, source: str, symbol: str
) -> None:
    analysis = analyze_files(
        [SourceFile(path, source)],
        cache_dir=DATA_ROOT / "tree-sitter-cache",
        chunk_max_bytes=2048,
    )

    assert analysis.failures == {}
    assert analysis.supported_files == 1
    assert analysis.coverage == 1
    file = analysis.files[path]
    assert file.language == language
    assert any(item.name == symbol and item.line >= 1 for item in file.definitions)
    assert file.chunks
    assert all(chunk.start_line >= 1 and chunk.end_line >= chunk.start_line for chunk in file.chunks)
    assert any(symbol in chunk.symbols for chunk in file.chunks)


def test_language_registry_is_explicit() -> None:
    assert language_for_path("src/view.tsx") == "tsx"
    assert language_for_path("src/main.py") == "python"
    assert language_for_path("README.md") is None


def test_identifier_scanner_is_centralized_and_boundary_aware() -> None:
    counts = identifier_counts("Core CoreFactory core_2 42Core Core")
    assert counts["Core"] == 2
    assert counts["CoreFactory"] == 1
    assert counts["core_2"] == 1
    assert "42Core" not in counts


def test_repo_map_prioritizes_cross_file_definition_and_is_deterministic() -> None:
    sources = [
        SourceFile("core.py", "class Core: pass"),
        SourceFile("service.py", "Core Core Core Core Core"),
        SourceFile("api.py", "Core Core Core"),
        SourceFile("isolated.py", "def lonely(): pass"),
    ]
    core_symbol = SymbolDefinition("Core", "class", 1, "class Core")
    lonely_symbol = SymbolDefinition("lonely", "function", 1, "def lonely()")
    analysis = RepositoryAnalysis(
        files={
            "core.py": FileAnalysis("core.py", "python", [core_symbol], Counter({"Core": 1}), []),
            "service.py": FileAnalysis("service.py", "python", [], Counter({"Core": 5}), []),
            "api.py": FileAnalysis("api.py", "python", [], Counter({"Core": 3}), []),
            "isolated.py": FileAnalysis(
                "isolated.py", "python", [lonely_symbol], Counter({"lonely": 1}), []
            ),
        },
        supported_files=4,
        parser_version="fixture",
    )

    first = build_repo_map(sources, analysis, max_chars=1000)
    second = build_repo_map(sources, analysis, max_chars=1000)

    assert first.text == second.text
    assert first.files[0].path == "core.py"
    assert "L1 class Core" in first.text
    assert first.edge_count == 2
    assert len(first.text) <= 1000


def test_chunk_identity_is_stable_and_anchor_sensitive() -> None:
    base = SyntaxChunk("core.py", "python", 2, 3, "def core():\n    return 1\n", ("core",))
    same = normalize_chunks([base, base])
    moved = normalize_chunks(
        [SyntaxChunk("core.py", "python", 3, 4, base.content, ("core",))]
    )

    assert len(same) == 1
    assert same[0].content_hash != moved[0].content_hash
    assert "file: core.py" in same[0].embedding_input()
    assert "symbols: core" in same[0].embedding_input()


@pytest.mark.asyncio
async def test_embedding_gateway_batches_and_restores_response_order() -> None:
    requests: list[list[str]] = []
    request_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        request_urls.append(str(request.url))
        body = json.loads(request.content)
        inputs = body["input"]
        requests.append(inputs)
        rows = [
            {"index": index, "embedding": [float(len(text)), float(index + 1)]}
            for index, text in enumerate(inputs)
        ]
        return httpx.Response(200, json={"data": list(reversed(rows))})

    gateway = EmbeddingGateway(
        EmbeddingProviderConfig(
            provider="openai_compatible",
            base_url="https://embedding.example/v1",
            api_key="secret-value",
            model="fixture-embed",
            batch_size=2,
        ),
        transport=httpx.MockTransport(handler),
    )
    try:
        batch = await gateway.embed(["a", "bb", "ccc"])
    finally:
        await gateway.aclose()

    assert requests == [["a", "bb"], ["ccc"]]
    assert request_urls == [
        "https://embedding.example/v1/embeddings",
        "https://embedding.example/v1/embeddings",
    ]
    assert batch.dimension == 2
    assert batch.vectors == [[1.0, 1.0], [2.0, 2.0], [3.0, 1.0]]
    assert "secret-value" not in str(gateway.capabilities())


@pytest.mark.asyncio
async def test_embedding_gateway_rejects_cross_batch_dimension_change() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        vector = [1.0, 2.0] if calls == 1 else [1.0, 2.0, 3.0]
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": vector}]})

    gateway = EmbeddingGateway(
        EmbeddingProviderConfig(
            provider="openai_compatible",
            base_url="https://embedding.example/v1",
            model="fixture-embed",
            batch_size=1,
        ),
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(UpstreamError, match="维度不一致"):
            await gateway.embed(["first", "second"])
    finally:
        await gateway.aclose()


@pytest.mark.asyncio
async def test_embedding_gateway_rejects_count_and_non_numeric_vectors_without_secret_leak() -> None:
    responses = [
        httpx.Response(200, json={"data": []}),
        httpx.Response(200, json={"data": [{"index": 0, "embedding": ["not-a-number"]}]}),
        httpx.Response(401, text="secret-value must never escape"),
    ]

    def handler(_request: httpx.Request) -> httpx.Response:
        return responses.pop(0)

    gateway = EmbeddingGateway(
        EmbeddingProviderConfig(
            provider="openai_compatible",
            base_url="https://embedding.example/v1",
            api_key="secret-value",
            model="fixture-embed",
        ),
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(UpstreamError, match="数量"):
            await gateway.embed(["missing"])
        with pytest.raises(UpstreamError, match="非数值"):
            await gateway.embed(["invalid"])
        with pytest.raises(UpstreamError) as captured:
            await gateway.embed(["unauthorized"])
        assert "secret-value" not in str(captured.value)
        assert "secret-value" not in str(captured.value.details)
    finally:
        await gateway.aclose()


@pytest.mark.asyncio
async def test_disabled_embedding_gateway_is_explicit() -> None:
    gateway = EmbeddingGateway(EmbeddingProviderConfig())
    with pytest.raises(NotConfigured, match="未配置"):
        await gateway.embed(["query"])
    assert gateway.capabilities() == {
        "configured": False,
        "provider": "disabled",
        "model": None,
        "dimension": None,
    }


def test_public_git_url_contract() -> None:
    assert validate_public_git_url("https://8.8.8.8/owner/repo.git") == (
        "https://8.8.8.8/owner/repo.git"
    )
    assert derive_repository_name("https://github.com/example/my-agent.git") == "my-agent"


@pytest.mark.parametrize(
    "url",
    [
        "file:///tmp/repo",
        "ssh://git@example.com/repo.git",
        "https://user:token@example.com/repo.git",
        "https://example.com/repo.git?token=secret",
        "https://localhost/repo.git",
        "https://127.0.0.1/repo.git",
        "https://10.1.2.3/repo.git",
        "https://169.254.1.1/repo.git",
    ],
)
def test_git_url_rejects_local_protocol_credentials_and_private_hosts(url: str) -> None:
    with pytest.raises(ValidationFailed):
        validate_public_git_url(url)


def test_git_ownership_matches_real_history() -> None:
    parent = DATA_ROOT / "test-projects"
    parent.mkdir(parents=True, exist_ok=True)
    repository = parent / f"ownership-{uuid4().hex}"
    repository.mkdir()
    try:
        _git(repository, ["init"])
        _commit_file(
            repository,
            "core.py",
            "def core():\n    return 1\n",
            "Alice Zhang",
            "alice@example.com",
            "core",
        )
        _commit_file(
            repository,
            "service.py",
            "from core import core\ndef serve():\n    return core()\n",
            "Bob Li",
            "bob@example.com",
            "service",
        )
        _commit_file(
            repository,
            "core.py",
            "def core():\n    return 2\n\ndef extra():\n    return core()\n",
            "Alice Zhang",
            "alice@example.com",
            "extend core",
        )

        ownership = analyze_git_ownership(repository, candidate_name="Alice Zhang")

        assert ownership["available"] is True
        assert ownership["history_scope"]["commits_analyzed"] == 3
        contributors = {item["name"]: item for item in ownership["contributors"]}
        assert contributors["Alice Zhang"]["commits"] == 2
        assert contributors["Bob Li"]["commits"] == 1
        by_path = {item["path"]: item for item in ownership["files"]}
        assert by_path["core.py"]["primary_author"] == "Alice Zhang"
        assert ownership["candidate"]["matched_authors"] == ["Alice Zhang"]
        assert ownership["candidate"]["commits"] == 2

        (repository / ".gitignore").write_text("ignored/\n", encoding="utf-8")
        (repository / "ignored").mkdir()
        (repository / "ignored" / "secret.py").write_text("secret = True\n", encoding="utf-8")
        link_like = repository / "escape.py"
        link_like.write_text("would point outside in an untrusted repository\n", encoding="utf-8")
        original_is_symlink = Path.is_symlink
        with patch.object(
            Path,
            "is_symlink",
            lambda path: path == link_like or original_is_symlink(path),
        ):
            visible = {
                path.relative_to(repository).as_posix()
                for path in enumerate_repository_files(repository)
            }
        assert "core.py" in visible
        assert "ignored/secret.py" not in visible
        assert "escape.py" not in visible
    finally:
        remove_owned_repository(repository, parent)


def _commit_file(
    repository: Path,
    relative_path: str,
    content: str,
    author: str,
    email: str,
    message: str,
) -> None:
    destination = repository / relative_path
    destination.write_text(content, encoding="utf-8")
    _git(repository, ["add", relative_path])
    environment = dict(os.environ)
    environment.update(
        {
            "GIT_AUTHOR_NAME": author,
            "GIT_AUTHOR_EMAIL": email,
            "GIT_COMMITTER_NAME": author,
            "GIT_COMMITTER_EMAIL": email,
        }
    )
    _git(repository, ["commit", "-m", message], environment=environment)


def _git(repository: Path, arguments: list[str], *, environment: dict[str, str] | None = None) -> None:
    completed = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env=environment,
    )
    assert completed.returncode == 0, completed.stderr

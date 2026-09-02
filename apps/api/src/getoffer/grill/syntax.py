"""Tree-sitter-backed repository analysis for G1 v2.

The adapter deliberately hides the parser package's object model. Downstream repo-map,
chunk persistence and retrieval code consume stable dataclasses and never import
``tree_sitter_language_pack`` directly.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from importlib.metadata import version
from pathlib import Path, PurePosixPath
from threading import Lock
from typing import Any

LANGUAGE_BY_SUFFIX = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
}

_CONFIG_LOCK = Lock()
_CONFIGURED_CACHE: Path | None = None


@dataclass(frozen=True)
class SymbolDefinition:
    name: str
    kind: str
    line: int
    signature: str


@dataclass(frozen=True)
class SyntaxChunk:
    path: str
    language: str
    start_line: int
    end_line: int
    content: str
    symbols: tuple[str, ...] = ()
    node_types: tuple[str, ...] = ()
    context_path: tuple[str, ...] = ()
    strategy: str = "tree_sitter"
    has_errors: bool = False


@dataclass
class FileAnalysis:
    path: str
    language: str
    definitions: list[SymbolDefinition] = field(default_factory=list)
    identifier_counts: Counter[str] = field(default_factory=Counter)
    chunks: list[SyntaxChunk] = field(default_factory=list)
    diagnostic_count: int = 0


@dataclass
class RepositoryAnalysis:
    files: dict[str, FileAnalysis] = field(default_factory=dict)
    failures: dict[str, str] = field(default_factory=dict)
    supported_files: int = 0
    parser_version: str = "unknown"

    @property
    def parsed_files(self) -> int:
        return len(self.files)

    @property
    def coverage(self) -> float:
        if self.supported_files == 0:
            return 0.0
        return self.parsed_files / self.supported_files

    @property
    def chunks(self) -> list[SyntaxChunk]:
        return [chunk for item in self.files.values() for chunk in item.chunks]


def language_for_path(path: str) -> str | None:
    return LANGUAGE_BY_SUFFIX.get(PurePosixPath(path).suffix.lower())


def identifier_counts(text: str) -> Counter[str]:
    """Tokenize identifier-shaped text without language regexes.

    Tree-sitter's high-level process API exposes definitions and syntax chunks but no
    cross-language reference capture. This single compatibility boundary supplies
    reference candidates; repo-map resolution still only accepts names that
    Tree-sitter identified as definitions.
    """
    counts: Counter[str] = Counter()
    current: list[str] = []
    for char in text:
        if char == "_" or char.isalnum():
            current.append(char)
            continue
        if current:
            token = "".join(current)
            if not token[0].isdigit():
                counts[token] += 1
            current.clear()
    if current:
        token = "".join(current)
        if not token[0].isdigit():
            counts[token] += 1
    return counts


def analyze_files(
    files: Iterable[Any],
    *,
    cache_dir: Path,
    chunk_max_bytes: int = 6000,
    max_source_bytes: int = 256 * 1024,
) -> RepositoryAnalysis:
    """Analyze collected files in one Tree-sitter ``process`` call per source file."""
    language_pack = _configure_language_pack(cache_dir)
    result = RepositoryAnalysis(parser_version=version("tree-sitter-language-pack"))
    for collected in files:
        rel_path = str(collected.rel_path)
        language = language_for_path(rel_path)
        if language is None:
            continue
        result.supported_files += 1
        source = str(collected.text)
        try:
            processed = language_pack.process(
                source,
                language_pack.ProcessConfig(
                    language=language,
                    structure=True,
                    imports=True,
                    exports=True,
                    symbols=True,
                    diagnostics=True,
                    chunk_max_size=chunk_max_bytes,
                    max_source_bytes=max_source_bytes,
                    parse_timeout_ms=5000,
                ),
            )
            result.files[rel_path] = _normalize_result(rel_path, language, source, processed)
        except Exception as exc:  # parser/download errors are recorded per file; v1 can continue
            result.failures[rel_path] = _safe_error(exc)
    return result


def _configure_language_pack(cache_dir: Path):
    global _CONFIGURED_CACHE
    import tree_sitter_language_pack as language_pack

    resolved = cache_dir.resolve()
    resolved.mkdir(parents=True, exist_ok=True)
    with _CONFIG_LOCK:
        if _CONFIGURED_CACHE is None:
            language_pack.configure(language_pack.PackConfig(cache_dir=str(resolved)))
            _CONFIGURED_CACHE = resolved
        elif _CONFIGURED_CACHE != resolved:
            raise RuntimeError(
                "tree-sitter-language-pack 已在另一缓存目录初始化；同一进程不能切换缓存目录"
            )
    return language_pack


def _normalize_result(path: str, language: str, source: str, processed: Any) -> FileAnalysis:
    structures = _field(processed, "structure", [])
    definitions: list[SymbolDefinition] = []
    seen: set[tuple[str, int]] = set()
    for item in _walk_structures(structures):
        name = str(_field(item, "name", "") or "").strip()
        span = _field(item, "span", None)
        if not name or span is None:
            continue
        line = int(_field(span, "start_line", 0)) + 1
        key = (name, line)
        if key in seen:
            continue
        seen.add(key)
        signature = str(_field(item, "signature", "") or name).strip()
        definitions.append(
            SymbolDefinition(
                name=name,
                kind=_enum_text(_field(item, "kind", "symbol")),
                line=line,
                signature=_single_line(signature)[:300],
            )
        )

    # Some grammars expose definitions through symbols but not structure.
    for item in _field(processed, "symbols", []):
        name = str(_field(item, "name", "") or "").strip()
        span = _field(item, "span", None)
        if not name or span is None:
            continue
        line = int(_field(span, "start_line", 0)) + 1
        key = (name, line)
        if key in seen:
            continue
        seen.add(key)
        definitions.append(
            SymbolDefinition(
                name=name,
                kind=_enum_text(_field(item, "kind", "symbol")),
                line=line,
                signature=name,
            )
        )

    chunks: list[SyntaxChunk] = []
    for chunk in _field(processed, "chunks", []):
        content = str(_field(chunk, "content", "") or "")
        if not content.strip():
            continue
        metadata = _field(chunk, "metadata", None)
        chunks.append(
            SyntaxChunk(
                path=path,
                language=language,
                start_line=int(_field(chunk, "start_line", 0)) + 1,
                end_line=int(_field(chunk, "end_line", 0)) + 1,
                content=content,
                symbols=tuple(str(value) for value in _field(metadata, "symbols_defined", [])),
                node_types=tuple(str(value) for value in _field(metadata, "node_types", [])),
                context_path=tuple(str(value) for value in _field(metadata, "context_path", [])),
                has_errors=bool(_field(metadata, "has_error_nodes", False)),
            )
        )
    if not chunks and source.strip():
        chunks = _line_window_chunks(path, language, source)

    diagnostics = _field(processed, "diagnostics", [])
    return FileAnalysis(
        path=path,
        language=language,
        definitions=sorted(definitions, key=lambda item: (item.line, item.name)),
        identifier_counts=identifier_counts(source),
        chunks=chunks,
        diagnostic_count=len(diagnostics),
    )


def _line_window_chunks(
    path: str, language: str, source: str, lines_per_chunk: int = 80
) -> list[SyntaxChunk]:
    """Explicit degraded fallback for a parser result that unexpectedly has no chunks."""
    lines = source.splitlines(keepends=True)
    chunks: list[SyntaxChunk] = []
    for offset in range(0, len(lines), lines_per_chunk):
        content = "".join(lines[offset : offset + lines_per_chunk])
        if content.strip():
            chunks.append(
                SyntaxChunk(
                    path=path,
                    language=language,
                    start_line=offset + 1,
                    end_line=min(len(lines), offset + lines_per_chunk),
                    content=content,
                    strategy="line_window",
                )
            )
    return chunks


def _walk_structures(items: Iterable[Any]) -> Iterable[Any]:
    for item in items:
        yield item
        yield from _walk_structures(_field(item, "children", []))


def _field(value: Any, key: str, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def _enum_text(value: Any) -> str:
    name = getattr(value, "name", None)
    if isinstance(name, str):
        return name.lower()
    return str(value).rsplit(".", maxsplit=1)[-1].lower()


def _single_line(value: str) -> str:
    return " ".join(part.strip() for part in value.splitlines() if part.strip())


def _safe_error(exc: Exception) -> str:
    # Parser errors can contain local cache paths; expose only the final concise message.
    text = str(exc).splitlines()[0].strip()
    return text[:300] or type(exc).__name__

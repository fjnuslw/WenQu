"""Stable persistence shape for Tree-sitter syntax chunks."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from getoffer.grill.syntax import SyntaxChunk


@dataclass(frozen=True)
class IndexedChunk:
    path: str
    language: str
    start_line: int
    end_line: int
    content: str
    content_hash: str
    symbols: tuple[str, ...]
    meta: dict[str, object]

    def embedding_input(self) -> str:
        symbols = ", ".join(self.symbols) if self.symbols else "(none)"
        return (
            f"file: {self.path}\n"
            f"language: {self.language}\n"
            f"lines: {self.start_line}-{self.end_line}\n"
            f"symbols: {symbols}\n\n"
            f"{self.content}"
        )


def normalize_chunks(chunks: list[SyntaxChunk]) -> list[IndexedChunk]:
    """Deduplicate parser output and assign content/anchor-sensitive SHA-256 identities."""
    normalized: list[IndexedChunk] = []
    seen: set[tuple[str, int, int, str]] = set()
    for chunk in sorted(chunks, key=lambda item: (item.path, item.start_line, item.end_line)):
        content = chunk.content.rstrip()
        if not content:
            continue
        digest = _chunk_hash(chunk.path, chunk.start_line, chunk.end_line, content)
        key = (chunk.path, chunk.start_line, chunk.end_line, digest)
        if key in seen:
            continue
        seen.add(key)
        normalized.append(
            IndexedChunk(
                path=chunk.path,
                language=chunk.language,
                start_line=chunk.start_line,
                end_line=chunk.end_line,
                content=content,
                content_hash=digest,
                symbols=tuple(dict.fromkeys(chunk.symbols)),
                meta={
                    "strategy": chunk.strategy,
                    "node_types": list(chunk.node_types),
                    "context_path": list(chunk.context_path),
                    "has_errors": chunk.has_errors,
                },
            )
        )
    return normalized


def _chunk_hash(path: str, start_line: int, end_line: int, content: str) -> str:
    identity = f"{path}\0{start_line}\0{end_line}\0{content}".encode()
    return hashlib.sha256(identity).hexdigest()

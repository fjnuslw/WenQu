"""Deterministic Aider-style repository map for G1 v2.

Algorithmic inspiration: ``references/aider/aider/repomap.py`` (Apache-2.0).
This is a clean, dependency-light implementation over G1's stable syntax dataclasses:
Tree-sitter definitions + cross-file identifier references -> weighted PageRank ->
budgeted signatures. It does not copy Aider's runtime, cache or rendering code.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from getoffer.grill.syntax import RepositoryAnalysis, SymbolDefinition


@dataclass(frozen=True)
class RankedFile:
    path: str
    score: float
    definitions: tuple[SymbolDefinition, ...]
    parsed: bool


@dataclass(frozen=True)
class RepoMap:
    text: str
    files: tuple[RankedFile, ...]
    edge_count: int
    parsed_files: int
    supported_files: int
    coverage: float
    failures: dict[str, str]
    parser_version: str

    def artifact(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "files": [
                {
                    "path": item.path,
                    "score": round(item.score, 8),
                    "parsed": item.parsed,
                    "symbols": [
                        {
                            "name": symbol.name,
                            "kind": symbol.kind,
                            "line": symbol.line,
                            "signature": symbol.signature,
                        }
                        for symbol in item.definitions
                    ],
                }
                for item in self.files
            ],
            "edge_count": self.edge_count,
            "parsed_files": self.parsed_files,
            "supported_files": self.supported_files,
            "coverage": round(self.coverage, 6),
            "failures": self.failures,
            "parser_version": self.parser_version,
            "reference_strategy": "tree_sitter_definitions+identifier_resolution",
        }


def build_repo_map(
    collected_files: Iterable[Any],
    analysis: RepositoryAnalysis,
    *,
    max_chars: int = 6000,
) -> RepoMap:
    """Rank all collected files and render the highest-value signatures within budget."""
    collected = list(collected_files)
    paths = sorted({str(item.rel_path) for item in collected})
    if not paths:
        return RepoMap("", (), 0, 0, 0, 0.0, analysis.failures, analysis.parser_version)

    importance = {str(item.rel_path): max(0, int(getattr(item, "importance", 0))) for item in collected}
    definitions: dict[str, list[str]] = defaultdict(list)
    for path, item in analysis.files.items():
        for symbol in item.definitions:
            if _is_identifier(symbol.name):
                definitions[symbol.name].append(path)

    edges: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for source_path, item in analysis.files.items():
        for name, count in item.identifier_counts.items():
            targets = definitions.get(name, [])
            if not targets or count <= 0:
                continue
            share = float(count) / len(targets)
            for target_path in targets:
                if source_path != target_path:
                    edges[source_path][target_path] += share * _production_weight(target_path)

    priors = {
        path: (1.0 + min(importance.get(path, 0), 1000) / 500) * _production_weight(path)
        for path in paths
    }
    scores = _weighted_pagerank(paths, edges, priors)
    ranked = tuple(
        RankedFile(
            path=path,
            score=scores[path],
            definitions=tuple(analysis.files[path].definitions[:12]) if path in analysis.files else (),
            parsed=path in analysis.files,
        )
        for path in sorted(paths, key=lambda value: (-scores[value], value))
    )
    text = _render(ranked, max_chars=max_chars)
    edge_count = sum(len(targets) for targets in edges.values())
    return RepoMap(
        text=text,
        files=ranked,
        edge_count=edge_count,
        parsed_files=analysis.parsed_files,
        supported_files=analysis.supported_files,
        coverage=analysis.coverage,
        failures=dict(sorted(analysis.failures.items())),
        parser_version=analysis.parser_version,
    )


def _weighted_pagerank(
    paths: list[str],
    edges: dict[str, dict[str, float]],
    priors: dict[str, float],
    *,
    damping: float = 0.85,
    iterations: int = 80,
    tolerance: float = 1e-10,
) -> dict[str, float]:
    total_prior = sum(priors.values()) or 1.0
    personalization = {path: priors[path] / total_prior for path in paths}
    scores = dict(personalization)
    for _ in range(iterations):
        next_scores = {path: (1 - damping) * personalization[path] for path in paths}
        dangling = sum(scores[path] for path in paths if not edges.get(path))
        if dangling:
            for path in paths:
                next_scores[path] += damping * dangling * personalization[path]
        for source in paths:
            targets = edges.get(source)
            if not targets:
                continue
            total_weight = sum(targets.values())
            if total_weight <= 0:
                continue
            for target, weight in targets.items():
                next_scores[target] += damping * scores[source] * weight / total_weight
        delta = sum(abs(next_scores[path] - scores[path]) for path in paths)
        scores = next_scores
        if delta <= tolerance:
            break
    total = sum(scores.values()) or 1.0
    return {path: scores[path] / total for path in paths}


def _render(files: tuple[RankedFile, ...], *, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    blocks: list[str] = []
    used = 0
    for item in files:
        lines = [f"{item.path}  [rank={item.score:.4f}]"]
        for symbol in item.definitions[:8]:
            lines.append(f"  L{symbol.line} {symbol.signature}")
        if not item.definitions:
            lines.append("  (无可展示的 Tree-sitter 结构符号)")
        block = "\n".join(lines)
        separator = "\n\n" if blocks else ""
        remaining = max_chars - used - len(separator)
        if remaining <= 0:
            break
        if len(block) > remaining:
            if not blocks:
                blocks.append(block[:remaining].rstrip())
            break
        blocks.append(block)
        used += len(separator) + len(block)
    return "\n\n".join(blocks)


def _is_identifier(value: str) -> bool:
    if not value or value[0].isdigit():
        return False
    return all(char == "_" or char.isalnum() for char in value)


def _production_weight(path: str) -> float:
    """Keep tests visible but stop fixture/helper references from dominating interview topics."""
    lowered = path.lower()
    parts = lowered.split("/")
    name = parts[-1]
    is_test = (
        any(part in {"test", "tests", "__tests__"} for part in parts[:-1])
        or name.startswith("test_")
        or ".test." in name
        or ".spec." in name
    )
    return 0.3 if is_test else 1.0

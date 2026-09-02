"""Read-only Git history attribution for G1 v2."""

from __future__ import annotations

import os
import subprocess
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class AuthorStats:
    name: str
    email: str
    commits: int = 0
    insertions: int = 0
    deletions: int = 0

    @property
    def changed_lines(self) -> int:
        return self.insertions + self.deletions


def analyze_git_ownership(
    root: Path,
    *,
    candidate_name: str | None = None,
    max_commits: int = 500,
) -> dict[str, Any]:
    if not (root / ".git").exists():
        return {"available": False, "reason": "no_history"}
    try:
        head = _git(root, ["rev-parse", "HEAD"]).strip()
        raw = _git(
            root,
            [
                "log", f"-n{max_commits + 1}", "--no-renames",
                "--format=%x1e%H%x1f%aN%x1f%aE", "--numstat", "--", ".",
            ],
            timeout=45,
        )
    except (OSError, subprocess.TimeoutExpired, RuntimeError) as exc:
        return {"available": False, "reason": "git_error", "error_type": type(exc).__name__}

    records = _parse_log(raw)
    truncated = len(records) > max_commits
    records = records[:max_commits]
    authors: dict[tuple[str, str], AuthorStats] = {}
    file_authors: dict[str, dict[tuple[str, str], AuthorStats]] = defaultdict(dict)
    for record in records:
        identity = (record["author"], record["email"])
        author = authors.setdefault(identity, AuthorStats(*identity))
        author.commits += 1
        seen_paths: set[str] = set()
        for path, insertions, deletions in record["files"]:
            author.insertions += insertions
            author.deletions += deletions
            file_author = file_authors[path].setdefault(identity, AuthorStats(*identity))
            if path not in seen_paths:
                file_author.commits += 1
                seen_paths.add(path)
            file_author.insertions += insertions
            file_author.deletions += deletions

    total_commits = len(records)
    contributors = sorted(authors.values(), key=lambda item: (-item.commits, -item.changed_lines, item.name))
    files = []
    for path, by_author in file_authors.items():
        ranked = sorted(
            by_author.values(),
            key=lambda item: (-item.changed_lines, -item.commits, item.name),
        )
        total_lines = sum(item.changed_lines for item in ranked)
        primary = ranked[0]
        files.append(
            {
                "path": path,
                "primary_author": primary.name,
                "primary_share": round(primary.changed_lines / total_lines, 6) if total_lines else 0,
                "commits": sum(item.commits for item in ranked),
                "changed_lines": total_lines,
                "contributors": [
                    {
                        "name": item.name,
                        "commits": item.commits,
                        "changed_lines": item.changed_lines,
                    }
                    for item in ranked[:5]
                ],
            }
        )
    files.sort(key=lambda item: (-int(item["changed_lines"]), str(item["path"])))

    normalized_candidate = _normalize_identity(candidate_name or "")
    matched = [
        item
        for item in contributors
        if normalized_candidate and _normalize_identity(item.name) == normalized_candidate
    ]
    candidate_commits = sum(item.commits for item in matched)
    return {
        "available": True,
        "head_commit": head,
        "history_scope": {
            "commits_analyzed": total_commits,
            "max_commits": max_commits,
            "truncated": truncated,
            "shallow": (root / ".git" / "shallow").exists(),
        },
        "contributors": [
            {
                "name": item.name,
                "email": item.email,
                "commits": item.commits,
                "commit_share": round(item.commits / total_commits, 6) if total_commits else 0,
                "insertions": item.insertions,
                "deletions": item.deletions,
            }
            for item in contributors
        ],
        "files": files[:600],
        "candidate": {
            "name": candidate_name,
            "matched_authors": [item.name for item in matched],
            "commits": candidate_commits,
            "commit_share": round(candidate_commits / total_commits, 6) if total_commits else 0,
        }
        if candidate_name
        else None,
    }


def _git(root: Path, arguments: list[str], *, timeout: int = 15) -> str:
    environment = dict(os.environ)
    environment["GIT_TERMINAL_PROMPT"] = "0"
    # Attribution is a read-only snapshot operation. A partial clone must fail explicitly
    # instead of silently fetching historical blobs after repository acquisition completed.
    environment["GIT_NO_LAZY_FETCH"] = "1"
    completed = subprocess.run(
        ["git", "-c", f"safe.directory={root.resolve()}", "-C", str(root), *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
        env=environment,
    )
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout).strip()[:300])
    return completed.stdout


def _parse_log(raw: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for block in raw.split("\x1e"):
        lines = block.strip().splitlines()
        if not lines:
            continue
        header = lines[0].split("\x1f")
        if len(header) != 3:
            continue
        files: list[tuple[str, int, int]] = []
        for line in lines[1:]:
            parts = line.split("\t", 2)
            if len(parts) != 3:
                continue
            insertions = int(parts[0]) if parts[0].isdigit() else 0
            deletions = int(parts[1]) if parts[1].isdigit() else 0
            files.append((parts[2].replace("\\", "/"), insertions, deletions))
        records.append({"commit": header[0], "author": header[1], "email": header[2], "files": files})
    return records


def _normalize_identity(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(char for char in normalized if char.isalnum())

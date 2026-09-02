"""GitHub 资源取证（只读）：搜索接口批量取元数据，落盘到 search/_raw/。

用途：为「学习路径」板块的四条线（应用 / 算法 / 开发 / 手撕）挑选资源时，
以 GitHub 官方元数据（stars / 最近推送 / license / 是否归档）为准，避免凭记忆写链接。

限速：未认证搜索接口 10 次/分钟，核心接口 60 次/小时。脚本按批执行，带节流。
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent
UA = {"User-Agent": "wenqu-research/0.1", "Accept": "application/vnd.github+json"}

QUERIES = [
    ("leetcode", "topic:leetcode"),
    ("interview", "topic:interview-questions"),
    ("llm", "topic:llm"),
    ("rag", "topic:rag"),
    ("agents", "topic:llm-agents"),
    ("prompt", "topic:prompt-engineering"),
    ("finetune", "topic:fine-tuning"),
    ("inference", "topic:llm-inference"),
    ("fromscratch", "llm from scratch in:name,description"),
    ("mlops", "topic:mlops"),
    ("deploy", "topic:mlops,llm"),
    ("algo", "topic:algorithms"),
]


def get_json(url: str) -> object:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def search(query: str, per_page: int = 60) -> list[dict]:
    url = (
        "https://api.github.com/search/repositories?q="
        + urllib.parse.quote(query, safe=":+>=<")
        + f"&sort=stars&order=desc&per_page={per_page}"
    )
    payload = get_json(url)
    items = payload.get("items", []) if isinstance(payload, dict) else []
    return [trim(item) for item in items]


def trim(item: dict) -> dict:
    return {
        "full_name": item.get("full_name"),
        "html_url": item.get("html_url"),
        "description": (item.get("description") or "").strip(),
        "stars": item.get("stargazers_count"),
        "language": item.get("language"),
        "license": (item.get("license") or {}).get("spdx_id"),
        "topics": item.get("topics", []),
        "archived": item.get("archived"),
        "pushed_at": item.get("pushed_at"),
        "created_at": item.get("created_at"),
    }


def main() -> None:
    collected: dict[str, dict] = {}
    by_query: dict[str, list[str]] = {}
    for i, (slug, query) in enumerate(QUERIES):
        try:
            items = search(query)
        except urllib.error.HTTPError as exc:
            print(f"[{slug}] HTTP {exc.code}: {exc.reason}")
            continue
        names = []
        for item in items:
            names.append(item["full_name"])
            prev = collected.get(item["full_name"])
            if prev is None or (item["stars"] or 0) > (prev["stars"] or 0):
                collected[item["full_name"]] = item
        by_query[slug] = names
        print(f"[{slug}] {query} -> {len(items)}")
        if i < len(QUERIES) - 1:
            time.sleep(7)  # 搜索接口 10 次/分钟
    (OUT_DIR / "gh_search_repos.json").write_text(
        json.dumps({"by_query": by_query, "repos": collected}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(f"total unique repos: {len(collected)}")


if __name__ == "__main__":
    main()

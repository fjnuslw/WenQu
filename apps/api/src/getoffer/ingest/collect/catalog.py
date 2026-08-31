"""可续采的公开候选目录（只发现/缓存，不把候选数冒充入库数）。

用法：python -m getoffer.ingest.collect.catalog --seed URL --max-pages 30
运行快照保存在 data/experience-catalog；失败逐 URL 记录并在 stdout 显式报告。
每次至多访问 30 个已发现的公开页面；不访问搜索、登录态或隐藏接口。
--channel cnblogs 将两篇已审核汇总缓存为独立候选，导入仍须每次最多 30 条。
"""

import argparse
import asyncio
import hashlib
import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from getoffer.config import Settings
from getoffer.errors import ComplianceViolation, UpstreamError
from getoffer.ingest.collect.base import PostPreview
from getoffer.ingest.collect.nowcoder_public import (
    canonical_post_url,
    discover_post_links,
    is_ai_interview,
    parse_nowcoder_public,
)
from getoffer.ingest.collect.polite import PoliteClient


def write_json(path: Path, value) -> None:
    """同目录原子替换；中断时保留上一个完整检查点。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    temporary.replace(path)


def read_json(path: Path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def url_key(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def add_candidate(candidates: dict, post: PostPreview, page_url: str) -> None:
    if not post.url or not is_ai_interview(post.as_text()):
        return
    previous = candidates.get(post.url)
    pages = set(previous.get("discovered_on", [])) if previous else set()
    pages.add(page_url)

    # 原帖正文优先于汇总/卡片；同来源类别保留更完整的可见文本。
    def rank(meta: str, text: str) -> tuple[int, int]:
        return (2 if "公开 SSR 正文" in meta else 1 if "公开汇总摘录" in meta else 0, len(text))

    if previous is None or rank(post.meta, post.content) > rank(
        previous["post"]["meta"], previous["post"]["content"]
    ):
        candidates[post.url] = {
            "channel": "nowcoder-public",
            "post": asdict(post),
            "discovered_on": sorted(pages),
            "fetched_at": datetime.now(UTC).isoformat(),
        }
    else:
        previous["discovered_on"] = sorted(pages)


async def collect_catalog(root: Path, seeds: list[str], max_pages: int, *, follow_links: bool = True) -> dict:
    if not 1 <= max_pages <= 30:
        raise ValueError("单次公开页面采集须为 1–30 页")
    settings = Settings()
    root.mkdir(parents=True, exist_ok=True)
    state_path, candidates_path = root / "state.json", root / "candidates.json"
    state = read_json(state_path, {"queue": [], "visited": {}, "failures": {}})
    candidates = read_json(candidates_path, {})
    priority_seeds = []
    for seed in seeds:
        parsed = urlsplit(seed)
        if parsed.hostname != "www.nowcoder.com" or not (
            canonical_post_url(seed) or parsed.path.startswith(("/creation/subject/", "/users/"))
        ):
            raise ComplianceViolation("候选目录只接受牛客公开帖子/话题/作者页", details={"url": seed})
        if seed not in state["visited"] and seed not in priority_seeds:
            priority_seeds.append(seed)
    state["queue"] = priority_seeds + [url for url in state["queue"] if url not in priority_seeds]

    client = PoliteClient(proxy=settings.collect_proxy, min_interval=8.0)
    fetched, failed = 0, 0
    try:
        while state["queue"] and fetched + failed < max_pages:
            url = state["queue"].pop(0)
            if url in state["visited"]:
                continue
            try:
                # 仅对 HTTP 200 但没有 SSR 正文的同一 URL 受限重试一次。
                for attempt in range(2):
                    response = await client.get(url)
                    final = urlsplit(str(response.url))
                    if final.hostname != "www.nowcoder.com" or "login" in final.path.lower():
                        raise ComplianceViolation("公开页跳转至登录或其他站点", details={"url": url})
                    try:
                        posts = parse_nowcoder_public(response.text, url)
                        break
                    except UpstreamError:
                        if attempt == 1:
                            raise
                snapshot = root / "pages" / (url_key(url) + ".html")
                snapshot.parent.mkdir(parents=True, exist_ok=True)
                snapshot.write_text(response.text, encoding="utf-8")
                for post in posts:
                    add_candidate(candidates, post, url)
                discovered = discover_post_links(response.text, url) if follow_links else []
                for discovered_url in discovered:
                    if discovered_url not in state["visited"] and discovered_url not in state["queue"]:
                        state["queue"].append(discovered_url)
                state["visited"][url] = {"path": str(snapshot), "posts": len(posts), "links": len(discovered)}
                fetched += 1
                print(
                    json.dumps(
                        {"fetched": url, "candidates": len(candidates), "queue": len(state["queue"])},
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
            except (UpstreamError, ComplianceViolation) as exc:
                failed += 1
                failure = {
                    "type": type(exc).__name__,
                    "message": str(exc),
                    "at": datetime.now(UTC).isoformat(),
                }
                state["visited"][url] = {"failed": True}
                state["failures"][url] = failure
                print(json.dumps({"failed": url, **failure}, ensure_ascii=False), flush=True)
            write_json(candidates_path, candidates)
            write_json(state_path, state)
    finally:
        await client.aclose()
    return {"fetched": fetched, "failed": failed, "candidates": len(candidates), "queue": len(state["queue"])}


async def collect_cnblogs_catalog(root: Path, max_pages: int) -> dict:
    """保留 35+4 个已审核章节，解决单次导入 30 条时剩余章节不可续导的问题。"""
    from getoffer.ingest.collect.cnblogs import (
        RECORD_BOUNDARIES,
        SECOND_BOUNDARIES,
        SECOND_URL,
        SEED_URL,
        parse_cnblogs_records,
    )

    if not 1 <= max_pages <= 30:
        raise ValueError("单次公开页面采集须为 1–30 页")
    candidates_path = root / "candidates-cnblogs.json"
    candidates = read_json(candidates_path, {})
    client = PoliteClient(proxy=Settings().collect_proxy, min_interval=12.0)
    pages = ((SEED_URL, RECORD_BOUNDARIES), (SECOND_URL, SECOND_BOUNDARIES))
    fetched = 0
    try:
        for url, boundaries in pages[:max_pages]:
            response = await client.get(url)
            posts = parse_cnblogs_records(response.text, url, boundaries=boundaries)
            snapshot = root / "pages" / (url_key(url) + ".html")
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            snapshot.write_text(response.text, encoding="utf-8")
            for post in posts:
                key = f"{post.url}#excerpt-{url_key(post.content)[:16]}"
                candidates[key] = {"channel": "cnblogs", "post": asdict(post), "sectioned": True}
            write_json(candidates_path, candidates)
            fetched += 1
            print(json.dumps({"fetched": url, "candidates": len(candidates)}, ensure_ascii=False), flush=True)
    finally:
        await client.aclose()
    return {"channel": "cnblogs", "fetched": fetched, "candidates": len(candidates)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Settings().data_dir / "experience-catalog")
    parser.add_argument("--seed", action="append", default=[])
    parser.add_argument("--channel", choices=("nowcoder-public", "cnblogs"), default="nowcoder-public")
    parser.add_argument("--max-pages", type=int, choices=range(1, 31), default=30)
    parser.add_argument("--no-follow", action="store_true")
    args = parser.parse_args()
    if args.channel == "cnblogs":
        if args.seed:
            parser.error("博客园目录仅使用代码中已审核的两个页面，不接受额外种子")
        result = asyncio.run(collect_cnblogs_catalog(args.root, args.max_pages))
    else:
        result = asyncio.run(
            collect_catalog(args.root, args.seed, args.max_pages, follow_links=not args.no_follow)
        )
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()

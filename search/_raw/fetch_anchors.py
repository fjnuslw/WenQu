"""补齐锚点取证（GitHub API 配额耗尽时的替代通道）。

两条路，都不消耗 GitHub API 配额：
  1. jsdelivr 数据接口拿仓库文件树（GET /v1/packages/gh/{repo}@{ref}?structure=flat）
  2. 文档站/教程站抓目录页，用标准库 HTMLParser 提取站内链接（禁正则硬解析 HTML）

产出：search/_raw/anchor_trees.json（仓库文件树）+ anchor_sites.json（站点章节链接）
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}

REPOS = [
    ("krahets/hello-algo", ["main", "master"]),
    ("youngyangyang04/leetcode-master", ["master", "main"]),
    ("greyireland/algorithm-pattern", ["master", "main"]),
    ("afatcoder/LeetcodeTop", ["master", "main"]),
    ("GokuMohandas/Made-With-ML", ["main", "master"]),
    ("stas00/ml-engineering", ["master", "main"]),
    ("labuladong/fucking-algorithm", ["master", "main"]),
    ("seanprashad/leetcode-patterns", ["main", "master"]),
]

SITES = [
    "https://www.hello-algo.com/",
    "https://programmercarl.com/",
    "https://datawhalechina.github.io/hello-agents/",
    "https://datawhalechina.github.io/all-in-rag/",
    "https://llmbook-zh.github.io/",
    "https://www.promptingguide.ai/zh",
    "https://madewithml.com/",
    "https://docs.langchain.com/",
    "https://langchain-ai.github.io/langgraph/",
    "https://modelcontextprotocol.io/",
    "https://huggingface.co/learn/llm-course/chapter1/1",
    "https://www.promptfoo.dev/docs/intro",
    "https://langfuse.com/docs",
    "https://neetcode.io/practice",
    "https://docs.vllm.ai/",
    "https://www.deepspeed.ai/",
    "https://docs.unsloth.ai/",
    "https://docs.dspy.ai/",
    "https://docs.llamaindex.ai/en/stable/",
    "https://docs.claude.com/en/docs/build-with-claude/overview",
]


class LinkCollector(HTMLParser):
    """只提取 <a href> 与锚文本；不用正则硬解析 HTML（spec §7 的解析纪律）。"""

    def __init__(self, base: str) -> None:
        super().__init__()
        self.base = base
        self.links: list[dict[str, str]] = []
        self._current: dict[str, str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        href = dict(attrs).get("href")
        if not href:
            return
        self._current = {"href": urllib.parse.urljoin(self.base, href), "text": ""}

    def handle_data(self, data: str) -> None:
        if self._current is not None:
            self._current["text"] += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._current is not None:
            text = " ".join(self._current["text"].split())
            if text:
                self.links.append({"href": self._current["href"], "text": text[:80]})
            self._current = None


def jsdelivr_tree(repo: str, refs: list[str]) -> tuple[str, list[str]] | None:
    for ref in refs:
        url = f"https://data.jsdelivr.com/v1/packages/gh/{repo}@{ref}?structure=flat"
        try:
            req = urllib.request.Request(url, headers=UA)
            data = json.loads(urllib.request.urlopen(req, timeout=40).read())
        except urllib.error.HTTPError:
            continue
        files = [f.get("name", "") for f in data.get("files", [])]
        if files:
            return ref, files
    return None


def fetch_site(url: str) -> list[dict[str, str]]:
    req = urllib.request.Request(url, headers=UA)
    html = urllib.request.urlopen(req, timeout=40).read().decode("utf-8", "ignore")
    parser = LinkCollector(url)
    parser.feed(html)
    seen: set[str] = set()
    links: list[dict[str, str]] = []
    for link in parser.links:
        href = link["href"].split("#")[0].rstrip("/")
        if not href.startswith("http") or href in seen:
            continue
        seen.add(href)
        links.append({"href": link["href"], "text": link["text"]})
    return links


def main() -> None:
    trees: dict[str, dict] = {}
    for repo, refs in REPOS:
        got = jsdelivr_tree(repo, refs)
        if got is None:
            print("FAIL", repo)
            continue
        ref, files = got
        trees[repo] = {"ref": ref, "files": files}
        print(f"OK   {repo:<44} ref={ref:<8} files={len(files)}")
        time.sleep(0.3)

    (ROOT / "anchor_trees.json").write_text(json.dumps(trees, ensure_ascii=False), encoding="utf-8")

    sites: dict[str, list[dict[str, str]]] = {}
    for url in SITES:
        try:
            links = fetch_site(url)
        except Exception as exc:  # noqa: BLE001
            print("FAIL", url, type(exc).__name__)
            continue
        sites[url] = links
        print(f"OK   {url:<62} links={len(links)}")
        time.sleep(0.2)

    (ROOT / "anchor_sites.json").write_text(json.dumps(sites, ensure_ascii=False), encoding="utf-8")
    print(f"repos={len(trees)} sites={len(sites)}")


if __name__ == "__main__":
    main()

"""抓取各文档站的 llms.txt（Mintlify 等站点自动生成的文档页索引）。

llms.txt 是「这个站点有哪些页面」的权威清单，正是学习锚点最合适的来源：
比仓库根目录精准，且页面可直接阅读（不是源码）。
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}

SITES = [
    "https://docs.langchain.com/llms.txt",
    "https://docs.llamaindex.ai/en/stable/llms.txt",
    "https://docs.vllm.ai/llms.txt",
    "https://docs.unsloth.ai/llms.txt",
    "https://dspy.ai/llms.txt",
    "https://www.promptfoo.dev/llms.txt",
    "https://langfuse.com/docs/llms.txt",
    "https://modelcontextprotocol.io/llms.txt",
    "https://docs.claude.com/llms.txt",
    "https://docs.sglang.ai/llms.txt",
    "https://docs.deepspeed.ai/llms.txt",
    "https://www.deepspeed.ai/llms.txt",
    "https://docs.lmdeploy.ai/llms.txt",
    "https://mlflow.org/docs/latest/llms.txt",
    "https://docs.ray.io/en/latest/llms.txt",
]

LINK_RE = re.compile(r"- \[([^\]]+)\]\((https?://[^)]+)\)(?::\s*(.*))?")


def main() -> None:
    out: dict[str, list[dict[str, str]]] = {}
    raw: dict[str, str] = {}
    for url in SITES:
        try:
            req = urllib.request.Request(url, headers=UA)
            text = urllib.request.urlopen(req, timeout=40).read().decode("utf-8", "ignore")
        except Exception as exc:  # noqa: BLE001
            print("FAIL", url, type(exc).__name__, getattr(exc, "code", ""))
            continue
        links = [
            {"title": m.group(1), "url": m.group(2), "desc": (m.group(3) or "").strip()}
            for m in LINK_RE.finditer(text)
        ]
        out[url] = links
        raw[url] = text
        print(f"OK   {url:<52} links={len(links)}")
    (ROOT / "llms_txt_links.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    (ROOT / "llms_txt_raw.json").write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    print(f"sites={len(out)} total_links={sum(len(v) for v in out.values())}")


if __name__ == "__main__":
    main()

"""一次性修复校验发现的失效/可疑锚点。

策略：
1. 显式替换已知失效 URL（路径迁移、文件名纠错）。
2. 把 hello-algo.com 的锚点切到 GitHub blob（已核验 200，避免站点限流）。
3. 对含非 ASCII 的 URL 做 percent-encoding（保留已有 %XX），修掉中文文件名链接。
4. 丢弃无法验证的 labuladong 中文文件名锚点。
"""

from __future__ import annotations

import json
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "apps" / "api" / "src" / "getoffer" / "paths" / "data"

FILES = ["nodes_l0.json", "nodes_app.json", "nodes_algo.json", "nodes_dev.json", "nodes_lc.json"]

# (旧 url 前缀, 新 url 前缀) —— 前缀替换，保证只动目标
REPLACEMENTS = [
    ("https://www.promptfoo.dev/docs/guides/rag/",
     "https://www.promptfoo.dev/docs/guides/evaluate-rag/"),
    ("https://github.com/shareAI-lab/learn-claude-code/tree/main/chapters",
     "https://github.com/shareAI-lab/learn-claude-code/tree/main/s08_context_compact"),
    ("https://github.com/microsoft/autogen/blob/main/python/packages/autogen-core/docs/src/user-guide/agentchat-user-guide/quickstart.ipynb",
     "https://microsoft.github.io/autogen/stable/user-guide/agentchat-user-guide/quickstart.html"),
    ("https://docs.dify.ai/guides/workflow",
     "https://github.com/langgenius/dify/blob/main/README.md"),
    ("https://github.com/ggml-org/llama.cpp/blob/master/docs/gguf.md",
     "https://github.com/ggml-org/llama.cpp/blob/master/README.md"),
    ("https://github.com/khangich/machine-learning-interview/tree/master/ML%20Interview%20Questions",
     "https://github.com/khangich/machine-learning-interview/blob/master/README.md"),
    ("https://docs.sglang.ai/backend/server_arguments.html",
     "https://docs.sglang.io/docs/advanced_features/server_arguments"),
    ("https://github.com/chiphuyen/machine-learning-systems-design/tree/main/content",
     "https://github.com/chiphuyen/machine-learning-systems-design/blob/master/README.md"),
    ("https://github.com/yangshun/tech-interview-handbook/tree/master/interviewing",
     "https://github.com/yangshun/tech-interview-handbook/blob/master/README.md"),
    ("https://programmercarl.com/0146.LRU%E7%BC%93%E5%AD%98.html",
     "https://leetcode.cn/problems/lru-cache/"),
    # hello-agents 中文文件名 → 英文文件名
    ("https://github.com/datawhalechina/hello-agents/blob/main/docs/chapter7/第七章 构建你的Agent框架.md",
     "https://github.com/datawhalechina/hello-agents/blob/main/docs/chapter7/Chapter7-Building-Your-Agent-Framework.md"),
    ("https://github.com/datawhalechina/hello-agents/blob/main/docs/chapter8/第八章 记忆与检索.md",
     "https://github.com/datawhalechina/hello-agents/blob/main/docs/chapter8/Chapter8-Memory-and-Retrieval.md"),
]

# hello-algo.com 章节 → github blob（此前 raw HEAD 已核验 200）
HELLO_ALGO_MAP = {
    "chapter_computational_complexity": "chapter_computational_complexity",
    "chapter_array_and_linkedlist": "chapter_array_and_linkedlist",
    "chapter_stack_and_queue": "chapter_stack_and_queue",
    "chapter_hashing": "chapter_hashing",
    "chapter_tree": "chapter_tree",
    "chapter_heap": "chapter_heap",
    "chapter_sorting": "chapter_sorting",
}

# 无法可靠核验中文文件名的 labuladong 锚点：整体丢弃
LABULADONG_PREFIX = "https://github.com/labuladong/fucking-algorithm/"


def fix_url(url: str) -> str:
    for old, new in REPLACEMENTS:
        if url.startswith(old):
            return new + url[len(old):]
    if url.startswith("https://www.hello-algo.com/"):
        chapter = url[len("https://www.hello-algo.com/"):].rstrip("/")
        if chapter in HELLO_ALGO_MAP:
            return f"https://github.com/krahets/hello-algo/blob/main/docs/{chapter}/index.md"
    return url


def main() -> None:
    dropped = 0
    for name in FILES:
        path = DATA / name
        doc = json.loads(path.read_text(encoding="utf-8"))
        for node in doc["nodes"]:
            for rid in list(node.get("pins", {}).keys()):
                kept = []
                for pin in node["pins"][rid]:
                    url = fix_url(pin["url"])
                    if url.startswith(LABULADONG_PREFIX):
                        dropped += 1
                        continue
                    # percent-encode 非 ASCII（保留已有 % 与保留字符）
                    url = urllib.parse.quote(url, safe="/:%#")
                    pin["url"] = url
                    kept.append(pin)
                if kept:
                    node["pins"][rid] = kept
                else:
                    del node["pins"][rid]
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"done; dropped labuladong pins = {dropped}")


if __name__ == "__main__":
    main()

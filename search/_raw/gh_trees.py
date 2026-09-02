"""抓取重点仓库的真实文件树，作为「节点 → 具体位置」锚点的唯一依据。

只保存路径列表（丢弃 sha），并按关注目录做轻量过滤，避免把几 MB 的 JSON 全落盘。
未认证核心接口 60 次/小时，本脚本一次约 34 次。
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
UA = {"User-Agent": "wenqu-research/0.1", "Accept": "application/vnd.github+json"}

# 关注目录：落盘时优先保留这些前缀，其余只保留到二级目录，控制体积
INTEREST = (
    "docs/",
    "doc/",
    "documentation/",
    "examples/",
    "example/",
    "tutorials/",
    "tutorial/",
    "notebooks/",
    "cookbook/",
    "chapter",
    "ch",
    "src/",
    "code/",
    "scripts/",
    "README",
)

MAX_PATHS = 4000

REPOS = [
    # 应用线
    "run-llama/llama_index",
    "langchain-ai/langgraph",
    "datawhalechina/hello-agents",
    "datawhalechina/all-in-rag",
    "bojieli/ai-agent-book",
    "modelcontextprotocol/servers",
    "modelcontextprotocol/python-sdk",
    "promptfoo/promptfoo",
    "NirDiamant/agents-towards-production",
    "infiniflow/ragflow",
    "stanfordnlp/dspy",
    "The-Pocket/PocketFlow-Tutorial-Codebase-Knowledge",
    "shareAI-lab/learn-claude-code",
    "pguso/agents-from-scratch",
    "pguso/rag-from-scratch",
    # 算法线
    "rasbt/LLMs-from-scratch",
    "karpathy/nanoGPT",
    "karpathy/minbpe",
    "jingyaogong/minimind",
    "huggingface/peft",
    "hiyouga/LLaMA-Factory",
    "huggingface/trl",
    "datawhalechina/llms-from-scratch-cn",
    "rasbt/reasoning-from-scratch",
    # 开发线
    "vllm-project/vllm",
    "deepspeedai/DeepSpeed",
    "huggingface/picotron",
    "liguodongiot/llm-action",
    "GokuMohandas/Made-With-ML",
    "stas00/ml-engineering",
    # 手撕线
    "krahets/hello-algo",
    "youngyangyang04/leetcode-master",
    "greyireland/algorithm-pattern",
    "afatcoder/LeetcodeTop",
]


def default_branch(repo: str) -> str:
    req = urllib.request.Request(f"https://api.github.com/repos/{repo}", headers=UA)
    data = json.loads(urllib.request.urlopen(req, timeout=30).read())
    return data.get("default_branch", "main")


def tree(repo: str, branch: str) -> list[str]:
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/git/trees/{branch}?recursive=1", headers=UA
    )
    data = json.loads(urllib.request.urlopen(req, timeout=60).read())
    paths = [item["path"] for item in data.get("tree", []) if item.get("type") == "blob"]
    if data.get("truncated"):
        print(f"  !! {repo} tree 被截断")
    return paths


def keep(path: str) -> bool:
    if any(path.startswith(prefix) or prefix in path for prefix in INTEREST):
        return True
    return path.count("/") <= 1


def main() -> None:
    out: dict[str, dict] = {}
    for repo in REPOS:
        try:
            branch = default_branch(repo)
            paths = tree(repo, branch)
        except urllib.error.HTTPError as exc:
            print("FAIL", repo, exc.code)
            continue
        except Exception as exc:  # noqa: BLE001
            print("FAIL", repo, type(exc).__name__)
            continue
        kept = [p for p in paths if keep(p)][:MAX_PATHS]
        out[repo] = {"branch": branch, "total": len(paths), "kept": kept}
        print(f"OK   {repo:<52} total={len(paths):<6} kept={len(kept)}")
        time.sleep(0.5)
    (ROOT / "gh_trees.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(f"saved {len(out)} repos")


if __name__ == "__main__":
    main()

"""定点核验候选仓库（只读）。

搜索接口会漏掉部分仓库（topic 标注不全或关键词不匹配），
这里用核心接口逐个确认：存在性、star、最近推送、license、是否归档。
未认证核心接口 60 次/小时，本脚本一次约 45 次。
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent
UA = {"User-Agent": "wenqu-research/0.1", "Accept": "application/vnd.github+json"}

TARGETS = [
    # 应用 / Agent
    "modelcontextprotocol/servers",
    "modelcontextprotocol/python-sdk",
    "stanfordnlp/dspy",
    "microsoft/autogen",
    "crewAIInc/crewAI",
    "openai/openai-agents-python",
    "FlowiseAI/Flowise",
    "bytedance/deer-flow",
    "All-Hands-AI/OpenHands",
    "anthropics/anthropic-cookbook",
    "openai/openai-cookbook",
    "promptfoo/promptfoo",
    "HKUDS/LightRAG",
    "qdrant/qdrant",
    "chroma-core/chroma",
    "Tencent/WeKnora",
    "datawhalechina/all-in-rag",
    "datawhalechina/self-llm",
    "datawhalechina/tiny-universe",
    # 算法 / 训练 / 推理
    "karpathy/nanoGPT",
    "karpathy/llama2.c",
    "karpathy/minbpe",
    "huggingface/transformers",
    "huggingface/trl",
    "huggingface/picotron",
    "hiyouga/LLaMA-Factory",
    "modelscope/ms-swift",
    "Dao-AILab/flash-attention",
    "deepspeedai/DeepSpeed",
    "NVIDIA/Megatron-LM",
    "sgl-project/sglang",
    "ggml-org/llama.cpp",
    "ollama/ollama",
    "triton-lang/triton",
    # 开发 / 工程化
    "bentoml/BentoML",
    "ray-project/ray",
    "triton-inference-server/server",
    "DataTalksClub/mlops-zoomcamp",
    "GokuMohandas/Made-With-ML",
    # 手撕 / 算法面试
    "youngyangyang04/leetcode",
    "Doocs/leetcode",
    "halfrost/LeetCode-Go",
    "azl397985856/leetcode",
    "TheAlgorithms/Python",
    "donnemartin/system-design-primer",
    "neetcode-gh/leetcode",
    "jwasham/coding-interview-university",
]


def fetch(full_name: str) -> dict:
    req = urllib.request.Request(f"https://api.github.com/repos/{full_name}", headers=UA)
    with urllib.request.urlopen(req, timeout=30) as resp:
        item = json.loads(resp.read().decode("utf-8"))
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
        "homepage": item.get("homepage"),
    }


def main() -> None:
    ok, missing = {}, []
    for i, name in enumerate(TARGETS):
        try:
            ok[name] = fetch(name)
            print("OK  ", name, ok[name]["stars"], (ok[name]["pushed_at"] or "")[:10], ok[name]["license"])
        except urllib.error.HTTPError as exc:
            missing.append({"full_name": name, "http": exc.code})
            print("FAIL", name, exc.code)
        if i < len(TARGETS) - 1:
            time.sleep(0.4)
    (OUT_DIR / "gh_verified_repos.json").write_text(
        json.dumps({"ok": ok, "missing": missing}, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"ok={len(ok)} missing={len(missing)}")


if __name__ == "__main__":
    main()

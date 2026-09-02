"""候选锚点路径验证（raw.githubusercontent.com，不消耗 GitHub API 配额）。

纪律：这里的路径是**假设**，只有 HEAD 返回 200 才会被采纳为锚点；
404/超时的候选一律丢弃，不写进节点数据。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}

CANDIDATES: list[tuple[str, str, str]] = [
    # (repo@ref, 候选路径, 说明)
    ("krahets/hello-algo@main", "docs/chapter_computational_complexity/index.md", "复杂度"),
    ("krahets/hello-algo@main", "docs/chapter_array_and_linkedlist/index.md", "数组链表"),
    ("krahets/hello-algo@main", "docs/chapter_stack_and_queue/index.md", "栈队列"),
    ("krahets/hello-algo@main", "docs/chapter_hashing/index.md", "哈希"),
    ("krahets/hello-algo@main", "docs/chapter_tree/index.md", "树"),
    ("krahets/hello-algo@main", "docs/chapter_heap/index.md", "堆"),
    ("krahets/hello-algo@main", "docs/chapter_searching/index.md", "查找"),
    ("krahets/hello-algo@main", "docs/chapter_sorting/index.md", "排序"),
    ("krahets/hello-algo@main", "docs/chapter_dynamic_programming/index.md", "动态规划"),
    ("krahets/hello-algo@main", "docs/chapter_greedy/index.md", "贪心"),
    ("krahets/hello-algo@main", "docs/chapter_backtracking/index.md", "回溯"),
    ("krahets/hello-algo@main", "docs/chapter_graph/index.md", "图"),
    ("krahets/hello-algo@main", "docs/chapter_divide_and_conquer/index.md", "分治"),
    ("krahets/hello-algo@main", "docs/chapter_string/index.md", "字符串"),
    ("krahets/hello-algo@main", "docs/chapter_bit_operation/index.md", "位运算"),

    ("run-llama/llama_index@main", "docs/docs/getting_started/starter_example.md", "最小 RAG"),
    ("run-llama/llama_index@main", "docs/docs/getting_started/installation.md", "安装"),
    ("run-llama/llama_index@main", "docs/docs/getting_started/concepts.md", "核心概念"),
    ("run-llama/llama_index@main", "docs/docs/optimizing/production_rag.md", "生产级 RAG"),
    ("run-llama/llama_index@main", "docs/docs/optimizing/basic_strategy.md", "RAG 优化基础"),
    ("run-llama/llama_index@main", "docs/docs/optimizing/advanced_retrieval/optimization.md", "高级检索"),
    ("run-llama/llama_index@main", "docs/docs/module_guides/indexing/index.md", "索引"),
    ("run-llama/llama_index@main", "docs/docs/module_guides/loading/documents_and_nodes/index.md", "文档与节点"),
    ("run-llama/llama_index@main", "docs/docs/module_guides/evaluating/index.md", "评测"),

    ("langchain-ai/langgraph@main", "docs/docs/index.md", "总览"),
    ("langchain-ai/langgraph@main", "docs/docs/concepts/low_level.md", "底层概念"),
    ("langchain-ai/langgraph@main", "docs/docs/concepts/agentic_concepts.md", "Agent 概念"),
    ("langchain-ai/langgraph@main", "docs/docs/concepts/persistence.md", "持久化"),
    ("langchain-ai/langgraph@main", "docs/docs/concepts/human_in_the_loop.md", "人在回路"),
    ("langchain-ai/langgraph@main", "docs/docs/concepts/memory.md", "记忆"),
    ("langchain-ai/langgraph@main", "docs/docs/concepts/multi_agent.md", "多智能体"),
    ("langchain-ai/langgraph@main", "docs/docs/tutorials/introduction.md", "入门教程"),
    ("langchain-ai/langgraph@main", "docs/docs/how-tos/index.md", "how-to 索引"),

    ("datawhalechina/hello-agents@main", "docs/chapter1/index.md", "第1章"),
    ("datawhalechina/hello-agents@main", "docs/chapter2/index.md", "第2章"),
    ("datawhalechina/hello-agents@main", "docs/chapter3/index.md", "第3章"),
    ("datawhalechina/hello-agents@main", "docs/chapter4/index.md", "第4章"),
    ("datawhalechina/hello-agents@main", "docs/chapter5/index.md", "第5章"),
    ("datawhalechina/hello-agents@main", "docs/chapter6/index.md", "第6章"),
    ("datawhalechina/hello-agents@main", "docs/chapter7/index.md", "第7章"),
    ("datawhalechina/hello-agents@main", "docs/chapter8/index.md", "第8章"),

    ("huggingface/peft@main", "examples/lora_dreambooth/README.md", "LoRA 示例"),
    ("huggingface/peft@main", "examples/qlora/README.md", "QLoRA 示例"),
    ("huggingface/peft@main", "docs/source/conceptual_guides/lora.md", "LoRA 概念"),
    ("huggingface/peft@main", "docs/source/conceptual_guides/adapter.md", "Adapter 概念"),
    ("huggingface/trl@main", "docs/source/dpo_trainer.md", "DPO Trainer"),
    ("huggingface/trl@main", "docs/source/sft_trainer.md", "SFT Trainer"),
    ("huggingface/trl@main", "docs/source/grpo_trainer.md", "GRPO Trainer"),
    ("huggingface/trl@main", "docs/source/ppo_trainer.md", "PPO Trainer"),
    ("jingyaogong/minimind@main", "README.md", "总览"),
    ("jingyaogong/minimind@main", "train_pretrain.py", "预训练脚本"),
    ("jingyaogong/minimind@main", "train_full_sft.py", "SFT 脚本"),
    ("jingyaogong/minimind@main", "model/model_minimind.py", "模型定义"),
    ("karpathy/nanoGPT@master", "model.py", "GPT 模型定义"),
    ("karpathy/nanoGPT@master", "train.py", "训练脚本"),
    ("karpathy/nanoGPT@master", "README.md", "总览"),
    ("karpathy/minbpe@master", "minbpe/basic.py", "BPE 基础实现"),
    ("karpathy/minbpe@master", "minbpe/gpt4.py", "GPT4 分词"),
    ("karpathy/minbpe@master", "minbpe/base.py", "分词器基类"),
    ("rasbt/LLMs-from-scratch@main", "ch02/01_main-chapter-code/ch02.ipynb", "第2章 文本处理"),
    ("rasbt/LLMs-from-scratch@main", "ch03/01_main-chapter-code/ch03.ipynb", "第3章 注意力"),
    ("rasbt/LLMs-from-scratch@main", "ch04/01_main-chapter-code/ch04.ipynb", "第4章 GPT 实现"),
    ("rasbt/LLMs-from-scratch@main", "ch05/01_main-chapter-code/ch05.ipynb", "第5章 预训练"),
    ("rasbt/LLMs-from-scratch@main", "ch06/01_main-chapter-code/ch06.ipynb", "第6章 微调"),
    ("rasbt/LLMs-from-scratch@main", "ch07/01_main-chapter-code/ch07.ipynb", "第7章 指令微调"),
    ("rasbt/LLMs-from-scratch@main", "ch02/02_bonus_bytepair-encoder/bpe_openai_gpt2.py", "BPE 实现"),
    ("rasbt/reasoning-from-scratch@main", "ch02/01_main-chapter-code/ch02.ipynb", "第2章"),
    ("rasbt/reasoning-from-scratch@main", "ch03/01_main-chapter-code/ch03.ipynb", "第3章"),
    ("vllm-project/vllm@main", "docs/optimization.md", "优化文档"),
    ("vllm-project/vllm@main", "docs/features/structured_outputs.md", "结构化输出"),
    ("vllm-project/vllm@main", "docs/quantization/README.md", "量化"),
    ("vllm-project/vllm@main", "benchmarks/README.md", "压测"),
    ("deepspeedai/DeepSpeed@master", "docs/_pages/config-json.md", "配置"),
    ("deepspeedai/DeepSpeed@master", "docs/_pages/zero3.md", "ZeRO-3"),
    ("deepspeedai/DeepSpeed@master", "docs/_pages/getting-started.md", "入门"),
    ("huggingface/picotron@main", "README.md", "总览"),
    ("huggingface/picotron@main", "train.py", "训练脚本"),
    ("huggingface/picotron@main", "picotron/models/llama.py", "模型实现"),
    ("stas00/ml-engineering@master", "README.md", "总览"),
    ("stas00/ml-engineering@master", "training/README.md", "训练篇"),
    ("stas00/ml-engineering@master", "compute/README.md", "算力篇"),
    ("stas00/ml-engineering@master", "debug/README.md", "调试篇"),
    ("GokuMohandas/Made-With-ML@main", "README.md", "总览"),
    ("GokuMohandas/Made-With-ML@main", "lessons/README.md", "课程索引"),
]


def probe(item: tuple[str, str, str]) -> dict:
    ref, path, label = item
    repo, branch = ref.split("@")
    url = f"https://raw.githubusercontent.com/{repo}/{branch}/{path}"
    req = urllib.request.Request(url, headers=UA, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            return {"repo": repo, "branch": branch, "path": path, "label": label,
                    "status": resp.status, "url": f"https://github.com/{repo}/blob/{branch}/{path}"}
    except urllib.error.HTTPError as exc:
        return {"repo": repo, "branch": branch, "path": path, "label": label,
                "status": exc.code, "url": None}
    except Exception as exc:  # noqa: BLE001
        return {"repo": repo, "branch": branch, "path": path, "label": label,
                "status": None, "url": None, "error": type(exc).__name__}


def main() -> None:
    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(probe, CANDIDATES))
    ok = [r for r in results if r["status"] == 200]
    bad = [r for r in results if r["status"] != 200]
    (ROOT / "verified_pins.json").write_text(
        json.dumps({"ok": ok, "rejected": bad}, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    for r in results:
        flag = "OK " if r["status"] == 200 else f"{r['status']}"
        print(f"{flag:<5} {r['repo']}/{r['path']}")
    print(f"\n采纳 {len(ok)}/{len(results)}，驳回 {len(bad)}")


if __name__ == "__main__":
    main()

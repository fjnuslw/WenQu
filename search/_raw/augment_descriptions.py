"""给有锚点的资源补 `description`（项目是什么），给关键 pin 补 `note`（点这里会看到什么）。

数据约束：
- description 是关于资源（项目）本身的一行话，不是为什么放这里（那是节点级 why）。
- note 是关于这个具体位置的一句话预告，帮读者决定要不要点。
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API = ROOT / "apps" / "api" / "src" / "getoffer" / "paths" / "data"

# resource_id → 一句话项目说明
DESCRIPTIONS: dict[str, str] = {
    # L0 + dev 共用
    "l0-1": "Hugging Face 官方 LLM 课程，Transformer / 微调 / RAG / 部署全覆盖",
    "l0-2": "dair-ai 维护的提示工程指南：零样本 / CoT / ReAct / 工具调用",
    "l0-4": "Arie Bregman 的 DevOps 练习题库（Linux / Docker / Git / Python）",
    "l0-5": "f/ 维护的 Awesome ChatGPT Prompts 提示词示例库",
    "dev-1-1": "tiangolo 的 Python 异步 Web 框架，OpenAPI 与 Pydantic 原生支持",
    "dev-1-3": "pytest：Python 最主流的测试框架（fixture / 参数化 / mock / 插件生态）",
    # 应用线 · 官方文档与 cookbook
    "app-1-1": "OpenAI 工具调用（Function Calling / Structured Outputs）官方规范",
    "app-1-2": "Anthropic Claude 的 tool_use schema、错误处理、多轮循环文档",
    "app-1-4": "OpenAI 官方实战 notebook 集（结构化输出 / 工具 / 视觉 / 微调）",
    "app-1-5": "Anthropic 官方 notebook 集（prompt / 工具 / 评估 / 长上下文）",
    "app-2-1": "Anthropic Agent 设计方法论：5 种基础模式与工作流边界",
    "app-2-2": "pguso 的从零 Agent 教程：极简实现 + 6 课作业",
    "app-2-3": "browser-use：让 LLM 直接操作浏览器的 Agent 框架",
    "app-2-4": "Anthropic 工程团队写的 tool description 最佳实践",
    # 应用线 · 框架与生态
    "app-3-1": "LlamaIndex：文档加载 / 索引 / 查询 / Agent 的 RAG 全栈框架",
    "app-3-2": "Datawhale 中文 RAG 全栈教程：从原理到工业部署",
    "app-3-3": "pguso 从零实现的 RAG（无框架，22 对 CONCEPT + CODE）",
    "app-3-4": "RAGFlow：InfiniFlow 的生产级 RAG 引擎（DeepDoc 解析 + GraphRAG）",
    "app-3-5": "LightRAG：HKUDS 的图增强轻量 RAG（EMNLP 2025）",
    "app-3-6": "百度飞桨 PaddleOCR（版面分析 / 表格抽取 / 多语言）",
    "app-3-7": "Qdrant：Rust 写的向量数据库（混合检索 / 过滤 / 分片）",
    "app-4-1": "LangGraph：LangChain 的状态图 Agent 框架（checkpoint / 人审 / 中断）",
    "app-4-2": "Hello-Agents：Datawhale 中文 Agent 教程（16 章）",
    "app-4-3": "李博杰《深入理解 AI Agent：设计原理与工程实践》开源书",
    "app-4-4": "OpenAI Agents SDK (Python)：官方极简 Agent SDK",
    "app-4-5": "shareAI-lab 对 Claude Code 源码的逐章拆解（17 章）",
    "app-4-6": "Pocket Flow：The Pocket 出品的 100 行 LLM 编排框架",
    "app-4-7": "shareAI-lab/learn-claude-code：Agent Harness 工程细节剖析",
    "app-4-8": "mem0：Agent 长期记忆层（add / search / decay）",
    "app-4-9": "OpenHands：事件流 + 沙箱 + 多语言 SDK 的大规模 Agent 系统",
    "app-5-1": "MCP Servers 官方参考实现集（fetch / everything / git / postgres）",
    "app-5-2": "MCP Python SDK 与示例（fastmcp 框架 / FastAPI 集成）",
    "app-5-3": "AutoGen 论文：多智能体对话范式的奠基工作",
    "app-5-4": "AutoGen 框架：微软多智能体对话框架",
    "app-5-5": "victordibia 的多智能体系统设计（微软教程，架构视角）",
    "app-5-6": "WenyuChiou/awesome-agentic-ai-zh：中文 Agentic AI 学习路线图",
    "app-5-7": "microsoft/agent-lightning：把 Agent 当模型一样训练的工具",
    "app-6-1": "NirDiamant/agents-towards-production：从 Demo 到生产的逐环节教程",
    "app-6-2": "promptfoo：LLM 评测 + 红队 + CI 集成的瑞士军刀",
    "app-6-3": "Langfuse：LLM 可观测与评测平台（trace / 评分 / 数据集）",
    "app-6-4": "LiteLLM：统一 100+ 模型 API + 成本追踪 + 路由网关",
    "app-6-5": "DSPy：把 prompt 当优化问题（编译器 + 评测驱动）",
    "app-6-6": "Dify：开源 LLM 应用平台（工作流 / RAG / Agent / 多模型）",
    "app-6-7": "Flowise：拖拽式 LLM 编排（LangChain.js 可视化）",
    # 算法线
    "algo-1-1": "PyTorch：研究 / 训练 / 部署的事实标准框架",
    "algo-1-2": "Hugging Face NLP Course：Transformer / 数据集 / 微调实战",
    "algo-1-3": "PyTorch（autograd 教程页）",
    "algo-2-1": "Attention Is All You Need（Transformer 原论文）",
    "algo-2-2": "rasbt/LLMs-from-scratch：手写 GPT 全流程教学（7 章）",
    "algo-2-3": "karpathy/nanoGPT：最短的 GPT 训练实现（一个 model.py）",
    "algo-2-5": "karpathy/minbpe：500 行 BPE 分词器教学实现",
    "algo-2-6": "karpathy/llama2.c：纯 C 的 LLaMA 2 推理实现",
    "algo-3-1": "MiniMind：单机 2 小时从零训练 26M 微型 LLM（流程完整）",
    "algo-3-2": "Transformers：Hugging Face 模型定义与训练框架",
    "algo-3-5": "Tongjilibo/build_MiniLLM_from_scratch：中文从零 LLM 全流程",
    "dev-5-2": "stas00/ml-engineering：大模型训练与工程实践开源书",
    "algo-4-1": "LoRA 原论文",
    "algo-4-2": "PEFT：Hugging Face 参数高效微调库",
    "algo-4-3": "LLaMA-Factory：中文社区最常用的一站式微调框架",
    "algo-4-5": "Unsloth：显存/速度双优的 LoRA/QLoRA 训练加速器",
    "algo-4-6": "Axolotl：配置驱动的微调框架（多机多卡 / DeepSpeed 一键）",
    "algo-4-7": "torchtune：PyTorch 官方微调库（原生 + 可读）",
    "algo-4-8": "ConardLi/easy-dataset：把文档转成指令数据集的中文工具",
    "algo-5-1": "HuggingFace TRL：SFT/DPO/GRPO/PPO 训练器",
    "algo-5-6": "ms-swift（ModelScope）：中文生态的全流程训练部署框架",
    "algo-5-7": "rasbt/reasoning-from-scratch：推理模型训练全流程教学",
    "algo-6-3": "Dao-AILab/flash-attention：CUDA kernel 实现的 IO 感知注意力",
    "algo-6-4": "FlashInfer：LLM 服务的可组合注意力算子库",
    "algo-6-5": "ggml-org/llama.cpp：CPU / 端侧 / GGUF 量化的 LLM 推理",
    "algo-6-7": "khangich/machine-learning-interview：ML/LLM 面试题与项目复现清单",
    # 开发线
    "dev-1-2": "liguodongiot/llm-action：大模型工程化中文项目（训练 / 推理 / 部署）",
    "dev-2-1": "vllm-project/vllm：高吞吐推理服务（PagedAttention / 连续批处理）",
    "dev-2-2": "lmsysorg/sglang：高性能结构化生成 / RadixAttention 推理框架",
    "dev-2-3": "InternLM/lmdeploy：压缩 / 部署 / 服务一体工具箱",
    "dev-2-4": "bentoml/OpenLLM：一行命令起任意开源 LLM 服务",
    "dev-2-5": "triton-inference-server：NVIDIA 推理服务（多框架 / 多模型）",
    "dev-2-7": "ai-dynamo/dynamo：数据中心级分布式 LLM 推理服务框架",
    "dev-3-1": "ollama/ollama：本地跑开源 LLM 的一键方案",
    "dev-3-2": "bregman-arie/devops-exercises 容器篇",
    "dev-3-3": "gpustack/gpustack：多机多卡 GPU 调度与共享",
    "dev-4-1": "huggingface/accelerate：分布式训练抽象（DDP / FSDP / DeepSpeed）",
    "dev-4-2": "deepspeedai/DeepSpeed：ZeRO 系列显存优化与并行训练",
    "dev-4-3": "huggingface/picotron：4000 行的 3D 并行极简实现",
    "dev-4-4": "NVIDIA/Megatron-LM：大规模张量并行训练工业实现",
    "dev-4-5": "ray-project/ray：分布式计算底座（训练 + 服务调度）",
    "dev-5-1": "GokuMohandas/Made-With-ML：从设计到部署的端到端 ML 课",
    "dev-5-3": "DataTalksClub/mlops-zoomcamp：免费的 MLOps 体系课",
    "dev-5-4": "mlflow/mlflow：实验追踪 / 模型注册 / 部署的一站式平台",
    "dev-5-5": "wandb/wandb：训练可视化与超参搜索平台",
    "dev-6-1": "langfuse/langfuse：LLM 可观测 + 评测 + 提示管理",
    "dev-6-2": "chiphuyen/machine-learning-systems-design：ML 系统设计讲义",
    "dev-6-3": "Full Stack Deep Learning：部署 / 监控 / 持续学习课",
    # 手撕线
    "lc-1-1": "krahets/hello-algo：动画图解 + 可运行代码的中文算法教程",
    "lc-1-2": "Hello 算法在线阅读：动画 + 交互式练习版",
    "lc-2-1": "youngyangyang04/leetcode-master：代码随想录（按专题排序 + 图解）",
    "lc-3-5": "williamfiset/Algorithms：图论 / 数据结构的参考实现与可视化",
    "lc-2-3": "seanprashad/leetcode-patterns：按套路组织的 LeetCode 题单",
    "lc-2-4": "labuladong/fucking-algorithm：算法思维系列（套路化讲解）",
    "lc-3-1": "labuladong 动态规划系列进阶篇",
    "lc-3-3": "OI Wiki：算法竞赛向的算法与数据结构百科",
    "lc-3-4": "labuladong KMP 字符串匹配讲解",
    "lc-4-1": "LeetCode 热题 HOT 100（官方学习计划）",
    "lc-4-2": "afatcoder/LeetcodeTop：按公司/方向整理的高频题清单",
    "lc-4-3": "Doocs/leetcode：多语言 LeetCode 题解（社区维护）",
    "lc-4-4": "牛客题霸：国内笔试 / 面试真题在线环境",
    "lc-5-1": "Tech Interview Handbook：算法 / 行为面试全流程指南",
    "lc-5-2": "NeetCode：按模式组织的 LeetCode 题单 + 配套视频",
    "lc-5-3": "Doocs/leetcode 题解（行为面试参考）",
    "lc-5-4": "donnemartin/system-design-primer：系统设计入门主题清单",
    "lc-5-5": "ByteByteGoHq/system-design-101：系统设计图解",
    "lc-6-1": "本站内部：从节点完成一键生成复习卡",
    "lc-6-2": "Tech Interview Handbook（复盘与行为面试章节）",
}

# (resource_id, pin_url) → 一行预告，帮读者决定要不要点
# 只补关键 pin（label 只是章节/题号编号的、或本身不够直白的）
PIN_NOTES: dict[tuple[str, str], str] = {
    # hello-algo 章节（label 只有章节名）
    ("lc-1-1", "https://github.com/krahets/hello-algo/blob/main/docs/chapter_computational_complexity/index.md"):
        "复杂度分析的正式定义（时间 / 空间 / 渐近记号 / 权衡）",
    ("lc-1-2", "https://github.com/krahets/hello-algo/blob/main/docs/chapter_array_and_linkedlist/index.md"):
        "数组 / 链表 / 列表，含 LRU 实现的链结构基础",
    ("lc-1-2", "https://github.com/krahets/hello-algo/blob/main/docs/chapter_stack_and_queue/index.md"):
        "栈 / 队列 / 双端队列 / 优先级队列的应用模式",
    ("lc-1-3", "https://github.com/krahets/hello-algo/blob/main/docs/chapter_hashing/index.md"):
        "哈希函数 / 冲突处理 / 哈希表与常见应用",
    ("lc-1-4", "https://github.com/krahets/hello-algo/blob/main/docs/chapter_tree/index.md"):
        "树 / 二叉树 / AVL / 红黑树的概念与遍历",
    ("lc-1-4", "https://github.com/krahets/hello-algo/blob/main/docs/chapter_heap/index.md"):
        "堆 / 完全二叉堆 / Top-K 与堆排序",
    ("lc-2-5", "https://github.com/krahets/hello-algo/blob/main/docs/chapter_sorting/index.md"):
        "11 种排序算法的对比（冒泡 / 快排 / 归并 / 堆排 / 桶排…）",
    # 代码随想录 / leetcode-master 章节
    ("lc-2-1", "https://github.com/youngyangyang04/leetcode-master/blob/master/README.md"):
        "按章节排序的刷题路线与高频题解",
    ("lc-2-1", "https://programmercarl.com/0704.%E4%BA%8C%E5%88%86%E6%9F%A5%E6%89%BE.html"):
        "二分的边界模板与常见题型（左右边界写法）",
    ("lc-2-2", "https://programmercarl.com/0209.%E9%95%BF%E5%BA%A6%E6%9C%80%E5%B0%8F%E7%9A%84%E5%AD%90%E6%95%B0%E7%BB%84.html"):
        "最小子数组：窗口何时扩何时缩",
    ("lc-2-3", "https://github.com/greyireland/algorithm-pattern/tree/master/basic_algorithm"):
        "二分 / 排序 / DP / BFS 的算法模板汇总",
    ("lc-2-4", "https://programmercarl.com/0077.%E7%BB%84%E5%90%88.html"):
        "组合 / 排列 / 子集三套回溯框架",
    ("lc-2-4", "https://github.com/labuladong/facking-algorithm/blob/master/%E7%AE%97%E6%B3%95%E6%80%9D%E7%BB%B4%E7%B3%BB%E5%88%97/%E5%9B%9E%E6%BA%AF%E7%AE%97%E6%B3%95%E8%AF%A6%E8%A7%A3%E4%BF%AE%E8%AE%A2%E7%89%88.md"):
        "回溯剪枝的通用判定与剪枝边界",
    ("lc-3-1", "https://programmercarl.com/0509.%E6%96%90%E6%B3%A2%E9%82%A3%E5%A5%91%E6%95%B0.html"):
        "01 背包的状态定义 / 转移 / 空间压缩",
    ("lc-3-1", "https://github.com/labuladong/facking-algorithm/blob/master/%E5%8A%A8%E6%80%81%E8%A7%84%E5%88%92%E7%B3%BB%E5%88%97/%E5%8A%A8%E6%80%81%E8%A7%84%E5%88%92%E8%AF%A6%E8%A7%A3%E8%BF%9B%E9%98%B6.md"):
        "DP 的「状态 / 选择 / base case」三件套",
    ("lc-3-2", "https://programmercarl.com/0455.%E5%88%86%E5%8F%91%E9%A5%BC%E5%B9%B2.html"):
        "贪心的证明 / 反例 / 与 DP 的取舍",
    ("lc-3-3", "https://github.com/williamfiset/algorithms/tree/master/src/main/java/com/williamfiset/algorithms/graphtheory"):
        "Dijkstra / Bellman-Ford / 拓扑排序的参考实现",
    ("lc-3-3", "https://oi-wiki.org/ds/dsu/"):
        "并查集的路径压缩 + 按秩合并",
    ("lc-3-4", "https://github.com/labuladong/facking-algorithm/blob/master/%E5%8A%A8%E6%80%81%E8%A7%84%E5%88%92%E7%B3%BB%E5%88%97/%E5%8A%A8%E6%80%81%E8%A7%84%E5%88%92%E4%B9%8BKMP%E5%AD%97%E7%AC%A6%E5%8C%B9%E9%85%8D%E7%AE%97%E6%B3%95.md"):
        "KMP 的 next 数组构造与匹配过程",
    ("lc-3-4", "https://oi-wiki.org/string/trie/"):
        "Trie 字典树的插入 / 查询 / 应用",
    ("lc-3-5", "https://github.com/greyireland/algorithm-pattern/blob/master/data_structure/binary_op.md"):
        "位运算常见技巧（lowbit / 异或 / 状态压缩）",
    # 应用 / 算法 / 开发的仓库章节
    ("app-3-1", "https://docs.llamaindex.ai/en/stable/getting_started/starter_example/"):
        "文档加载 → 索引 → 查询的最小可运行示例",
    ("app-3-1", "https://docs.llamaindex.ai/en/stable/understanding/rag/"):
        "RAG 的原理与 LlamaIndex 的 RAG 抽象",
    ("app-3-1", "https://docs.llamaindex.ai/en/stable/module_guides/loading/node_parsers/"):
        "Node Parser：SentenceSplitter / 层级切分 / 元数据保留",
    ("app-3-1", "https://docs.llamaindex.ai/en/stable/module_guides/indexing/"):
        "索引类型与向量库选择指南",
    ("app-3-1", "https://docs.llamaindex.ai/en/stable/module_guides/querying/retriever/retrievers/"):
        "向量检索 / BM25 / 融合检索的选型",
    ("app-3-1", "https://docs.llamaindex.ai/en/stable/module_guides/querying/node_postprocessors/"):
        "重排 / 去重 / 过滤的实现",
    ("app-3-1", "https://docs.llamaindex.ai/en/stable/module_evaluing/"):
        "评估指标 / 数据集 / 评测器",
    ("app-3-1", "https://docs.llamaindex.ai/en/stable/understanding/evaluating/cost_analysis/"):
        "每千次调用的成本构成与优化点",
    ("app-3-1", "https://docs.llamaindex.ai/en/stable/understanding/agent/multi_agent/"):
        "多 Agent 协作模式（主管-工人 / 辩论 / 流水线）",
    ("app-3-1", "https://docs.llamaindex.ai/en/stable/module_guides/mcp/"):
        "把 LlamaIndex 工具暴露为 MCP server",
    ("app-3-2", "https://github.com/datawhalechina/all-in-rag/blob/main/docs/chapter1/01_RAG_intro.md"):
        "RAG 是什么 / 整体流程 / 与微调的边界",
    ("app-3-2", "https://github.com/datawhalechina/all-in-rag/blob/main/docs/chapter2/05_text_chunking.md"):
        "切分策略（按字符 / 按 token / 语义）对比",
    ("app-3-2", "https://github.com/datawhalechina/all-in-rag/blob/main/docs/chapter4/11_hybrid_search.md"):
        "BM25 + 向量融合检索的实战配方",
    ("app-3-2", "https://github.com/datawhalechina/all-in-rag/blob/main/docs/chapter2/04_data_load.md"):
        "多格式文档加载（PDF / Markdown / 数据库）",
    ("app-3-3", "https://github.com/pguso/rag-from-scratch/tree/main/examples/03_text_splitting_and_chunking"):
        "从零实现 5 种切分策略并跑评测",
    ("app-3-5", "https://www.promptfoo.dev/docs/guides/evaluate-rag/"):
        "断言 / 评分器 / 数据集三件套搭 RAG 评测",
    ("app-3-5", "https://github.com/HKUDS/LightRAG/tree/main/examples"):
        "跑起来看 LightRAG 如何组织图谱与检索",
    ("app-3-7", "https://qdrant.tech/documentation/concepts/hybrid-queries/"):
        "向量 + 稀疏双路召回 + RRF 融合",
    ("app-4-1", "https://docs.langchain.com/oss/python/langgraph/graph-api"):
        "State / Node / Edge 的定义与条件边",
    ("app-4-2", "https://docs.langchain.com/oss/python/langgraph/add-memory"):
        "短期 checkpoint + 长期 store 的两层记忆",
    ("app-4-3", "https://docs.langchain.com/oss/python/langgraph/persistence"):
        "checkpoint 的存储后端与中断恢复",
    ("app-4-3", "https://github.com/bojieli/ai-agent-book/tree/main/chapter1/context"):
        "第 1 章配套代码：context 工程实验",
    ("app-4-4", "https://github.com/openai/openai-agents-python/tree/main/examples/agent_patterns"):
        "路由 / 并行 / Agents-as-Tools 的编排范式",
    ("app-4-5", "https://github.com/shareAI-lab/learn-claude-code/tree/main/s08_context_compact"):
        "上下文压缩策略与触发条件",
    ("app-5-1", "https://modelcontextprotocol.io/docs/2026-07-28/learn/server-concepts"):
        "三种能力（tools/resources/prompts）与生命周期",
    ("app-5-1", "https://github.com/modelcontextprotocol/servers/tree/main/src/fetch"):
        "fetch server 源码：从 schema 到工具调用",
    ("algo-2-2", "https://github.com/rasbt/LLMs-from-scratch/blob/main/ch03/01_main-chapter-code/ch03.ipynb"):
        "因果掩码 MHA 的完整实现 + 与官方库对账",
    ("algo-2-4", "https://github.com/rasbt/LLMs-from-scratch/blob/main/ch04/01_main-chapter-code/ch04.ipynb"):
        "GPT 架构逐层搭建 + 张量形状与参数量",
    ("algo-2-4", "https://github.com/karpathy/nanoGPT/blob/master/model.py"):
        "可一口气读完的 GPT 完整实现（300 行）",
    ("algo-2-5", "https://github.com/karpathy/minbpe/blob/master/minbpe/basic.py"):
        "BPE 训练 / 编码 / 解码的极简实现",
    ("algo-2-5", "https://github.com/karpathy/minbpe/blob/master/minbpe/gpt4.py"):
        "GPT-4 的正则表达式驱动的分词拆分",
    ("algo-2-6", "https://github.com/karpathy/llama2.c/blob/master/run.c"):
        "纯 C 的 LLaMA 2 推理：transformer + KV Cache",
    ("algo-3-1", "https://github.com/jingyaogong/minimind/blob/master/trainer/train_pretrain.py"):
        "从零预训练脚本（数据 / tokenizer / loss 一体）",
    ("algo-3-1", "https://github.com/jingyaogong/minimind/blob/master/trainer/train_full_sft.py"):
        "指令微调脚本（含数据模板与对话格式）",
    ("algo-3-1", "https://github.com/jingyaogong/minimind/blob/master/model/model_minimind.py"):
        "26M 参数的 GPT 完整模型定义",
    ("algo-4-2", "https://github.com/huggingface/peft/blob/main/docs/source/package_reference/lora.md"):
        "LoRA 配置项详解（r/alpha/dropout/target_modules）",
    ("algo-4-3", "https://github.com/hiyouga/LLaMA-Factory/tree/main/examples/train_lora"):
        "Qwen3 LoRA SFT / DPO / KTO 一键配置",
    ("algo-4-8", "https://github.com/ConardLi/easy-dataset/blob/main/README.md"):
        "PDF / 网页 → 指令数据集的 GUI 流水线",
    ("algo-4-3", "https://github.com/hiyouga/LLaMA-Factory/blob/main/data/README.md"):
        "数据准备格式与多任务混合配比",
    ("algo-5-7", "https://github.com/rasbt/reasoning-from-scratch/blob/main/ch02/01_main-chapter-code/ch02_main.ipynb"):
        "推理模型训练循环的实现 + 思考长度变化",
    ("algo-6-3", "https://github.com/ggml-org/llama.cpp/blob/master/README.md"):
        "端侧 / CPU 量化推理与 GGUF 格式",
    ("algo-6-1", "https://github.com/Dao-AILab/flash-attention/tree/main/csrc/flash_attn"):
        "CUDA kernel：分块 + online softmax",
    ("algo-6-4", "https://github.com/flashinfer-ai/flashinfer/blob/main/README.md"):
        "可组合的注意力 / 归一化 / 采样 kernel",
    ("algo-6-7", "https://github.com/khangich/machine-learning-interview/blob/master/README.md"):
        "ML/LLM 面试题库与项目复现视角清单",
    ("dev-2-1", "https://docs.vllm.ai/en/latest/getting_started/quickstart.html"):
        "起服务 / 选模型 / 调 batch 的最短路径",
    ("dev-2-1", "https://github.com/vllm-project/vllm/blob/main/benchmarks/README.md"):
        "vLLM 内置的压测工具与指标定义",
    ("dev-2-2", "https://docs.vllm.ai/en/latest/design/overview.html"):
        "调度策略 / 内存池 / PagedAttention 原理",
    ("dev-2-2", "https://docs.sglang.io/docs/advanced_features/server_arguments"):
        "SGLang 服务端启动参数与调优项",
    ("dev-2-3", "https://docs.sglang.ai/backend/server_arguments.html"):
        "SGLang 后端参数与调优（旧站回退）",
    ("dev-4-1", "https://huggingface.co/docs/accelerate/basic_tutorials/launch"):
        "Accelerate launch / 多机多卡启动指南",
    ("dev-4-2", "https://github.com/deepspeedai/DeepSpeed/blob/master/docs/_pages/config-json.md"):
        "DeepSpeed 配置项逐字段说明",
    ("dev-4-3", "https://github.com/huggingface/picotron/blob/main/train.py"):
        "极简分布式训练脚本（数据 / 张量 / 流水线并行的入口）",
    ("dev-5-2", "https://github.com/stas00/ml-engineering/tree/master/training"):
        "显存 / 吞吐 / 并行的排障与最佳实践",
    ("dev-5-2", "https://github.com/stas00/ml-engineering/tree/master/debug"):
        "loss 尖峰 / NaN / 不收敛的定位清单",
    ("dev-6-1", "https://langfuse.com/docs/tracing"):
        "trace / span / generation 的完整结构",
    ("app-6-3", "https://langfuse.com/docs/scores/overview"):
        "人工 / 自动 / LLM-as-judge 三类评分",
    ("app-6-5", "https://dspy.ai/tutorials/"):
        "把 prompt 当编译问题：数据集 → 优化器 → 指标",
    ("app-6-4", "https://docs.litellm.ai/docs/proxy/cost_tracking"):
        "每千次调用的成本分解 + 模型路由",
    ("app-6-1", "https://github.com/NirDiamant/agents-towards-production/tree/main/tutorials"):
        "逐环节教程（tracing / eval / 安全 / 部署）",
    ("app-6-1", "https://www.promptfoo.dev/docs/getting-started/"):
        "promptfoo 快速开始：定义断言 + 跑评测",
    ("app-6-2", "https://www.promptfoo.dev/docs/integrations/ci-cd/"):
        "把评测嵌入 CI（GitHub Actions 等）",
    ("app-4-7", "https://github.com/shareAI-lab/learn-claude-code/tree/main/docs"):
        "Claude Code 文档（与源码拆解配套）",
    ("app-4-9", "https://github.com/All-Hands-AI/OpenHands/tree/main/docs"):
        "OpenHands 架构：事件流 / 沙箱 / 多语言 SDK",
}


def main() -> None:
    # 1) 给 resources.json 加 description
    res_path = API / "resources.json"
    res_doc = json.loads(res_path.read_text(encoding="utf-8"))
    missing = []
    for item in res_doc["items"]:
        if item["id"] in DESCRIPTIONS:
            item["description"] = DESCRIPTIONS[item["id"]]
        elif "description" not in item:
            missing.append(item["id"])
    res_path.write_text(
        json.dumps(res_doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print(f"resources.json: 加 description {len(DESCRIPTIONS)} 个；未覆盖 {len(missing)}")

    # 2) 给节点 pin 加 note
    node_count = 0
    note_count = 0
    for name in ["nodes_l0", "nodes_app", "nodes_algo", "nodes_dev", "nodes_lc"]:
        path = API / f"{name}.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        for node in doc["nodes"]:
            node_count += 1
            for rid, pins in node.get("pins", {}).items():
                for pin in pins:
                    key = (rid, pin["url"])
                    if key in PIN_NOTES:
                        pin["note"] = PIN_NOTES[key]
                        note_count += 1
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"节点文件: 扫描 {node_count} 节点；补 note {note_count} 条")


if __name__ == "__main__":
    main()
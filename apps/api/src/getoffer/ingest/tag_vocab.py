"""题库标签规范词表：canonical 显示名 + 别名归一。

qa_extract 的抽取词表、导入器的 get-or-create、归一脚本都从这里取，
避免"rag/agent/llm基础"这类大小写漂移导致 UI 筛选零命中。
"""

from getoffer.ingest.importers.markdown_repo import normalize_text

# canonical 显示名（与 UI chips 一致）
CANONICAL_TAGS = [
    "LLM基础",
    "Transformer",
    "训练与微调",
    "RAG",
    "Agent",
    "MCP与工具调用",
    "多智能体",
    "推理部署",
    "评测",
    "手撕代码",
    "算法",
    "场景设计",
    "HR面",
    "机器学习基础",
    "安全",
    "数据合成",
    "上下文工程",
    # 工程能力维度（spec 续二十）：只收大模型应用岗真实会问的语言/后端基础与项目追问
    "Python",
    "Java",
    "后端工程",
    "项目深挖",
]

# 存量别名/变体 → canonical（显式数据表，不做模糊猜测）
ALIASES: dict[str, str] = {
    "rag": "RAG",
    "检索增强": "RAG",
    "检索增强生成": "RAG",
    "agent": "Agent",
    "智能体": "Agent",
    "llm基础": "LLM基础",
    "大模型基础": "LLM基础",
    "transformer": "Transformer",
    "mcp与工具调用": "MCP与工具调用",
    "mcp": "MCP与工具调用",
    "hr面": "HR面",
    "安全合规": "安全",
    "质量保障": "评测",
    "prompt engineering": "LLM基础",
    "prompt工程": "LLM基础",
    "python": "Python",
    "python基础": "Python",
    "java": "Java",
    "后端": "后端工程",
    "backend": "后端工程",
    "工程能力": "后端工程",
    "项目": "项目深挖",
    "项目拷打": "项目深挖",
    "项目追问": "项目深挖",
}


def canonical_tag_name(raw: str) -> str:
    """任意来源的标签名 → canonical 显示名。

    先精确匹配 canonical/别名，再按"忽略大小写与空白"匹配 canonical，
    最后返回原样（由调用方决定是否创建新标签）。
    """
    name = raw.strip()
    if name in CANONICAL_TAGS:
        return name
    alias_hit = ALIASES.get(normalize_text(name))
    if alias_hit:
        return alias_hit
    for canonical in CANONICAL_TAGS:
        if normalize_text(name) == normalize_text(canonical):
            return canonical
    return name

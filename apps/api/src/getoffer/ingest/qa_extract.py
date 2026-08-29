"""LLM 结构化抽取：markdown 章节 → 题目条目（spec §3）。

标签使用受控词表（TAG_FAMILIES 12 族），LLM 只能从中选择；
未知标签保留原样入库由人审处理，不静默丢弃。
"""

from pydantic import BaseModel, Field

from getoffer.ingest.markdown_ast import Section
from getoffer.llm.gateway import LLMGateway

TAG_FAMILIES = [
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
]

QuestionKind = str  # knowledge | handwritten_code | algorithm | scenario | behavior（由 QAItem Literal 约束）

TRACKS = ["大模型应用", "大模型算法", "大模型应用算法", "视觉算法", "通用基础"]

TRACK_GUIDE = """岗位大类判定：
- 大模型应用：Agent/RAG/MCP/多智能体/Prompt 工程/评测落地/推理部署等工程与系统实现题（通常说的 Agent 应用就在这类）
- 大模型算法：预训练/SFT/RLHF/强化学习/蒸馏/模型结构(注意力/位置编码)/解码采样/Scaling 等训练与原理题
- 大模型应用算法：应用侧的算法问题（检索算法/重排/embedding 微调/RAG 评测算法/Agent 规划/数据合成）
- 视觉算法：CV 经典与视觉模型题（图像分类/检测/分割/CNN/ViT/多模态视觉理解）
- 通用基础：LeetCode 算法、计算机网络/操作系统等工程基础、HR 面（机器学习/CV 基础请优先归入机器学习基础或视觉算法）"""


class QAItem(BaseModel):
    stem: str = Field(min_length=6, max_length=500)
    answer: str | None = None
    tags: list[str] = Field(default_factory=list, max_length=6)
    kind: str = Field(default="knowledge", pattern="^(knowledge|handwritten_code|algorithm|scenario|behavior)$")
    track: str | None = Field(
        default=None, pattern="^(大模型应用|大模型算法|大模型应用算法|视觉算法|通用基础)$"
    )
    difficulty: int = Field(default=3, ge=1, le=5)


class QABatch(BaseModel):
    items: list[QAItem] = Field(max_length=20)


EXTRACTION_SYSTEM = f"""你是题库数据工程师。输入是来自开源面试知识仓库的一个或多个 markdown 章节文本。
任务：抽取其中"真实的面试问题/知识点条目"，每条输出：
- stem：问题原文（事实性题干，保留原意，去掉 markdown 记号与编号）
- answer：该来源给出的答案要点（允许压缩；来源没有答案则留空）
- tags：从以下词表中选 1-3 个：{'、'.join(TAG_FAMILIES)}
- kind：knowledge（知识八股）/ handwritten_code（手撕代码）/ algorithm（LeetCode 类算法题）/ scenario（场景设计）/ behavior（行为面）
- track：岗位大类，从以下词表选 1 个：{'、'.join(TRACKS)}
- difficulty：1-5

规则：
1. 不编造来源中不存在的问题；叙述性内容不是问题时跳过。
2. 一章包含多个小问题时拆成多条。
3. answer 忠于原文，不改写技术结论。
4. 标签判定：手撕代码 ONLY 用于"要求手写实现代码"的题（如"手撕 Attention"）；
   概念原理题（含 CNN/卷积/反向传播等深度学习基础）用"机器学习基础"或"LLM基础"，不要用"手撕代码"。

{TRACK_GUIDE}"""

STEMS_ONLY_SUFFIX = "\n\n【本题库来源为无 license 仓库，只允许使用题干。所有条目 answer 一律留空。】"


async def extract_from_sections(
    sections: list[Section],
    gateway: LLMGateway,
    *,
    source_name: str,
    allow_answers: bool,
    batch_size: int = 6,
) -> list[QAItem]:
    system = EXTRACTION_SYSTEM + ("" if allow_answers else STEMS_ONLY_SUFFIX)
    items: list[QAItem] = []
    for start in range(0, len(sections), batch_size):
        chunk = sections[start : start + batch_size]
        blocks: list[str] = []
        for index, section in enumerate(chunk, start=1):
            blocks.append(f"## 片段 {index}（标题：{section.title}）\n\n{section.text}")
        batch = await gateway.complete_structured(
            [{"role": "user", "content": f"来源仓库：{source_name}\n\n" + "\n\n---\n\n".join(blocks)}],
            QABatch,
            system=system,
            purpose="ingest.extract_qa",
        )
        if not allow_answers:
            batch = QABatch(items=[item.model_copy(update={"answer": None}) for item in batch.items])
        items.extend(item for item in batch.items if item.stem.strip())
    return items

"""面经结构化抽取：帖子可见文本 → 公司-岗位-轮次-问题树（F1，spec §4）。

忠实性规则与题库抽取（qa_extract）一致：不编造文本中不存在的问题；
广告/资料帖/讨论帖判定为非面经（is_interview_experience=false），宁缺毋滥。
"""

from pydantic import BaseModel, Field

from getoffer.llm.gateway import LLMGateway


class ExperienceItemDraft(BaseModel):
    question_text: str = Field(min_length=4, max_length=400)
    note: str | None = Field(default=None, max_length=300)
    followups: list[str] = Field(default_factory=list, max_length=5)


class ExperienceDraft(BaseModel):
    is_interview_experience: bool
    company: str | None = Field(default=None, max_length=32)
    role: str | None = Field(default=None, max_length=64)
    rounds: str | None = Field(default=None, max_length=64)
    occurred_on: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    result: str | None = Field(default=None, pattern="^(通过|未通过|未知)$")
    items: list[ExperienceItemDraft] = Field(default_factory=list, max_length=30)


EXPERIENCE_SYSTEM = """你是面经数据工程师。输入是社区一条帖子的可见文本（可能是面经、广告、资料分享或讨论）。
任务：判断是否为真实求职面经；若是，抽取结构化字段：
- company：面试公司，保留原文写法（如"网易""B站""阿里淘天"；无法判断则留空）
- role：应聘岗位（如"大模型算法""Agent 开发"）
- rounds：覆盖轮次（如"一面"或"一面、二面"）
- occurred_on：面试日期 YYYY-MM-DD（原文只有相对时间或无日期则留空）
- result：结果（通过/未通过/未知）
- items：问题列表。question_text=问题原文（去编号，保留原意）；
  note=该题上下文（候选人怎么答的/面试官反应/属于哪一轮）；
  followups=该题的追问（原文有才写）

规则：
1. 不编造。预览被截断时只抽取可见部分，不要补全没出现的问题。
2. 广告/引流/资料帖/纯讨论 → is_interview_experience=false 且 items 留空。
3. 一个帖子含多轮面试时全部抽出，rounds 汇总。
4. 非问题内容（自我介绍要求、闲聊、评价）不进 items，可作对应题的 note。
5. 可见文本中抽不出任何问题时，is_interview_experience 必须为 false（没有问题内容的"面经"不入库）。"""


async def extract_experience(
    text: str, gateway: LLMGateway, *, source_name: str
) -> ExperienceDraft:
    return await gateway.complete_structured(
        [
            {
                "role": "user",
                "content": f"来源渠道：{source_name}\n\n帖子文本：\n{text[:6000]}",
            }
        ],
        ExperienceDraft,
        system=EXPERIENCE_SYSTEM,
        purpose="ingest.extract_experience",
    )


class ExperienceBatchEntry(BaseModel):
    """批量路径的独立输入记录；不能把一条输入自行拆成多场。"""

    post_id: str
    draft: ExperienceDraft


class ExperienceBatch(BaseModel):
    entries: list[ExperienceBatchEntry] = Field(max_length=5)


async def extract_experience_batch(
    posts: dict[str, str], gateway: LLMGateway, *, source_name: str
) -> ExperienceBatch:
    """新增批量路径；保留原有单帖函数、schema 与调用行为不变。

    每个输入已经由渠道确定为一个独立记录；每批最多 5 篇，输出必须逐一对应。
    题干要求原文摘录，调用方进一步检查证据覆盖后再交给原有入库函数。
    """
    import json

    from getoffer.errors import StructuredOutputError

    if not 1 <= len(posts) <= 5:
        raise ValueError("每批输入必须为 1 至 5 条")
    result = await gateway.complete_structured(
        [{"role": "user", "content": json.dumps(
            {"source_name": source_name, "posts": {key: text[:6000] for key, text in posts.items()}},
            ensure_ascii=False,
        )}],
        ExperienceBatch,
        system=EXPERIENCE_SYSTEM + """

这是批量任务。posts 的每个键为 post_id，分别应用上述规则，返回 entries。
必须为每个 post_id 返回恰好一个 entry，不能合并输入或凭公司/轮次增加记录。
question_text 必须逐字摘取该帖可见原文中的完整问题或明确面试考点（可去掉编号），
禁止根据“项目拷打/介绍论文”等概述展开未出现的问题，也不要翻译、润色或补成问句。
每个 question_text 长度必须为 4 至 400 字符。只有“场景题”“手撕”“反问”“项目拷打”等
无具体题目的标签直接省略，不要为了达到长度限制编造或扩写。没有剩余题目则拒收。
仅自我介绍、求职动机、到岗时间、面试感受不算具体考题；省略号截断的题目不要入库。
只说“某技术/某场景/A技术”而未提供实际技术名称或任务的吐槽，也不能推演成题干。
每条面经 items 最多 30 项，超过时只选有具体细节的 30 项，不得输出第 31 项。
过长题干仅摘一个不超过 400 字符的原文连续片段；原文中的答案或括号答案不属于题干。
rounds 轮次字段最多 32 字符，可简写为一面/二面/终面，不要粘贴冗长标题。
如果输入仍混杂多个不同人的面经、无法确定单场边界，应拒收，不能把它们合并成一次面试。
未知公司、日期、结果留空；学校、作者职业、发布日不是面试公司/岗位/面试日。
纯题库/教程/模拟面试/推测问题/没有实际问答的求助帖拒收。
对明确按单场记录的公开汇总摘录可以抽取，但只摘可见题干，不抄参考答案。
这一批只取题干：note 一律 null，followups 仅在源文明确标为追问且逐字存在时返回。
""",
        purpose="ingest.extract_experience_batch",
    )
    keys = [entry.post_id for entry in result.entries]
    if len(keys) != len(set(keys)) or set(keys) != set(posts):
        raise StructuredOutputError("面经批量抽取的 post_id 与输入不一一对应")
    return result

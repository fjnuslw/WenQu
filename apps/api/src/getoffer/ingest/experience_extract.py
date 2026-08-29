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

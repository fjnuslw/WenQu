"""题目分类管道：一次 LLM 调用同时产出 岗位大类(track) + 厂商标注（spec F2）。

厂商标注是 AI 推断（question_companies 初始 freq=1），不是事实统计；频率榜随
真实面经挖掘与 UGC 爆料逐步校准。宁缺毋滥：LLM 只允许输出高把握的 0-3 家，
track 只能使用四类词表，词表外输出在入库前被硬校验丢弃。
"""

from pydantic import BaseModel, Field

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from getoffer.errors import NotFound
from getoffer.llm.gateway import LLMGateway
from getoffer.models import Company, Question, QuestionCompany

TRACKS = ["大模型应用", "大模型算法", "大模型应用算法", "视觉算法", "通用基础"]

# (公司名, 别名, logo 路径)；logo 为 None 表示待补充素材
DEFAULT_COMPANIES = [
    ("字节跳动", ["字节", "bytedance", "抖音", "豆包"], "/logos/bytedance.png"),
    ("阿里巴巴", ["阿里", "alibaba", "淘天", "通义"], "/logos/alibaba.png"),
    ("蚂蚁集团", ["蚂蚁", "ant"], "/logos/antgroup.png"),
    ("腾讯", ["tencent", "腾讯云", "混元"], "/logos/tencent.png"),
    ("百度", ["baidu", "文心"], "/logos/baidu.png"),
    ("美团", ["meituan"], "/logos/meituan.png"),
    ("快手", ["kuaishou"], "/logos/kuaishou.png"),
    ("拼多多", ["pinduoduo", "temu"], "/logos/pinduoduo.png"),
    ("小红书", ["xhs", "rednote"], "/logos/xiaohongshu.png"),
    ("小米", ["xiaomi"], "/logos/xiaomi.png"),
    ("京东", ["jd"], "/logos/jd.png"),
    ("网易", ["netease"], "/logos/netease.png"),
    ("哔哩哔哩", ["bilibili", "b站"], "/logos/bilibili.png"),
    ("微博", ["weibo"], "/logos/weibo.png"),
    ("华为", ["huawei", "昇腾"], "/logos/huawei.png"),
    ("DeepSeek", ["deepseek", "深度求索"], "/logos/deepseek.png"),
    ("月之暗面", ["moonshot", "kimi"], "/logos/moonshot.png"),
    ("MiniMax", ["minimax", "海螺"], "/logos/minimax.png"),
    ("智谱AI", ["zhipu", "glm", "清言"], "/logos/zhipuai.png"),
    ("阶跃星辰", ["stepfun", "阶跃"], None),
    ("科大讯飞", ["iflytek", "讯飞星火"], "/logos/iflytek.png"),
    ("商汤", ["sensetime"], "/logos/sensetime.png"),
    ("微软", ["microsoft", "msra"], "/logos/microsoft.png"),
    ("Google", ["google", "谷歌"], "/logos/google.png"),
    ("亚马逊", ["amazon", "aws"], "/logos/amazon.png"),
]

DEFAULT_COMPANY_NAMES = [name for name, _, _ in DEFAULT_COMPANIES]

TRACK_GUIDE = """岗位大类判定：
- 大模型应用：Agent/RAG/MCP/多智能体/Prompt 工程/评测落地/推理部署等工程与系统实现题（通常说的 Agent 应用就在这类）
- 大模型算法：预训练/SFT/RLHF/强化学习/蒸馏/模型结构(注意力/位置编码)/解码采样/Scaling 等训练与原理题
- 大模型应用算法：应用侧的算法问题（检索算法/重排/embedding 微调/RAG 评测算法/Agent 规划/数据合成）
- 视觉算法：CV 经典与视觉模型题（图像分类/检测/分割/CNN/ViT/多模态视觉理解）
- 通用基础：LeetCode 算法、计算机网络/操作系统等工程基础、HR 面（机器学习/CV 基础请优先归入机器学习基础或视觉算法）"""


class CompanyTagItem(BaseModel):
    question_id: int
    track: str | None = Field(
        default=None, pattern="^(大模型应用|大模型算法|大模型应用算法|视觉算法|通用基础)$"
    )
    companies: list[str] = Field(default_factory=list, max_length=3)


class CompanyTagBatch(BaseModel):
    """LLM 输出：题目 id → 岗位大类 + 高把握公司列表（0-3 家）。"""

    items: list[CompanyTagItem] = Field(max_length=50)


def classify_system_prompt(company_names: list[str]) -> str:
    return (
        "你是面试题库的标注员，完成两个任务：岗位大类判定 + 厂商标注。\n"
        "公司词表：" + "、".join(company_names) + "。\n\n"
        "厂商标注规则：\n"
        "1. 宁缺毋滥：只输出有把握的，最多 3 家，可以为 0 家。\n"
        "2. 通用性题目（LeetCode 经典算法、Transformer 基本原理）可标主流大厂；\n"
        "   与某家产品强相关的题（如 RAG 落地、Agent 平台）标对应强相关公司。\n"
        "3. 不要根据题目来源仓库猜测公司；只依据题目内容本身。\n"
        "4. companies 只能使用词表中的名称原文。\n\n"
        + TRACK_GUIDE
    )


async def _get_or_create_company(session: AsyncSession, name: str) -> Company:
    existing = await session.scalar(select(Company).where(Company.name == name))
    if existing is not None:
        return existing
    logo = next((entry_logo for cand, _, entry_logo in DEFAULT_COMPANIES if cand == name), None)
    company = Company(name=name, aliases=[], logo=logo)
    session.add(company)
    await session.flush()
    return company


async def seed_companies(session: AsyncSession) -> int:
    """把厂商词表（含 logo 路径，缺失为 NULL 待补素材）写入 companies 表（幂等，且补空 logo）。"""
    count = 0
    for name, aliases, logo in DEFAULT_COMPANIES:
        existing = await session.scalar(select(Company).where(Company.name == name))
        if existing is None:
            session.add(Company(name=name, aliases=aliases, logo=logo))
            count += 1
        elif existing.logo is None and logo:
            existing.logo = logo
    await session.flush()
    return count


async def classify_unclassified_questions(
    session: AsyncSession,
    gateway: LLMGateway,
    *,
    limit: int = 20,
) -> dict:
    """为「待分类」题目做一轮推断。

    待分类 = track 为空 OR 从未被尝试过（classify_attempted_at 为空）。
    一轮结束后所有入选项都打上尝试标记出池——"无把握厂商"是合法终态，
    否则按 id 升序会永远选中同一批题，后面的积压永远轮不到。
    """
    names = [row for row in (await session.scalars(select(Company.name))).all()]
    if not names:
        raise NotFound("companies 表为空：先调用 seed-companies")

    rows = (
        (
            await session.execute(
                select(Question)
                .where(
                    Question.track.is_(None) | Question.classify_attempted_at.is_(None)
                )
                .order_by(Question.id)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return {"attempted": 0, "classified": 0, "track_set": 0, "remaining": 0}

    payload = "\n\n".join(
        f"题目 id={q.id}（当前大类：{q.track or '未分类'}）：{q.stem[:300]}" for q in rows
    )
    batch = await gateway.complete_structured(
        [{"role": "user", "content": payload}],
        CompanyTagBatch,
        system=classify_system_prompt(names),
        purpose="classify.companies",
    )
    valid_names = set(names)
    id_to_question = {q.id: q for q in rows}
    company_tags = 0
    track_set = 0
    for item in batch.items:
        question = id_to_question.get(item.question_id)
        if question is None:
            continue
        if item.track and question.track is None:
            question.track = item.track  # 只补空值，不覆盖已有判定
            track_set += 1
        for company_name in item.companies:
            if company_name not in valid_names:
                continue  # 词表外标注直接丢弃（prompt 约束的硬校验）
            company = await _get_or_create_company(session, company_name)
            exists = await session.scalar(
                select(QuestionCompany).where(
                    QuestionCompany.question_id == question.id,
                    QuestionCompany.company_id == company.id,
                )
            )
            if exists is None:
                session.add(QuestionCompany(question_id=question.id, company_id=company.id, freq=1))
                company_tags += 1
    # 无论 LLM 是否给出标注，入选项全部标记为已尝试（出池）
    for question in rows:
        question.classify_attempted_at = func.now()
    await session.commit()

    remaining_row = (
        await session.execute(
            select(Question.id)
            .where(Question.track.is_(None) | Question.classify_attempted_at.is_(None))
            .limit(1)
        )
    ).first()
    return {
        "attempted": len(rows),
        "classified": company_tags,
        "track_set": track_set,
        "remaining": 0 if remaining_row is None else 1,
    }

"""模拟面试组卷 API（F3 · I1）：检索增强的确定性组卷。

设计原则（spec §4 F3 / D5）：
- 检索与组卷在 api 侧完成（候选池=公司频率榜 ∪ 简历考点标签命中；追问素材=该公司真实面经的
  追问链），LLM 只做"从候选池选 id + 本地化展示题干 + 分配追问素材 + 写简报"——id 越池即丢弃，
  不足按频率榜确定性补齐。canonical 题干始终保留，面试官 agent（apps/agents）只消费受验证的
  display_stem 和简历证据锚点，保持题单驱动与收敛。
- 简历画像（resumes.parsed）提供 exam_tags/highlights；面经追问来自 experience_items 的
  子节点（parent_id 非空即真实追问）。
"""

from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from getoffer.api.deps import get_db_session, get_gateway
from getoffer.errors import NotFound, StructuredOutputError
from getoffer.interview import (
    ResumeAnchor,
    extract_resume_anchors,
    resume_question_budget,
    resume_question_stem,
    select_resume_anchors,
    validate_display_stem,
)
from getoffer.llm.gateway import LLMGateway
from getoffer.models import Company, Experience, ExperienceItem, Question, QuestionCompany, Resume, Tag

router = APIRouter(prefix="/api/interview", tags=["interview"])

_EAGER = (
    selectinload(Question.tags),
    selectinload(Question.company_stats).selectinload(QuestionCompany.company),
)

DEFAULT_KINDS = ["knowledge", "handwritten_code", "algorithm", "scenario"]
POOL_LIMIT = 40  # 候选池上限（LLM 定卷的输入预算）
PROBE_POOL_LIMIT = 40  # 追问素材池上限


class InterviewPlanRequest(BaseModel):
    company: str | None = None
    track: str | None = None
    kinds: list[str] = Field(default_factory=lambda: list(DEFAULT_KINDS), max_length=5)
    size: int = Field(default=8, ge=3, le=20)
    resume_id: int | None = None
    language: Literal["zh-CN", "en-US"] = "zh-CN"


class PlanQuestion(BaseModel):
    id: int
    stem: str
    display_stem: str
    kind: str
    track: str | None
    difficulty: int
    answer: str | None
    tags: list[str]
    companies: list[str]
    source: Literal["bank", "resume"]
    grounding: dict[str, str] | None = None
    probes: list[str] = Field(default_factory=list, max_length=3)


class ProbeAssignment(BaseModel):
    question_id: int
    probes: list[str] = Field(default_factory=list, max_length=3)


class QuestionPresentation(BaseModel):
    question_id: int
    display_stem: str = Field(min_length=1, max_length=240)


class ComposedPlan(BaseModel):
    """LLM 定卷输出：只能从候选池选 id（越池硬校验丢弃）。"""

    question_ids: list[int] = Field(max_length=20)
    question_presentations: list[QuestionPresentation] = Field(default_factory=list, max_length=20)
    probe_assignments: list[ProbeAssignment] = Field(default_factory=list, max_length=20)
    brief: str = Field(default="", max_length=800)


def _compose_system_prompt(language: Literal["zh-CN", "en-US"]) -> str:
    presentation_rule = (
        "每道入选题生成自然、口语化的中文 display_stem；提问句法必须是中文，但保留 RAG、ACL、API、"
        "Embedding、类名、函数名等必要技术标识。"
        if language == "zh-CN"
        else "每道入选题生成自然、口语化的英文 display_stem。"
    )
    return (
        "你是大模型岗位的面试组卷官。输入：候选人简历画像、候选题目池（id/stem/类型/标签/难度/答案要点）、"
        "该公司真实面经的追问素材池。任务四件事：\n"
        "1. 定卷：从候选题目池中选出指定数量的题目，输出池内 id 原文（不得编造 id）。\n"
        "   配比：约一半选与候选人技术栈/项目考点对应的题（押题），其余覆盖该公司高频题；\n"
        "   若池中有 scenario（场景设计）或 handwritten_code（手撕）题，至少各含 1 道。\n"
        "2. 分配追问：为每道题从追问素材池挑 0-2 条与该题知识相关的真实追问（宁缺毋滥，不相关不给）。\n"
        "3. 候选人展示：为每个 question_id 输出且只输出一个对应 question_presentations 项。"
        f"{presentation_rule}保持原题考察意图，不增加答案或候选人事实；每题只保留一个主要问题。\n"
        "4. 写简报 brief：2-3 句候选人画像与本场考察重点，给面试官看，不念给候选人。\n"
        "输出严格按 Schema；brief 用中文。"
    )


def _profile_prompt(profile: dict[str, Any] | None, anchors: list[ResumeAnchor]) -> str:
    if profile is None:
        return "未使用简历；只按目标岗位、公司频率与题型覆盖组卷。"
    tech_stack = profile.get("tech_stack") or []
    anchor_lines = "\n".join(f"- {anchor.prompt_line()}" for anchor in anchors) or "- 未抽取到声明"
    return (
        f"求职方向：{profile.get('role_target') or '未标注'}\n"
        f"技术栈：{'、'.join(str(item) for item in tech_stack[:15]) or '未提取'}\n"
        f"真实声明锚点（只用于相关性判断，不得补充事实）：\n{anchor_lines}"
    )


def _presentation_for(
    question: Question,
    presentations: dict[int, str],
    language: Literal["zh-CN", "en-US"],
) -> str:
    candidate = presentations.get(question.id)
    if candidate is None:
        # Planner 漏项时，只有 canonical 本身已经符合目标语言才可复用；禁止英文题静默泄漏。
        candidate = question.stem
    try:
        return validate_display_stem(candidate, language)
    except ValueError as exc:
        raise StructuredOutputError(
            "面试题展示语言校验失败",
            details={"question_id": question.id, "language": language, "error": str(exc)},
        ) from exc


async def _load_resume_profile(session: AsyncSession, resume_id: int) -> dict[str, Any]:
    row = await session.get(Resume, resume_id)
    if row is None:
        raise NotFound(f"简历不存在: {resume_id}")
    parsed = row.parsed or {}
    if not parsed:
        raise NotFound(f"简历 {resume_id} 缺少解析画像（parsed 为空），请重新上传")
    return parsed


async def _company_probe_pool(session: AsyncSession, company_id: int) -> list[str]:
    """该公司真实面经的追问链（experience_items 子节点），去重截断。"""
    rows = (
        await session.scalars(
            select(ExperienceItem.question_text)
            .join(Experience, Experience.id == ExperienceItem.experience_id)
            .where(Experience.company_id == company_id, ExperienceItem.parent_id.is_not(None))
            .group_by(ExperienceItem.question_text)
            .limit(PROBE_POOL_LIMIT)
        )
    ).all()
    return [text for text in rows if text and len(text) >= 6]


@router.post("/plan")
async def create_plan(
    request: InterviewPlanRequest,
    session: AsyncSession = Depends(get_db_session),
    gateway: LLMGateway = Depends(get_gateway),
) -> dict[str, Any]:
    conditions = []
    if request.kinds:
        conditions.append(Question.kind.in_(request.kinds))
    if request.track:
        conditions.append(Question.track == request.track)

    company: Company | None = None
    if request.company:
        company = await session.scalar(select(Company).where(Company.name == request.company))
        if company is None:
            raise NotFound(f"未知公司: {request.company}")
        conditions.append(
            Question.id.in_(
                select(QuestionCompany.question_id).where(QuestionCompany.company_id == company.id)
            )
        )

    stmt = select(Question).where(*conditions).options(*_EAGER)
    if company is not None:
        # 该公司频率降序（CodeTop 范式），随机打散并列
        stmt = (
            stmt.join(
                QuestionCompany,
                (QuestionCompany.question_id == Question.id)
                & (QuestionCompany.company_id == company.id),
            )
            .order_by(QuestionCompany.freq.desc(), func.random())
        )
    else:
        stmt = stmt.order_by(func.random())

    pool_total = await session.scalar(select(func.count()).select_from(Question).where(*conditions))
    rows = (await session.scalars(stmt.limit(POOL_LIMIT))).unique().all()

    # 简历画像：exam_tags 命中的题并入候选池（与频率榜求并，去重）
    resume_profile: dict[str, Any] | None = None
    if request.resume_id is not None:
        resume_profile = await _load_resume_profile(session, request.resume_id)
        exam_tags = [str(tag) for tag in resume_profile.get("exam_tags") or []]
        if exam_tags:
            tagged_rows = (
                (
                    await session.scalars(
                        select(Question)
                        .join(Question.tags)
                        .where(Tag.name.in_(exam_tags))
                        .options(*_EAGER)
                        .order_by(func.random())
                        .limit(20)
                    )
                )
                .unique()
                .all()
            )
            seen_ids = {q.id for q in rows}
            rows = list(rows) + [q for q in tagged_rows if q.id not in seen_ids]

    anchors = extract_resume_anchors(resume_profile or {})
    anchor_budget = resume_question_budget(request.size, len(anchors)) if resume_profile is not None else 0
    selected_anchors = select_resume_anchors(anchors, anchor_budget)
    bank_target = request.size - len(selected_anchors)

    picked: list[Question] = []
    probe_map: dict[int, list[str]] = {}
    presentation_map: dict[int, str] = {}
    brief = ""

    if rows and bank_target > 0:
        # LLM 定卷：选 id + 本地化展示 + 分配追问 + 简报（id 越池丢弃，不足按序补齐）
        probe_pool = await _company_probe_pool(session, company.id) if company is not None else []
        candidates_text = "\n\n".join(
            f"id={q.id} [{q.kind}] 标签:{','.join(t.name for t in q.tags) or '无'} 难度:{q.difficulty}\n"
            f"题干:{q.stem[:150]}\n答案要点:{(q.answer or '无')[:160]}"
            for q in rows
        )
        probes_text = "\n".join(f"- {probe}" for probe in probe_pool) or "（该公司暂无面经追问素材）"
        profile_text = _profile_prompt(resume_profile, anchors)
        composed = await gateway.complete_structured(
            [
                {
                    "role": "user",
                    "content": (
                        f"## 候选人画像\n{profile_text}\n\n"
                        f"## 面试语言\n{request.language}\n\n"
                        f"## 题库题目标数量\n{bank_target} 道"
                        "（简历深挖题由 Harness 另行生成，不计入此处）\n\n"
                        f"## 候选题目池（共 {len(rows)} 道）\n{candidates_text}\n\n"
                        f"## 该公司面经追问素材池\n{probes_text}"
                    ),
                }
            ],
            ComposedPlan,
            system=_compose_system_prompt(request.language),
            purpose="interview.compose_plan",
        )
        by_id = {q.id: q for q in rows}
        valid_ids = [qid for qid in composed.question_ids if qid in by_id]
        seen: set[int] = set()
        for qid in valid_ids:
            if qid not in seen:
                seen.add(qid)
                picked.append(by_id[qid])
        # 不足按原序（频率榜序）确定性补齐——显式行为，不是静默降级
        for q in rows:
            if len(picked) >= bank_target:
                break
            if q.id not in seen:
                seen.add(q.id)
                picked.append(q)
        picked = picked[:bank_target]
        assignment_map = {a.question_id: a.probes for a in composed.probe_assignments}
        raw_presentations = {
            item.question_id: item.display_stem.strip() for item in composed.question_presentations
        }
        for q in picked:
            presentation_map[q.id] = _presentation_for(q, raw_presentations, request.language)
            probes = [str(p) for p in assignment_map.get(q.id, []) if str(p).strip()]
            if probes:
                probe_map[q.id] = probes[:3]
        brief = composed.brief.strip()

    resume_questions = []
    for ordinal, anchor in enumerate(selected_anchors):
        stem = validate_display_stem(
            resume_question_stem(anchor, language=request.language, ordinal=ordinal),
            request.language,
        )
        resume_questions.append(
            {
                "id": -(ordinal + 1),
                "stem": stem,
                "display_stem": stem,
                "kind": "experience" if anchor.kind == "experience" else "project",
                "track": request.track,
                "difficulty": 2,
                "answer": None,
                "tags": [],
                "companies": [company.name] if company is not None else [],
                "source": "resume",
                "grounding": {
                    "kind": anchor.kind,
                    "label": anchor.label,
                    "evidence": anchor.evidence,
                },
                "probes": [],
            }
        )

    bank_questions = [
        {
            "id": q.id,
            "stem": q.stem,
            "display_stem": presentation_map[q.id],
            "kind": q.kind,
            "track": q.track,
            "difficulty": q.difficulty,
            "answer": q.answer,
            "tags": [tag.name for tag in q.tags],
            "companies": [item.company.name for item in q.company_stats],
            "source": "bank",
            "grounding": None,
            "probes": probe_map.get(q.id, []),
        }
        for q in picked
    ]

    return {
        "total_pool": pool_total or 0,
        "brief": brief,
        "resume_used": resume_profile is not None,
        "language": request.language,
        "resume_question_count": len(resume_questions),
        "questions": [*resume_questions, *bank_questions],
    }

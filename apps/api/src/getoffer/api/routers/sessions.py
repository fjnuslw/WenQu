"""面试会话与评分报告 API（F3 · I1 里程碑第一块）。

agents 服务把面试过程以 JSONL append-only 落盘（spec §5.2）；本路由读取日志、
用 LLM 按多维 rubric 评分并持久化——失分点回流 SM-2 的数据源（F6）。
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from getoffer.api.deps import get_db_session, get_gateway, get_settings
from getoffer.errors import NotFound
from getoffer.llm.gateway import LLMGateway
from getoffer.models import InterviewSession, ReviewItem

router = APIRouter(prefix="/api/sessions", tags=["sessions"])

MAX_LOG_ENTRIES = 80  # 防止超长面试撑爆上下文


class EvidenceRef(BaseModel):
    """证据链：结论 → 候选人原话 / 面试官引用的代码位置（G1 证据链报告）。"""

    kind: Literal["quote", "code"] = Field(description="quote=候选人原话；code=对话中引用的代码位置")
    quote: str = Field(default="", max_length=300, description="原话摘录（kind=quote）")
    file: str | None = Field(default=None, max_length=200, description="相对路径（kind=code，来自面试官的 引用）")
    line: int | None = Field(default=None, ge=1)


class ReportScoreItem(BaseModel):
    dimension: str = Field(description="评分维度：理解深度/设计决策质量/表达结构/量化口径/诚实度 之一")
    score: int = Field(ge=1, le=5)
    comment: str
    evidence: list[EvidenceRef] = Field(default_factory=list, max_length=4)


class WeaknessItem(BaseModel):
    """失分点带证据：回流 SM-2 时保留代码锚点，复习时能回看现场。"""

    text: str = Field(description="失分点/盲区，具体到知识点")
    tags: list[str] = Field(default_factory=list, max_length=3, description="涉及的知识标签（从指定词表选）")
    evidence: list[EvidenceRef] = Field(default_factory=list, max_length=3)


class InterviewReport(BaseModel):
    summary: str = Field(description="3-5 句总体评价")
    scores: list[ReportScoreItem] = Field(min_length=3, max_length=6)
    strengths: list[str] = Field(max_length=6)
    weaknesses: list[WeaknessItem] = Field(max_length=8)
    review_suggestions: list[str] = Field(max_length=6, description="可执行的复习建议，注明涉及的知识标签")


REPORT_SYSTEM = """你是大模型应用/Agent 岗位的资深面试评价官。输入是一场 AI 模拟面试/项目拷打的完整记录（含导演指令，可据此理解每个问题的考察意图，但不要评价导演指令本身）。
按以下维度打分（1-5 分）并给出具体证据：
- 理解深度：是否讲到实现层与原理层，还是停留在名词罗列
- 设计决策质量：是否说清"为什么这么选、代价是什么"
- 表达结构：总分总、是否有量化口径、是否答非所问
- 诚实度：被追问到不会时是否坦诚，有没有编造

证据链（重要）：
- 每个维度的 comment 论断必须配 evidence：优先引用**候选人回答的原话**（kind=quote，逐字摘录关键句）；若面试官在提问/对质中引用了代码位置（形如 `路径:行号`），且该证据支撑你的论断，则输出 kind=code 的引用（file=相对路径原文，line=行号）。
- 失分点（weaknesses）同样带 evidence：quote=暴露问题的原话；code=相关的代码位置（如有）。
- 禁止臆造未出现的内容：evidence 必须能在记录中逐字找到。

同时输出：亮点、失分点（供复习回流，每条从词表选 0-3 个 tags：{TAG_FAMILIES}）、复习建议（注明涉及的知识标签）。"""


def _report_system() -> str:
    from getoffer.ingest.qa_extract import TAG_FAMILIES

    return REPORT_SYSTEM.replace("{TAG_FAMILIES}", "、".join(TAG_FAMILIES))


def _load_transcript(log_path: Path) -> dict[str, Any]:
    if not log_path.exists():
        raise NotFound(f"会话日志不存在: {log_path.name}")
    entries: list[dict[str, Any]] = []
    config: dict[str, Any] = {}
    for raw in log_path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError:
            continue  # 损坏行跳过并计入（日志是 append-only，尾部半行属正常崩溃残留）
        if entry.get("type") == "session_start":
            config = entry.get("config") or {}
        entries.append(entry)
    transcript_parts: list[str] = []
    for entry in entries[-MAX_LOG_ENTRIES:]:
        kind = entry.get("type")
        if kind == "user":
            note = entry.get("director_note")
            prefix = f"[导演] {note} " if note else ""
            transcript_parts.append(f"候选人：{prefix}{entry.get('text', '')}")
        elif kind == "assistant":
            transcript_parts.append(f"面试官：{entry.get('text', '')}")
    return {"config": config, "transcript": "\n\n".join(transcript_parts)}


async def _upsert_session_row(
    session: AsyncSession,
    *,
    session_id: str,
    config: dict[str, Any],
    log_path: Path,
    report: InterviewReport,
) -> InterviewSession:
    row = await session.scalar(select(InterviewSession).where(InterviewSession.id == session_id))
    if row is None:
        row = InterviewSession(id=session_id, mode="mock", persona={}, config={}, status="finished")
        session.add(row)
    row.persona = (config or {}).get("persona") or {}
    row.config = config or {}
    row.status = "finished"
    row.log_path = str(log_path)
    row.score = report.model_dump()
    row.finished_at = datetime.now().astimezone()
    await session.flush()
    return row


async def _ingest_weaknesses(session: AsyncSession, *, session_id: str, report: InterviewReport) -> int:
    """失分点 → 复习队列（F6）。按会话幂等：该会话已回流过即跳过——重生成报告的 LLM
    措辞不同，按文本去重挡不住重复回流。证据锚点（file:line）并入文本，复习时可回看现场。"""
    import hashlib

    already = await session.scalar(
        select(func.count()).select_from(ReviewItem).where(ReviewItem.source_ref == session_id)
    )
    if already:
        return 0

    added = 0
    for weakness in report.weaknesses:
        anchors = "；".join(
            f"见 {ref.file}:{ref.line}" for ref in weakness.evidence if ref.kind == "code" and ref.file
        )
        text = weakness.text.strip() if isinstance(weakness.text, str) else str(weakness.text)
        if anchors:
            text = f"{text}（{anchors}）"
        if len(text) < 6:
            continue
        digest = hashlib.sha256(text.lower().encode("utf-8")).hexdigest()
        session.add(
            ReviewItem(
                source="interview",
                source_ref=session_id,
                content_hash=digest,
                question_text=text[:120],
                weakness=text,
                tag=next((t for t in weakness.tags if t.strip()), None),  # 掌握度统计维度
            )
        )
        added += 1
    return added


@router.post("/{session_id}/report")
async def generate_report(
    session_id: str,
    session: AsyncSession = Depends(get_db_session),
    gateway: LLMGateway = Depends(get_gateway),
    settings=Depends(get_settings),
) -> dict[str, Any]:
    log_path = Path(settings.sessions_dir) / f"{session_id}.jsonl"
    loaded = _load_transcript(log_path)
    report = await gateway.complete_structured(
        [{
            "role": "user",
            "content": f"面试配置：{json.dumps(loaded['config'], ensure_ascii=False)}\n\n面试记录：\n{loaded['transcript']}",
        }],
        InterviewReport,
        system=_report_system(),
        purpose="interview.report",
        max_tokens=8192,
    )
    row = await _upsert_session_row(
        session,
        session_id=session_id,
        config=loaded["config"],
        log_path=log_path,
        report=report,
    )
    review_added = await _ingest_weaknesses(session, session_id=session_id, report=report)
    await session.commit()
    return {
        "session_id": session_id,
        "mode": row.mode,
        "report": report.model_dump(),
        "review_added": review_added,
    }


@router.get("/{session_id}/report")
async def get_report(session_id: str, session: AsyncSession = Depends(get_db_session)) -> dict[str, Any]:
    row = await session.scalar(select(InterviewSession).where(InterviewSession.id == session_id))
    if row is None or row.score is None:
        raise NotFound(f"会话 {session_id} 尚无评分报告")
    return {"session_id": session_id, "status": row.status, "report": row.score}

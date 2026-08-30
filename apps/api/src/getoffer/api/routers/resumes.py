"""简历工作台 API（F5 · I1 简历押题的数据源）：上传解析 → 结构化画像 → claims 入库 + JD 匹配度。

解析流水线（可审计，spec §7）：
1. PDF 文本提取（pypdf，无正则）；
2. LLM 结构化画像（技术栈/项目/亮点/exam_tags——exam_tags 只允许题库标签词表）；
3. 持久化 resumes.parsed + resume_claims（项目要点即"声明"，供 G1 项目拷打做声明-证据映射）。
"""

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from getoffer.api.deps import get_db_session, get_gateway, get_settings
from getoffer.config import Settings
from getoffer.errors import NotFound, ValidationFailed
from getoffer.ingest.qa_extract import TAG_FAMILIES
from getoffer.llm.gateway import LLMGateway
from getoffer.models import Resume, ResumeClaim

router = APIRouter(prefix="/api/resumes", tags=["resumes"])

MAX_PDF_BYTES = 10 * 1024 * 1024
MAX_PDF_CHARS = 30000  # 超长简历截断（LLM 输入预算）；截断在 details 里显式标注


class ResumeProjectOut(BaseModel):
    name: str
    points: list[str] = Field(default_factory=list, max_length=8)
    stack: list[str] = Field(default_factory=list, max_length=12)


class ResumeProfile(BaseModel):
    candidate_name: str | None = None
    role_target: str | None = None
    tech_stack: list[str] = Field(default_factory=list, max_length=25)
    projects: list[ResumeProjectOut] = Field(default_factory=list, max_length=8)
    highlights: list[str] = Field(default_factory=list, max_length=6)
    exam_tags: list[str] = Field(
        default_factory=list,
        max_length=6,
        description="从题库标签词表中选择的考点标签",
    )

    def public(self) -> dict[str, Any]:
        return self.model_dump()


RESUME_SYSTEM = f"""你是简历解析器。输入是一份求职简历的纯文本（可能来自 PDF 提取，版面有些噪声）。
任务：抽取结构化画像。
- candidate_name：姓名（没有则空）
- role_target：求职方向（如"大模型应用开发实习"）
- tech_stack：全部技术栈关键词（框架/模型/工具/语言，保留原文写法）
- projects：项目列表。name=项目名；points=面试官会拷打的要点（量化指标、架构决策、你的具体职责——3-6 条）；
  stack=该项目用到的技术
- highlights：3-6 条"最值得面试官深挖的点"（一句话一条，具体不空泛）
- exam_tags：从以下词表中选 2-5 个该简历对应的考点标签：{'、'.join(TAG_FAMILIES)}

规则：只抽取简历里真实存在的内容，不推断不编造；PDF 噪声行忽略。"""


def extract_pdf_text(data: bytes) -> str:
    import io

    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
        pages = [(page.extract_text() or "") for page in reader.pages]
    except Exception as exc:  # pypdf 对损坏 PDF 抛多种异常，统一转类型化错误
        raise ValidationFailed(f"PDF 解析失败: {exc}") from exc
    text = "\n".join(pages).strip()
    if len(text) < 50:
        raise ValidationFailed("PDF 提取文本过短（可能是扫描件或加密文件），无法解析")
    return text[:MAX_PDF_CHARS]  # 超长简历截断（LLM 输入预算）


@router.post("/upload")
async def upload_resume(
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_db_session),
    gateway: LLMGateway = Depends(get_gateway),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    raw = await file.read()
    if len(raw) > MAX_PDF_BYTES:
        raise ValidationFailed(f"PDF 超过 {MAX_PDF_BYTES // (1024 * 1024)}MB 上限")
    if not raw.startswith(b"%PDF"):
        raise ValidationFailed("仅支持 PDF 简历（目前未开 docx 通道）")

    text = extract_pdf_text(raw)
    profile = await gateway.complete_structured(
        [{"role": "user", "content": text}],
        ResumeProfile,
        system=RESUME_SYSTEM,
        purpose="resume.parse",
    )

    uploads_dir = settings.uploads_dir
    stored = uploads_dir / file.filename if file.filename else uploads_dir / "resume.pdf"
    # 同名覆盖是合法语义：同一份简历的迭代版本
    stored.write_bytes(raw)

    row = Resume(file_path=str(stored), parsed=profile.public())
    session.add(row)
    await session.flush()
    for project in profile.projects:
        for point in project.points:
            session.add(
                ResumeClaim(
                    resume_id=row.id,
                    kind="project",
                    claim_text=point,
                    project_hint=project.name,
                )
            )
    await session.commit()
    return {"id": row.id, "profile": profile.public()}


@router.get("")
async def list_resumes(session: AsyncSession = Depends(get_db_session)) -> dict[str, Any]:
    rows = (await session.scalars(select(Resume).order_by(Resume.id.desc()).limit(20))).all()
    return {
        "items": [
            {
                "id": row.id,
                "file_name": Path(row.file_path).name,
                "candidate_name": (row.parsed or {}).get("candidate_name"),
                "role_target": (row.parsed or {}).get("role_target"),
                "tech_stack": (row.parsed or {}).get("tech_stack") or [],
                "highlights": (row.parsed or {}).get("highlights") or [],
            }
            for row in rows
        ]
    }


@router.get("/{resume_id}")
async def get_resume(
    resume_id: int,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    row = await session.get(Resume, resume_id)
    if row is None:
        raise NotFound(f"简历不存在: {resume_id}")
    return {"id": row.id, "file_name": Path(row.file_path).name, "profile": row.parsed or {}}


class JdMatchRequest(BaseModel):
    jd_text: str = Field(min_length=20, max_length=8000)


class JdMatchResult(BaseModel):
    match_score: int = Field(ge=0, le=100, description="匹配度 0-100")
    matched: list[str] = Field(max_length=12, description="已覆盖的要求")
    gaps: list[str] = Field(max_length=10, description="缺口：JD 要求但简历未见")
    advantages: list[str] = Field(max_length=6, description="超出 JD 的加分项")
    suggestions: list[str] = Field(max_length=6, description="改简历/补技能的可执行建议")


JD_MATCH_SYSTEM = """你是资深技术招聘官。输入：候选人简历画像（结构化 JSON）+ 目标岗位 JD 原文。
任务：评估匹配度。
- match_score：0-100（60=基本够格，80=强匹配）
- matched：JD 核心要求中简历已有对应证据的（引用简历里的技术/项目要点）
- gaps：JD 要求但简历没有的（具体到技能/经历，按重要度排序）
- advantages：简历有而 JD 未要求、但对该岗位加分的
- suggestions：可执行建议（简历措辞怎么改、快速补哪个技能/项目）
规则：只依据给定材料判断，不假设简历未提及的经历；gaps 宁全勿漏，matched 必须有据。"""


@router.post("/{resume_id}/jd-match")
async def jd_match(
    resume_id: int,
    request: JdMatchRequest,
    session: AsyncSession = Depends(get_db_session),
    gateway: LLMGateway = Depends(get_gateway),
) -> dict[str, Any]:
    row = await session.get(Resume, resume_id)
    if row is None:
        raise NotFound(f"简历不存在: {resume_id}")
    if not row.parsed:
        raise ValidationFailed(f"简历 {resume_id} 缺少解析画像，请重新上传")
    result = await gateway.complete_structured(
        [
            {
                "role": "user",
                "content": (
                    f"## 简历画像\n{json.dumps(row.parsed, ensure_ascii=False)}"
                    f"\n\n## 目标 JD\n{request.jd_text}"
                ),
            }
        ],
        JdMatchResult,
        system=JD_MATCH_SYSTEM,
        purpose="resume.jd_match",
    )
    return result.model_dump()


@router.delete("/{resume_id}")
async def delete_resume(
    resume_id: int,
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """删除简历（行 + 声明 + 本地 PDF 文件）。本地单用户工具：删除后重新上传即替换。"""
    row = await session.get(Resume, resume_id)
    if row is None:
        raise NotFound(f"简历不存在: {resume_id}")
    await session.execute(
        delete(ResumeClaim).where(ResumeClaim.resume_id == resume_id)
    )
    await session.delete(row)
    await session.commit()
    removed_file = False
    file_path = Path(row.file_path)
    if file_path.is_file() and file_path.parent == settings.uploads_dir:
        file_path.unlink(missing_ok=True)
        removed_file = True
    return {"deleted": resume_id, "file_removed": removed_file}

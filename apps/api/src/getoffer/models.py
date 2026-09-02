"""核心数据模型（spec §5.3）。

边界校验在 service 层用 Pydantic 完成；这里只定义持久化形态。
枚举值统一用 str 列存储，合法取值由各 service 的 Pydantic 模型约束。
"""

from datetime import date, datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    BigInteger,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from getoffer.db import Base


class IntPkMixin:
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class User(Base, IntPkMixin, TimestampMixin):
    __tablename__ = "users"

    display_name: Mapped[str] = mapped_column(String(64), nullable=False)


class Source(Base, IntPkMixin, TimestampMixin):
    """摄入源注册表；allowed_use 是 license 门禁的持久化形态（spec §3）。"""

    __tablename__ = "sources"

    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    repo_url: Mapped[str] = mapped_column(Text, nullable=False)
    license: Mapped[str] = mapped_column(String(64), nullable=False)
    allowed_use: Mapped[str] = mapped_column(String(32), nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)


class Company(Base, IntPkMixin, TimestampMixin):
    __tablename__ = "companies"

    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    aliases: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    logo: Mapped[str | None] = mapped_column(String(255), nullable=True)  # web 静态资源路径
    # 官方校招/网申入口（题库页公司瓷片直达投递）；只存官方域名，人工核验后由种子脚本写入
    career_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    career_note: Mapped[str | None] = mapped_column(String(255), nullable=True)  # 补充通道/筛选建议


class Tag(Base, IntPkMixin):
    __tablename__ = "tags"

    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("tags.id"), nullable=True)


class SourceFile(Base):
    """源文件的导入处理记录：无论是否抽出题目都记 done，保证增量导入收敛。"""

    __tablename__ = "source_files"
    __table_args__ = (UniqueConstraint("source_id", "path"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)  # posix 相对路径
    questions_extracted: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Question(Base, IntPkMixin, TimestampMixin):
    __tablename__ = "questions"

    stem: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), default="knowledge", nullable=False)
    difficulty: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    # source=来自仓库原文 / generated=LLM 依题干生成 / manual=人工编写 / pending=待生成
    answer_provenance: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id"), nullable=True)
    source_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    # 岗位大类：大模型应用 / 大模型算法 / 大模型应用算法 / 通用基础；NULL=未分类
    track: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # 分类管道的尝试标记：碰过即出池（companies=0 是合法终态，不能永远重选）
    classify_attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    source: Mapped[Source | None] = relationship()
    tags: Mapped[list[Tag]] = relationship(secondary="question_tags", lazy="selectin")
    followups: Mapped[list["QuestionFollowup"]] = relationship(
        back_populates="question", cascade="all, delete-orphan", order_by="QuestionFollowup.order_no"
    )
    company_stats: Mapped[list["QuestionCompany"]] = relationship(
        back_populates="question", cascade="all, delete-orphan"
    )


class QuestionTag(Base):
    __tablename__ = "question_tags"
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"), primary_key=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id"), primary_key=True)


class QuestionFollowup(Base, IntPkMixin):
    __tablename__ = "question_followups"

    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"), nullable=False)
    order_no: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    # 4 级提示降级文案（spec §7 prompt 设计）
    hint_ladder: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)

    question: Mapped[Question] = relationship(back_populates="followups")


class QuestionCompany(Base, IntPkMixin):
    __tablename__ = "question_companies"
    __table_args__ = (UniqueConstraint("question_id", "company_id", "role"),)

    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"), nullable=False)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(64), default="default", nullable=False)
    freq: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    last_seen: Mapped[date | None] = mapped_column(Date, nullable=True)
    # 频率来源：ai=LLM 推断（K1 阶段产物）· experience=面经实证（可追溯到具体条目）
    # 区分二者是为了「频率榜可追溯到面经条目」（F2 验收）与避免实证被推断值覆盖
    source: Mapped[str] = mapped_column(String(16), default="ai", nullable=False)

    question: Mapped[Question] = relationship(back_populates="company_stats")
    company: Mapped[Company] = relationship()


class QuestionCompanyEvidence(Base, IntPkMixin):
    """频率证据：把 question_companies 的 freq 追溯到具体面经条目。

    一条面经里同一道题可能出现在多个追问节点，用 (question, item) 唯一约束
    保证重复跑校准脚本是幂等的，不会把 freq 越跑越大。
    """

    __tablename__ = "question_company_evidence"
    __table_args__ = (UniqueConstraint("question_id", "experience_item_id"),)

    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"), nullable=False)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False)
    experience_id: Mapped[int] = mapped_column(ForeignKey("experiences.id"), nullable=False)
    experience_item_id: Mapped[int] = mapped_column(
        ForeignKey("experience_items.id"), nullable=False
    )
    # 匹配置信度（IDF 加权包含度，0~1），保留以便后续调阈值时不必重跑匹配
    score: Mapped[float] = mapped_column(Float, nullable=False)

    question: Mapped[Question] = relationship()
    company: Mapped[Company] = relationship()
    experience_item: Mapped["ExperienceItem"] = relationship()


class Experience(Base, IntPkMixin, TimestampMixin):
    """结构化面经（spec F1）。"""

    __tablename__ = "experiences"

    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id"), nullable=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True)
    role: Mapped[str | None] = mapped_column(String(64), nullable=True)
    round: Mapped[str | None] = mapped_column(String(32), nullable=True)
    occurred_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    result: Mapped[str | None] = mapped_column(String(32), nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)

    company: Mapped[Company | None] = relationship()
    source: Mapped["Source | None"] = relationship()
    items: Mapped[list["ExperienceItem"]] = relationship(
        back_populates="experience", cascade="all, delete-orphan", order_by="ExperienceItem.order_no"
    )


class ExperienceItem(Base, IntPkMixin):
    """面经问题树节点：parent_id 构成追问链。"""

    __tablename__ = "experience_items"

    experience_id: Mapped[int] = mapped_column(ForeignKey("experiences.id"), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("experience_items.id"), nullable=True)
    order_no: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    experience: Mapped[Experience] = relationship(back_populates="items")


class Resume(Base, IntPkMixin, TimestampMixin):
    __tablename__ = "resumes"

    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    parsed: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class ResumeClaim(Base, IntPkMixin):
    __tablename__ = "resume_claims"

    resume_id: Mapped[int] = mapped_column(ForeignKey("resumes.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    claim_text: Mapped[str] = mapped_column(Text, nullable=False)
    project_hint: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_status: Mapped[str | None] = mapped_column(String(32), nullable=True)


class Project(Base, IntPkMixin, TimestampMixin):
    __tablename__ = "projects"

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    repo_path: Mapped[str] = mapped_column(Text, nullable=False)
    head_commit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class RepoArtifact(Base, IntPkMixin):
    """备课流水线产物（repomap/wiki/向量索引/git 归属），分步 checkpoint（spec §7）。"""

    __tablename__ = "repo_artifacts"

    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    path: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Suspicion(Base, IntPkMixin, TimestampMixin):
    """简历声明 ↔ 代码证据映射产出的注水疑点（spec F4）。"""

    __tablename__ = "suspicions"

    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    claim_id: Mapped[int | None] = mapped_column(ForeignKey("resume_claims.id"), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_ref: Mapped[str | None] = mapped_column(Text, nullable=True)  # 文件:行号
    verdict: Mapped[str] = mapped_column(String(32), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class InterviewSession(Base):
    """会话由 agents 服务以 uuid 创建；评分报告回写 api。"""

    __tablename__ = "interview_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)  # mock | grill
    persona: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    log_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    score: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Message(Base, IntPkMixin):
    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_session", "session_id"),)

    session_id: Mapped[str] = mapped_column(ForeignKey("interview_sessions.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ReviewCard(Base, IntPkMixin):
    """SM-2 间隔重复（spec F6）。"""

    __tablename__ = "review_cards"
    __table_args__ = (UniqueConstraint("question_id"),)

    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"), nullable=False)
    ease: Mapped[float] = mapped_column(Float, default=2.5, nullable=False)
    interval_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    due_on: Mapped[date] = mapped_column(Date, nullable=False)
    lapses: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_result: Mapped[str | None] = mapped_column(String(16), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Mastery(Base):
    __tablename__ = "mastery"

    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id"), primary_key=True)
    score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class GoldenCase(Base, IntPkMixin, TimestampMixin):
    __tablename__ = "golden_cases"

    module: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    input_ref: Mapped[str] = mapped_column(Text, nullable=False)
    expected: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class Embedding(Base, IntPkMixin):
    """统一向量表：维度随模型不同，故不固定 typmod，由 dim 列声明。"""

    __tablename__ = "embeddings"
    __table_args__ = (Index("ix_embeddings_ref", "kind", "ref_id"),)

    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    ref_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    dim: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(), nullable=False)


class LLMCall(Base, IntPkMixin):
    __tablename__ = "llm_calls"

    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    purpose: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ReviewItem(Base, IntPkMixin, TimestampMixin):
    """失分点复习队列（F6，SM-2 间隔重复）。评分报告的 weaknesses 自动回流。"""

    __tablename__ = "review_items"
    __table_args__ = (UniqueConstraint("source_ref", "content_hash"),)

    source: Mapped[str] = mapped_column(String(32), default="interview", nullable=False)
    source_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)  # 如 session_id
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)  # 失分点对应的题目/知识点
    weakness: Mapped[str] = mapped_column(Text, nullable=False)  # 失分详情
    tag: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # SM-2 状态
    ease: Mapped[float] = mapped_column(Float, default=2.5, nullable=False)
    interval_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    repetitions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    lapses: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_grade: Mapped[int | None] = mapped_column(Integer, nullable=True)
    due_on: Mapped[date] = mapped_column(Date, default=date.today, nullable=False)


class LearningEnrollment(Base, IntPkMixin):
    """学习路径订阅与目标设定（F7）。目录本身不落库，这里只存用户侧状态。"""

    __tablename__ = "learning_enrollments"
    __table_args__ = (UniqueConstraint("path_slug"),)

    path_slug: Mapped[str] = mapped_column(String(64), nullable=False)
    target_role: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    daily_minutes: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    started_on: Mapped[date] = mapped_column(Date, default=date.today, nullable=False)
    target_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class LearningNodeProgress(Base, IntPkMixin):
    """单个学习节点的进度（F7）。

    node_id 是目录里的字符串 id 而非外键——目录增删节点不会破坏历史进度，
    废弃节点在前端折叠显示即可（spec 续二十二 §4）。
    """

    __tablename__ = "learning_node_progress"
    __table_args__ = (
        UniqueConstraint("node_id"),
        Index("ix_node_progress_status", "status"),
    )

    node_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="todo", nullable=False)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

import pytest

from getoffer.api.routers.interview import (
    ComposedPlan,
    InterviewPlanRequest,
    QuestionPresentation,
    create_plan,
)
from getoffer.interview.planning import (
    ResumeAnchor,
    extract_resume_anchors,
    resume_question_budget,
    resume_question_stem,
    select_resume_anchors,
    validate_display_stem,
)
from getoffer.models import Question, Resume


class _ScalarRows:
    def __init__(self, rows: list[Question]) -> None:
        self._rows = rows

    def unique(self) -> "_ScalarRows":
        return self

    def all(self) -> list[Question]:
        return self._rows


class _PlanSession:
    def __init__(self, questions: list[Question], resume: Resume) -> None:
        self.questions = questions
        self.resume = resume

    async def scalar(self, _statement: object) -> int:
        return len(self.questions)

    async def scalars(self, _statement: object) -> _ScalarRows:
        return _ScalarRows(self.questions)

    async def get(self, model: type[object], row_id: int) -> Resume | None:
        assert model is Resume
        return self.resume if row_id == self.resume.id else None


class _PlanGateway:
    async def complete_structured(self, *_args: object, **_kwargs: object) -> ComposedPlan:
        return ComposedPlan(
            question_ids=[101, 102],
            question_presentations=[
                QuestionPresentation(
                    question_id=101,
                    display_stem="请说明 RAG 中 chunk 切分会如何影响召回？",
                ),
                QuestionPresentation(
                    question_id=102,
                    display_stem="你会如何评估 Embedding 模型的检索效果？",
                ),
            ],
            brief="先深挖简历事实，再检验 RAG 基础。",
        )


def _question(question_id: int, stem: str) -> Question:
    question = Question(
        stem=stem,
        kind="knowledge",
        difficulty=3,
        answer="合成答案要点",
        content_hash=f"hash-{question_id}",
    )
    question.id = question_id
    question.tags = []
    question.company_stats = []
    return question


def test_resume_anchors_cover_each_experience_and_project_before_secondary_points() -> None:
    profile = {
        "experiences": [
            {
                "organization": "合成科技",
                "role": "Agent 实习生",
                "points": ["负责知识库评测", "将召回率提升到合成阈值"],
            },
            {
                "organization": "示例实验室",
                "role": "研究助理",
                "points": ["实现多跳检索基线"],
            },
        ],
        "projects": [
            {"name": "MockAgent", "points": ["用状态机约束面试流程", "设计证据化评分"]},
        ],
        "highlights": ["在另一家公司实习并维护模型网关", "获得合成竞赛一等奖"],
    }

    anchors = extract_resume_anchors(profile)

    assert [anchor.evidence for anchor in anchors[:3]] == [
        "负责知识库评测",
        "实现多跳检索基线",
        "用状态机约束面试流程",
    ]
    assert anchors[-2].kind == "experience", "旧画像中的明确实习亮点也应进入经历深挖"
    assert anchors[-1].kind == "highlight"


def test_resume_anchors_deduplicate_same_claim_without_reordering() -> None:
    profile = {
        "projects": [{"name": "A", "points": ["实现 RAG 链路"]}],
        "highlights": ["实现 RAG 链路", "补充了线上评测"],
    }

    anchors = extract_resume_anchors(profile)

    assert [anchor.evidence for anchor in anchors] == ["实现 RAG 链路", "补充了线上评测"]


@pytest.mark.parametrize(
    ("total", "available", "expected"),
    [(2, 8, 0), (3, 8, 1), (4, 8, 2), (5, 1, 1), (6, 8, 3), (8, 8, 3), (8, 0, 0)],
)
def test_resume_question_budget_preserves_bank_coverage(
    total: int, available: int, expected: int
) -> None:
    assert resume_question_budget(total, available) == expected


def test_resume_selection_covers_experience_and_project_when_budget_allows() -> None:
    anchors = [
        ResumeAnchor("h", "highlight", "亮点", "会调优模型"),
        ResumeAnchor("e", "experience", "合成科技 · 实习生", "负责评测"),
        ResumeAnchor("p", "project", "MockAgent", "实现状态机"),
    ]

    selected = select_resume_anchors(anchors, 2)

    assert [anchor.kind for anchor in selected] == ["experience", "project"]


def test_grounded_question_quotes_only_supplied_evidence_in_target_language() -> None:
    anchor = ResumeAnchor("e", "experience", "合成科技 · Agent 实习生", "负责 RAG 评测")

    chinese = resume_question_stem(anchor, language="zh-CN", ordinal=0)
    english = resume_question_stem(anchor, language="en-US", ordinal=0)

    assert "负责 RAG 评测" in chinese
    assert validate_display_stem(chinese, "zh-CN") == chinese
    assert "负责 RAG 评测" in english
    assert validate_display_stem(english, "en-US") == english


def test_display_language_gate_allows_technical_terms_but_rejects_wrong_language() -> None:
    assert validate_display_stem("请说明 RAG 的 embedding 与 reranker 如何评测？", "zh-CN")
    with pytest.raises(ValueError, match="不符合面试语言"):
        validate_display_stem("Explain the RAG retrieval pipeline?", "zh-CN")
    with pytest.raises(ValueError, match="过多并列问题"):
        validate_display_stem("你做了什么？为什么这样做？结果如何？", "zh-CN")


@pytest.mark.parametrize(
    "stem",
    [
        "请说明 RAG 从召回到生成的完整链路？",
        "Embedding 模型应如何做离线评测？",
        "BM25 与向量召回各自解决什么问题？",
        "你会如何设计 Reranker 的对照实验？",
        "ACL 更新后怎样避免旧索引继续服务？",
        "Agent Tool Calling 的参数 Schema 有什么作用？",
        "如何保证 API 重试不会重复创建订单？",
        "请解释 LLM 上下文窗口的主要限制？",
        "chunk 切分粒度会怎样影响召回质量？",
        "如何监控线上 RAG 的答案质量漂移？",
        "你会怎样设计多租户知识库的数据隔离？",
        "请说明 Prompt Injection 的主要防护边界？",
        "模型超时后系统应该如何降级？",
        "如何验证流式输出没有丢失 token？",
        "请比较 LoRA 与全量微调的工程取舍？",
        "怎样评估向量数据库的召回性能？",
        "你会如何处理工具调用的幂等性？",
        "请说明缓存命中率下降时的排查顺序？",
        "如何为 Agent 建立可复现的评测集？",
        "线上指标异常时怎样定位是检索还是生成问题？",
    ],
)
def test_twenty_mixed_technical_stems_pass_chinese_display_gate(stem: str) -> None:
    assert validate_display_stem(stem, "zh-CN") == stem


@pytest.mark.asyncio
async def test_plan_composes_resume_evidence_before_localized_bank_questions() -> None:
    questions = [
        _question(101, "How does chunking affect RAG retrieval?"),
        _question(102, "How do you evaluate an embedding model?"),
        _question(103, "Explain reranking tradeoffs."),
    ]
    resume = Resume(
        file_path="synthetic-resume.pdf",
        parsed={
            "experiences": [
                {
                    "organization": "合成科技",
                    "role": "Agent 实习生",
                    "points": ["负责 RAG 评测与回归集建设"],
                }
            ],
            "projects": [
                {"name": "MockAgent", "points": ["实现状态机约束的面试流程"]}
            ],
            "exam_tags": [],
        },
    )
    resume.id = 7
    session = _PlanSession(questions, resume)

    result = await create_plan(
        InterviewPlanRequest(size=4, resume_id=7, language="zh-CN"),
        session=session,  # type: ignore[arg-type]
        gateway=_PlanGateway(),  # type: ignore[arg-type]
    )

    assert result["resume_used"] is True
    assert result["resume_question_count"] == 2
    assert len(result["questions"]) == 4
    assert [item["source"] for item in result["questions"]] == [
        "resume",
        "resume",
        "bank",
        "bank",
    ]
    assert result["questions"][0]["grounding"] == {
        "kind": "experience",
        "label": "合成科技 · Agent 实习生",
        "evidence": "负责 RAG 评测与回归集建设",
    }
    assert result["questions"][1]["grounding"]["kind"] == "project"
    assert result["questions"][2]["stem"].startswith("How does")
    assert result["questions"][2]["display_stem"].startswith("请说明")
    assert result["questions"][3]["display_stem"].startswith("你会如何")

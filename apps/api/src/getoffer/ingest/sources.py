"""摄入源注册表：license 门禁的代码级强制（spec §3 / research/02 §5）。

allowed_use 含义：
- ANSWERS       可作为答案底稿（MIT/Apache），入库时保留来源署名
- STEMS_ONLY    无 license 仓库：只取事实性题干，答案由我们的 LLM 生成（answer_provenance=generated）
- REFERENCE_ONLY  GPL/NC 等：禁止入库，只能站外引用链接
"""

from dataclasses import dataclass
from enum import StrEnum

from getoffer.errors import NotFound


class AllowedUse(StrEnum):
    ANSWERS = "answers"
    STEMS_ONLY = "stems_only"
    REFERENCE_ONLY = "reference_only"


@dataclass(frozen=True)
class SourceSpec:
    slug: str
    name: str
    repo_url: str
    license: str
    allowed_use: AllowedUse
    md_globs: tuple[str, ...] = ("**/*.md",)
    exclude_dirs: tuple[str, ...] = (
        ".git", "node_modules", "dist", "build", "assets", "img", "images", "docs/_site", ".github",
    )
    notes: str = ""


def _build_sources() -> dict[str, SourceSpec]:
    entries: list[SourceSpec] = [
        # --- MIT / Apache：答案底稿（research/02 §1.1/§1.2） ---
        SourceSpec(
            slug="faq-of-llm-interview",
            name="FAQ_Of_LLM_Interview",
            repo_url="https://github.com/aceliuchanghong/FAQ_Of_LLM_Interview",
            license="MIT",
            allowed_use=AllowedUse.ANSWERS,
        ),
    SourceSpec(
        slug="llms-interview-notes",
        name="LLMs_interview_notes (km1994)",
        repo_url="https://github.com/km1994/LLMs_interview_notes",
        license="Apache-2.0",
        allowed_use=AllowedUse.ANSWERS,
        notes="2024-12 停更，仅作补充底稿",
    ),
    SourceSpec(
        slug="llm-for-everybody",
        name="LLMForEverybody",
        repo_url="https://github.com/luhengshiwo/LLMForEverybody",
        license="Apache-2.0",
        allowed_use=AllowedUse.ANSWERS,
    ),
    SourceSpec(
        slug="ai-agent-interview-guide",
        name="ai-agent-interview-guide",
        repo_url="https://github.com/bcefghj/ai-agent-interview-guide",
        license="MIT",
        allowed_use=AllowedUse.ANSWERS,
    ),
    SourceSpec(
        slug="ai-agents-from-zero",
        name="ai-agents-from-zero",
        repo_url="https://github.com/didilili/ai-agents-from-zero",
        license="MIT",
        allowed_use=AllowedUse.ANSWERS,
        notes="教程+题库混合，抽取时只取问答性章节",
    ),
    SourceSpec(
        slug="llm-interview-guide",
        name="llm-interview-guide (Meko1)",
        repo_url="https://github.com/Meko1/llm-interview-guide",
        license="MIT",
        allowed_use=AllowedUse.ANSWERS,
    ),
    SourceSpec(
        slug="awesome-llms-interview-notes",
        name="awesome_LLMs_interview_notes (jackaduma)",
        repo_url="https://github.com/jackaduma/awesome_LLMs_interview_notes",
        license="MIT",
        allowed_use=AllowedUse.ANSWERS,
        notes="2023 停更，低优先级",
    ),
    # --- 无 license：只取题干，答案自写 ---
    SourceSpec(
        slug="llm-interview-note",
        name="llm_interview_note (wdndev)",
        repo_url="https://github.com/wdndev/llm_interview_note",
        license="NONE",
        allowed_use=AllowedUse.STEMS_ONLY,
        notes="15k star 事实标准；仅提取题干",
    ),
    SourceSpec(
        slug="agent-guide",
        name="AgentGuide",
        repo_url="https://github.com/adongwanai/AgentGuide",
        license="NONE",
        allowed_use=AllowedUse.STEMS_ONLY,
        notes="Agent 岗垂直题库；仅提取题干",
    ),
    SourceSpec(
        slug="easy-offer",
        name="EasyOffer（大模型岗按公司面经）",
        repo_url="https://github.com/jingtian11/EasyOffer",
        license="NONE",
        allowed_use=AllowedUse.STEMS_ONLY,
        notes="真实面经，按公司目录；仅提取题干",
    ),
    SourceSpec(
        slug="interview-python",
        name="interview_python（Python 面试题）",
        repo_url="https://github.com/taizilongxu/interview_python",
        license="NONE",
        allowed_use=AllowedUse.STEMS_ONLY,
        notes="17k star Python 语言基础问答；仅提取题干。语言维度补缺（spec 续二十），答案自写",
    ),
    # --- GPL / NC：禁止入库 ---
    SourceSpec(
        slug="aigc-interview-book",
        name="AIGC-Interview-Book",
        repo_url="https://github.com/WeThinkIn/AIGC-Interview-Book",
        license="GPL-3.0",
        allowed_use=AllowedUse.REFERENCE_ONLY,
        notes="强传染：不入库，仅站外引用",
    ),
    SourceSpec(
        slug="hello-agents-interview",
        name="hello-agents 面试附录章",
        repo_url="https://github.com/datawhalechina/hello-agents",
        license="CC BY-NC-SA 4.0",
        allowed_use=AllowedUse.REFERENCE_ONLY,
        notes="禁商用：不入库",
    ),
    ]
    return {spec.slug: spec for spec in entries}


SOURCES: dict[str, SourceSpec] = _build_sources()


def get_source(slug: str) -> SourceSpec:
    spec = SOURCES.get(slug)
    if spec is None:
        raise NotFound(f"未知摄入源: {slug}", details={"known": sorted(SOURCES)})
    return spec

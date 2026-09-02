"""模拟面试题单的纯领域规则。

这里不访问数据库、不调用 LLM：简历锚点、配额、排序和展示语言门禁可以单独测试。
LLM 只在 router 里为题库 canonical stem 生成 candidate-facing presentation。
"""

from dataclasses import dataclass
from typing import Any, Literal

InterviewLanguage = Literal["zh-CN", "en-US"]
ResumeAnchorKind = Literal["experience", "project", "highlight"]


@dataclass(frozen=True, slots=True)
class ResumeAnchor:
    """一条可追溯的简历声明；题目不得添加该声明之外的候选人事实。"""

    key: str
    kind: ResumeAnchorKind
    label: str
    evidence: str

    def prompt_line(self) -> str:
        return f"anchor_id={self.key} [{self.kind}] {self.label}：{self.evidence}"


def _clean(value: Any, *, limit: int) -> str:
    text = " ".join(str(value or "").split()).strip()
    return text if len(text) <= limit else f"{text[: limit - 1]}…"


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [cleaned for item in value if (cleaned := _clean(item, limit=360))]


def _highlight_kind(text: str) -> ResumeAnchorKind:
    """为旧版画像补最小分类；只改变追问阶段，不把关键词扩写成候选人事实。"""

    normalized = text.casefold()
    experience_markers = (
        "实习",
        "任职",
        "工作经历",
        "就职",
        "internship",
        "intern ",
        "worked at",
    )
    return "experience" if any(marker in normalized for marker in experience_markers) else "highlight"


def _label(item: dict[str, Any], *, kind: ResumeAnchorKind, ordinal: int) -> str:
    if kind == "experience":
        organization = _clean(
            item.get("organization") or item.get("company") or item.get("name"), limit=72
        )
        role = _clean(item.get("role") or item.get("title"), limit=48)
        if organization and role:
            return f"{organization} · {role}"
        return organization or role or f"经历 {ordinal + 1}"
    name = _clean(item.get("name"), limit=96)
    return name or f"项目 {ordinal + 1}"


def extract_resume_anchors(profile: dict[str, Any], *, limit: int = 8) -> list[ResumeAnchor]:
    """按经历优先、项目次之抽取声明；旧画像没有 experiences 时仍兼容 projects/highlights。"""

    groups: list[list[ResumeAnchor]] = []
    for kind, field in (("experience", "experiences"), ("project", "projects")):
        rows = profile.get(field)
        if not isinstance(rows, list):
            continue
        for item_ordinal, raw_item in enumerate(rows):
            if not isinstance(raw_item, dict):
                continue
            label = _label(raw_item, kind=kind, ordinal=item_ordinal)
            points = _string_list(raw_item.get("points"))
            anchors = [
                ResumeAnchor(
                    key=f"{kind}:{item_ordinal}:{point_ordinal}",
                    kind=kind,
                    label=label,
                    evidence=point,
                )
                for point_ordinal, point in enumerate(points)
            ]
            if anchors:
                groups.append(anchors)

    # 每段经历/项目先取一个，避免同一项目的多个 bullet 挤掉其他经历；再补充次要声明。
    ordered = [group[0] for group in groups]
    ordered.extend(anchor for group in groups for anchor in group[1:])

    for ordinal, highlight in enumerate(_string_list(profile.get("highlights"))):
        ordered.append(
            ResumeAnchor(
                key=f"highlight:{ordinal}",
                kind=_highlight_kind(highlight),
                label="简历亮点",
                evidence=highlight,
            )
        )

    result: list[ResumeAnchor] = []
    seen: set[str] = set()
    for anchor in ordered:
        identity = anchor.evidence.casefold()
        if identity in seen:
            continue
        seen.add(identity)
        result.append(anchor)
        if len(result) >= limit:
            break
    return result


def resume_question_budget(total_questions: int, available_anchors: int) -> int:
    """保留至少两道题库题；8 题默认 3 道简历题。"""

    if total_questions < 3 or available_anchors <= 0:
        return 0
    desired = 3 if total_questions >= 6 else 2 if total_questions >= 4 else 1
    return min(desired, available_anchors, max(1, total_questions - 2))


def select_resume_anchors(anchors: list[ResumeAnchor], count: int) -> list[ResumeAnchor]:
    """材料允许时先覆盖一段经历和一个项目，再按原始证据顺序补齐。"""

    if count <= 0:
        return []
    selected: list[ResumeAnchor] = []
    for required_kind in ("experience", "project"):
        match = next((anchor for anchor in anchors if anchor.kind == required_kind), None)
        if match is not None and match not in selected and len(selected) < count:
            selected.append(match)
    for anchor in anchors:
        if anchor not in selected:
            selected.append(anchor)
        if len(selected) >= count:
            break
    return selected[:count]


def _quoted_evidence(anchor: ResumeAnchor, *, limit: int = 112) -> str:
    evidence = anchor.evidence
    return evidence if len(evidence) <= limit else f"{evidence[: limit - 1]}…"


def resume_question_stem(
    anchor: ResumeAnchor,
    *,
    language: InterviewLanguage,
    ordinal: int,
) -> str:
    """确定性生成只引用锚点的问题；后续细节由实时 probe 自然展开。"""

    evidence = _quoted_evidence(anchor)
    if language == "en-US":
        if anchor.kind == "experience":
            return (
                f'Your resume says “{evidence}” in “{anchor.label}”. '
                "What part did you personally own, and how did you make the key decision?"
            )
        if ordinal % 2 == 0:
            return (
                f'In “{anchor.label}”, you wrote “{evidence}”. '
                "What was the hardest technical problem, and what did you personally do to solve it?"
            )
        return (
            f'In “{anchor.label}”, you wrote “{evidence}”. '
            "How did you verify that your implementation actually worked?"
        )

    if anchor.kind == "experience":
        return (
            f"你在「{anchor.label}」中提到“{evidence}”。"
            "这项工作里你本人具体负责哪一部分，关键决策是怎么做的？"
        )
    if ordinal % 2 == 0:
        return (
            f"你在「{anchor.label}」中提到“{evidence}”。"
            "这里最难的技术问题是什么，你具体是怎么解决的？"
        )
    return f"你在「{anchor.label}」中提到“{evidence}”。你当时如何验证这项实现确实有效？"


def is_display_language(text: str, language: InterviewLanguage) -> bool:
    """轻量门禁：保留技术英文，但中文场景必须确实存在中文提问句法。"""

    if not text.strip():
        return False
    han_count = sum(1 for char in text if "\u3400" <= char <= "\u9fff")
    ascii_letters = sum(1 for char in text if char.isascii() and char.isalpha())
    if language == "zh-CN":
        return han_count >= 4
    return ascii_letters >= 8


def validate_display_stem(text: str, language: InterviewLanguage) -> str:
    stem = " ".join(text.split()).strip()
    if not 1 <= len(stem) <= 240:
        raise ValueError(f"候选人可见题干长度必须为 1..240，实际为 {len(stem)}")
    if not is_display_language(stem, language):
        raise ValueError(f"题干不符合面试语言 {language}: {stem[:80]}")
    if stem.count("？") + stem.count("?") > 2:
        raise ValueError("候选人可见题干包含过多并列问题")
    return stem

"""源注册表与 license 门禁的单元测试（纯逻辑，无 DB/网络）。"""

import pytest

from getoffer.errors import LicenseViolation, NotFound
from getoffer.ingest.sources import AllowedUse, SOURCES, get_source


def test_sources_is_dict_keyed_by_slug() -> None:
    assert isinstance(SOURCES, dict)
    for slug, spec in SOURCES.items():
        assert spec.slug == slug
        assert spec.repo_url.startswith("https://github.com/")


def test_get_source_known_and_unknown() -> None:
    spec = get_source("faq-of-llm-interview")
    assert spec.allowed_use is AllowedUse.ANSWERS
    with pytest.raises(NotFound):
        get_source("does-not-exist")


def test_expected_sources_registered() -> None:
    for slug in (
        "faq-of-llm-interview",
        "llm-interview-note",
        "agent-guide",
        "easy-offer",
        "aigc-interview-book",
        "hello-agents-interview",
    ):
        assert slug in SOURCES


def test_license_tiers_complete() -> None:
    # 每个 slugs 的 allowed_use 必须三选一（Enum 已保证），此处锁住关键仓库的分层策略
    assert SOURCES["llm-interview-note"].allowed_use is AllowedUse.STEMS_ONLY
    assert SOURCES["agent-guide"].allowed_use is AllowedUse.STEMS_ONLY
    assert SOURCES["aigc-interview-book"].allowed_use is AllowedUse.REFERENCE_ONLY
    assert SOURCES["hello-agents-interview"].allowed_use is AllowedUse.REFERENCE_ONLY
    answers = [slug for slug, spec in SOURCES.items() if spec.allowed_use is AllowedUse.ANSWERS]
    assert len(answers) >= 6  # MIT/Apache 底稿源

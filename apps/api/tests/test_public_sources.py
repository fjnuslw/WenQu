"""新增公开来源与批量审核边界；只用合成文本，不复制来源正文。"""

import asyncio
from pathlib import Path

import pytest

from getoffer.errors import ComplianceViolation, StructuredOutputError, UpstreamError
from getoffer.ingest.collect.base import PostPreview
from getoffer.ingest.collect.batch import ground_draft, import_candidates, unsegmented_compilation
from getoffer.ingest.collect.catalog import collect_catalog
from getoffer.ingest.collect.cnblogs import parse_cnblogs_records
from getoffer.ingest.collect.geeksforgeeks import merge_gfg_rounds, parse_gfg_article
from getoffer.ingest.collect.nowcoder_public import fetch_nowcoder_public_posts
from getoffer.ingest.experience_extract import ExperienceDraft, ExperienceItemDraft


def test_cnblogs_keeps_rounds_and_separates_reviewed_sections():
    html = """<div id='cnblogs_post_body'><p>准备资料</p><p>不是面经的题库。</p>
    <p>公司甲</p><p>一面：怎样进行检索评估？</p><p>二面：工具失败如何恢复？</p>
    <script>不应出现在正文中的脚本</script><p>公司乙</p><p>训练样本如何去重？</p></div>"""
    boundaries = (("准备资料", None), ("公司甲", "公司甲 Agent 面经"), ("公司乙", "公司乙算法面经"))
    posts = parse_cnblogs_records(html, "https://www.cnblogs.com/test/p/1", boundaries=boundaries)
    assert len(posts) == 2
    assert "一面" in posts[0].content and "二面" in posts[0].content
    assert "样本" not in posts[0].content
    assert "脚本" not in posts[0].content and "题库" not in posts[0].content
    assert posts[0].url == posts[1].url
    assert "未核验上游" in posts[0].meta


def test_cnblogs_changed_boundary_fails_explicitly():
    with pytest.raises(UpstreamError):
        parse_cnblogs_records(
            "<div id='cnblogs_post_body'><p>公司丙</p></div>", boundaries=(("公司甲", "甲"),)
        )


def test_gfg_only_reads_article_not_recommendations():
    html = "<h1>Example ML Interview Experience</h1><div class='article--viewer_content'>"
    html += "<p>How would you evaluate the model?</p>" * 10
    html += "<script>hidden instructions</script></div><aside>unrelated questions</aside>"
    post = parse_gfg_article(html, "https://www.geeksforgeeks.org/interview-experiences/example/")
    assert "evaluate the model" in post.content
    assert "unrelated" not in post.content and "hidden" not in post.content
    assert "保留英文原题" in post.meta


def test_gfg_missing_article_is_not_an_empty_success():
    with pytest.raises(UpstreamError):
        parse_gfg_article("<h1>Login</h1>", "https://www.geeksforgeeks.org/example/")


def test_gfg_followup_article_is_one_record_with_both_sources():
    posts = [
        PostPreview(url=f"https://example.test/{i}", title=f"Round {i}", meta="", content="问题原文")
        for i in (1, 2)
    ]
    merged = merge_gfg_rounds(posts)
    assert merged.url == posts[0].url
    assert all(p.url in merged.meta for p in posts)
    assert all(p.title in merged.content for p in posts)


def test_multi_candidate_compilation_cannot_masquerade_as_one_interview():
    assert unsegmented_compilation("面经 01\n第一位候选人\n面经 02\n第二位候选人")
    assert not unsegmented_compilation("一面\n问题原文\n二面\n追问原文")


def test_grounding_omits_generic_labels_and_duplicate_questions():
    post = PostPreview(
        url=None, title="测试面经", meta="", content="【项目经验深挖】实习拷打\n如何评估召回率？"
    )
    draft = ExperienceDraft(
        is_interview_experience=True,
        items=[
            ExperienceItemDraft(question_text="【项目经验深挖】实习拷打"),
            ExperienceItemDraft(question_text="如何评估召回率？"),
            ExperienceItemDraft(question_text="如何评估召回率？"),
        ],
    )
    grounded, warnings = ground_draft(draft, post)
    assert len(grounded.items) == 1
    assert len(warnings) == 2


def test_overlong_rounds_are_logged_not_silently_truncated():
    post = PostPreview(url=None, title="测试面经", meta="", content="如何评估召回率？")
    rounds = "Detailed ML engineering technical rounds with manager"
    draft = ExperienceDraft(
        is_interview_experience=True,
        rounds=rounds,
        items=[ExperienceItemDraft(question_text="如何评估召回率？")],
    )
    grounded, warnings = ground_draft(draft, post)
    assert grounded.rounds is None
    assert rounds in warnings[0]


def test_truncated_question_is_not_counted_as_complete():
    post = PostPreview(url=None, title="测试面经", meta="", content="介绍一下你做过...")
    draft = ExperienceDraft(
        is_interview_experience=True,
        items=[ExperienceItemDraft(question_text="介绍一下你做过...")],
    )
    grounded, warnings = ground_draft(draft, post)
    assert not grounded.is_interview_experience
    assert "截断" in warnings[0]


def test_invalid_calendar_date_is_a_typed_failure():
    draft = ExperienceDraft(is_interview_experience=False, occurred_on="2026-02-31")
    post = PostPreview(url=None, title="测试", meta="", content="无题目")
    with pytest.raises(StructuredOutputError):
        ground_draft(draft, post)


@pytest.mark.parametrize("limit", [0, 31])
def test_import_limit_enforced_before_any_io(limit):
    with pytest.raises(ValueError):
        asyncio.run(import_candidates(Path("not-accessed"), "nowcoder-public", limit))


@pytest.mark.parametrize("limit", [0, 31])
def test_catalog_limit_enforced_before_any_io(limit):
    with pytest.raises(ValueError):
        asyncio.run(collect_catalog(Path("not-accessed"), [], limit))


def test_manual_batch_never_fetches_source_sites():
    with pytest.raises(ComplianceViolation):
        asyncio.run(
            import_candidates(Path("not-accessed"), "manual-reddit", 1, manual_source="Reddit", fetch=True)
        )


def test_zero_nowcoder_limit_does_not_request_pages():
    assert asyncio.run(fetch_nowcoder_public_posts(None, 0)) == []

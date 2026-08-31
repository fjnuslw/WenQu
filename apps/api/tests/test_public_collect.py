"""公开面经解析、原文证据与跨链接去重；全部为小型合成测试文本。"""

import asyncio

import pytest

from getoffer.errors import StructuredOutputError, UpstreamError
from getoffer.ingest.collect.base import PostPreview
from getoffer.ingest.collect.batch import ContentIndex, ground_draft
from getoffer.ingest.collect.easy_offer import EXPERIENCE_PATHS, parse_easy_offer_markdown
from getoffer.ingest.collect.nowcoder_public import (
    canonical_post_url,
    discover_post_links,
    parse_nowcoder_public,
)
from getoffer.ingest.experience_extract import (
    ExperienceBatch,
    ExperienceBatchEntry,
    ExperienceDraft,
    ExperienceItemDraft,
    extract_experience_batch,
)


def test_nowcoder_primary_does_not_include_sidebar():
    html = """<h1>公司甲 Agent 一面</h1><a href='/users/123'>作者甲</a>
    <div class='nc-slate-editor-content'><p>如何设置工具调用超时？</p><p>怎样评测检索质量？</p></div>
    <aside>不属于这次面试的相关推荐内容</aside>"""
    posts = parse_nowcoder_public(html, "https://www.nowcoder.com/discuss/123?sourceSSR=home")
    assert len(posts) == 1
    assert posts[0].content == "如何设置工具调用超时？\n怎样评测检索质量？"
    assert posts[0].url == "https://www.nowcoder.com/discuss/123"
    assert "作者甲" in posts[0].meta


def test_nowcoder_compilation_requires_separate_source_links():
    html = """<h1>Agent 面经汇总</h1><div class='nc-slate-editor-content'>
    <h2>1. 公司甲｜Agent开发｜一面、二面</h2>
    <ol><li>如何处理工具调用超时？</li><li>怎样保存长期记忆？</li></ol>
    <p>原帖链接：https://www.nowcoder.com/discuss/100?sourceSSR=search</p>
    <h2>2. 公司乙｜大模型算法｜一面</h2><p>请解释旋转位置编码。</p>
    <p>原帖链接：https://www.nowcoder.com/discuss/101</p></div>"""
    posts = parse_nowcoder_public(html, "https://www.nowcoder.com/discuss/999")
    assert len(posts) == 2
    assert "一面、二面" in posts[0].title
    assert "旋转位置编码" not in posts[0].content
    assert "公开汇总摘录" in posts[0].meta
    with pytest.raises(UpstreamError):
        parse_nowcoder_public(html.replace("原帖链接：", "缺失："), "https://www.nowcoder.com/discuss/999")


def test_nowcoder_shell_is_explicit_failure():
    with pytest.raises(UpstreamError):
        parse_nowcoder_public("<html><script>load()</script></html>", "https://www.nowcoder.com/discuss/1")


@pytest.mark.parametrize(
    "url",
    [
        "https://www.nowcoder.com/search?q=Agent",
        "https://evil.test/discuss/123",
        "/discuss/comment/123",
        "/discuss/not-a-number",
    ],
)
def test_canonical_url_rejects_non_posts(url):
    assert canonical_post_url(url) is None


def test_discovery_only_follows_observed_relevant_post_links():
    html = """<a href='/discuss/10'>大模型面经</a><a href='/search?q=Agent'>Agent面经</a>
    <a href='https://elsewhere.test/discuss/11'>Agent面经</a><a href='/discuss/12'>食堂菜单</a>"""
    assert discover_post_links(html, "https://www.nowcoder.com/discuss/9") == [
        "https://www.nowcoder.com/discuss/10",
    ]


def test_grounding_discards_invented_expansion_and_answers():
    post = PostPreview(url=None, title="公司甲 Agent 面经", meta="", content="如何处理工具超时？\n项目拷打")
    draft = ExperienceDraft(
        is_interview_experience=True,
        company="公司乙",
        items=[
            ExperienceItemDraft(
                question_text="如何处理工具超时？", note="不应复制答案", followups=["没有的追问？"]
            ),
            ExperienceItemDraft(question_text="如何实现带指数退避的重试队列？"),
        ],
    )
    grounded, warnings = ground_draft(draft, post)
    assert grounded.company is None
    assert len(grounded.items) == 1
    assert grounded.items[0].note is None
    assert grounded.items[0].followups == []
    assert len(warnings) == 3


def test_grounding_does_not_save_empty_experience():
    post = PostPreview(url=None, title="今天去面试", meta="", content="只聊了项目。")
    draft = ExperienceDraft(
        is_interview_experience=True,
        items=[
            ExperienceItemDraft(question_text="项目的架构如何设计？"),
        ],
    )
    grounded, _ = ground_draft(draft, post)
    assert not grounded.is_interview_experience
    assert not grounded.items


def test_content_dedupe_ignores_url_and_detects_preview_subset():
    original = "".join(f"第{i}项讨论工具调用错误的处理方案与检索评价指标。" for i in range(25))
    index = ContentIndex()
    index.add("source-A", original)
    assert index.duplicate_of(original) == "source-A"
    assert index.duplicate_of(original[:300]) == "source-A"
    assert index.duplicate_of("完全无关的正文" * 40) is None


def test_easy_offer_uses_allowlisted_files_and_fixed_revision():
    post = parse_easy_offer_markdown(
        EXPERIENCE_PATHS[0], "# 一面\n\n" + "解释训练策略。" * 12 + "\n# 二面\n评测方案。"
    )
    assert "9aed2cb583a141dce76f24d0e5be82b355dc8843" in post.url
    assert "一面" in post.content and "二面" in post.content
    with pytest.raises(UpstreamError):
        parse_easy_offer_markdown("README.md", "资料说明" * 50)


def test_batch_does_not_accept_invented_post_ids():
    class FakeGateway:
        async def complete_structured(self, *args, **kwargs):
            return ExperienceBatch(
                entries=[
                    ExperienceBatchEntry(
                        post_id="invented",
                        draft=ExperienceDraft(is_interview_experience=False),
                    )
                ]
            )

    with pytest.raises(StructuredOutputError):
        asyncio.run(extract_experience_batch({"actual": "原文"}, FakeGateway(), source_name="测试"))


def test_batch_limit_is_bounded():
    with pytest.raises(ValueError):
        asyncio.run(extract_experience_batch({str(i): "原文" for i in range(6)}, None, source_name="测试"))

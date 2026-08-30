"""CSDN 公开文章采集：低频读取已人工审核的单公司/个人面经。

合规与结构事实（2026-08-30 实测）：
- ``blog.csdn.net/robots.txt`` 允许下列公开文章路径，门禁仍由 PoliteClient 每次请求前执行；
- 文章正文服务端渲染在 ``#content_views``，使用 selectolax DOM 解析；
- 只保存内部检索所需的 raw_text 与原帖 URL，不生成对外转载页；
- 种子刻意选择单公司或单人的面试记录，避免把多家公司汇总错误合并为一场面试。
"""

import html as html_module

from selectolax.parser import HTMLParser

from getoffer.errors import UpstreamError
from getoffer.ingest.collect.base import PoliteClientProtocol, PostPreview

SEED_ARTICLES = (
    # 字节大模型岗面经汇总（同一公司，多轮真题）
    "https://blog.csdn.net/qq_45717425/article/details/160315245",
    # 阿里淘天 AI Agent 应用开发算法一二面
    "https://blog.csdn.net/m0_59235945/article/details/160747004",
    # 美团到店大模型算法一面
    "https://blog.csdn.net/m0_63171455/article/details/141757778",
)


def _clean_lines(text: str) -> str:
    """保留题目分行，同时折叠每行内部空白；不使用正则解析 HTML。"""
    lines = []
    for raw_line in html_module.unescape(text.replace("\xa0", " ")).splitlines():
        line = " ".join(raw_line.split())
        if line:
            lines.append(line)
    return "\n".join(lines)


def parse_csdn_article(page_html: str, *, url: str) -> PostPreview:
    tree = HTMLParser(page_html)
    title_node = tree.css_first("h1.title-article")
    content_node = tree.css_first("#content_views")
    if title_node is None or content_node is None:
        raise UpstreamError(
            f"CSDN 文章 DOM 结构不符合预期: {url}",
            details={
                "has_title": title_node is not None,
                "has_content": content_node is not None,
            },
        )

    for node in content_node.css("script, style"):
        node.decompose()
    title = _clean_lines(title_node.text(separator=" "))
    content = _clean_lines(content_node.text(separator="\n"))
    if not title or len(content) < 200:
        raise UpstreamError(
            f"CSDN 文章正文过短，拒绝按空内容继续: {url}",
            details={"title_chars": len(title), "content_chars": len(content)},
        )
    return PostPreview(
        url=url,
        title=title,
        meta="CSDN 公开文章 · 仅内部结构化检索 · 原帖可溯源",
        content=content,
    )


async def fetch_csdn_posts(client: PoliteClientProtocol, max_posts: int) -> list[PostPreview]:
    if max_posts <= 0:
        return []
    posts: list[PostPreview] = []
    for url in SEED_ARTICLES[:max_posts]:
        response = await client.get(url)
        posts.append(parse_csdn_article(response.text, url=url))
    return posts

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
    # 小米 NLP 暑期实习；正文中给出了具体的一面题目。
    "https://blog.csdn.net/2201_75499313/article/details/137187143",
    # 智普清言 AIGC 产品实习，同次求职多轮合并。
    "https://blog.csdn.net/2401_85324918/article/details/141036433",
    # 上海 AI 实验室，多模态/图像方向，同场技术面与 HR 面合并。
    "https://blog.csdn.net/2301_78285120/article/details/140137118",
    # 理想汽车大模型算法，同一人的技术一面和二面合并。
    "https://blog.csdn.net/2201_75499313/article/details/135833590",
    # 字节算法实习；只摘录问题，不导入文章中的参考答案。
    "https://blog.csdn.net/2201_75499313/article/details/135983223",
    # 深信服大模型算法，同一候选人的基础面与技术面。
    "https://blog.csdn.net/2201_75499313/article/details/137185530",
)

REVIEWED_COLLECTION_URL = "https://blog.csdn.net/linxid/article/details/137396018"


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


def parse_csdn_reviewed_collection(page_html: str) -> list[PostPreview]:
    """只读取已核验的两个可见公司章节，不把标题中的 20 家当成 20 条。"""
    tree = HTMLParser(page_html)
    body = tree.css_first("#content_views")
    if body is None:
        raise UpstreamError("CSDN 汇总缺少公开正文")
    expected = ("淘天【offer】：", "字节AML【offer】：")
    headings = [_clean_lines(node.text()) for node in body.css("h3")]
    if tuple(headings) != expected:
        raise UpstreamError("CSDN 汇总章节发生变化，需要重新审核", details={"headings": headings})
    posts = []
    title = ""
    include = False
    lines = []

    def finish():
        if title and lines:
            posts.append(
                PostPreview(
                    url=REVIEWED_COLLECTION_URL,
                    title=f"{title}大模型岗位面经（公开汇总摘录）",
                    meta=(
                        f"整理者 linxid；公开可见部分；章节：{title}；"
                        "排除猎头提供的预备题库；不补全未展示部分"
                    ),
                    content="\n".join(lines),
                )
            )

    for node in body.iter():
        text = _clean_lines(node.text(separator=" "))
        if node.tag == "h3":
            finish()
            title, lines, include = text, [], False
        elif node.tag == "h4":
            include = text in ("一面：", "二面：", "HR 面：", "HR面：")
            if include:
                lines.append(text)
        elif include:
            if node.tag in ("ol", "ul"):
                lines.extend(_clean_lines(item.text(separator=" ")) for item in node.css("li"))
            elif node.tag not in ("script", "style") and text:
                lines.append(text)
    finish()
    return posts


async def fetch_csdn_posts(client: PoliteClientProtocol, max_posts: int) -> list[PostPreview]:
    if max_posts <= 0:
        return []
    posts: list[PostPreview] = []
    for url in SEED_ARTICLES[:max_posts]:
        response = await client.get(url)
        posts.append(parse_csdn_article(response.text, url=url))
    if len(posts) < max_posts:
        response = await client.get(REVIEWED_COLLECTION_URL)
        posts.extend(parse_csdn_reviewed_collection(response.text)[: max_posts - len(posts)])
    return posts

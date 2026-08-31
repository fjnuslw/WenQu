"""牛客公开 SSR 正文与带原帖链接的汇总，严格使用页面中实际出现的链接。

2026-08-31 实测 /discuss/{id} 已能返回 .nc-slate-editor-content；
不调用站内搜索/隐藏接口，不假造分页，不把相关推荐拼进当前帖正文。
汇总必须有明确的独立面试标题及原帖链接，才允许按记录切分。
"""

import html as html_module
from urllib.parse import urljoin, urlsplit

from selectolax.parser import HTMLParser, Node

from getoffer.errors import UpstreamError
from getoffer.ingest.collect.base import PoliteClientProtocol, PostPreview

SITE = "https://www.nowcoder.com"
PUBLIC_SEEDS = (
    "https://www.nowcoder.com/discuss/917561494512861184?sourceSSR=subject",
    "https://www.nowcoder.com/discuss/872120976190816256",
    "https://www.nowcoder.com/discuss/879393838081597440",
    "https://www.nowcoder.com/discuss/790266269374091264",
    "https://www.nowcoder.com/discuss/876505573997432832",
)
AI_TERMS = (
    "大模型",
    "agent",
    "rag",
    "nlp",
    "自然语言",
    "llm",
    "多模态",
    "mcp",
    "lora",
    "rlhf",
    "语言模型",
    "ai应用",
    "ai 应用",
    "ai工程",
    "ai 工程",
    "人工智能",
    "sft",
    "transformer",
    "模型训练",
    "推理优化",
    "ai infra",
    "ai-infra",
    "cuda",
    "机器学习",
    "深度学习",
    "强化学习",
    "算法工程师",
    "算法实习",
    "算法岗",
    "计算机视觉",
    "视觉算法",
    "推荐算法",
    "搜广推",
)
INTERVIEW_TERMS = ("面经", "面试", "一面", "二面", "三面", "四面", "凉经")


def clean_text(text: str) -> str:
    return " ".join(html_module.unescape(text).replace("\xa0", " ").split())


def canonical_post_url(url: str) -> str | None:
    parts = urlsplit(urljoin(SITE, url))
    if parts.hostname != "www.nowcoder.com":
        return None
    path = parts.path.rstrip("/")
    components = path.split("/")
    if len(components) == 3 and components[1] == "discuss" and components[2].isdigit():
        return SITE + path
    if (
        len(components) == 5
        and components[1:4] == ["feed", "main", "detail"]
        and len(components[4]) == 32
        and all(c in "0123456789abcdef" for c in components[4])
    ):
        return SITE + path
    return None


def is_ai_interview(text: str) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in AI_TERMS) and any(term in lowered for term in INTERVIEW_TERMS)


def _blocks_text(nodes: list[Node]) -> str:
    lines = []
    for node in nodes:
        if node.tag in ("script", "style"):
            continue
        if node.tag in ("ol", "ul"):
            lines.extend(clean_text(item.text(separator=" ", strip=True)) for item in node.css("li"))
        else:
            lines.append(clean_text(node.text(separator=" ", strip=True)))
    return "\n".join(line for line in lines if line)


def _compilation_posts(body: Node, page_url: str, author: str) -> list[PostPreview]:
    sections: list[tuple[str, list[Node]]] = []
    current_title = ""
    current_nodes: list[Node] = []
    for node in body.iter():
        text = clean_text(node.text())
        # 来自真实 DOM h2；不是用字符串/正则猜文章标题。
        if node.tag == "h2" and "｜" in text:
            if current_title:
                sections.append((current_title, current_nodes))
            current_title, current_nodes = text, []
        elif current_title:
            current_nodes.append(node)
    if current_title:
        sections.append((current_title, current_nodes))
    if not sections:
        return []

    posts = []
    for title, nodes in sections:
        content = _blocks_text(nodes)
        original_url = None
        for line in content.splitlines():
            if line.startswith("原帖链接："):
                original_url = canonical_post_url(line.removeprefix("原帖链接：").strip())
        if original_url is None:
            raise UpstreamError("牛客汇总章节缺少有效原帖链接", details={"url": page_url, "title": title})
        posts.append(
            PostPreview(
                url=original_url,
                title=title,
                content=content,
                meta=f"公开汇总摘录（不是原帖全文）；汇总作者：{author}；摘录页：{page_url}",
            )
        )
    return posts


def parse_nowcoder_public(html: str, page_url: str) -> list[PostPreview]:
    tree = HTMLParser(html)
    posts: list[PostPreview] = []
    body = tree.css_first(".nc-slate-editor-content")
    heading = tree.css_first("h1")
    if body is not None and heading is not None:
        title = clean_text(heading.text())
        authors = [clean_text(a.text()) for a in tree.css('a[href*="/users/"]') if clean_text(a.text())]
        author = authors[0] if authors else "页面未提供署名"
        posts = _compilation_posts(body, page_url, author)
        if not posts:
            posts.append(
                PostPreview(
                    url=canonical_post_url(page_url),
                    title=title,
                    meta=f"公开 SSR 正文；作者：{author}；采集页：{page_url}",
                    content=_blocks_text(list(body.iter())),
                )
            )

    # 相关推荐/话题页卡片作为独立候选，保留自身 URL，不污染主帖。
    for anchor in tree.css('a[href*="/feed/main/detail/"], a[href*="/discuss/"]'):
        url = canonical_post_url(anchor.attributes.get("href", ""))
        preview = anchor.css_first("div.placeholder-text")
        if url is None or preview is None:
            continue
        content = clean_text(preview.text())
        if len(content) < 40:
            continue
        meta = clean_text(" ".join(n.text() for n in anchor.css("div.skeleton-item")))
        wrapper = anchor.parent.parent if anchor.parent is not None else None
        title = ""
        if wrapper is not None:
            wrapper_text = clean_text(wrapper.text())
            if content[:40] in wrapper_text:
                title = wrapper_text.split(content[:40], 1)[0].strip()[:300]
        posts.append(
            PostPreview(
                url=url,
                title=title,
                content=content,
                meta=f"{meta}；公开卡片预览（非全文）；采集页：{page_url}",
            )
        )

    if not posts:
        raise UpstreamError("牛客公开页无可见正文或卡片（可能是 JS 壳）", details={"url": page_url})
    unique: dict[str, PostPreview] = {}
    for post in posts:
        if post.url and (post.url not in unique or len(post.content) > len(unique[post.url].content)):
            unique[post.url] = post
    return list(unique.values())


def discover_post_links(html: str, page_url: str) -> list[str]:
    tree = HTMLParser(html)
    links: dict[str, None] = {}
    for anchor in tree.css("a[href]"):
        url = canonical_post_url(anchor.attributes.get("href", ""))
        if url and is_ai_interview(clean_text(anchor.text())):
            links[url] = None
    body = tree.css_first(".nc-slate-editor-content")
    if body is not None:
        for line in _blocks_text(list(body.iter())).splitlines():
            if line.startswith("原帖链接："):
                url = canonical_post_url(line.removeprefix("原帖链接：").strip())
                if url:
                    links[url] = None
    links.pop(canonical_post_url(page_url), None)
    return list(links)


async def fetch_nowcoder_public_posts(client: PoliteClientProtocol, max_posts: int) -> list[PostPreview]:
    if max_posts <= 0:
        return []
    posts = []
    seen = set()
    for url in PUBLIC_SEEDS:
        response = await client.get(url)
        for post in parse_nowcoder_public(response.text, url):
            if post.url in seen or not is_ai_interview(post.as_text()):
                continue
            seen.add(post.url)
            posts.append(post)
            if len(posts) >= max_posts:
                return posts
    return posts

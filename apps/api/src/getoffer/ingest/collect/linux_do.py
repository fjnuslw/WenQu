"""linux.do 采集（公开 RSS 优先，正文仅尝试 Discourse 游客 JSON）。

已知限制：站点有 Cloudflare 防护，游客程序化请求可能被挑战页拦截——
按项目原则显式失败（不绕过、不带登录态、不改指纹）。RSS 可用而 JSON 被拦时，
只使用 RSS 自带摘要，并在 PostPreview.meta 中明确标注，不做静默降级。
"""

import html as html_module
import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import urlsplit

from selectolax.parser import HTMLParser

from getoffer.errors import UpstreamError
from getoffer.ingest.collect.base import PoliteClientProtocol, PostPreview

SITE = "https://linux.do"
RSS_FEEDS = (f"{SITE}/top.rss", f"{SITE}/latest.rss")
INTERVIEW_KEYWORDS = ("面经", "面试")


def cooked_to_text(cooked: str) -> str:
    """Discourse 帖子 cooked HTML → 纯文本（selectolax DOM，不用正则）。"""
    tree = HTMLParser(cooked)
    return " ".join(html_module.unescape(tree.text(separator="\n")).split())


def _is_cloudflare_challenge(status: int, body: str) -> bool:
    return status == 403 and "Just a moment" in body


def parse_linux_do_rss(payload: bytes, *, feed_url: str) -> list[PostPreview]:
    """RSS XML → 摘要预览；XML 用标准库解析，description 内 HTML 才交给 selectolax。"""
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise UpstreamError(
            f"linux.do RSS XML 无法解析: {feed_url}",
            details={"error": str(exc)},
        ) from exc
    channel = root.find("channel")
    items = channel.findall("item") if channel is not None else []
    if not items:
        raise UpstreamError(
            f"linux.do RSS 结构不符合预期（无 channel/item）: {feed_url}",
            details={"root_tag": root.tag},
        )

    previews: list[PostPreview] = []
    for item in items:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        description = item.findtext("description") or ""
        published = (item.findtext("pubDate") or "").strip()
        if not title or not link:
            raise UpstreamError(
                f"linux.do RSS item 缺少 title/link: {feed_url}",
                details={"has_title": bool(title), "has_link": bool(link)},
            )
        previews.append(
            PostPreview(
                url=link,
                title=title,
                meta=" · ".join(part for part in (published, f"RSS: {feed_url}") if part),
                content=cooked_to_text(description),
            )
        )
    return previews


def _topic_id(url: str) -> int | None:
    for segment in reversed([part for part in urlsplit(url).path.split("/") if part]):
        if segment.isdecimal():
            return int(segment)
    return None


def _parse_topic_json(data: Any, *, url: str) -> tuple[str, str]:
    try:
        title = data["title"]
        cooked = data["post_stream"]["posts"][0]["cooked"]
    except (KeyError, IndexError, TypeError) as exc:
        raise UpstreamError(
            f"Discourse 话题 JSON 结构不符合预期: {url}",
            details={"error": str(exc)},
        ) from exc
    return str(title), cooked_to_text(str(cooked))


async def fetch_linux_do_posts(client: PoliteClientProtocol, max_posts: int) -> list[PostPreview]:
    if max_posts <= 0:
        return []

    rss_previews: list[PostPreview] = []
    blocked_feeds: list[dict[str, str | int]] = []
    successful_feeds: list[str] = []
    for feed_url in RSS_FEEDS:
        response = await client.get_raw(feed_url)
        if _is_cloudflare_challenge(response.status_code, response.text):
            blocked_feeds.append({"url": feed_url, "status": response.status_code})
            continue
        if response.status_code != 200:
            raise UpstreamError(
                f"linux.do RSS 返回非 200: {feed_url}",
                details={"status": response.status_code, "body_head": response.text[:200]},
            )
        successful_feeds.append(feed_url)
        rss_previews.extend(parse_linux_do_rss(response.content, feed_url=feed_url))

    if not successful_feeds:
        raise UpstreamError(
            "linux.do 的 top.rss 与 latest.rss 均被 Cloudflare 挑战页拦截；"
            "不绕过防护，请改走人工摘录",
            details={"feeds": blocked_feeds},
        )

    candidates: list[PostPreview] = []
    seen_urls: set[str] = set()
    for preview in rss_previews:
        if preview.url in seen_urls:
            continue
        searchable = f"{preview.title}\n{preview.content}"
        if not any(keyword in searchable for keyword in INTERVIEW_KEYWORDS):
            continue
        seen_urls.add(preview.url)
        candidates.append(preview)
    if not candidates:
        raise UpstreamError(
            "linux.do RSS 可访问，但当前 top/latest feed 中没有面经候选",
            details={"feeds": successful_feeds, "rss_items": len(rss_previews)},
        )

    posts: list[PostPreview] = []
    json_blocked = False
    for preview in candidates:
        if len(posts) >= max_posts:
            break
        title = preview.title
        content = preview.content
        meta = preview.meta
        topic_id = _topic_id(preview.url)
        if topic_id is not None and not json_blocked:
            json_url = f"{SITE}/t/{topic_id}.json"
            response = await client.get_raw(json_url)
            if _is_cloudflare_challenge(response.status_code, response.text):
                json_blocked = True
                meta = f"{meta} · 正文 JSON 被 Cloudflare 403 拦截，仅使用 RSS 摘要"
            elif response.status_code != 200:
                raise UpstreamError(
                    f"linux.do 话题接口返回非 200: {json_url}",
                    details={"status": response.status_code, "body_head": response.text[:200]},
                )
            else:
                try:
                    data: Any = response.json()
                except ValueError as exc:
                    raise UpstreamError(
                        f"linux.do 话题接口未返回合法 JSON: {json_url}",
                        details={"error": str(exc)},
                    ) from exc
                title, content = _parse_topic_json(data, url=json_url)
        elif json_blocked:
            meta = f"{meta} · 正文 JSON 被 Cloudflare 403 拦截，仅使用 RSS 摘要"

        if len(content) < 30:
            continue
        posts.append(PostPreview(url=preview.url, title=title, meta=meta, content=content))
    if not posts:
        raise UpstreamError(
            "linux.do RSS 面经候选缺少可抽取摘要",
            details={"candidates": len(candidates)},
        )
    return posts

"""linux.do 采集（Discourse 游客 JSON API，research/02 §2.2）。

已知限制：站点有 Cloudflare 防护，游客程序化请求可能被挑战页拦截——
按项目原则显式失败（不绕过、不带登录态、不改指纹），提示改走人工摘录。
"""

import html as html_module
from typing import Any

from selectolax.parser import HTMLParser

from getoffer.errors import UpstreamError
from getoffer.ingest.collect.base import PoliteClientProtocol, PostPreview

SITE = "https://linux.do"
# research/02 §2.2 甄别的公开高质量面经/题库帖（游客可见）
SEED_TOPIC_IDS = (2365650, 1791257, 2700223, 1471403)


def cooked_to_text(cooked: str) -> str:
    """Discourse 帖子 cooked HTML → 纯文本（selectolax DOM，不用正则）。"""
    tree = HTMLParser(cooked)
    return " ".join(html_module.unescape(tree.text(separator="\n")).split())


async def fetch_linux_do_posts(client: PoliteClientProtocol, max_posts: int) -> list[PostPreview]:
    posts: list[PostPreview] = []
    for topic_id in SEED_TOPIC_IDS[:max_posts]:
        url = f"{SITE}/t/{topic_id}.json"
        response = await client.get_raw(url)
        if response.status_code == 403 and "Just a moment" in response.text:
            raise UpstreamError(
                "linux.do 被 Cloudflare 挑战页拦截：游客程序化访问不可用（不绕过反爬，spec §10）；"
                "该渠道改走人工摘录，或待有浏览器级采集方案",
                details={"status": 403, "topic": topic_id},
            )
        if response.status_code != 200:
            raise UpstreamError(
                f"linux.do 话题接口返回非 200: {url}",
                details={"status": response.status_code, "body_head": response.text[:200]},
            )
        try:
            data: Any = response.json()
            title = data["title"]
            cooked = data["post_stream"]["posts"][0]["cooked"]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise UpstreamError(
                f"Discourse 话题 JSON 结构不符合预期: {url}",
                details={"error": str(exc)},
            ) from exc
        posts.append(
            PostPreview(
                url=f"{SITE}/t/topic/{topic_id}",
                title=str(title),
                meta="",
                content=cooked_to_text(str(cooked)),
            )
        )
    return posts

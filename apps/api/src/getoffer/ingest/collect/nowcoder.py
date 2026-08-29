"""牛客话题页采集（SSR）——面经第一主阵地（research/02 §2.1）。

页面事实（2026-08 实测）：
- 话题聚合页（/creation/subject/{id}）服务端渲染，feed 卡片含 标题行 + 日期/作者 + 内容预览；
- /feed/main/detail/{id} 详情页是 JS 壳（正文客户端渲染，游客不可得全文）——
  预览即采集上限，抽取忠于预览文本（experience_extract 规则 1）。
- robots.txt 未禁 discuss/subject/feed 路径（门禁仍由 PoliteClient 每次请求前强制）。
"""

import html as html_module
from urllib.parse import urlsplit

from selectolax.parser import HTMLParser

from getoffer.ingest.collect.base import PoliteClientProtocol, PostPreview

SITE = "https://www.nowcoder.com"
# 大模型面经话题（SSR 种子，research/02 §2.1 实测 240KB 含正文）
SEED_SUBJECTS = (
    "https://www.nowcoder.com/creation/subject/8603768d1f224b6bbaa48c6b32880a1a",
)
DETAIL_PATH_MARKER = "/feed/main/detail/"


def _clean(text: str) -> str:
    # 源页实体存在双重转义（&amp;nbsp;），unescape 后折叠空白；纯文本清理，非 HTML 解析
    return " ".join(html_module.unescape(text.replace("\xa0", " ")).split())


async def fetch_nowcoder_posts(client: PoliteClientProtocol, max_posts: int) -> list[PostPreview]:
    posts: list[PostPreview] = []
    seen_urls: set[str] = set()
    for subject_url in SEED_SUBJECTS:
        if len(posts) >= max_posts:
            break
        response = await client.get(subject_url)
        tree = HTMLParser(response.text)
        for anchor in tree.css(f'a[href*="{DETAIL_PATH_MARKER}"]'):
            href = anchor.attributes.get("href") or ""
            path = urlsplit(href).path
            if not path.startswith(DETAIL_PATH_MARKER):
                continue
            url = SITE + path
            if url in seen_urls:
                continue
            preview_node = anchor.css_first("div.placeholder-text")
            if preview_node is None:
                continue  # 纯骨架卡片（无可见文本）不是可抽取对象
            content = _clean(preview_node.text())
            if len(content) < 30:
                continue
            meta = _clean(" ".join(node.text() for node in anchor.css("div.skeleton-item")))
            # 标题 = 外层容器文本去掉预览正文后的前缀（DOM 顺序：标题行 → feed 卡片 → 页脚）
            title = ""
            card = anchor.parent
            wrapper = card.parent if card is not None else None
            if wrapper is not None:
                wrapper_text = _clean(wrapper.text())
                head = content[:40]
                if head and head in wrapper_text:
                    title = _clean(wrapper_text.split(head)[0])
            seen_urls.add(url)
            posts.append(PostPreview(url=url, title=title, meta=meta, content=content))
            if len(posts) >= max_posts:
                break
    return posts

"""牛客话题页采集（SSR）——面经第一主阵地。

页面事实（2026-08 实测）：
- 话题聚合页（/creation/subject/{id}）服务端渲染，feed 卡片含 标题行 + 日期/作者 + 内容预览；
- /feed/main/detail/{id} 详情页是 JS 壳（正文客户端渲染，游客不可得全文）——
  预览即采集上限，抽取忠于预览文本（experience_extract 规则 1）。
- 话题页 ``?type=new&page=1/2/3`` 的 SSR 帖子 URL 集合完全相同，``page`` 被服务端忽略；
  未发现可合规复用的 SSR 翻页参数，因此只采每个话题的最新首页，不臆造滚动接口。
- robots.txt 未禁 discuss/subject/feed 路径（门禁仍由 PoliteClient 每次请求前强制）。
"""

import html as html_module
import math
from urllib.parse import urlsplit

from selectolax.parser import HTMLParser

from getoffer.errors import UpstreamError
from getoffer.ingest.collect.base import PoliteClientProtocol, PostPreview

SITE = "https://www.nowcoder.com"
# 2026-08-30 逐个人工打开确认的话题页；只保存真实 URL，不猜测 subject hash。
SEED_SUBJECTS = (
    # 大模型面经（原有主种子，SSR 实测约 240KB）
    "https://www.nowcoder.com/creation/subject/8603768d1f224b6bbaa48c6b32880a1a",
    # Agent 面经
    "https://www.nowcoder.com/creation/subject/bdbbe1dc5f2d4396b09a261d2871ad01",
    # 面试官拷打 AI 项目都会问什么
    "https://www.nowcoder.com/creation/subject/64d29ae024874248b2f8e10c88d41f7d",
    # 实习面试记录（当前 feed 含多条 AI Agent/RAG 实习面经）
    "https://www.nowcoder.com/creation/subject/b8fb04662b3e4a3698d028cff4f643f2",
)
DETAIL_PATH_MARKER = "/feed/main/detail/"
LATEST_PAGE_QUERY = "?type=new&page=1"


def _clean(text: str) -> str:
    # 源页实体存在双重转义（&amp;nbsp;），unescape 后折叠空白；纯文本清理，非 HTML 解析
    return " ".join(html_module.unescape(text.replace("\xa0", " ")).split())


async def fetch_nowcoder_posts(client: PoliteClientProtocol, max_posts: int) -> list[PostPreview]:
    if max_posts <= 0:
        return []

    posts: list[PostPreview] = []
    seen_urls: set[str] = set()
    for subject_index, subject_url in enumerate(SEED_SUBJECTS):
        if len(posts) >= max_posts:
            break
        page_url = subject_url + LATEST_PAGE_QUERY
        response_sizes: list[int] = []
        anchors = []
        # 牛客偶发返回 HTTP 200 的 6KB SSR 壳；同一公开 URL 做一次受限重试，
        # 两次仍无 feed 就显式报结构错误，绝不把上游异常伪装成“零帖子”。
        for _attempt in range(2):
            response = await client.get(page_url)
            response_sizes.append(len(response.content))
            tree = HTMLParser(response.text)
            anchors = tree.css(f'a[href*="{DETAIL_PATH_MARKER}"]')
            if anchors:
                break
        if not anchors:
            raise UpstreamError(
                f"牛客话题页 SSR 结构不符合预期（未找到 feed 卡片）: {subject_url}",
                details={"response_bytes": response_sizes, "attempts": len(response_sizes)},
            )

        # 公平覆盖多个话题：按“剩余条数 / 剩余话题数”动态分配本话题配额，
        # 避免第一个 20 条首页吃满 max_posts，导致新增种子永远不会被访问。
        remaining_subjects = len(SEED_SUBJECTS) - subject_index
        subject_quota = math.ceil((max_posts - len(posts)) / remaining_subjects)
        subject_added = 0
        for anchor in anchors:
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
            subject_added += 1
            if len(posts) >= max_posts or subject_added >= subject_quota:
                break
    return posts

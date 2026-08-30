"""面经采集渠道注册表（F1 后半）。"""

from getoffer.errors import NotFound
from getoffer.ingest.collect.base import ChannelSpec, PostPreview  # noqa: F401 (re-export)
from getoffer.ingest.collect.csdn import fetch_csdn_posts
from getoffer.ingest.collect.linux_do import fetch_linux_do_posts
from getoffer.ingest.collect.nowcoder import fetch_nowcoder_posts


def _build_channels() -> dict[str, ChannelSpec]:
    specs = [
        ChannelSpec(
            slug="nowcoder",
            name="牛客网·大模型面经话题",
            base_url="https://www.nowcoder.com",
            license_note="公开UGC（署名+原帖链接，不做实质性替代）",
            min_interval=8.0,
            fetch_posts=fetch_nowcoder_posts,
            notes="话题聚合页 SSR；详情页正文需登录，仅采话题页可见预览",
        ),
        ChannelSpec(
            slug="linux-do",
            name="linux.do（公开 RSS）",
            base_url="https://linux.do",
            license_note="公开UGC（署名+原帖链接）；Cloudflare 挑战时显式失败",
            min_interval=10.0,
            fetch_posts=fetch_linux_do_posts,
            notes="top/latest RSS 优先；正文 JSON 受 CF 限制时仅使用 RSS 摘要并明确标注",
        ),
        ChannelSpec(
            slug="csdn",
            name="CSDN·大模型面经精选",
            base_url="https://blog.csdn.net",
            license_note="公开文章（保留原帖链接，仅内部结构化检索，不对外转载正文）",
            min_interval=12.0,
            fetch_posts=fetch_csdn_posts,
            notes="已人工审核的单公司/个人面经种子；SSR 正文经 selectolax DOM 解析",
        ),
    ]
    return {spec.slug: spec for spec in specs}


CHANNELS: dict[str, ChannelSpec] = _build_channels()


def get_channel(slug: str) -> ChannelSpec:
    spec = CHANNELS.get(slug)
    if spec is None:
        raise NotFound(f"未知采集渠道: {slug}", details={"known": sorted(CHANNELS)})
    return spec

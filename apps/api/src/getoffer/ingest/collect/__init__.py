"""面经采集渠道注册表（F1 后半）。"""

from getoffer.errors import NotFound
from getoffer.ingest.collect.base import ChannelSpec, PostPreview  # noqa: F401 (re-export)
from getoffer.ingest.collect.cnblogs import fetch_cnblogs_posts
from getoffer.ingest.collect.csdn import fetch_csdn_posts
from getoffer.ingest.collect.easy_offer import fetch_easy_offer_posts
from getoffer.ingest.collect.geeksforgeeks import fetch_gfg_posts
from getoffer.ingest.collect.linux_do import fetch_linux_do_posts
from getoffer.ingest.collect.nowcoder import fetch_nowcoder_posts
from getoffer.ingest.collect.nowcoder_public import fetch_nowcoder_public_posts


def _build_channels() -> dict[str, ChannelSpec]:
    specs = [
        ChannelSpec(
            slug="geeksforgeeks",
            name="GeeksforGeeks·AI/ML 面经",
            base_url="https://www.geeksforgeeks.org/interview-experiences/",
            license_note="公开投稿；仅事实题干，保留英文原文与来源链接，不转载答案",
            min_interval=12.0,
            fetch_posts=fetch_gfg_posts,
            notes="LLM、RAG、Agent 与机器学习岗位；同一次求职的后续轮次合并，不猜测未给出的面试题",
        ),
        ChannelSpec(
            slug="cnblogs",
            name="博客园·公开面经摘录",
            base_url="https://www.cnblogs.com",
            license_note="公开汇总；仅事实题干，保留原页与整理者署名，不转载答案",
            min_interval=12.0,
            fetch_posts=fetch_cnblogs_posts,
            notes="已审核的逐公司段落；同场多轮合并，原帖未验证时明确标为汇总摘录",
        ),
        ChannelSpec(
            slug="github-easy-offer",
            name="GitHub·EasyOffer 逐场面经",
            base_url="https://github.com/jingtian11/EasyOffer",
            license_note="未找到 LICENSE 文件；仅提取事实题干，保留作者与固定版本来源",
            min_interval=8.0,
            fetch_posts=fetch_easy_offer_posts,
            notes="固定提交的 LLM 大厂面经目录；同一文件多轮不拆开，教程和答案不入库",
        ),
        ChannelSpec(
            slug="nowcoder-public",
            name="牛客·公开正文与溯源摘录",
            base_url="https://www.nowcoder.com",
            license_note="公开UGC；内部结构化检索，署名及原帖/汇总页双重溯源，不转载全文",
            min_interval=8.0,
            fetch_posts=fetch_nowcoder_public_posts,
            notes="2026-08-31 实测 discuss SSR 可见；汇总只有明确独立记录和原帖链接才拆分",
        ),
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

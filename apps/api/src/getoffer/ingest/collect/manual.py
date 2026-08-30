"""人工摘录渠道：仅接收用户主动提供的文本，绝不访问来源网站。"""

from datetime import date

from getoffer.errors import ComplianceViolation, ValidationFailed
from getoffer.ingest.collect.base import ChannelSpec, PoliteClientProtocol, PostPreview


async def _manual_fetch_forbidden(
    client: PoliteClientProtocol,  # noqa: ARG001 - ChannelSpec 协议签名
    max_posts: int,  # noqa: ARG001 - ChannelSpec 协议签名
) -> list[PostPreview]:
    raise ComplianceViolation("人工摘录渠道禁止自动采集；请使用 POST /api/ingest/collect/manual")


def _manual_spec(slug: str, name: str, provenance: str) -> ChannelSpec:
    return ChannelSpec(
        slug=slug,
        name=name,
        # 非网络 scheme 刻意阻断误用；用户提供的真实溯源链接只落 Experience.url，不会被请求。
        base_url=f"manual://{provenance}",
        license_note="用户主动提供的人工摘录（仅内部结构化检索；保留原帖链接）",
        min_interval=0.0,
        fetch_posts=_manual_fetch_forbidden,
        notes="人工浏览后复制文本导入；系统不访问原站，不提供正文转载页",
    )


_MANUAL_SPECS = (
    _manual_spec("manual-xhs", "小红书人工摘录", "xiaohongshu"),
    _manual_spec("manual-douyin", "抖音人工摘录", "douyin"),
    _manual_spec("manual-zhihu", "知乎人工摘录", "zhihu"),
    _manual_spec("manual-maimai", "脉脉人工摘录", "maimai"),
    _manual_spec("manual-friend", "朋友分享", "friend-share"),
)
_BY_NAME = {spec.name: spec for spec in _MANUAL_SPECS}
_BY_NAME.update(
    {
        "小红书": _BY_NAME["小红书人工摘录"],
        "抖音": _BY_NAME["抖音人工摘录"],
        "知乎": _BY_NAME["知乎人工摘录"],
        "脉脉": _BY_NAME["脉脉人工摘录"],
    }
)


def get_manual_channel(source_name: str) -> ChannelSpec:
    spec = _BY_NAME.get(source_name.strip())
    if spec is None:
        raise ValidationFailed(
            f"不支持的人工摘录渠道: {source_name}",
            details={"allowed": [spec.name for spec in _MANUAL_SPECS]},
        )
    return spec


def make_manual_post(
    *,
    text: str,
    source_url: str | None,
    source_name: str,
    occurred_on: date | None,
) -> tuple[ChannelSpec, PostPreview]:
    spec = get_manual_channel(source_name)
    meta = "用户人工摘录；系统未访问来源网站"
    if occurred_on is not None:
        meta = f"{meta} · 面试日期 {occurred_on.isoformat()}"
    return spec, PostPreview(
        url=source_url,
        title=spec.name,
        meta=meta,
        content=text.strip(),
        occurred_on=occurred_on,
    )

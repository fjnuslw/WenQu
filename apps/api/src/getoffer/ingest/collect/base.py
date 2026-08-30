"""面经采集渠道的公共类型（F1 后半，spec §3 / research/02 §2）。"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date
from typing import Protocol


class PoliteClientProtocol(Protocol):
    """渠道抓取函数对客户端的最小依赖面（便于测试替身）。"""

    async def get(self, url: str): ...

    async def get_raw(self, url: str): ...

    async def aclose(self) -> None: ...


@dataclass(frozen=True)
class PostPreview:
    """话题页/feed 里一条帖子的可见快照（游客可见文本 + 原帖链接）。

    牛客详情页正文需登录渲染，话题页预览即游客可得的全部内容；
    抽取只忠于该文本，截断部分不编造（experience_extract 规则 1）。
    """

    url: str | None
    title: str
    meta: str  # 日期/作者行等页面元信息（可能为空）
    content: str
    # 人工确认的面试日期优先于 LLM 推断；自动渠道默认为 None。
    occurred_on: date | None = None

    def as_text(self) -> str:
        return "\n".join(part for part in (self.title, self.meta, self.content) if part)


FetchPosts = Callable[[PoliteClientProtocol, int], Awaitable[list[PostPreview]]]


@dataclass(frozen=True)
class ChannelSpec:
    slug: str
    name: str
    base_url: str
    license_note: str
    min_interval: float  # 同渠道两次请求的最小间隔（秒），低频合规基线
    fetch_posts: FetchPosts
    notes: str = ""

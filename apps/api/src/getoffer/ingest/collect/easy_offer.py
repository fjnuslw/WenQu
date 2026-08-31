"""EasyOffer 公开仓库中的逐场面经，固定版本保证重跑幂等。

仅使用实际存在的面经目录文件，不把手撕教程/题库章节当面经。
README 声称 MIT，但当前快照缺少 LICENSE 文件，保守按 stems_only 使用。
"""

from pathlib import PurePosixPath
from urllib.parse import quote

from getoffer.errors import UpstreamError
from getoffer.ingest.collect.base import PoliteClientProtocol, PostPreview
from getoffer.ingest.markdown_ast import blocks_text, parse_markdown

REPOSITORY = "jingtian11/EasyOffer"
REVISION = "9aed2cb583a141dce76f24d0e5be82b355dc8843"
EXPERIENCE_PATHS = (
    "LLM大厂面经合集/字节/【0301】字节二面.md",
    "LLM大厂面经合集/字节/【0305】字节二面.md",
    "LLM大厂面经合集/字节/【0313】字节面经.md",
    "LLM大厂面经合集/字节/【0324】字节一面.md",
    "LLM大厂面经合集/小米/【0316】小米大模型面经.md",
    "LLM大厂面经合集/快手/【0314】快手一面.md",
    "LLM大厂面经合集/旷视/【0323】旷视.md",
    "LLM大厂面经合集/百度/【0226】百度一面.md",
    "LLM大厂面经合集/百度/【0317】百度一面.md",
    "LLM大厂面经合集/百度/【0318】百度二面.md",
    "LLM大厂面经合集/科大讯飞/【0306】科大讯飞一面.md",
    "LLM大厂面经合集/腾讯/【0228】腾讯IEG.md",
    "LLM大厂面经合集/腾讯/【0307】腾讯PCG面经.md",
    "LLM大厂面经合集/腾讯/【0310】腾讯IEG一面.md",
    "LLM大厂面经合集/腾讯/【0311】腾讯WXG一面.md",
    "LLM大厂面经合集/腾讯/【0324】腾讯PCG一面.md",
    "LLM大厂面经合集/蚂蚁/【0315】蚂蚁一面.md",
    "LLM大厂面经合集/蚂蚁/【0320】蚂蚁一面.md",
    "LLM大厂面经合集/阿里/【0303】阿里面经.md",
    "LLM大厂面经合集/阿里/【0308】阿里面经.md",
    "LLM大厂面经合集/阿里/【0321】阿里一面.md",
)


def parse_easy_offer_markdown(path: str, text: str) -> PostPreview:
    if path not in EXPERIENCE_PATHS:
        raise UpstreamError("EasyOffer 文件不在已审核的面经清单内", details={"path": path})
    content = blocks_text(parse_markdown(text)).strip()
    if len(content) < 50:
        raise UpstreamError("EasyOffer 面经正文过短或结构异常", details={"path": path})
    file = PurePosixPath(path)
    return PostPreview(
        url=f"https://github.com/{REPOSITORY}/blob/{REVISION}/{quote(path)}",
        title=f"{file.parent.name} · {file.stem}",
        meta=f"EasyOffer 逐场面经；作者/整理者 jingtian11；版本 {REVISION}；仅事实题干，不转载答案",
        content=content,
    )


async def fetch_easy_offer_posts(client: PoliteClientProtocol, max_posts: int) -> list[PostPreview]:
    if max_posts <= 0:
        return []
    posts = []
    for path in EXPERIENCE_PATHS[:max_posts]:
        url = f"https://raw.githubusercontent.com/{REPOSITORY}/{REVISION}/{quote(path)}"
        response = await client.get(url)
        posts.append(parse_easy_offer_markdown(path, response.text))
    return posts

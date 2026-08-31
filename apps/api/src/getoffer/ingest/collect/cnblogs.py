"""博客园已审核的面经汇总：DOM 段落边界+原文锚点，保留内部摘录来源。

本页明确逐公司/岗位记述独立面试，不把八股准备段落或同公司多轮拆成多条。
只使用已经核验的文本锚点；结构变化时抛错，不能把相邻公司的内容混合。
"""

from selectolax.parser import HTMLParser

from getoffer.errors import UpstreamError
from getoffer.ingest.collect.base import PoliteClientProtocol, PostPreview
from getoffer.ingest.collect.nowcoder_public import clean_text

SEED_URL = "https://www.cnblogs.com/hhdom/p/19792831"
SECOND_URL = "https://www.cnblogs.com/hhdom/p/22745595"
# (原文 DOM 段落起始锚点，记录标题)；None 表示题库/准备讨论，不计面经。
RECORD_BOUNDARIES = (
    ("1.深入剖析ReAct框架", None),
    ("1.zero123", "星海图面试记录（汇总摘录）"),
    ("蔚来一面：", "蔚来一面"),
    ("1.手撕三数之和", "腾讯 wxg 面试记录（汇总摘录）"),
    ("测测多模态一面", "测测多模态一面"),
    ("字节多模态二面面经", "字节多模态二面面经"),
    ("淘天agent一面", "淘天agent一面"),
    ("阿里淘天lm算法日常实习一面", "阿里淘天lm算法日常实习一面"),
    ("美的ai研究院：", "美的ai研究院"),
    ("美团风控大模型算法一面：", "美团风控大模型算法一面"),
    ("美团一面凉经（大模型应用）", "美团一面凉经（大模型应用）"),
    ("小米-多模态大模型算法实习一面", "小米-多模态大模型算法实习一面"),
    ("字节（剪映）多模态大模型日常实习面经", "字节（剪映）多模态大模型日常实习面经"),
    ("拼多多大模型一面", "拼多多大模型一面"),
    ("小红书基座大模型后训练面经", "小红书基座大模型后训练面经"),
    ("小红书智能客服大模型一面面经", "小红书智能客服大模型一面面经"),
    ("抖音电商-多模态大模型暑期面经", "抖音电商-多模态大模型暑期面经（含转部门的四轮）"),
    ("拼多多一面凉经（算法）", "拼多多一面凉经（算法）"),
    ("找实习日记4.3|字节面试凉经", "找实习日记4.3|字节面试凉经"),
    ("百度多模态大模型暑期二面面经", "百度多模态大模型暑期二面面经"),
    ("阿里-大模型一面", "阿里-大模型一面"),
    ("百度暑期多模态算法一面面经", "百度暑期多模态算法一面面经"),
    ("近期大模型岗位面经总结第一篇", None),
    ("OPPO AI中心 暑期实习面经", "OPPO AI中心 暑期实习面经"),
    ("2026小鹏汽车—多模态大模型算法实习生面经", "2026小鹏汽车—多模态大模型算法实习生面经"),
    ("百度一面凉经（大模型训推）", "百度一面凉经（大模型训推）"),
    ("wxg多模态日常实习面经", "wxg多模态日常实习面经"),
    ("京东大模型算法面经", "京东大模型算法面经"),
    ("京东大模型实习面经", "京东大模型实习面经"),
    ("发面经攒人品", "虾皮算法日常实习（汇总摘录）"),
    ("懂车帝 多模态大模型一面", "懂车帝 多模态大模型一面"),
    ("大模型暑期实习面经之京东", "大模型暑期实习面经之京东"),
    ("字节&快手面经", "字节tiktok内容安全-mllm面经"),
    ("快手视频内容", "快手视频内容理解-mllm面经"),
    ("蚂蚁暑期实习 多模态面经", "蚂蚁暑期实习 多模态面经"),
    ("ViVo 大模型算法面经", "ViVo 大模型算法面经"),
    ("阿里淘天llm算法日常实习一面", None),  # 同页前面已出现的 3.19 记录。
    ("OPPO Agent 算法日常（一面）", "OPPO Agent 算法日常（一面）"),
    ("百度多模态二面面经，纠结要不要三面", None),  # 只有概述，无明确题干。
    ("如何准备大模型算法面试？", None),
)
SECOND_BOUNDARIES = (
    ("高德大模型实习一面凉经", "高德大模型实习一面凉经"),
    ("百度AIGC算法实习生一面", "百度AIGC算法实习生一面"),
    ("6月面经", "百度多模态六月面经（汇总摘录）"),
    ("元戎启行感知算法实习生一面面经", "元戎启行感知算法实习生一面面经"),
)


def parse_cnblogs_records(
    html: str, url: str = SEED_URL, *, boundaries=RECORD_BOUNDARIES
) -> list[PostPreview]:
    tree = HTMLParser(html)
    body = tree.css_first("#cnblogs_post_body")
    if body is None:
        raise UpstreamError("博客园缺少公开正文", details={"url": url})
    for node in body.css("script, style"):
        node.decompose()
    records = []
    matched = []
    title = None
    lines: list[str] = []

    def finish() -> None:
        if title and lines:
            records.append(
                PostPreview(
                    url=url,
                    title=title,
                    content="\n".join(lines),
                    meta=f"博客园公开汇总摘录；整理者 hrdom；章节：{title}；来源：{url}；未核验上游社交原帖",
                )
            )

    for node in body.iter():
        text = clean_text(node.text())
        if not text:
            continue
        boundary = next((item for item in boundaries if text.startswith(item[0])), None)
        if boundary:
            finish()
            matched.append(boundary[0])
            title, lines = boundary[1], []
        if title:
            lines.extend(
                clean_text(line)
                for line in node.text(separator="\n", strip=True).splitlines()
                if clean_text(line)
            )
    finish()
    if matched != [anchor for anchor, _ in boundaries]:
        raise UpstreamError(
            "博客园汇总边界发生变化，需重新人工审核", details={"url": url, "matched": matched}
        )
    return records


async def fetch_cnblogs_posts(client: PoliteClientProtocol, max_posts: int) -> list[PostPreview]:
    if max_posts <= 0:
        return []
    response = await client.get(SEED_URL)
    return parse_cnblogs_records(response.text)[:max_posts]

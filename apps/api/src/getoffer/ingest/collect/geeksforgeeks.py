"""GeeksforGeeks 公开 AI/ML 求职面经；正文 DOM 与经审核的独立记录列表。

仅抽取事实题干，不转载解答。Accenture 同一候选人的首轮与后续录用篇
作为同一条面经，不能按轮次增加计数。旧 ML 面经保留原文年份，不伪装成最新。
"""

from selectolax.parser import HTMLParser

from getoffer.errors import UpstreamError
from getoffer.ingest.collect.base import PoliteClientProtocol, PostPreview
from getoffer.ingest.collect.nowcoder_public import clean_text

BASE_URL = "https://www.geeksforgeeks.org/interview-experiences/"
RECORD_GROUPS = (
    ("zs-llm-engineer-interview-experience/",),
    (
        "accenture-interview-experience-for-llm-operations-engineer-experienced/",
        "accenture-final-interview-experience-for-llm-operations-engineer-experienced-selected/",
    ),
    ("nice-interview-experience-for-professional-services-engineer-chatbot/",),
    ("zycus-interview-experience-ai-machine-learning-engineer/",),
    ("motive-interview-experience-for-applied-scientist-1/",),
    ("amazon-interview-experience-for-applied-scientist/",),
    ("microsoft-interview-experience-for-ml-engineer-2020/",),
    ("quantiphi-interview-experience-for-machine-learning-engineer-2024-on-campus/",),
    ("accenture-interview-experience-for-ai-engineer/",),
    ("futures-first-interview-experience-for-ai-ml-internship-off-campus-experience/",),
    ("teradata-interview-experience-for-ai-ml-intern/",),
    ("ion-group-interview-experience-for-data-scientist-on-campus/",),
    ("tata-consultancy-services-tcs-prime-interview-experience-on-campus-2026/",),
    ("linkedin-interview-experience-for-ai-intern/",),
    ("amazon-ai-engineer-interview-experience/",),
    ("tredence-interview-experience-for-data-analyst/",),
    ("bridgei2i-on-campus-interview-experience/",),
    ("virtusa-interview-experience-for-jr-data-scientist/",),
    ("lowes-india-interview-experience-for-data-scientist-on-campus-2023/",),
    ("swiggy-interview-experience-for-data-scientist-1-role/",),
    ("amazon-ml-scientist-intern-interview-experience-2022/",),
    ("uber-interview-experience-for-data-scientist/",),
    ("airbus-on-line-interview-experience/",),
    ("omfys-technologies-interview-experience-system-engineer-trainee-chatbot-developer/",),
    ("tiger-analytics-interview-experience-for-sr-data-analyst/",),
    ("binary-semantics-interview-experience/",),
    ("willis-towers-watson-interview-experience-for-analyst-on-campus/",),
    ("amazon-interview-experience-for-applied-scientist-internship-2023/",),
    ("nvidia-interview-experience-for-qa-sdet-intern-on-campus/",),
)


def parse_gfg_article(html: str, url: str) -> PostPreview:
    tree = HTMLParser(html)
    title_node = tree.css_first("h1")
    body = tree.css_first(".article--viewer_content")
    if title_node is None or body is None:
        raise UpstreamError("GeeksforGeeks 缺少标题或公开正文", details={"url": url})
    for node in body.css("script, style"):
        node.decompose()
    title = clean_text(title_node.text())
    content = "\n".join(
        clean_text(line) for line in body.text(separator="\n").splitlines() if clean_text(line)
    )
    if "interview" not in title.lower() or len(content) < 200:
        raise UpstreamError("GeeksforGeeks 不是完整面经正文", details={"url": url})
    return PostPreview(
        url=url,
        title=title,
        meta=f"GeeksforGeeks 公开面经；保留英文原题；仅题干、不转载答案；来源：{url}",
        content=content,
    )


def merge_gfg_rounds(posts: list[PostPreview]) -> PostPreview:
    if not posts:
        raise ValueError("同场面试至少须有一篇原文")
    if len(posts) == 1:
        return posts[0]
    return PostPreview(
        url=posts[0].url,
        title=posts[0].title + "（首轮与后续终面合并）",
        meta="GeeksforGeeks 同次求职多轮合并；只计一条；原帖：" + "；".join(p.url for p in posts),
        content="\n\n".join(p.title + "\n" + p.content for p in posts),
    )


async def fetch_gfg_posts(client: PoliteClientProtocol, max_posts: int) -> list[PostPreview]:
    if max_posts <= 0:
        return []
    records = []
    for group in RECORD_GROUPS[:max_posts]:
        rounds = []
        for path in group:
            url = BASE_URL + path
            response = await client.get(url)
            rounds.append(parse_gfg_article(response.text, url))
        records.append(merge_gfg_rounds(rounds))
    return records

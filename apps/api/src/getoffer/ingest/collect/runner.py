"""采集编排：渠道拉取 → LLM 结构化 → experiences 幂等入库（F1 后半）。

幂等：content_hash = sha256(NFKC(url + 可见文本))，重复帖跳过（重跑收敛）。
公司归属：LLM 输出与 companies 表 name/alias 精确匹配（大小写不敏感）；
匹配不上不建新公司行——面经侧的公司是事实记录，词表扩充由 seed 流程管理。
原始文本存 experiences.raw_text（署名 + 原帖链接在 url 列），可追溯。
"""

import hashlib
import unicodedata
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from getoffer.config import Settings
from getoffer.ingest.collect import get_channel
from getoffer.ingest.collect.base import ChannelSpec, PostPreview
from getoffer.ingest.collect.polite import PoliteClient
from getoffer.ingest.experience_extract import extract_experience
from getoffer.llm.gateway import LLMGateway
from getoffer.models import Company, Experience, ExperienceItem, Source


def experience_content_hash(url: str, content: str) -> str:
    normalized = " ".join(unicodedata.normalize("NFKC", f"{url}\n{content}").split()).lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


@dataclass
class CollectReport:
    channel: str
    posts_seen: int = 0
    duplicates: int = 0
    skipped_non_experience: int = 0
    inserted: int = 0
    unmatched_companies: list[str] = field(default_factory=list)


class CompanyMatcher:
    """companies 表的 name/alias 精确匹配（大小写不敏感）；一次性载入。"""

    def __init__(self, rows: list[Company]) -> None:
        self._by_lower_name: dict[str, Company] = {}
        for row in rows:
            self._by_lower_name[row.name.lower()] = row
            for alias in row.aliases or []:
                self._by_lower_name.setdefault(str(alias).lower(), row)

    def match(self, name: str | None) -> Company | None:
        if not name:
            return None
        return self._by_lower_name.get(name.strip().lower())


async def _get_or_create_channel_source(session: AsyncSession, spec: ChannelSpec) -> Source:
    row = await session.scalar(select(Source).where(Source.slug == spec.slug))
    if row is None:
        row = Source(
            slug=spec.slug,
            name=spec.name,
            repo_url=spec.base_url,
            license=spec.license_note,
            allowed_use="stems_only",
            notes=spec.notes,
        )
        session.add(row)
        await session.flush()
    return row


async def collect_channel(
    slug: str,
    *,
    session: AsyncSession,
    gateway: LLMGateway,
    settings: Settings,
    max_posts: int,
) -> CollectReport:
    spec = get_channel(slug)
    report = CollectReport(channel=slug)
    source_row = await _get_or_create_channel_source(session, spec)
    matcher = CompanyMatcher(list((await session.scalars(select(Company))).all()))

    client = PoliteClient(proxy=settings.collect_proxy, min_interval=spec.min_interval)
    try:
        posts: list[PostPreview] = await spec.fetch_posts(client, max_posts)
    finally:
        await client.aclose()

    for post in posts:
        report.posts_seen += 1
        digest = experience_content_hash(post.url, post.content)
        exists = await session.scalar(select(Experience).where(Experience.content_hash == digest))
        if exists is not None:
            report.duplicates += 1
            continue

        draft = await extract_experience(post.as_text(), gateway, source_name=spec.name)
        if not draft.is_interview_experience:
            report.skipped_non_experience += 1
            continue

        company = matcher.match(draft.company)
        if draft.company and company is None and draft.company not in report.unmatched_companies:
            report.unmatched_companies.append(draft.company)

        experience = Experience(
            source_id=source_row.id,
            company_id=company.id if company is not None else None,
            role=draft.role,
            round=draft.rounds,
            occurred_on=date.fromisoformat(draft.occurred_on) if draft.occurred_on else None,
            result=draft.result,
            url=post.url,
            raw_text=post.as_text(),
            content_hash=digest,
        )
        session.add(experience)
        await session.flush()
        for order_no, item in enumerate(draft.items):
            node = ExperienceItem(
                experience_id=experience.id,
                parent_id=None,
                order_no=order_no,
                question_text=item.question_text,
                note=item.note,
            )
            session.add(node)
            await session.flush()
            for followup_no, followup in enumerate(item.followups):
                session.add(
                    ExperienceItem(
                        experience_id=experience.id,
                        parent_id=node.id,
                        order_no=followup_no,
                        question_text=followup,
                    )
                )
        report.inserted += 1

    await session.commit()
    return report

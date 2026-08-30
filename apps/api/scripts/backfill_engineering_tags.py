"""存量题回填工程能力标签：Python / Java / 后端工程 / 项目深挖（spec 续二十）。

两阶段：SQL 关键词粗筛候选 → LLM 按"大模型应用场景相关性"口径精判。
- 口径红线（用户明确要求）：贴合大模型应用/Agent 开发岗真实会问的工程基础；
  与 AI 场景无关的泛后端八股（Spring/JVM/集合/泛型等）不打标，不确定不标。
- 只增标签不删除；处理过的题写 meta.eng_backfill_at 幂等标记，重跑自动跳过；
- Python/Java/后端工程 命中且 track 为空/未分类 → track=通用基础。

用法（apps/api 目录）：
    uv run python scripts/backfill_engineering_tags.py --dry-run   # 只看候选量与抽样
    uv run python scripts/backfill_engineering_tags.py --limit 600
"""

import argparse
import asyncio
import datetime as dt
import json
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select

from getoffer.config import load_settings
from getoffer.db import make_engine, make_sessionmaker
from getoffer.ingest.tag_vocab import canonical_tag_name
from getoffer.llm.gateway import LLMGateway
from getoffer.models import Question, QuestionTag, Tag

NEW_TAGS = ("Python", "Java", "后端工程", "项目深挖")
ENGINEERING_TAGS = ("Python", "Java", "后端工程")  # 触发 track 归入通用基础的子集

# 粗筛关键词（只做召回，不做判定；LLM 负责口径把关）
KEYWORD_GROUPS: dict[str, tuple[str, ...]] = {
    "语言": (
        "python", "java", "gil", "asyncio", "装饰器", "生成器", "迭代器", "协程",
        "多线程", "线程", "进程", "元类",
    ),
    "后端": (
        "mysql", "redis", "kafka", "消息队列", "缓存", "索引", "事务", "分库", "分表",
        "微服务", "分布式", "并发", "锁", "后端",
    ),
    "基础设施": (
        "docker", "k8s", "kubernetes", "linux", "http", "tcp", "计算机网络", "操作系统", "部署", "nginx",
    ),
    "项目追问": (
        "为什么这样设计", "为什么这么设计", "这样设计的", "遇到什么", "遇到了什么", "遇到哪些",
        "踩过", "踩坑", "哪些坑", "什么坑", "难点", "挑战", "怎么解决", "如何解决",
        "怎么优化", "如何优化", "复盘",
    ),
}

SYSTEM = """你是题库分类员。输入是 JSON 题目列表 [{id, stem}]，来自一个大模型应用/Agent 开发求职平台的题库。
对每条题目判断下面四个标签哪些适用（可全部不适用，tags 返回空数组）：

- Python：大模型应用/Agent 开发岗真实会问的 Python 语言与工程题
  （GIL、asyncio/并发编程、装饰器、生成器与迭代器、上下文管理器、内存管理、类型注解等）。
- Java：只限与 AI/大模型应用集成相关的 Java 题（Java 调用 LLM 服务、Spring AI、LangChain4j 等）；
  纯 JVM/Spring/集合/泛型八股【不标】。
- 后端工程：大模型应用岗语境下真实会问的服务化通用工程题
  （HTTP/网络/操作系统常识、缓存、消息队列、数据库基础、并发服务化、部署运维）；
  与 AI 场景无关的纯后端八股（SSM、分布式事务理论长文等）【不标】。
- 项目深挖：关于"你的项目"的追问式问题（遇到什么问题/为什么这样设计/怎么优化/技术难点）。

红线：拿不准就不标；宁缺毋滥。输出 JSON。"""


class TagDecision(BaseModel):
    id: int
    tags: list[Literal["Python", "Java", "后端工程", "项目深挖"]] = Field(default_factory=list)


class TagDecisionBatch(BaseModel):
    items: list[TagDecision]


def candidate_conditions():
    """工程关键词全 kind 召回；项目追问只召回行为/场景类（知识题的"如何优化"是噪声）。"""
    engineering = []
    probe = []
    for group, keywords in KEYWORD_GROUPS.items():
        for keyword in keywords:
            condition = func.lower(Question.stem).like(f"%{keyword}%")
            (probe if group == "项目追问" else engineering).append(condition)
    probe_in_behavior = and_(or_(*probe), Question.kind.in_(("behavior", "scenario")))
    return or_(*engineering, probe_in_behavior)


async def load_pending(sessionmaker, limit: int):
    """粗筛（id 升序，稳定分批）并过滤已回填（meta.eng_backfill_at 存在的跳过）。"""
    async with sessionmaker() as session:
        rows = (
            await session.execute(
                select(Question.id, Question.stem, Question.meta)
                .where(candidate_conditions())
                .order_by(Question.id)
                .limit(limit * 3)  # 粗筛放大，再在内存里滤掉已回填的
            )
        ).all()
    pending = []
    for qid, stem, meta in rows:
        if (meta or {}).get("eng_backfill_at"):
            continue
        pending.append((qid, stem))
        if len(pending) >= limit:
            break
    return pending


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=600, help="本轮最多处理的候选题数")
    parser.add_argument("--batch-size", type=int, default=15)
    parser.add_argument("--dry-run", action="store_true", help="只统计候选量并抽样，不调 LLM 不写库")
    args = parser.parse_args()

    settings = load_settings()
    engine = make_engine(settings)
    sessionmaker = make_sessionmaker(engine)
    gateway = LLMGateway(settings.llm)

    try:
        async with sessionmaker() as session:
            total_candidates = (
                await session.scalar(select(func.count()).select_from(Question).where(candidate_conditions()))
            )
        pending = await load_pending(sessionmaker, args.limit)
        print(f"粗筛候选总数 {total_candidates}，本轮待回填 {len(pending)}（limit={args.limit}）")
        if args.dry_run:
            for qid, stem in pending[:10]:
                print(f"  样例 {qid}: {stem[:80]}")
            return
        if not pending:
            print("没有待回填候选，结束")
            return

        stats = {tag: 0 for tag in NEW_TAGS}
        track_fixed = touched = 0
        for start in range(0, len(pending), args.batch_size):
            chunk = pending[start : start + args.batch_size]
            payload = json.dumps(
                [{"id": qid, "stem": stem[:300]} for qid, stem in chunk], ensure_ascii=False
            )
            decision = await gateway.complete_structured(
                [{"role": "user", "content": payload}],
                TagDecisionBatch,
                system=SYSTEM,
                purpose="ingest.backfill_engineering_tags",
            )
            by_id = {item.id: item.tags for item in decision.items}
            async with sessionmaker() as session:
                for qid, _stem in chunk:
                    tags = by_id.get(qid, [])
                    question = await session.get(Question, qid)
                    if question is None:
                        continue
                    for tag_name in tags:
                        canonical = canonical_tag_name(tag_name)
                        if canonical not in NEW_TAGS:
                            continue
                        tag_row = (
                            await session.execute(select(Tag).where(Tag.name == canonical))
                        ).scalar_one_or_none()
                        if tag_row is None:
                            tag_row = Tag(name=canonical)
                            session.add(tag_row)
                            await session.flush()
                        already = (
                            await session.execute(
                                select(QuestionTag.tag_id).where(
                                    QuestionTag.question_id == qid, QuestionTag.tag_id == tag_row.id
                                )
                            )
                        ).scalar_one_or_none()
                        if already is None:
                            session.add(QuestionTag(question_id=qid, tag_id=tag_row.id))
                            stats[canonical] += 1
                    if set(tags) & set(ENGINEERING_TAGS) and question.track in (None, "未分类"):
                        question.track = "通用基础"
                        track_fixed += 1
                    # 无论是否打标都写检查点：重跑从断点继续，不重复烧 LLM
                    question.meta = {**(question.meta or {}), "eng_backfill_at": dt.date.today().isoformat()}
                    touched += 1
                await session.commit()
            print(f"  批次 {start // args.batch_size + 1}: 处理 {len(chunk)}，累计打标 {sum(stats.values())}")
        print(f"\n完成：触及 {touched} 题（新增标签见上，track→通用基础 {track_fixed} 题）")
    finally:
        await gateway.aclose()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

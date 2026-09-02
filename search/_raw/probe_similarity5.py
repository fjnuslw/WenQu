"""探测 v5：主题词命中约束 —— 最终配置的精度验证。

v4 残留假阳性的机理：
  「MCP 解决了什么问题？」的内容词里混着 决了 / 了什 / 么问 这类
  **滑窗二元组碎片**——它们不是词，却凑够了共享数，把分数顶到 0.8。
  面经「什么是 RoPE？它核心解决了什么问题？」正是靠这些碎片"命中"的，
  而真正的主题词 MCP 根本没出现。

v5 追加一条硬规则：**题目最具区分度的主题词必须被命中**。
  - 取题目内容词里 idf 最高的前 K 个作为"主题词"
  - 要求命中数 ≥ 1（K=2 时即"最核心两词至少中一个"）
主题词没出现 = 不是同一道题，无论碎片凑出多高的分数。
"""

from __future__ import annotations

import math
import random
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parents[1] / "apps" / "api" / "src"))

import asyncio  # noqa: E402

from sqlalchemy import select  # noqa: E402

from getoffer.config import load_settings  # noqa: E402
from getoffer.db import make_engine, make_sessionmaker  # noqa: E402
from getoffer.models import ExperienceItem, Question  # noqa: E402

CJK = re.compile(r"[\u4e00-\u9fff]+")
WORD = re.compile(r"[a-zA-Z][a-zA-Z0-9+#.]{1,}")
STOP_RATE = 0.025
MIN_CONTENT = 3
MIN_SHARED = 3
TOPIC_K = 2


def tokens(text: str) -> set[str]:
    out: set[str] = set()
    for seg in CJK.findall(text):
        if len(seg) == 1:
            out.add(seg)
        for i in range(len(seg) - 1):
            out.add(seg[i : i + 2])
    out.update(w.lower() for w in WORD.findall(text))
    return out


async def main() -> None:
    settings = load_settings()
    engine = make_engine(settings)
    sm = make_sessionmaker(engine)

    async with sm() as session:
        questions = (await session.execute(select(Question.id, Question.stem))).all()
        items = (await session.execute(select(ExperienceItem.id, ExperienceItem.question_text))).all()

    n = len(questions)
    q_tokens = {qid: tokens(stem or "") for qid, stem in questions}
    q_stem = dict(questions)

    df: dict[str, int] = defaultdict(int)
    for toks in q_tokens.values():
        for t in toks:
            df[t] += 1
    stop = {t for t, c in df.items() if c > n * STOP_RATE}
    idf = {t: math.log(n / c) for t, c in df.items() if t not in stop}

    q_content = {qid: {t for t in toks if t in idf} for qid, toks in q_tokens.items()}
    usable = {qid: c for qid, c in q_content.items() if len(c) >= MIN_CONTENT}
    q_norm = {qid: sum(idf[t] for t in c) for qid, c in usable.items()}
    # 主题词：idf 最高的前 TOPIC_K 个内容词
    q_topic = {
        qid: {t for t, _ in sorted(((t, idf[t]) for t in c), key=lambda kv: -kv[1])[:TOPIC_K]}
        for qid, c in usable.items()
    }
    print(f"题库 {n} · 停用词 {len(stop)} · 可匹配题目 {len(usable)}")

    index: dict[str, list[int]] = defaultdict(list)
    for qid, toks in usable.items():
        for t in toks:
            index[t].append(qid)

    samples: dict[str, list[tuple[float, str, str]]] = defaultdict(list)
    matched = 0

    for _id, text in items:
        itoks = {t for t in tokens(text or "") if t in idf}
        if len(itoks) < MIN_SHARED:
            continue
        cand: dict[int, list[str]] = defaultdict(list)
        for t in itoks:
            for qid in index.get(t, ()):
                cand[qid].append(t)
        best: tuple[float, int] | None = None
        for qid, shared in cand.items():
            if len(shared) < MIN_SHARED:
                continue
            # 主题词必须命中：否则只是共享了疑问框架或二元组碎片
            if not (q_topic[qid] & set(shared)):
                continue
            score = sum(idf[t] for t in shared) / q_norm[qid]
            if best is None or score > best[0]:
                best = (score, qid)
        if best and best[0] >= 0.5:
            matched += 1
            score, qid = best
            band = "≥0.8" if score >= 0.8 else "0.65-0.8" if score >= 0.65 else "0.5-0.65"
            samples[band].append((score, text or "", q_stem.get(qid, "?")))

    print(f"\n面经条目 {len(items)}，命中 ≥0.5 的 {matched} 条（{matched / len(items):.1%}）")
    for band in ("≥0.8", "0.65-0.8", "0.5-0.65"):
        rows = samples.get(band, [])
        print(f"\n===== {band}（{len(rows)} 条）抽 12 条判读 =====")
        rnd = random.Random(13)
        rnd.shuffle(rows)
        for score, item_text, stem in rows[:12]:
            print(f"  [{score:.2f}] 面经: {item_text[:58]}")
            print(f"         题目: {stem[:58]}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

"""探测 v4：题目侧包含度 —— 收敛最终配置。

v3 用对称 Jaccard 后，长度不对称的真阳性被打到 0.17：
  「请详细解释 Multi-Head Attention，并指出它目前存在的主要问题。」
  ↔ 「Multi-head Attention 存在什么问题？」   ← 明明是同一道题，只得 0.17
因为长文本并集分母大，短题干再怎么命中也拉不高。

v4：问的是「这道**题**在面经条目里被提到没有」，所以分子分母都以**题目**为基准：
    score = Σidf(共享内容词) / Σidf(题目全部内容词)
再叠加 v3 已经验证有效的硬门槛（题目内容词 ≥3、共享 ≥3），
这样 v2 的"一词定终身"和 v3 的"长度惩罚"同时被解决。
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
    print(f"题库 {n} · 停用词 {len(stop)} · 内容词 {len(idf)} · 可匹配题目 {len(usable)}")

    index: dict[str, list[int]] = defaultdict(list)
    for qid, toks in usable.items():
        for t in toks:
            index[t].append(qid)

    samples: dict[str, list[tuple[float, str, str]]] = defaultdict(list)
    matched_items = 0
    pair_count = 0

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
            score = sum(idf[t] for t in shared) / q_norm[qid]
            if best is None or score > best[0]:
                best = (score, qid)
        if best and best[0] >= 0.5:
            matched_items += 1
            pair_count += 1
            score, qid = best
            band = "1.0(全覆盖)" if score >= 0.999 else "0.8-1.0" if score >= 0.8 else "0.65-0.8" if score >= 0.65 else "0.5-0.65"
            samples[band].append((score, text or "", q_stem.get(qid, "?")))

    print(f"\n面经条目 {len(items)}，最佳匹配 ≥0.5 的 {matched_items} 条")

    total = defaultdict(int)
    for band, rows in samples.items():
        total[band] = len(rows)
    for band in ("1.0(全覆盖)", "0.8-1.0", "0.65-0.8", "0.5-0.65"):
        rows = samples.get(band, [])
        print(f"\n===== {band}（{len(rows)} 条）抽 12 条判读 =====")
        rnd = random.Random(9)
        rnd.shuffle(rows)
        for score, item_text, stem in rows[:12]:
            print(f"  [{score:.2f}] 面经: {item_text[:58]}")
            print(f"         题目: {stem[:58]}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

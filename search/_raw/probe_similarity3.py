"""探测 v3：收敛到高精确率匹配配置。

v2 残留的假阳性形态：
  「熵坍塌的本质是什么？」 ↔ 「Agent 的本质是什么？」  score 1.00
  「DPU在集群训练中的作用？」 ↔ 「RAG的作用是什么？」    score 0.80
根因：题干只有 1~2 个内容词时，min() 归一化会让"命中那一个词"直接得满分。

v3 三处收敛：
1. 分母改用**并集**（对称加权 Jaccard）—— 不匹配的部分要扣分
2. 提高自动停用词阈值 5% → 2.5%（把「作用/问题/设计/系统」这类泛词一并压掉）
3. 硬门槛：两侧内容词各 ≥3、共享内容词 ≥3 —— 杜绝"一词定终身"
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
    print(f"题库 {n} 题 · token {len(df)} · 停用词 {len(stop)} · 可用内容词 {len(idf)}")

    q_content = {qid: {t for t in toks if t in idf} for qid, toks in q_tokens.items()}
    usable = {qid: c for qid, c in q_content.items() if len(c) >= MIN_CONTENT}
    print(f"内容词 ≥{MIN_CONTENT} 的可用题目 {len(usable)} / {n}")

    index: dict[str, list[int]] = defaultdict(list)
    for qid, toks in usable.items():
        for t in toks:
            index[t].append(qid)

    samples: dict[str, list[tuple[float, str, str]]] = defaultdict(list)
    matched = 0

    for _id, text in items:
        toks = {t for t in tokens(text or "") if t in idf}
        if len(toks) < MIN_CONTENT:
            continue
        i_norm = sum(idf[t] for t in toks)
        cand: dict[int, list[str]] = defaultdict(list)
        for t in toks:
            for qid in index.get(t, ()):
                cand[qid].append(t)
        best: tuple[float, int] | None = None
        for qid, shared in cand.items():
            if len(shared) < MIN_SHARED:
                continue
            num = sum(idf[t] for t in shared)
            # 对称加权 Jaccard：并集做分母，不匹配的部分要扣分
            den = i_norm + sum(idf[t] for t in usable[qid]) - num
            score = num / den if den else 0.0
            if best is None or score > best[0]:
                best = (score, qid)
        if best and best[0] >= 0.15:
            matched += 1
            score, qid = best
            band = "0.30+" if score >= 0.30 else "0.20-0.30" if score >= 0.20 else "0.15-0.20"
            samples[band].append((score, text or "", q_stem.get(qid, "?")))

    print(f"\n面经条目 {len(items)}，命中 ≥0.15 的 {matched} 条（{matched / len(items):.1%}）")
    for band in ("0.30+", "0.20-0.30", "0.15-0.20"):
        rows = samples.get(band, [])
        print(f"\n===== {band}（{len(rows)} 条）抽 12 条判读 =====")
        rnd = random.Random(5)
        rnd.shuffle(rows)
        for score, item_text, stem in rows[:12]:
            print(f"  [{score:.2f}] 面经: {item_text[:60]}")
            print(f"         题目: {stem[:60]}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

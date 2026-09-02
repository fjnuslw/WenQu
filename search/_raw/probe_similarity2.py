"""探测 v2：IDF 加权 + 自动停用词后的匹配质量。

v1 的结论：原始 Dice 在 0.4~0.5 区间大量误判，原因是「是什么 / 有什么区别 /
解决了什么问题」这类**疑问框架词**撑起了相似度，而它们不携带任何主题信息。

v2 改进：
1. 自动停用词：df 超过题库 5% 的 token 视为通用框架词，从匹配中剔除
2. IDF 加权的包含度：score = Σidf(A∩B) / min(Σidf(A), Σidf(B))
   —— 回答「较短文本的核心内容被覆盖了多少」，通用词 idf 低自然被压下去
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
        items = (await session.execute(
            select(ExperienceItem.id, ExperienceItem.question_text)
        )).all()

    n = len(questions)
    q_tokens = {qid: tokens(stem or "") for qid, stem in questions}
    q_stem = dict(questions)

    df: dict[str, int] = defaultdict(int)
    for toks in q_tokens.values():
        for t in toks:
            df[t] += 1

    # 自动停用词：出现面超过题库 5% 的都是疑问框架或口水词
    stop = {t for t, c in df.items() if c > n * 0.05}
    print(f"题库 {n} 题，token 表 {len(df)}，自动停用词 {len(stop)}")
    top = sorted(df.items(), key=lambda kv: -kv[1])[:30]
    print("最高频 token（将被剔除）：", " ".join(f"{t}({c})" for t, c in top[:22]))

    idf = {t: math.log(n / c) for t, c in df.items() if t not in stop}

    q_content = {qid: {t for t in toks if t in idf} for qid, toks in q_tokens.items()}
    q_norm = {qid: sum(idf[t] for t in toks) or 1e-9 for qid, toks in q_content.items()}

    index: dict[str, list[int]] = defaultdict(list)
    for qid, toks in q_content.items():
        if not toks:
            continue
        for t in toks:
            index[t].append(qid)
    print(f"倒排索引（去停用词后）{len(index)} 个 token")

    samples_by_band: dict[str, list[tuple[float, str, str]]] = defaultdict(list)
    matched_items = 0

    for _item_id, text in items:
        toks = {t for t in tokens(text or "") if t in idf}
        if len(toks) < 2:
            continue
        cand: dict[int, list[str]] = defaultdict(list)
        for t in toks:
            for qid in index.get(t, ()):  # 内容词天然低频，倒排表很短
                cand[qid].append(t)
        best: tuple[float, int] | None = None
        for qid, shared in cand.items():
            if len(shared) < 2:
                continue
            num = sum(idf[t] for t in shared)
            den = min(q_norm[qid], sum(idf[t] for t in toks))
            score = num / den if den else 0.0
            if best is None or score > best[0]:
                best = (score, qid)
        if best and best[0] >= 0.25:
            matched_items += 1
            score, qid = best
            band = "0.25-0.4" if score < 0.4 else "0.4-0.6" if score < 0.6 else "≥0.6"
            samples_by_band[band].append((score, text or "", q_stem.get(qid, "?")))

    print(f"\n面经条目 {len(items)}，最佳匹配 ≥0.25 的 {matched_items} 条")
    for band in ("≥0.6", "0.4-0.6", "0.25-0.4"):
        rows = samples_by_band.get(band, [])
        print(f"\n===== {band}（{len(rows)} 条），抽 10 条判读 =====")
        rnd = random.Random(3)
        rnd.shuffle(rows)
        for score, item_text, stem in rows[:10]:
            print(f"  [{score:.2f}] 面经: {item_text[:62]}")
            print(f"         题目: {stem[:62]}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

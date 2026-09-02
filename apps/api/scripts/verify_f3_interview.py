"""F3 v2 长面试验收（30 分钟、追问链、decision 覆盖与协议安全）。

F3 验收「产出 ≥8 条追问链」此前从未被量化验证过。本脚本把「追问链」定义成
可落盘统计的指标，并给出通过/未通过结论：

    追问链   = `interview_decision` 中 appliedAction=probe 且 depthBefore=0，
               即一道题首次进入追问；同题继续深挖只增加 probe turns，不重复算链。
    决策覆盖 = interview_decision 数 / 候选人回答数。
    追问深度 = decision.depthAfter 最大值。
    时长     = 会话 JSONL 最后事件 ts − session_start ts。

数据来源：agents 会话落盘的 data/sessions/*.jsonl。v2 直接读取
`interview_decision / state_transition / protocol_error`；旧日志只保留只读兼容统计，
没有 decision 的旧场次不能通过 v2 验收。

两种运行方式：
    python scripts/verify_f3_interview.py                 # 扫描历史会话，汇总对照验收线
    python scripts/verify_f3_interview.py --since 7       # 只看最近 7 天
    python scripts/verify_f3_interview.py --json          # 机器可读输出
    python scripts/verify_f3_interview.py --drive --synthetic
                                                        # 合成题长面（默认推荐）
    python scripts/verify_f3_interview.py --drive --allow-local-data-egress
                                                        # 明确授权后才读取本地题库

验收线：时长 ≥30 分钟、追问链 ≥8、decision 覆盖 100%、协议错误 0 → PASS。
"""

from __future__ import annotations

import argparse
import asyncio
import glob
import json
import math
import sys
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

# scripts/ → api → apps → 项目根（get_offer）
PROJECT_ROOT = Path(__file__).resolve().parents[3]
SESSIONS_DIR = PROJECT_ROOT / "data" / "sessions"
AGENTS_BASE = "http://127.0.0.1:23481"
MIN_MINUTES = 30  # 严格遵守父 Spec 的 30 分钟长面，不以“接近”替代
MIN_CHAINS = 8  # 验收线：≥8 条追问链

API_SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(API_SRC))


def _parse_ts(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _percentile_ms(values: list[float], ratio: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * ratio) - 1))
    return round(ordered[index] * 1000)


def analyze_jsonl(path: Path) -> dict:
    """统计单场会话：时长、追问链、最大深度、各阶段 assistant 数。"""
    chains = 0
    probe_turns = 0
    max_depth = 0
    legacy_cur_depth = 0
    legacy_chains = 0
    decision_count = 0
    forced_advance = 0
    protocol_errors = 0
    started_at: str | None = None
    ended_at: str | None = None
    mode = "unknown"
    runtime_model: str | None = None
    thinking_level: str | None = None
    protocol_version: str | None = None
    final_status: str | None = None
    final_phase: str | None = None
    assistant_by_phase: dict[str, int] = {}
    n_user = 0
    pending_user_at: datetime | None = None
    decision_latencies: list[float] = []
    total_turn_latencies: list[float] = []

    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        ts = event.get("ts")
        event_at = _parse_ts(ts)
        if ts:
            started_at = started_at or ts
            ended_at = ts
        etype = event.get("type")
        if etype == "session_start":
            mode = (event.get("config") or {}).get("mode", "unknown")
            runtime = event.get("runtime") or {}
            runtime_model = runtime.get("model")
            thinking_level = runtime.get("thinkingLevel")
            protocol_version = runtime.get("protocolVersion")
        elif etype == "user":
            n_user += 1
            pending_user_at = event_at
        elif etype == "interview_decision":
            decision_count += 1
            if pending_user_at is not None and event_at is not None:
                decision_latencies.append(max(0.0, (event_at - pending_user_at).total_seconds()))
            before = int(event.get("depthBefore", 0) or 0)
            after = int(event.get("depthAfter", 0) or 0)
            max_depth = max(max_depth, after)
            if event.get("appliedAction") == "probe":
                probe_turns += 1
                if before == 0:
                    chains += 1
            if event.get("forcedByPolicy"):
                forced_advance += 1
        elif etype == "state_transition":
            after = event.get("after") or {}
            final_status = after.get("status") or final_status
            final_phase = after.get("phase") or final_phase
        elif etype == "protocol_error":
            protocol_errors += 1
        elif etype == "assistant":
            if pending_user_at is not None and event_at is not None:
                total_turn_latencies.append(max(0.0, (event_at - pending_user_at).total_seconds()))
            pending_user_at = None
            state = event.get("state") or {}
            depth = state.get("followUpDepth", 0)
            if depth > legacy_cur_depth:
                legacy_chains += 1
            legacy_cur_depth = depth
            if decision_count == 0:
                max_depth = max(max_depth, depth)
            phase = state.get("phase", "?")
            final_phase = phase or final_phase
            assistant_by_phase[phase] = assistant_by_phase.get(phase, 0) + 1

    contract_version = "v2" if decision_count else "legacy"
    if decision_count == 0:
        chains = legacy_chains
        probe_turns = legacy_chains
    decision_coverage = min(1.0, decision_count / n_user) if n_user else 0.0

    duration_seconds = 0.0
    if started_at and ended_at:
        try:
            duration_seconds = (
                datetime.fromisoformat(ended_at.replace("Z", "+00:00"))
                - datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            ).total_seconds()
        except ValueError:
            duration_seconds = 0.0
    return {
        "id": path.stem,
        "mode": mode,
        "model": runtime_model,
        "thinking_level": thinking_level,
        "protocol_version": protocol_version,
        "final_status": final_status,
        "final_phase": final_phase,
        "duration_seconds": round(duration_seconds, 3),
        "minutes": round(duration_seconds / 60, 1),
        "chains": chains,
        "probe_turns": probe_turns,
        "max_depth": max_depth,
        "decision_count": decision_count,
        "decision_coverage": round(decision_coverage, 4),
        "forced_advance": forced_advance,
        "protocol_errors": protocol_errors,
        "decision_latency_p50_ms": _percentile_ms(decision_latencies, 0.50),
        "decision_latency_p95_ms": _percentile_ms(decision_latencies, 0.95),
        "total_turn_latency_p50_ms": _percentile_ms(total_turn_latencies, 0.50),
        "total_turn_latency_p95_ms": _percentile_ms(total_turn_latencies, 0.95),
        "contract_version": contract_version,
        "n_assistant": sum(assistant_by_phase.values()),
        "n_user": n_user,
        "by_phase": assistant_by_phase,
        "path": str(path),
    }


def is_pass(stat: dict) -> bool:
    return (
        stat["duration_seconds"] >= MIN_MINUTES * 60
        and stat["chains"] >= MIN_CHAINS
        and stat["contract_version"] == "v2"
        and stat["protocol_version"] == "f3.v2.one_step_question_arg"
        and stat["final_status"] in {"closing", "finished"}
        and stat["final_phase"] == "closing"
        and stat["decision_coverage"] == 1.0
        and stat["protocol_errors"] == 0
    )


def summarize(stats: list[dict], json_out: bool) -> int:
    """对照验收线输出结论。返回退出码：0=有场次通过；1=无通过场次；2=无数据。"""
    if not stats:
        print("未找到会话数据。")
        return 2

    if json_out:
        print(
            json.dumps(
                {
                    "runs": stats,
                    "pass": any(is_pass(s) for s in stats),
                },
                ensure_ascii=False,
                indent=1,
            )
        )
        return 0 if any(is_pass(s) for s in stats) else 1

    print(
        f"{'会话':<38} {'协议':<7} {'时长':>6} {'链':>3} {'probe':>5} "
        f"{'决策覆盖':>8} {'错误':>4}  结论"
    )
    passed = 0
    for s in sorted(stats, key=lambda x: -x["minutes"]):
        ok = is_pass(s)
        passed += int(ok)
        print(
            f"{s['id'][:36]:<38} {s['contract_version']:<7} {s['minutes']:>5.1f}m "
            f"{s['chains']:>3} {s['probe_turns']:>5} {s['decision_coverage']:>7.0%} "
            f"{s['protocol_errors']:>4}  "
            f"{'✅ PASS' if ok else '—'}"
        )
        if s["chains"]:
            detail = ", ".join(f"{k}×{v}" for k, v in sorted(s["by_phase"].items()))
            print(f"    phase: {detail}")
    print(
        f"\n共 {len(stats)} 场，达标 {passed} 场（时长≥{MIN_MINUTES}min、追问链≥{MIN_CHAINS}、"
        "decision 覆盖=100%、协议错误=0）。"
    )
    return 0 if passed else 1


def drive_session(
    max_minutes: int = 35,
    turn_delay: int = 105,
    agents_base: str = AGENTS_BASE,
    synthetic: bool = False,
) -> dict:
    """拉起一场真实长面：8 道高频题 + 持续候选人回答，直到 closing 或超时。"""
    # 1) 默认取本地题库高频题；--synthetic 使用仓库内人工合成 fixture，避免外发本地数据。
    if synthetic:
        fixture_path = PROJECT_ROOT / "apps" / "agents" / "evals" / "f3-decision-fixtures.json"
        fixtures = json.loads(fixture_path.read_text(encoding="utf-8"))
        selected = [
            item
            for item in fixtures
            if item.get("kind") != "self_intro" and item.get("expectedAction") == "advance"
        ][:8]
        questions = [
            {
                "id": 900_000 + index,
                "stem": item["question"],
                "kind": item["kind"],
                # 追问后的第二次作答使用人工金标中的完整回答。只拼接参考点会
                # 丢失论证关系，反而把 soak 变成对“关键词列表”的重复追问测试。
                "answer": item["candidateAnswer"],
            }
            for index, item in enumerate(selected)
        ]
    else:
        from sqlalchemy import func, select  # noqa: E402

        from getoffer.config import load_settings  # noqa: E402
        from getoffer.db import make_engine, make_sessionmaker  # noqa: E402
        from getoffer.models import Question, QuestionCompany  # noqa: E402

        async def fetch_questions() -> list[dict]:
            settings = load_settings()
            engine = make_engine(settings)
            sm = make_sessionmaker(engine)
            async with sm() as session:
                rows = (
                    await session.execute(
                        select(Question.id, Question.stem, Question.kind, Question.answer)
                        .join(QuestionCompany, QuestionCompany.question_id == Question.id)
                        .group_by(Question.id, Question.stem, Question.kind)
                        .order_by(func.max(QuestionCompany.freq).desc())
                        .limit(8)
                    )
                ).all()
                return [
                    {"id": qid, "stem": stem, "kind": kind, "answer": answer}
                    for qid, stem, kind, answer in rows
                ]

        questions = asyncio.run(fetch_questions())
    if len(questions) < 4:
        print("题库可用题不足，无法驱动长面。")
        sys.exit(2)

    # 2) 创建面试会话
    body = json.dumps(
        {
            "mode": "mock",
            "persona": {"role": "大模型应用工程师 · 面试官"},
            "maxQuestionsPerPhase": 8,
            "maxFollowUpDepth": 4,
            "questions": questions,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{agents_base}/sessions",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        session_id = json.loads(resp.read())["id"]
    print(f"已创建长面会话 {session_id}，题单 {len(questions)} 题，开始逐轮作答…")

    # 3) 每个 target 先给一次信息不足回答触发 probe，再根据参考要点补答触发 advance。
    # 默认 105 秒间隔时，self_intro + 8 题约 18 轮，严格覆盖 30 分钟墙钟长面。
    deadline = time.time() + max_minutes * 60
    last = ""
    turn_no = 0
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{agents_base}/sessions/{session_id}", timeout=10) as resp:
                before_state = json.loads(resp.read())
        except Exception as exc:  # noqa: BLE001
            print(f"  读取轮前状态失败：{exc}")
            time.sleep(2)
            continue
        if before_state.get("phase") in ("finished", "closed", "error", "closing"):
            break

        turn_no += 1
        depth = int(before_state.get("followUpDepth", 0) or 0)
        target = before_state.get("currentTarget") or {}
        if depth == 0:
            answer = (
                "我对这个点只有大概印象，项目里基本按常规方案处理；"
                "具体实现、指标和为什么这样取舍，我现在还说不清。"
            )
        elif target.get("kind") == "self_intro":
            answer = (
                "我主要负责企业知识库的检索链路，独立实现混合召回、重排和离线评测；"
                "通过固定问答集把 Recall@20 从 0.71 提升到 0.86，并负责灰度和监控。"
            )
        else:
            question_index = target.get("index")
            reference = ""
            if isinstance(question_index, int) and 0 <= question_index < len(questions):
                reference = str(questions[question_index].get("answer") or "")[:1200]
            answer = (
                f"我补充完整回答。核心要点是：{reference}。"
                "实际落地时我会先明确输入输出和失败边界，再用离线用例验证，最后灰度并监控延迟与错误率。"
            )
        turn_body = json.dumps({"text": answer}, ensure_ascii=False).encode("utf-8")
        turn_req = urllib.request.Request(
            f"{agents_base}/sessions/{session_id}/turn",
            data=turn_body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(turn_req, timeout=180) as resp:
                resp.read()  # 等 SSE 完整结束；验收事实以 JSONL 为准
            with urllib.request.urlopen(f"{agents_base}/sessions/{session_id}", timeout=10) as resp:
                state = json.loads(resp.read())
        except Exception as exc:  # noqa: BLE001
            print(f"  第 {turn_no} 轮异常：{exc}")
            continue
        if state.get("phase") != last:
            last = state.get("phase", "")
            print(f"  phase={last} · 深度={state.get('followUpDepth')}")
        else:
            print(f"  turn={turn_no} · phase={last} · 深度={state.get('followUpDepth')}")
        if state.get("phase") in ("finished", "closed", "error", "closing"):
            time.sleep(5)  # 等 JSONL 写完
            break
        time.sleep(turn_delay)

    path = SESSIONS_DIR / f"{session_id}.jsonl"
    if not path.exists():
        print(f"未找到会话落盘 {path}，验收失败。")
        sys.exit(1)
    return analyze_jsonl(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="F3 长面试验收：追问链统计与验收结论")
    parser.add_argument("--since", type=int, default=0, help="只看最近 N 天的会话")
    parser.add_argument("--json", action="store_true", help="机器可读输出")
    parser.add_argument(
        "--drive", action="store_true", help="拉起一场新长面并验收（需 agents 服务与 LLM key）"
    )
    parser.add_argument("--drive-delay", type=int, default=105, help="真实长面每轮间隔秒数（默认 105）")
    parser.add_argument("--drive-max-minutes", type=int, default=35, help="真实长面最长分钟数（默认 35）")
    parser.add_argument("--agents-base", default=AGENTS_BASE, help="agents 服务地址")
    parser.add_argument(
        "--synthetic",
        action="store_true",
        help="使用仓库内人工合成 fixture，不读取或外发本地题库内容",
    )
    parser.add_argument(
        "--allow-local-data-egress",
        action="store_true",
        help="明确允许 --drive 读取本地题库并把题目/参考答案发送给外部模型",
    )
    parser.add_argument("--dir", default=str(SESSIONS_DIR), help="会话目录（默认 data/sessions）")
    args = parser.parse_args()

    if args.drive:
        if not args.synthetic and not args.allow_local_data_egress:
            parser.error(
                "--drive 默认拒绝外发本地题库；请使用 --synthetic，"
                "或在确认数据边界后显式添加 --allow-local-data-egress"
            )
        stats = [
            drive_session(
                max_minutes=args.drive_max_minutes,
                turn_delay=max(0, args.drive_delay),
                agents_base=args.agents_base.rstrip("/"),
                synthetic=args.synthetic,
            )
        ]
    else:
        today = datetime.now(UTC).date()
        files = sorted(glob.glob(str(Path(args.dir) / "*.jsonl")))
        stats = []
        for f in files:
            path = Path(f)
            try:
                mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).date()
            except OSError:
                mtime = today
            if args.since and (today - mtime).days > args.since:
                continue
            stats.append(analyze_jsonl(path))

    return summarize(stats, args.json)


if __name__ == "__main__":
    raise SystemExit(main())

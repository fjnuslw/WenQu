import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from getoffer.api.routers.sessions import _load_transcript

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verify_f3_interview.py"
SPEC = importlib.util.spec_from_file_location("verify_f3_interview", SCRIPT)
assert SPEC and SPEC.loader
verify = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify)


def _event(ts: datetime, **payload) -> str:
    return json.dumps({"ts": ts.isoformat(), **payload}, ensure_ascii=False)


def test_v2_analysis_uses_decision_events_and_reports_contract_health(tmp_path: Path):
    start = datetime(2026, 9, 1, tzinfo=UTC)
    lines = [
        _event(
            start,
            type="session_start",
            config={"mode": "mock"},
            runtime={"protocolVersion": "f3.v2.one_step_question_arg"},
        )
    ]
    for index in range(8):
        at = start + timedelta(minutes=3, seconds=index)
        lines.append(_event(at, type="user", text=f"answer-{index}"))
        lines.append(
            _event(
                at + timedelta(seconds=1),
                type="interview_decision",
                turnNo=index + 1,
                requestedAction="probe",
                appliedAction="probe",
                depthBefore=0,
                depthAfter=1,
                forcedByPolicy=False,
            )
        )
        lines.append(
            _event(
                at + timedelta(seconds=2),
                type="assistant",
                text="follow-up",
                state={"phase": "knowledge", "followUpDepth": 1},
            )
        )
    lines.append(
        _event(
            start + timedelta(minutes=31),
            type="state_transition",
            before={},
            after={"status": "closing", "phase": "closing"},
        )
    )
    path = tmp_path / "v2.jsonl"
    path.write_text("\n".join(lines), encoding="utf-8")

    stat = verify.analyze_jsonl(path)
    assert stat["contract_version"] == "v2"
    assert stat["protocol_version"] == "f3.v2.one_step_question_arg"
    assert stat["chains"] == 8
    assert stat["probe_turns"] == 8
    assert stat["decision_coverage"] == 1.0
    assert stat["protocol_errors"] == 0
    assert stat["decision_latency_p50_ms"] == 1000
    assert stat["total_turn_latency_p50_ms"] == 2000
    assert stat["duration_seconds"] >= 30 * 60
    assert stat["final_status"] == "closing"
    assert stat["final_phase"] == "closing"
    assert verify.is_pass(stat)
    assert not verify.is_pass({**stat, "duration_seconds": 1799.9, "minutes": 30.0})
    assert not verify.is_pass({**stat, "protocol_version": "f3.v2.two_step"})
    assert not verify.is_pass({**stat, "final_status": "active"})
    assert not verify.is_pass({**stat, "final_phase": "knowledge"})


def test_protocol_error_or_missing_decision_fails_v2_acceptance(tmp_path: Path):
    start = datetime(2026, 9, 1, tzinfo=UTC)
    path = tmp_path / "broken.jsonl"
    path.write_text(
        "\n".join(
            [
                _event(start, type="session_start", config={"mode": "mock"}),
                _event(start + timedelta(minutes=1), type="user", text="answer"),
                _event(
                    start + timedelta(minutes=26),
                    type="protocol_error",
                    code="missing_decision",
                ),
                _event(
                    start + timedelta(minutes=26, seconds=1),
                    type="assistant",
                    text="fallback",
                    state={"phase": "knowledge", "followUpDepth": 0},
                ),
            ]
        ),
        encoding="utf-8",
    )

    stat = verify.analyze_jsonl(path)
    assert stat["decision_coverage"] == 0
    assert stat["protocol_errors"] == 1
    assert not verify.is_pass(stat)


def test_report_transcript_ignores_v2_control_events(tmp_path: Path):
    """新增 decision/transition 只用于审计，不能污染离线评分对话。"""
    start = datetime(2026, 9, 1, tzinfo=UTC)
    path = tmp_path / "report-compatible.jsonl"
    control_events = [
        _event(
            start + timedelta(milliseconds=index + 2),
            type="interview_decision" if index % 2 == 0 else "state_transition",
            requestedAction="probe",
            appliedAction="probe",
            before={},
            after={},
        )
        for index in range(90)
    ]
    path.write_text(
        "\n".join(
            [
                _event(start, type="session_start", config={"mode": "mock"}),
                _event(start + timedelta(seconds=1), type="user", text="候选人原话"),
                *control_events,
                _event(start + timedelta(seconds=4), type="assistant", text="面试官追问"),
            ]
        ),
        encoding="utf-8",
    )

    loaded = _load_transcript(path)
    assert loaded["transcript"] == "候选人：候选人原话\n\n面试官：面试官追问"
    assert "interview_decision" not in loaded["transcript"]

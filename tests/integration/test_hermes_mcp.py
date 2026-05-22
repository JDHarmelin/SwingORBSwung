"""Tests for the Hermes MCP bridge — tool surface + execution-moment wiring."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from trading_engine.core.config import load_app_config
from trading_engine.core.types import (
    Direction,
    SetupType,
    Signal,
    SignalEvent,
    SignalStatus,
    TargetPlan,
)
from trading_engine.integrations.hermes_mcp import build_hermes_mcp
from trading_engine.services.signal_service import SignalService


class _FakeRepo:
    def __init__(self) -> None:
        self.signals: dict[str, Signal] = {}
        self.events: list[SignalEvent] = []

    async def save_signal(self, signal: Signal) -> None:
        self.signals[signal.signal_id] = signal

    async def get_signal(self, signal_id: str) -> Signal | None:
        return self.signals.get(signal_id)

    async def open_signals(self) -> list[Signal]:
        open_st = {SignalStatus.PENDING, SignalStatus.TRIGGERED, SignalStatus.TRIMMED}
        return [s for s in self.signals.values() if s.status in open_st]

    async def append_signal_event(self, event: SignalEvent) -> None:
        self.events.append(event)

    async def list_signal_events(self, signal_id: str) -> list[SignalEvent]:
        return [e for e in self.events if e.signal_id == signal_id]

    async def list_events_by_type(self, event_type: str) -> list[SignalEvent]:
        return [e for e in self.events if e.event_type == event_type]

    async def latest_regime(self) -> None:
        return None


class _FakeAlert:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def send(self, message: str, *, dedupe_key: str) -> None:
        self.sent.append((message, dedupe_key))


def _signal(signal_id: str, *, age_hours: float) -> Signal:
    return Signal(
        signal_id=signal_id,
        timestamp=datetime.now(tz=UTC) - timedelta(hours=age_hours),
        symbol="TEST",
        setup_type=SetupType.B_BREAKOUT_RETEST,
        direction=Direction.LONG,
        trigger_price=100.0,
        stop_price=95.0,
        target_plan=TargetPlan(),
        rationale="test",
        confidence=0.7,
        status=SignalStatus.PENDING,
    )


def _build() -> tuple[Any, _FakeRepo, _FakeAlert]:
    repo = _FakeRepo()
    alerts = _FakeAlert()
    svc = SignalService(None, repo, alerts, config=load_app_config(), gate=None)  # type: ignore[arg-type]
    return build_hermes_mcp(svc, repo), repo, alerts  # type: ignore[arg-type]


def _call(mcp: Any, name: str, args: dict[str, Any]) -> Any:
    res = asyncio.run(mcp.call_tool(name, args))
    content = res[0] if isinstance(res, tuple) else res
    return json.loads(content[0].text)


def test_bridge_exposes_expected_tools() -> None:
    mcp, _repo, _alerts = _build()
    names = {t.name for t in asyncio.run(mcp.list_tools())}
    assert {
        "engine_status",
        "list_candidates",
        "get_candidate",
        "outcome_stats",
        "confirm_candidate",
        "scan_now",
    } <= names


def test_list_candidates_hides_stale_by_default() -> None:
    mcp, repo, _alerts = _build()
    asyncio.run(repo.save_signal(_signal("fresh", age_hours=1)))
    asyncio.run(repo.save_signal(_signal("old", age_hours=48)))

    fresh_only = _call(mcp, "list_candidates", {})["candidates"]
    assert {c["signal_id"] for c in fresh_only} == {"fresh"}

    with_stale = _call(mcp, "list_candidates", {"include_stale": True})["candidates"]
    assert {c["signal_id"] for c in with_stale} == {"fresh", "old"}


def test_confirm_candidate_fires_alert() -> None:
    mcp, repo, alerts = _build()
    asyncio.run(repo.save_signal(_signal("fresh", age_hours=1)))

    out = _call(mcp, "confirm_candidate", {"signal_id": "fresh", "confidence": 0.9})

    assert out["status"] == "triggered"
    assert out["alert_sent"] is True
    assert repo.signals["fresh"].status == SignalStatus.TRIGGERED
    assert len(alerts.sent) == 1


def test_confirm_candidate_rejects_stale_and_missing() -> None:
    mcp, repo, _alerts = _build()
    asyncio.run(repo.save_signal(_signal("old", age_hours=48)))

    assert _call(mcp, "confirm_candidate", {"signal_id": "old"})["error"] == "stale"
    assert _call(mcp, "confirm_candidate", {"signal_id": "nope"})["error"] == "not_found"


def test_outcome_stats_aggregates_paper_log() -> None:
    mcp, repo, _alerts = _build()
    asyncio.run(
        repo.append_signal_event(
            SignalEvent(
                signal_id="x",
                event_timestamp=datetime.now(tz=UTC),
                event_type="paper_outcome",
                event_payload={"result": "win", "r_multiple": 2.0},
            )
        )
    )
    stats = _call(mcp, "outcome_stats", {})
    assert stats["samples"] == 1
    assert stats["counts"]["win"] == 1
    assert stats["win_rate"] == 1.0
    assert stats["avg_r"] == 2.0

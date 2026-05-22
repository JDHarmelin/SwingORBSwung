"""Hermes MCP bridge — expose the engine's execution-only surface as MCP tools.

Architecture (see project memory): SwingORSwung is the deterministic *sensor*;
the Hermes agent is the *brain*. This module runs an MCP **server** so Hermes
(an MCP client) can read candidates plus the paper-outcome learning log and call
``confirm_candidate`` at the execution moment.

GUARDRAIL: every tool here is ALERT / PAPER-ONLY. ``confirm_candidate`` fires a
human alert (Telegram/console) and flips paper state — it NEVER places an order
or moves money. There is deliberately no order/broker tool in this surface.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from mcp.server.fastmcp import FastMCP

from trading_engine.core.interfaces import Repository
from trading_engine.core.types import Signal, SignalStatus
from trading_engine.services.signal_service import SignalService

INSTRUCTIONS = (
    "SwingORSwung execution-only sensor. Read candidates and the paper-outcome "
    "history, then call confirm_candidate(signal_id, confidence, reason) to fire "
    "a human alert at the execution moment. Alert/paper-only: no orders are ever "
    "placed."
)


def _candidate_view(signal: Signal, svc: SignalService, now: datetime) -> dict[str, Any]:
    view: dict[str, Any] = signal.model_dump(mode="json")
    age_h = (now - signal.timestamp).total_seconds() / 3600.0
    view["age_hours"] = round(age_h, 2)
    view["stale"] = svc.is_stale(signal, now=now)
    return view


def build_hermes_mcp(svc: SignalService, repo: Repository) -> FastMCP:
    """Build the FastMCP server that exposes the engine to Hermes."""
    mcp: FastMCP = FastMCP("swingorswung", instructions=INSTRUCTIONS)

    @mcp.tool()
    async def engine_status() -> dict[str, Any]:
        """Health/summary: candidate TTL, open-candidate counts, latest regime."""
        now = datetime.now(tz=UTC)
        open_signals = await repo.open_signals()
        pending = [s for s in open_signals if s.status == SignalStatus.PENDING]
        regime = await repo.latest_regime()
        return {
            "candidate_ttl_hours": svc.candidate_ttl_hours,
            "open_signals": len(open_signals),
            "pending_candidates": len(pending),
            "fresh_candidates": sum(1 for s in pending if not svc.is_stale(s, now=now)),
            "regime": regime.model_dump(mode="json") if regime else None,
            "execution_only": True,
        }

    @mcp.tool()
    async def list_candidates(include_stale: bool = False) -> dict[str, Any]:
        """List open PENDING candidates awaiting an execution decision."""
        now = datetime.now(tz=UTC)
        out: list[dict[str, Any]] = []
        for s in await repo.open_signals():
            if s.status != SignalStatus.PENDING:
                continue
            if not include_stale and svc.is_stale(s, now=now):
                continue
            out.append(_candidate_view(s, svc, now))
        return {"candidates": out, "count": len(out)}

    @mcp.tool()
    async def get_candidate(signal_id: str) -> dict[str, Any]:
        """Full detail for one candidate, including its event history."""
        signal = await repo.get_signal(signal_id)
        if signal is None:
            return {"error": "not_found", "signal_id": signal_id}
        now = datetime.now(tz=UTC)
        view = _candidate_view(signal, svc, now)
        events = await repo.list_signal_events(signal_id)
        view["events"] = [e.model_dump(mode="json") for e in events]
        return view

    @mcp.tool()
    async def outcome_stats() -> dict[str, Any]:
        """Aggregate the paper-outcome learning log (win/loss/no_trigger, avg R)."""
        events = await repo.list_events_by_type("paper_outcome")
        counts: dict[str, int] = {"win": 0, "loss": 0, "no_trigger": 0}
        r_values: list[float] = []
        for e in events:
            result = str(e.event_payload.get("result", ""))
            if result in counts:
                counts[result] += 1
            r = e.event_payload.get("r_multiple")
            if isinstance(r, int | float):
                r_values.append(float(r))
        resolved = counts["win"] + counts["loss"]
        return {
            "samples": len(events),
            "counts": counts,
            "win_rate": (counts["win"] / resolved) if resolved else None,
            "avg_r": (sum(r_values) / len(r_values)) if r_values else None,
        }

    @mcp.tool()
    async def confirm_candidate(
        signal_id: str, confidence: float = 0.7, reason: str = "hermes_confirmed"
    ) -> dict[str, Any]:
        """Fire the execution alert for a candidate (the execution moment).

        ALERT/PAPER-ONLY: sends a human alert and marks the candidate TRIGGERED.
        Never places an order. ``confidence`` in [0, 1]; ``reason`` is recorded.
        """
        if not 0.0 <= confidence <= 1.0:
            return {"error": "confidence_out_of_range", "confidence": confidence}
        signal = await repo.get_signal(signal_id)
        if signal is None:
            return {"error": "not_found", "signal_id": signal_id}
        if signal.status != SignalStatus.PENDING:
            return {"error": "not_pending", "status": signal.status.value}
        if svc.is_stale(signal):
            return {"error": "stale", "ttl_hours": svc.candidate_ttl_hours}
        alert_sent = await svc.confirm_signal(signal, confidence=confidence, reason_codes=[reason])
        return {
            "signal_id": signal_id,
            "status": SignalStatus.TRIGGERED.value,
            "alert_sent": alert_sent,
        }

    @mcp.tool()
    async def scan_now() -> dict[str, Any]:
        """Run one scan tick (generate candidates + expire stale). Fires no alerts."""
        created = await svc.scan_once(alert_candidates=False)
        expired = await svc.expire_stale_candidates()
        return {"candidates": len(created), "expired": len(expired)}

    return mcp

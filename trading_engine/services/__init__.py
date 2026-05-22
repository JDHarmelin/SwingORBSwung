"""Services — orchestration of the data → setup → alert pipeline."""

from trading_engine.services.backfill import backfill_symbol, backfill_universe
from trading_engine.services.confirmation import (
    AlwaysOnGate,
    ConfirmationDecision,
    ConfirmationGate,
    PriceCrossConfirmationGate,
)
from trading_engine.services.management_service import ManagementService
from trading_engine.services.paper_tracker import (
    PaperOutcome,
    record_outcome,
    simulate_outcome,
)
from trading_engine.services.scheduler import TickResult, run_loop, run_tick
from trading_engine.services.signal_service import PipelineResult, SignalService

__all__ = [
    "AlwaysOnGate",
    "ConfirmationDecision",
    "ConfirmationGate",
    "ManagementService",
    "PaperOutcome",
    "PipelineResult",
    "PriceCrossConfirmationGate",
    "SignalService",
    "TickResult",
    "backfill_symbol",
    "backfill_universe",
    "record_outcome",
    "run_loop",
    "run_tick",
    "simulate_outcome",
]

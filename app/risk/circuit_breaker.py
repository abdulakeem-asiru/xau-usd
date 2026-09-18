"""Pure daily-loss circuit-breaker logic, deliberately decoupled from persistence
so the exact same decision code runs in the live loop (state backed by the
`circuit_breaker_state` DB table) and in the backtester (state kept in memory,
"today" driven by the simulated bar's timestamp rather than wall-clock time).
"""
from dataclasses import dataclass
from datetime import date, datetime


@dataclass
class CircuitBreakerSnapshot:
    trading_day: date
    starting_equity: float
    realized_pnl_today: float = 0.0
    halted: bool = False
    halted_reason: str | None = None


class CircuitBreaker:
    def __init__(self, max_daily_loss_pct: float):
        self.max_daily_loss_pct = max_daily_loss_pct

    def is_new_trading_day(self, snapshot: CircuitBreakerSnapshot, current_time: datetime) -> bool:
        return snapshot.trading_day != current_time.date()

    def start_new_day(self, current_time: datetime, starting_equity: float) -> CircuitBreakerSnapshot:
        return CircuitBreakerSnapshot(trading_day=current_time.date(), starting_equity=starting_equity)

    def record_pnl(self, snapshot: CircuitBreakerSnapshot, pnl: float) -> CircuitBreakerSnapshot:
        """Mutates and returns the snapshot with realized PnL applied and halts if breached.
        Halting is one-directional within a day — once halted, only a new trading day clears it.
        """
        snapshot.realized_pnl_today += pnl
        max_loss = snapshot.starting_equity * (self.max_daily_loss_pct / 100)
        if snapshot.realized_pnl_today <= -max_loss and not snapshot.halted:
            snapshot.halted = True
            snapshot.halted_reason = (
                f"Daily loss limit hit: {snapshot.realized_pnl_today:.2f} <= -{max_loss:.2f} "
                f"({self.max_daily_loss_pct}% of starting equity {snapshot.starting_equity:.2f})"
            )
        return snapshot

    def is_halted(self, snapshot: CircuitBreakerSnapshot) -> bool:
        return snapshot.halted

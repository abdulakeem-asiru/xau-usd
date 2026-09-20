from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(primary_key=True)
    broker_trade_id: Mapped[str | None] = mapped_column(String, nullable=True)
    instrument: Mapped[str] = mapped_column(String, default="XAU_USD", nullable=False)
    side: Mapped[str] = mapped_column(String, nullable=False)  # "buy" | "sell"
    volume: Mapped[float] = mapped_column(Numeric, nullable=False)  # lots (MT5 native quantity)
    entry_price: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    stop_loss_price: Mapped[float] = mapped_column(Numeric, nullable=False)
    take_profit_price: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    trailing_stop_distance: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    exit_price: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)  # pending|open|closed|cancelled
    close_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    pnl: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    pnl_pct: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    risk_amount: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    strategy_name: Mapped[str] = mapped_column(String, nullable=False)
    signal_reason: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    mode: Mapped[str] = mapped_column(String, nullable=False)  # "practice" | "live"
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class EquitySnapshot(Base):
    __tablename__ = "equity_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    balance: Mapped[float] = mapped_column(Numeric, nullable=False)
    equity: Mapped[float] = mapped_column(Numeric, nullable=False)
    open_positions_count: Mapped[int] = mapped_column(nullable=False)
    mode: Mapped[str] = mapped_column(String, nullable=False)


class BotConfig(Base):
    __tablename__ = "bot_config"
    __table_args__ = (CheckConstraint("id = 1", name="bot_config_singleton"),)

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    is_running: Mapped[bool] = mapped_column(default=True, nullable=False)
    is_paused: Mapped[bool] = mapped_column(default=False, nullable=False)
    mode: Mapped[str] = mapped_column(String, default="practice", nullable=False)
    strategy_name: Mapped[str] = mapped_column(String, default="ema_atr_rsi_macd", nullable=False)
    strategy_params: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    risk_pct_per_trade: Mapped[float] = mapped_column(Numeric, default=1.0, nullable=False)
    max_daily_loss_pct: Mapped[float] = mapped_column(Numeric, default=3.0, nullable=False)
    max_concurrent_positions: Mapped[int] = mapped_column(default=1, nullable=False)
    flip_mode: Mapped[bool] = mapped_column(default=False, nullable=False)
    flip_risk_pct: Mapped[float] = mapped_column(Numeric, default=10.0, nullable=False)
    flip_equity_floor: Mapped[float] = mapped_column(Numeric, default=25.0, nullable=False)
    flip_equity_target: Mapped[float] = mapped_column(Numeric, default=100.0, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CircuitBreakerState(Base):
    __tablename__ = "circuit_breaker_state"

    id: Mapped[int] = mapped_column(primary_key=True)
    trading_day: Mapped[date] = mapped_column(Date, unique=True, nullable=False)
    starting_equity: Mapped[float] = mapped_column(Numeric, nullable=False)
    realized_pnl_today: Mapped[float] = mapped_column(Numeric, default=0, nullable=False)
    halted: Mapped[bool] = mapped_column(default=False, nullable=False)
    halted_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    halted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BacktestRun(Base):
    __tablename__ = "backtest_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    strategy_name: Mapped[str] = mapped_column(String, nullable=False)
    params: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    instrument: Mapped[str] = mapped_column(String, nullable=False)
    timeframe: Mapped[str] = mapped_column(String, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    initial_balance: Mapped[float] = mapped_column(Numeric, nullable=False)
    final_balance: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    win_rate: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    max_drawdown_pct: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    sharpe_ratio: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    profit_factor: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    total_trades: Mapped[int | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String, default="running", nullable=False)
    error_message: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BacktestTrade(Base):
    __tablename__ = "backtest_trades"

    id: Mapped[int] = mapped_column(primary_key=True)
    backtest_run_id: Mapped[int] = mapped_column(nullable=False)
    entry_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    exit_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    side: Mapped[str] = mapped_column(String, nullable=False)
    entry_price: Mapped[float] = mapped_column(Numeric, nullable=False)
    exit_price: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    pnl: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    exit_reason: Mapped[str | None] = mapped_column(String, nullable=True)

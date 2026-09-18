from datetime import datetime, timezone

import pytest

from app.broker.schemas import SymbolSpecification
from app.risk.circuit_breaker import CircuitBreaker
from app.risk.limits import can_open_new_position
from app.risk.position_sizing import PositionTooSmallError, size_position

XAUUSD_SPEC = SymbolSpecification(contract_size=100.0, min_volume=0.01, max_volume=100.0, volume_step=0.01)


def test_size_position_risks_exact_percentage():
    volume = size_position(
        equity=10_000, risk_pct_per_trade=1.0, entry_price=2400.0, stop_loss_price=2390.0, spec=XAUUSD_SPEC
    )
    # $100 risk / ($10 stop distance * 100 oz/lot) = 0.1 lots; a full stop-out loses
    # exactly $100 = 1% of equity
    assert volume == pytest.approx(0.1)


def test_size_position_rejects_zero_width_stop():
    with pytest.raises(ValueError):
        size_position(
            equity=10_000, risk_pct_per_trade=1.0, entry_price=2400.0, stop_loss_price=2400.0, spec=XAUUSD_SPEC
        )


def test_size_position_refuses_when_min_volume_forces_outsized_risk():
    # A small account risking a tiny % with a normal stop distance computes a volume
    # far below the broker's minimum tradeable lot size — forcing min_volume here would
    # risk ~10x the intended amount, which must be refused rather than silently accepted.
    with pytest.raises(PositionTooSmallError):
        size_position(
            equity=1_000, risk_pct_per_trade=0.1, entry_price=2400.0, stop_loss_price=2390.0, spec=XAUUSD_SPEC
        )


def test_size_position_respects_max_volume_cap():
    huge_equity_spec = SymbolSpecification(contract_size=100.0, min_volume=0.01, max_volume=5.0, volume_step=0.01)
    volume = size_position(
        equity=10_000_000, risk_pct_per_trade=1.0, entry_price=2400.0, stop_loss_price=2390.0, spec=huge_equity_spec
    )
    assert volume == 5.0


def test_can_open_new_position_respects_cap():
    assert can_open_new_position(open_positions_count=0, max_concurrent_positions=1) is True
    assert can_open_new_position(open_positions_count=1, max_concurrent_positions=1) is False


def test_circuit_breaker_halts_on_daily_loss_limit():
    breaker = CircuitBreaker(max_daily_loss_pct=3.0)
    snapshot = breaker.start_new_day(datetime(2026, 1, 1, tzinfo=timezone.utc), starting_equity=10_000)

    breaker.record_pnl(snapshot, -200)
    assert breaker.is_halted(snapshot) is False

    breaker.record_pnl(snapshot, -150)  # total -350, breaches -300 (3% of 10,000)
    assert breaker.is_halted(snapshot) is True
    assert "Daily loss limit hit" in snapshot.halted_reason


def test_circuit_breaker_does_not_unhalt_within_same_day_on_recovery():
    breaker = CircuitBreaker(max_daily_loss_pct=3.0)
    snapshot = breaker.start_new_day(datetime(2026, 1, 1, tzinfo=timezone.utc), starting_equity=10_000)
    breaker.record_pnl(snapshot, -400)
    assert breaker.is_halted(snapshot) is True

    breaker.record_pnl(snapshot, +500)  # a later winning trade must not silently re-enable trading today
    assert breaker.is_halted(snapshot) is True


def test_circuit_breaker_new_day_resets_state():
    breaker = CircuitBreaker(max_daily_loss_pct=3.0)
    day1 = breaker.start_new_day(datetime(2026, 1, 1, tzinfo=timezone.utc), starting_equity=10_000)
    breaker.record_pnl(day1, -400)
    assert breaker.is_halted(day1) is True

    assert breaker.is_new_trading_day(day1, datetime(2026, 1, 2, tzinfo=timezone.utc)) is True
    day2 = breaker.start_new_day(datetime(2026, 1, 2, tzinfo=timezone.utc), starting_equity=9_600)
    assert breaker.is_halted(day2) is False

import pytest

from app.broker.schemas import SymbolSpecification
from app.risk.flip import FlipSettings, FlipStatus, check_flip_status, flip_end_message
from app.risk.position_sizing import PositionTooSmallError, size_position

SETTINGS = FlipSettings(risk_pct_per_trade=10.0, equity_floor=25.0, equity_target=100.0)
XAUUSD_SPEC = SymbolSpecification(contract_size=100.0, min_volume=0.01, max_volume=100.0, volume_step=0.01)


def test_status_active_between_floor_and_target():
    assert check_flip_status(50.5, SETTINGS) is FlipStatus.ACTIVE


def test_status_floor_hit_at_and_below_floor():
    assert check_flip_status(25.0, SETTINGS) is FlipStatus.FLOOR_HIT
    assert check_flip_status(10.0, SETTINGS) is FlipStatus.FLOOR_HIT


def test_status_target_hit_at_and_above_target():
    assert check_flip_status(100.0, SETTINGS) is FlipStatus.TARGET_HIT
    assert check_flip_status(240.0, SETTINGS) is FlipStatus.TARGET_HIT


def test_floor_wins_if_settings_overlap():
    overlapping = FlipSettings(risk_pct_per_trade=10.0, equity_floor=60.0, equity_target=40.0)
    assert check_flip_status(50.0, overlapping) is FlipStatus.FLOOR_HIT


def test_end_messages_name_the_reason_and_the_equity():
    target_msg = flip_end_message(FlipStatus.TARGET_HIT, 104.2, SETTINGS)
    floor_msg = flip_end_message(FlipStatus.FLOOR_HIT, 21.7, SETTINGS)
    assert "target" in target_msg and "104.20" in target_msg
    assert "floor" in floor_msg and "21.70" in floor_msg


def test_flip_risk_lets_a_minimum_lot_trade_through_on_a_50_dollar_account():
    # The reason flip mode exists: at the normal 1% this account's minimum lot is refused.
    assert size_position(50.5, 10.0, entry_price=2400.0, stop_loss_price=2395.0, spec=XAUUSD_SPEC) == 0.01
    with pytest.raises(PositionTooSmallError):
        size_position(50.5, 1.0, entry_price=2400.0, stop_loss_price=2395.0, spec=XAUUSD_SPEC)


def test_flip_risk_still_refuses_stops_too_wide_for_the_minimum_lot():
    # 10% of 50.5 = 5.05; the tolerated ceiling is 1.5x that = 7.575, so an $8 stop is refused.
    with pytest.raises(PositionTooSmallError):
        size_position(50.5, 10.0, entry_price=2400.0, stop_loss_price=2392.0, spec=XAUUSD_SPEC)

"""Position sizing by fixed percentage risk per trade, expressed in lots (MT5's
native trading unit) rather than raw ounces — the conversion depends on the
symbol's contract size, which varies by broker and must always be looked up
live via `broker.get_symbol_specification()`, never assumed.
"""
from app.broker.schemas import SymbolSpecification

# If the broker's minimum tradeable volume forces a position that risks more than
# this multiple of the intended risk_pct_per_trade, refuse rather than silently take
# on outsized risk — this can happen on a small account with a tight stop distance.
MAX_RISK_OVERAGE_MULTIPLE = 1.5


class PositionTooSmallError(ValueError):
    """Raised when the broker's minimum volume would force more risk than intended."""


def size_position(
    equity: float, risk_pct_per_trade: float, entry_price: float, stop_loss_price: float, spec: SymbolSpecification
) -> float:
    """Returns a volume in lots, sized so that a full stop-loss hit loses
    approximately `risk_pct_per_trade`% of current equity — "approximately" because
    the result is rounded to the broker's volume_step and clamped to
    [min_volume, max_volume], which can shift the realized risk slightly.
    """
    stop_distance = abs(entry_price - stop_loss_price)
    if stop_distance <= 0:
        raise ValueError("stop_distance must be positive — refusing to size a position with a zero-width stop")

    risk_amount = equity * (risk_pct_per_trade / 100)
    # risk per lot = stop_distance (price move) * contract_size (units per lot)
    risk_per_lot = stop_distance * spec.contract_size
    raw_volume = risk_amount / risk_per_lot

    steps = round(raw_volume / spec.volume_step)
    volume = steps * spec.volume_step
    volume = max(spec.min_volume, min(spec.max_volume, volume))

    actual_risk_amount = volume * risk_per_lot
    if actual_risk_amount > risk_amount * MAX_RISK_OVERAGE_MULTIPLE:
        raise PositionTooSmallError(
            f"Broker minimum volume ({spec.min_volume}) would risk {actual_risk_amount:.2f} "
            f"({actual_risk_amount / equity * 100:.2f}% of equity), more than "
            f"{MAX_RISK_OVERAGE_MULTIPLE}x the intended {risk_pct_per_trade}% risk — refusing to trade."
        )

    return round(volume, 8)

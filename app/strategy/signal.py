from dataclasses import dataclass, field


@dataclass
class Signal:
    side: str  # "buy" | "sell"
    stop_loss_price: float
    take_profit_price: float | None
    trailing_stop_distance: float | None
    reason: dict = field(default_factory=dict)


@dataclass
class Adjustment:
    action: str  # "hold" | "move_stop" | "close"
    new_stop_loss_price: float | None = None
    reason: str = ""

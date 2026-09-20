"""Flip mode: an opt-in, bounded high-risk run for a small account.

It does two things and nothing else:
  1. Sizes trades off its own, higher risk percentage instead of the normal one.
  2. Ends the run — no new entries — once equity reaches a floor or a target, so a run
     can't quietly drift on past the point the operator chose.

It does NOT improve the strategy's odds. Whether a run climbs to the target or falls to
the floor is decided by the strategy's edge and by variance; this only bounds the outcome.

Pure logic with no DB dependency so the live loop and tests can share it.
"""
from dataclasses import dataclass
from enum import Enum


class FlipStatus(str, Enum):
    ACTIVE = "active"
    FLOOR_HIT = "floor_hit"
    TARGET_HIT = "target_hit"


@dataclass(frozen=True)
class FlipSettings:
    risk_pct_per_trade: float
    equity_floor: float
    equity_target: float


def check_flip_status(equity: float, settings: FlipSettings) -> FlipStatus:
    # Floor is checked first: if the two were ever misconfigured so equity satisfies both,
    # stopping is the safer reading.
    if equity <= settings.equity_floor:
        return FlipStatus.FLOOR_HIT
    if equity >= settings.equity_target:
        return FlipStatus.TARGET_HIT
    return FlipStatus.ACTIVE


def flip_end_message(status: FlipStatus, equity: float, settings: FlipSettings) -> str:
    if status is FlipStatus.TARGET_HIT:
        return (
            f"🎯 Flip run reached its target: equity {equity:.2f} >= {settings.equity_target:.2f}. "
            "Flip mode is off and the bot is paused — withdraw some profit or start a new run."
        )
    return (
        f"🛑 Flip run hit its floor: equity {equity:.2f} <= {settings.equity_floor:.2f}. "
        "Flip mode is off and the bot is paused."
    )

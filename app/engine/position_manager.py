"""Ongoing management of already-open positions — shared by live loop and backtester.

This is what makes the bot "adjust positions based on recent analysis" rather than
just waiting passively for the initial stop-loss/take-profit: every tick, each open
position is re-evaluated against the strategy's `manage_position` logic, and any
stop adjustment or early close is applied through the broker (not just tracked
in-app), so it survives a restart and is reflected at the source of truth.
"""
from dataclasses import dataclass

import pandas as pd

from app.broker.interface import BrokerProtocol
from app.broker.schemas import Position
from app.strategy.base import StrategyBase


@dataclass
class ManagedOutcome:
    position: Position
    action: str  # "move_stop" | "close"
    new_stop_loss_price: float | None = None
    close_fill_price: float | None = None
    reason: str = ""


async def manage_open_positions(
    positions: list[Position], df: pd.DataFrame, strategy: StrategyBase, broker: BrokerProtocol
) -> list[ManagedOutcome]:
    outcomes: list[ManagedOutcome] = []
    for position in positions:
        adjustment = strategy.manage_position(position, df)
        if adjustment.action == "hold":
            continue
        if adjustment.action == "move_stop":
            await broker.modify_stop_loss(position.broker_trade_id, adjustment.new_stop_loss_price)
            outcomes.append(
                ManagedOutcome(
                    position=position,
                    action="move_stop",
                    new_stop_loss_price=adjustment.new_stop_loss_price,
                    reason=adjustment.reason,
                )
            )
        elif adjustment.action == "close":
            fill_price = await broker.close_position(position.broker_trade_id)
            outcomes.append(
                ManagedOutcome(position=position, action="close", close_fill_price=fill_price, reason=adjustment.reason)
            )
    return outcomes

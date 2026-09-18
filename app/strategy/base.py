from abc import ABC, abstractmethod

import pandas as pd

from app.broker.schemas import Position
from app.strategy.signal import Adjustment, Signal


class StrategyBase(ABC):
    """Contract the trading loop and backtester depend on. A strategy owns both
    entry-signal generation and ongoing management of positions it opened —
    this is what lets the bot "adjust positions based on recent analysis"
    rather than just waiting passively for the initial stop-loss/take-profit.
    """

    name: str

    def __init__(self, params: dict | None = None):
        self.params = params or {}

    @abstractmethod
    def generate_signal(self, df: pd.DataFrame) -> Signal | None:
        """df is a candle+indicator DataFrame ending at the most recently CLOSED bar.
        Return None when no entry condition is met.
        """
        ...

    @abstractmethod
    def manage_position(self, position: Position, df: pd.DataFrame) -> Adjustment:
        """Called every loop tick for each open position. Returns a hold/move_stop/close
        decision — never returns None, so callers always get an explicit action.
        """
        ...

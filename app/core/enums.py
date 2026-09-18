from enum import StrEnum


class BotMode(StrEnum):
    PRACTICE = "practice"
    LIVE = "live"


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class TradeStatus(StrEnum):
    PENDING = "pending"
    OPEN = "open"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class CloseReason(StrEnum):
    SL_HIT = "sl_hit"
    TP_HIT = "tp_hit"
    TRAILING_STOP = "trailing_stop"
    MANUAL = "manual"
    KILL_SWITCH = "kill_switch"
    STRATEGY_EXIT = "strategy_exit"

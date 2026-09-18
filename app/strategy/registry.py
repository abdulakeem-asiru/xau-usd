from app.strategy.base import StrategyBase
from app.strategy.ema_atr_rsi_macd import EmaAtrRsiMacdStrategy

STRATEGY_REGISTRY: dict[str, type[StrategyBase]] = {
    EmaAtrRsiMacdStrategy.name: EmaAtrRsiMacdStrategy,
}


def get_strategy(name: str, params: dict | None = None) -> StrategyBase:
    try:
        cls = STRATEGY_REGISTRY[name]
    except KeyError:
        raise ValueError(f"Unknown strategy '{name}'. Available: {list(STRATEGY_REGISTRY)}") from None
    return cls(params)

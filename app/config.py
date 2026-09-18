from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # MetaApi (bridges to your MT5 broker account — see README for provisioning)
    metaapi_token: str
    metaapi_account_id: str
    metaapi_domain: str = "agiliumtrade.agiliumtrade.ai"
    # The symbol name for gold exactly as it appears in your MT5 terminal's Market
    # Watch — brokers vary (XAUUSD, XAUUSDm, GOLD, GOLDm, ...). Check yours before deploying.
    instrument: str = "XAUUSD"
    # MetaApi/MT5 timeframe strings, e.g. "15m", "1h" — not OANDA-style "M15".
    candle_timeframe: str = "15m"
    # There's no single practice/live toggle for MT5 the way OANDA has a base-URL
    # swap — demo vs live is a property of WHICH account `metaapi_account_id` points
    # to. This flag is a manual, operator-set assertion of that fact, playing the
    # same "infra-level gate the running app can't flip on its own" role that
    # OANDA_ENV played: set it to true only once you've confirmed metaapi_account_id
    # is genuinely a live MT5 account, not a demo.
    broker_live_account_confirmed: bool = False

    # Telegram
    telegram_bot_token: str
    owner_telegram_chat_id: str
    telegram_webhook_secret: str
    telegram_webhook_base_url: str

    # Dashboard auth
    dashboard_username: str
    dashboard_password_hash: str
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 12

    # Database
    database_url: str

    # Trading loop
    poll_interval_seconds: int = 30


@lru_cache
def get_settings() -> Settings:
    return Settings()

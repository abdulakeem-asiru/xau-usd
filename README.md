# XAU/USD Trading Bot

Automated gold (XAU/USD) trading bot on your MT5 broker account (via MetaApi), with
a web dashboard, Telegram notifications/commands, broker-enforced stop-losses, and a
backtester. Deploys as a single service on Railway.

## Honest expectations

No system can guarantee a fixed win rate — anyone claiming that is not being
straight with you. This bot does not promise "80% accuracy." What it does instead:

- A real backtester (`app/backtest/`) that replays the exact same strategy/risk code
  the live bot uses against historical candles, and reports actual win rate, max
  drawdown, Sharpe ratio, and profit factor. Trust those numbers, not a marketing
  claim — run one before you trust the strategy with any money, including practice.
- Every trade carries a broker-side stop-loss attached at order placement, so it
  fires even if this process crashes or Railway restarts the container.
- A daily-loss circuit breaker that halts new entries (not existing position
  management) once a configurable % of the day's starting equity is lost.
- Live trading is off by default and gated behind two independent checks (see
  "Going live" below) — it will not silently start trading real money.

## Prerequisites

1. **An MT5 trading account** with a broker that accepts you (many Nigeria-friendly
   brokers — Exness, HFM, FBS, Tickmill, etc. — offer MT5). You'll need its login
   number, password, and server name (all visible in your MT5 terminal).
2. **A MetaApi account** (metaapi.cloud — free tier covers a single low-volume
   account like this). MT5 has no native API, so MetaApi bridges it to a real
   REST/WebSocket API this bot talks to:
   - Sign up at metaapi.cloud and, from its dashboard, add your MT5 account (enter
     the login/password/server from step 1 — this is a one-time setup done directly
     in MetaApi's UI, so your MT5 password never passes through this bot's code).
   - Generate an API token (MetaApi dashboard → API access) — this is `METAAPI_TOKEN`.
   - Copy the provisioned account's ID — this is `METAAPI_ACCOUNT_ID`.
   - In your MT5 terminal's Market Watch, confirm the exact symbol name for gold
     (commonly `XAUUSD`, but brokers vary — `XAUUSDm`, `GOLD`, etc.) — this is
     `INSTRUMENT`. Also note its contract size, min/max volume, and volume step
     (right-click the symbol → Specification) for accurate backtest P&L later.
3. **Telegram bot** — message [@BotFather](https://t.me/BotFather) on Telegram,
   run `/newbot`, and save the token it gives you. Then message
   [@userinfobot](https://t.me/userinfobot) to get your own numeric chat ID — this
   is your `OWNER_TELEGRAM_CHAT_ID`; only this chat ID can issue bot commands.
4. **Railway account** with a new project and the **Postgres** plugin added to it.

## Environment variables

See `.env.example` for the full list with descriptions. Set these as Railway
service variables (never commit a real `.env`). Notably:

- `BROKER_LIVE_ACCOUNT_CONFIRMED` — leave `false` until you've deliberately decided
  to go live (see "Going live" below). MT5 has no practice/live API toggle the way
  OANDA does — demo vs. live is just a property of which MT5 account you provisioned
  in MetaApi, so this flag is your own manual confirmation of that fact.
- `DATABASE_URL` — set to `${{Postgres.DATABASE_URL}}` in Railway once the Postgres
  plugin is attached, so it's wired automatically.
- `DASHBOARD_PASSWORD_HASH` — generate with:
  `python -c "import bcrypt; print(bcrypt.hashpw(b'your-password', bcrypt.gensalt()).decode())"`
- `TELEGRAM_WEBHOOK_BASE_URL` — your Railway service's public HTTPS domain (found
  under the service's "Settings → Networking" once it's created).

## Local development

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env   # fill in real values; a local Postgres works fine too
alembic upgrade head
uvicorn app.main:app --reload
```

The dashboard login cookie is marked `secure`, so it's only sent over HTTPS. For
local HTTP testing, either test against the deployed Railway URL, or temporarily
set `secure=False` in `app/api/auth.py`'s `set_cookie` call — revert before deploying.

Run the test suite (needs a local Postgres reachable via `DATABASE_URL`):

```bash
pytest
```

## Deploying to Railway

1. Push this repository to GitHub.
2. In Railway: New Project → Deploy from GitHub repo → select this repo.
3. Add the **Postgres** plugin to the project.
4. On the app service, set `DATABASE_URL=${{Postgres.DATABASE_URL}}` and all the
   other environment variables listed above.
5. Railway will build from the included `Dockerfile` and run `entrypoint.sh`, which
   applies database migrations (`alembic upgrade head`) before starting the server.
6. Once deployed, copy the service's public domain into `TELEGRAM_WEBHOOK_BASE_URL`
   and redeploy — the bot registers its Telegram webhook on startup.
7. Visit `https://<your-domain>/dashboard` and log in with `DASHBOARD_USERNAME` /
   the password you hashed into `DASHBOARD_PASSWORD_HASH`.

The bot starts in **practice mode** — it deploys/connects to whichever MT5 account
`METAAPI_ACCOUNT_ID` points to (make that a demo account first) and trades it
immediately using the default strategy and risk settings. Review/adjust risk
settings on the dashboard before letting it run for real. First boot can take a
couple of minutes while MetaApi deploys and synchronizes the account — check
Railway's logs if the dashboard looks empty at first.

## Going live

Flipping to real money requires **both**:

1. `METAAPI_ACCOUNT_ID` actually pointing to a live MT5 account (provisioned as
   such in MetaApi) and `BROKER_LIVE_ACCOUNT_CONFIRMED=true` set as a Railway
   environment variable — restart the service after changing this.
2. On the dashboard, "Switch to live…" → type the exact confirmation phrase shown
   → re-enter your dashboard password.

Either alone is not enough — this is deliberate. Start with a small
`risk_pct_per_trade` the first time you go live, and watch it closely via the
dashboard and Telegram alerts.

## Telegram commands

`/status`, `/pause`, `/resume`, `/balance`, `/close <trade_id>` — all rejected
unless sent from `OWNER_TELEGRAM_CHAT_ID`.

## Dashboard

`/dashboard` — live positions, recent trades, equity curve, strategy/risk config,
pause/resume, the live-mode switch, and a kill switch (closes everything and pauses
immediately). `/backtest` — run and review backtests (double-check the contract
size/volume fields there against your broker's actual symbol specification).

## Architecture notes

- `app/broker/metaapi_client.py` — async client wrapping the official MetaApi
  Python SDK, which bridges to your MT5 account (MT5 has no native REST API).
- `app/engine/executor.py` + `app/engine/position_manager.py` — entry and
  position-management decision logic, shared verbatim between the live loop
  (`app/engine/trading_loop.py`) and the backtester (`app/backtest/engine.py`), so
  a backtest is a faithful preview of live behavior rather than an approximation.
- `app/strategy/ema_atr_rsi_macd.py` — the default trend + momentum strategy.
  Swap or add strategies via `app/strategy/registry.py`.
- `app/engine/state.py` — reconciles the broker's actual open positions against the
  local database on every startup and every tick, since the broker (not our
  database) is the source of truth for what's really open.
- Position sizes are in **lots** (MT5's native quantity), converted from your
  configured risk % using the symbol's real contract size/volume step looked up
  live from the broker (`app/risk/position_sizing.py`) — never hardcoded.

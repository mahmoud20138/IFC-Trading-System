# IFC Trading System — Institutional Flow Confluence

A fully automated (switchable semi-auto/full-auto) trading system for MT5, implementing an 8-layer confluence strategy across Forex, Indices, and Crypto.

---

## Architecture

```
ifc_trading_system/
├── main.py                    # Entry point — APScheduler orchestrator
├── requirements.txt
├── config/
│   ├── settings.py            # All strategy parameters
│   ├── credentials.py         # MT5 login, API keys (gitignored)
│   └── instruments.py         # Watchlist + per-instrument metadata
├── data/
│   ├── mt5_connector.py       # MT5 terminal wrapper
│   ├── intermarket.py         # yfinance DXY, VIX, yields, etc.
│   ├── sentiment.py           # COT, Fear & Greed, retail positioning
│   └── economic_calendar.py   # High-impact news + blackout windows
├── analysis/
│   ├── layer1_intermarket.py  # Macro context scoring
│   ├── layer2_trend.py        # EMA stack + BOS/CHoCH structure
│   ├── layer3_volume_profile.py # POC / VAH / VAL / HVN / LVN
│   ├── layer4_candle_density.py # Body overlap density zones
│   ├── layer5_liquidity.py    # EQH/EQL, sweep detection
│   ├── layer6_fvg_ob.py       # Fair Value Gaps + Order Blocks
│   ├── layer7_order_flow.py   # Tick volume delta proxy
│   ├── layer8_killzone.py     # Session timing + news filter
│   ├── confluence_scorer.py   # 8-layer aggregation → grade
│   ├── setup_detector.py      # 5 setup patterns + TradeSetup
│   └── regime_detector.py     # Market regime classification
├── execution/
│   ├── risk_manager.py        # 5-multiplier position sizing
│   ├── order_manager.py       # MT5 order placement
│   ├── scaling.py             # Entry (50/30/20) and exit (40/30/30)
│   └── trade_manager.py       # Trailing stops, BE, news/session rules
├── journal/
│   ├── models.py              # SQLAlchemy ORM (Trade, DailyStats, etc.)
│   ├── database.py            # CRUD operations
│   └── analytics.py           # Win rate, expectancy, MFE/MAE, equity curve
├── dashboard/
│   ├── app.py                 # Streamlit main (5 pages)
│   ├── pages/
│   │   ├── live_monitor.py    # Real-time positions + market state
│   │   ├── trade_journal.py   # Browse, filter, annotate trades
│   │   ├── performance.py     # Equity curve, breakdowns, KPIs
│   │   ├── analysis_page.py   # Run live 8-layer analysis on any symbol
│   │   └── settings_page.py   # View/change system configuration
│   └── components/
│       ├── charts.py          # Reusable chart builders
│       └── widgets.py         # Status badges, gauges, cards
├── alerts/
│   └── notifier.py            # Telegram alerts + semi-auto confirm buttons
└── utils/
    └── helpers.py             # Time utils, logging, decorators
```

---

## Quick Start

### 1. Prerequisites
- **Windows only** (MT5 Python package is Windows-only)
- **MetaTrader 5** terminal installed, running, and **already logged in**
- **Python 3.9+**

### 2. Install
```bash
cd ifc_trading_system
pip install -r requirements.txt
```

### 3. Configure (Optional)
No MT5 credentials needed — the system attaches to the already-open terminal.

Symbols are pre-configured for **EXNESS** (suffix `m`, e.g. `EURUSDm`, `US30m`, `USTECm`).  
If your broker uses a different suffix (e.g. `c`), edit `config/instruments.py`.

For Telegram alerts (optional), edit `config/credentials.py`:
```python
TELEGRAM_BOT_TOKEN = "123456:ABC..."
TELEGRAM_CHAT_ID = "987654321"
```

### 4. Run
```bash
# Full system (auto-scan, auto-trade during killzones)
python main.py

# Demo / paper mode (logs everything, no real orders)
python main.py --mode demo

# Dashboard (separate terminal)
streamlit run dashboard/app.py
```

---

## The 8 Layers

| # | Layer | What it does |
|---|-------|-------------|
| 1 | **Intermarket** | DXY, yields, VIX, Gold, Oil correlations → risk-on/off regime |
| 2 | **Trend** | EMA stack (10/21/50/200) + BOS/CHoCH on W/D/4H weighted |
| 3 | **Volume Profile** | POC, VAH, VAL, HVN/LVN, naked POCs, profile shape |
| 4 | **Candle Density** | Body overlap zones → dense=support, thin=fast-move |
| 5 | **Liquidity** | Equal highs/lows, sweep detection, target pools |
| 6 | **FVG + OB** | Fair Value Gaps, Order Blocks, CE entry refinement |
| 7 | **Order Flow** | Tick volume delta, divergence, absorption (proxy) |
| 8 | **Killzone** | London/NY/Asia timing + news blackout filter |

A+ grade = 7+ layers pass (score ≥ 6/10)  
A grade = 6 layers  
B grade = 5 layers  
Below 5 = NO TRADE

---

## Risk Management

**5-multiplier dynamic sizing:**
```
Final Risk % = 1.5% × Setup × Volatility × Streak × Time × Intermarket
```
- Capped at 3%, floored at 0.25%
- Daily max: 5% total risk
- 5 consecutive losses → HARD STOP
- 5% monthly DD → half size
- 10% monthly DD → demo for 1 week
- 15% monthly DD → full stop + audit

---

## Entry / Exit Scaling

**Entry (3 limit orders, same SL):**
- 50% at Consequent Encroachment (CE)
- 30% at FVG low / OB
- 20% at POC edge

**Exit:**
- TP1: 40% at next VP level → move SL to breakeven
- TP2: 30% at major structure → activate trailing EMA
- TP3: 30% runner → trail behind 10 EMA until stopped

---

## Trading Mode

Toggle in `config/settings.py`:
```python
TRADING_MODE = "SEMI_AUTO"  # or "FULL_AUTO"
```
- **SEMI_AUTO**: System detects and alerts, you confirm via Telegram or dashboard
- **FULL_AUTO**: Executes immediately when criteria met

---

## Dashboard

Run in a separate terminal:
```bash
streamlit run dashboard/app.py
```

5 pages:
1. **Live Monitor** — account state, open positions, killzone status
2. **Trade Journal** — searchable history with notes and tags
3. **Performance** — equity curve, win rate, expectancy, breakdowns
4. **Analysis** — run live 8-layer scan on any instrument
5. **Settings** — view all parameters and system info

---

## Telegram Alerts (Optional)

1. Create a bot via @BotFather
2. Get your chat ID
3. Add to `config/credentials.py`:
```python
TELEGRAM_BOT_TOKEN = "123456:ABC..."
TELEGRAM_CHAT_ID = "987654321"
```

Alerts: setup detected, trade opened/closed, TP hit, circuit breaker, daily summary.

---

## Notes

- Broker provides **tick volume only** — real volume delta is approximated (close > open = buy). Supplemented with yfinance futures data where available.
- All times internally UTC, display in EST.
- Never moves stop further from entry (iron rule).
- SQLite journal at `ifc_journal.db` — back it up regularly.

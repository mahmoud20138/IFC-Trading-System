# MT5 IFC Trading System

**Institutional Flow Confluence -- 11-Layer Automated Trading System for MetaTrader 5**

A fully automated (switchable semi-auto/full-auto) trading system that runs an 11-layer confluence analysis pipeline across Forex, Indices, Crypto, Commodities, and US Stocks via MetaTrader 5. The system scans 25+ instruments during active killzones, scores setups through weighted confluence, manages risk dynamically, and executes scaled entries with trailing stop management.

---

## Architecture

```
                         +------------------+
                         |     main.py      |
                         |  IFCSystem       |
                         |  (APScheduler)   |
                         +--------+---------+
                                  |
          +-----------+-----------+-----------+-----------+
          |           |           |           |           |
    +-----+----+ +----+-----+ +--+-------+ +-+------+ +-+--------+
    |  data/   | | analysis/ | | execution| | journal| |  alerts  |
    | MT5, IM, | | 11 Layers | | Orders,  | | SQLite | | Telegram |
    | Sentiment| | Pipeline  | | Scaling, | | Analytics| Notifier |
    | Calendar | | Regime    | | Risk Mgr | |        | |          |
    +----------+ +----------+ +----------+ +--------+ +----------+
```

### Data Flow

```
MT5 OHLCV (W1/D1/H4/H1/M15/M1)
        |
        v
+-----------------------------------+
|  11-Layer Analysis Pipeline       |
|  L1  Intermarket (DXY,VIX,Yields) |
|  L2  Trend (EMA stack, BOS/CHoCH) |
|  L3  Volume Profile (POC/VA/HVN)  |
|  L4  Candle Density               |
|  L5  Liquidity (sweeps, EQH/EQL)  |
|  L6  FVG + Order Blocks           |
|  L7  Order Flow (delta, absorption)|
|  L8  Killzone (session timing)    |
|  L9  Correlation (cross-asset)    |
|  L10 Sentiment (COT, Fear&Greed)  |
|  L11 AI/Regime (LLM evaluation)   |
+-----------------------------------+
        |
        v
  Confluence Scorer (Weighted QAS)
        |
        v
  Grade: A+ / A / B / NO
        |
        v
  Setup Detector (Entry/SL/TP)
        |
        v
  Risk Manager (position sizing, circuit breakers)
        |
        v
  Scaling Manager (3-tranche entry, 3-tranche exit)
        |
        v
  MT5 Order Execution + Journal Logging + Telegram Alert
```

---

## The 11 Analysis Layers

| Layer | Name | Weight | What It Analyzes |
|-------|------|--------|-----------------|
| L1 | Intermarket | 12% | DXY, US10Y, VIX, SPX correlation with instrument. Confirms macro context. |
| L2 | Trend | 16% | EMA stack (10/21/50/200) across W1/D1/H4. BOS/CHoCH structure detection. |
| L3 | Volume Profile | 12% | POC, VAH, VAL, HVN, LVN from M1 data. Institutional acceptance levels. |
| L4 | Candle Density | 6% | Overlapping bar clusters at HVN/LVN zones. Supplementary confluence. |
| L5 | Liquidity | 10% | Equal highs/lows, trendline liquidity, swing point stop hunts. |
| L6 | FVG + Order Blocks | 14% | Fair Value Gaps and Order Blocks with ATR-based sizing. Entry precision. |
| L7 | Order Flow | 10% | Cumulative delta, absorption, divergence. Real-time confirmation via yfinance futures. |
| L8 | Killzone | 8% | Session timing with category-specific rules (forex/equity/crypto/commodity). |
| L9 | Correlation | 5% | Cross-asset correlation penalties. Prevents correlated exposure. |
| L10 | Sentiment | 4% | COT positioning, Fear & Greed Index, broker sentiment. Useful at extremes. |
| L11 | AI/Regime | 3% | LLM-based evaluation (Ollama/OpenAI/Gemini). Regime detection (trend/range/volatile). |

Layer weights are regime-adaptive: in strong trends L2 gets a 1.4x boost; in ranges L5/L6 get boosted instead.

---

## Supported Instruments (25+)

| Category | Instruments |
|----------|------------|
| Forex | EUR/USD, GBP/USD, USD/JPY, AUD/USD, USD/CAD, NZD/USD, USD/CHF |
| Indices | US30 (Dow), NAS100, S&P 500 |
| Commodities | Gold (XAU/USD), Silver (XAG/USD), US Oil (WTI) |
| Crypto | BTC/USD, ETH/USD |
| US Stocks | AAPL, TSLA, NVDA, AMZN, MSFT, META, GOOGL, NFLX, AMD, JPM |

Each instrument has broker-specific symbol mapping, pip size, pip value, typical spread, ATR reference, intermarket correlations, COT report name, and killzone preference.

---

## Dashboard (14 Pages)

The system includes a multi-page Dash web dashboard on `localhost:8501`:

| Page | Description |
|------|------------|
| Command Center | Overview of system state, account info, active scans |
| Live Monitor | Real-time instrument scanning with layer scores |
| Pro Monitor | Advanced view with multi-TF grid and QAS grades |
| Full Monitor | All instruments with all 11 layer scores in a heatmap |
| Multi-TF Scanner | Cross-timeframe analysis grid |
| Analysis Page | Deep-dive into single instrument analysis |
| Layer Evaluator | Inspect individual layer outputs and confidence |
| AI Evaluator | LLM deep analysis results and reasoning |
| LLM Dashboard | Manage LLM backend settings and view responses |
| Correlation Dashboard | Cross-asset correlation matrix visualization |
| Sentiment Dashboard | COT data, Fear & Greed, broker positioning |
| Trade Journal | All trades with P&L, R-multiples, grades |
| Performance | Equity curve, win rate, drawdown analytics |
| Settings | Runtime configuration adjustments |

---

## Execution Engine

- **Scaled Entry**: 3-tranche entry (50%/30%/20%) at CE price, FVG low, and POC edge
- **Scaled Exit**: 40% at TP1, 30% at TP2, 30% runner with trailing stop
- **Trailing Stop**: EMA-based (M15 after TP1, H1 after TP2), or structure/HVN-based
- **Breakeven**: Auto-move SL to breakeven when 1H close exceeds 1.5R in profit
- **Smart Orders**: Handles MT5 order types, magic numbers, deviation control

---

## Risk Management

- **Base risk**: 1.5% per trade (configurable 0.25% - 3.0% range)
- **Daily cap**: 5% cumulative risk, max 3 trades per day
- **Setup quality multipliers**: A+ = 1.5x, A = 1.0x, B = 0.5x
- **Volatility multipliers**: Quiet = 1.2x, Normal = 1.0x, High = 0.6x, Extreme = 0.3x
- **Streak protection**: 3+ consecutive losses = 0.5x size, 5 losses = full stop
- **Drawdown circuit breakers**: 5% monthly = half size, 10% = demo only, 15% = 2-week break
- **Correlation penalties**: Highly correlated instruments get position size reduced up to 60%
- **Hard vetoes**: Trend layer fail, portfolio risk > 5%, 2+ daily losses, news blackout within 15 min

---

## Installation

### Prerequisites

- Python 3.10+
- MetaTrader 5 terminal running on Windows
- MT5 broker account (uses Exness-style symbol naming by default)

### Setup

```bash
cd ifc_trading_system
pip install -r requirements.txt
```

### Configuration

1. Create `config/credentials.py` and fill in:
   ```python
   MT5_LOGIN = 12345678
   MT5_PASSWORD = "your_password"
   MT5_SERVER = "YourBroker-Server"
   TELEGRAM_BOT_TOKEN = ""   # optional
   TELEGRAM_CHAT_ID = ""     # optional
   ```

2. Edit `config/settings.py` to adjust:
   - `TRADING_MODE`: `"FULL_AUTO"` or `"SEMI_AUTO"`
   - Risk parameters, killzone times, layer weights
   - LLM backend (`ollama`, `openai`, or `gemini`)

3. Edit `config/instruments.py` to set correct `mt5_symbol` names for your broker and toggle instruments on/off with `.active`.

---

## Usage

```bash
# Start in live mode (real orders in FULL_AUTO, confirmations in SEMI_AUTO)
python main.py

# Start in demo/paper mode (no real orders, logs signals only)
python main.py --mode demo
```

The system will:
1. Connect to MT5 and verify account
2. Load intermarket data (DXY, VIX, yields via yfinance)
3. Start the scheduler with 7 recurring jobs
4. Scan all active instruments every 5 minutes during killzones
5. Execute trades when A+/A/B grade setups are detected

### Scheduled Jobs

| Job | Interval | Description |
|-----|----------|------------|
| Instrument Scan | 5 min | Full 11-layer analysis during killzones |
| Position Management | 30 sec | Trailing stops, breakeven, partial exits |
| Intermarket Refresh | 15 min | Update DXY, VIX, yields from yfinance |
| Sentiment Refresh | 4 hours | Update COT, Fear & Greed data |
| Account Snapshot | 1 hour | Log balance/equity/margin to journal |
| Daily Reset | 00:01 EST | Reset daily counters |
| Daily Summary | 17:00 EST | Generate and send performance summary |

---

## Results & Output

### Signal Output

```
TRADEABLE: EURUSDm | Grade=A | Dir=LONG | Layers=8/11
  L1=7.2 L2=8.5 L3=6.8 L4=5.9 L5=7.1 L6=8.0 L7=6.5 L8=9.0 L9=5.5 L10=4.8 L11=6.0
  Setup: BOS_RETEST | Entry=1.0845 | SL=1.0820 | TP1=1.0895 | TP2=1.0945 | RR=3.0
  Risk=1.2% | Lots=0.15 | Regime=STRONG_TREND
```

### Trade Execution

```
TRADE PLACED: GRP_20260308_1 #42 | BUY EURUSDm 0.15 lots
  Scaled: 0.075 @ market, 0.045 @ FVG_low=1.0838, 0.030 @ POC=1.0832
```

### Daily Summary (via Telegram)

```
Daily Summary -- 2 trades, P&L $245.00
  Wins: 2 | Losses: 0 | Win Rate: 100%
  Total R: +4.2R | Risk Used: 2.7%
```

### Journal

All trades logged to SQLite (`ifc_journal.db`) with: entry/exit times, prices, volumes, P&L, R-multiples, confluence scores, all 11 layer scores, regime, killzone, and risk multipliers.

---

## Project Structure

```
ifc_trading_system/
  main.py                          # Entry point, APScheduler orchestrator
  requirements.txt
  config/
    settings.py                    # All parameters (risk, layers, killzones)
    instruments.py                 # 25+ instrument definitions
    credentials.py                 # MT5 login, API keys (gitignored)
  analysis/
    pipeline.py                    # 11-layer pipeline orchestrator
    layer1_intermarket.py          # DXY, VIX, yields scoring
    layer2_trend.py                # EMA stack, BOS/CHoCH
    layer3_volume_profile.py       # POC, VAH, VAL, HVN, LVN
    layer4_candle_density.py       # Overlapping bar clusters
    layer5_liquidity.py            # Equal highs/lows, sweeps
    layer6_fvg_ob.py               # Fair Value Gaps + Order Blocks
    layer7_order_flow.py           # Delta, absorption, divergence
    layer8_killzone.py             # Session timing
    layer9_correlation.py          # Cross-asset correlation
    layer10_sentiment.py           # COT, Fear & Greed
    layer11_ai_evaluation.py       # LLM evaluation, regime
    confluence_scorer.py           # Weighted QAS scoring
    regime_detector.py             # Market regime detection
    setup_detector.py              # Entry/SL/TP generation
    llm_evaluator.py               # LLM prompt builder
  execution/
    order_manager.py               # MT5 order placement
    risk_manager.py                # Position sizing, circuit breakers
    scaling.py                     # 3-tranche scaled entry/exit
    trade_manager.py               # Position lifecycle management
    smart_orders.py                # Advanced order types
  journal/
    database.py                    # SQLite journal storage
    models.py                      # Trade/snapshot data models
    analytics.py                   # Performance analytics
  dashboard/
    app.py                         # Dash application
    components/charts.py           # Plotly chart builders
    components/widgets.py          # Reusable UI components
    pages/                         # 14 dashboard pages
  data/
    mt5_connector.py               # MT5 terminal wrapper
    intermarket.py                 # yfinance macro data
    sentiment.py                   # COT, Fear & Greed
    economic_calendar.py           # News events, blackout windows
  alerts/
    notifier.py                    # Telegram notifications
  utils/
    helpers.py                     # Logging, killzone, time utils
  test_all.py                      # Component tests
```

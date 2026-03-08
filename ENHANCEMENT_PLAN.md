# IFC Trading System — Enhancement Plan
**Created:** February 12, 2026
**Status:** Pending Implementation

---

## NEW FEATURES REQUESTED

### A. LLM Second Evaluation
- Integrate an LLM model (e.g., OpenAI GPT-4 / local Ollama / Gemini) to provide a **second opinion** on each trade signal
- The LLM receives a structured prompt containing:
  - All 11 layer scores, directions, confidences, and key details
  - Current market regime (from L11)
  - Intermarket snapshot (DXY, VIX, yields, SPX)
  - COT positioning summary
  - Active killzone and day-of-week
  - Any veto flags triggered
- The LLM returns:
  - Agreement/disagreement with the system's signal
  - Risk assessment (1-10)
  - Key concerns or confirmations
  - Suggested position sizing adjustment
  - Plain-English reasoning
- Display LLM evaluation alongside the system's evaluation in the dashboard
- Cache LLM responses per symbol for 5 minutes to avoid excessive API calls
- Support multiple LLM backends: OpenAI API, local Ollama, Google Gemini

### B. Auto-Monitoring Every Minute
- Add a background loop (or Streamlit auto-refresh) that re-evaluates all layers for all watchlist instruments every 60 seconds
- Dashboard shows:
  - Last update timestamp per instrument
  - Score change indicators (up/down arrows) since last evaluation
  - Alert highlights when a signal flips direction or grade changes
  - Auto-scroll to instruments with significant changes
- Store evaluation history in memory (last N evaluations per symbol) for trend tracking
- Optional sound/notification when A+ or A grade appears

---

## CRITICAL FIXES (Bugs actively hurting signal quality)

### 1. Build AnalysisPipeline Orchestrator
- **Problem:** Each dashboard page manually wires layers with different (often wrong) parameters. No data flows between layers.
- **Fix:** Create `analysis/pipeline.py` with a single `AnalysisPipeline.run(instrument, snapshot)` that chains L1-L11, passing:
  - L1 regime -> L8 (context), L11 (regime input)
  - L2 direction -> L3, L4, L5, L6, L7 (trade_direction)
  - L3 POC/VAH/VAL/HVN/LVN -> L4 (cross-validation), L6 (confluence_levels)
  - L5 sweep data -> L6 (entry refinement)
  - L9 open_positions from MT5

### 2. Fix L6 Silent SHORT Bias
- **File:** `dashboard/pages/layer_evaluator.py`, `dashboard/pages/ai_evaluator.py`
- **Problem:** `trade_direction="NEUTRAL"` passed to L6. Inside L6, `NEUTRAL != "LONG"` causes BEARISH FVG filter only.
- **Fix:** Pass L2's actual direction to L6.

### 3. Fix ai_evaluator.py L3 Crash
- **File:** `dashboard/pages/ai_evaluator.py`
- **Problem:** Calls `vp_layer.compute_profile(m1)` — method doesn't exist. Correct: `compute_volume_profile(m1)`
- **Fix:** Rename the method call.

---

## HIGH PRIORITY ENHANCEMENTS

### 4. Category-Specific Killzones (L8)
- **Problem:** All 25 instruments get forex killzones. Crypto (24/7) shouldn't have killzone penalties. Stocks should use US equity hours.
- **Fix:** Add `killzone_preference` field to Instrument. L8 checks category:
  - Forex: current killzones (with pair-specific weighting — Asian higher for JPY/AUD)
  - Index: home-session killzones
  - Crypto: no killzone penalty (or CME BTC futures hours)
  - Stock: US market hours 9:30-16:00 ET
  - Commodity: mixed (Gold follows forex sessions, Oil follows NYMEX)

### 5. Category-Specific Regime Bonus (L1)
- **Problem:** Only `{index, crypto}` + AUDUSD/NZDUSD get regime bonus. Gold, stocks, commodities get nothing.
- **Fix:** Expand risk_assets/haven_assets logic:
  - Risk assets: indices, crypto, AUD/NZD, stocks, oil
  - Haven assets: Gold, Silver, JPY, CHF
  - Commodity-specific: Gold inverse to DXY, Oil sensitive to risk regime

### 6. Wire L3 VP Data -> L6 Confluence
- **Problem:** L6 accepts `confluence_levels` but no caller passes them.
- **Fix:** Pipeline passes L3 output (POC, VAH, VAL, naked POCs) as `confluence_levels` to L6.

### 7. Add Trendline Liquidity + PDH/PDL to L5
- **Problem:** Settings define `MIN_TRENDLINE_TOUCHES = 3` but no trendline code exists. PDH/PDL missing.
- **Fix:** Implement trendline detection via linear regression on swing points. Add PDH/PDL/session-open as liquidity pools.

### 8. Rolling Correlations in L9
- **Problem:** `compute_rolling_correlation()` exists but is never called.
- **Fix:** Call it in `analyze()` and blend with static matrix (e.g., 70% rolling, 30% static fallback).

---

## MEDIUM PRIORITY

### 9. Regime-Adaptive Layer Weights
- In STRONG_TREND: boost L2 weight
- In VOLATILE: boost L8 weight
- In RANGE: boost L5/L6 weight
- Implement as weight multipliers applied on top of base LAYER_WEIGHTS

### 10. Reconcile Pass Thresholds
- settings.py: `LAYER_PASS_THRESHOLD = 6.0`
- layer_evaluator.py: `_PASS = 7.0`
- Grade comments say "8/8" but system has 11 layers
- Fix: single source of truth in settings.py

### 11. Add `cot_name` to Instrument Config
- Move _COT_NAMES from L10 into each Instrument's definition in instruments.py

### 12. Stock Correlations in L9
- Add AAPL<->NAS100, TSLA<->NAS100, NVDA<->NAS100, sector correlations

### 13. Real Crypto Funding Rates (L10)
- Use Binance public API: `GET /fapi/v1/fundingRate`
- Replace VIX-based proxy with actual funding data

### 14. Wire L7 Supplementary Futures Data
- Fetch yfinance futures OHLCV and pass as `supplementary_df` to OrderFlowLayer

---

## LOW PRIORITY (Polish)

### 15. Time-Decay for L4 Density and L6 FVGs
- Weight recent zones higher than old ones
- FVG staleness penalty after N bars

### 16. Breaker Block Logic in L6
- When OB is broken through, flip to breaker (role reversal entry)

### 17. L5 Sweep Confirmation Window
- Expand from 1-candle to 2-3 candle confirmation

### 18. Fallback Economic Calendar
- Add Forex Factory or investing.com as backup to Myfxbook scraper

### 19. MT5 Market Depth in L7
- Use `mt5_connector.market_book_get()` for real order flow data

---

## IMPLEMENTATION ORDER (Recommended)

1. **Pipeline orchestrator** (#1) — foundation for everything else
2. **Fix bugs** (#2, #3) — immediate quality improvement
3. **LLM integration** (#A) — new feature, high user value
4. **Auto-monitoring** (#B) — new feature, high user value
5. **Category-specific fixes** (#4, #5) — correct behavior for non-forex instruments
6. **Cross-layer wiring** (#6, #7, #8, #14) — unlock full confluence scoring
7. **Adaptive weights + threshold fixes** (#9, #10) — tune scoring accuracy
8. **Data enrichment** (#11, #12, #13) — more signal sources
9. **Polish** (#15-#19) — refinements

---

## FILES TO CREATE
- `analysis/pipeline.py` — AnalysisPipeline orchestrator
- `analysis/llm_evaluator.py` — LLM second evaluation engine
- `dashboard/pages/llm_dashboard.py` — LLM evaluation display page
- Modify `config/settings.py` — LLM API config, killzone_preference, cot_name
- Modify `config/instruments.py` — new fields per instrument
- Modify `dashboard/app.py` — auto-refresh, new pages

## FILES TO MODIFY
- `analysis/layer1_intermarket.py` — regime bonus expansion
- `analysis/layer5_liquidity.py` — trendline + PDH/PDL
- `analysis/layer6_fvg_ob.py` — direction fix, breaker blocks
- `analysis/layer8_killzone.py` — category-specific sessions
- `analysis/layer9_correlation.py` — rolling correlations, stock pairs
- `analysis/layer10_sentiment.py` — cot_name from instrument, crypto funding API
- `analysis/layer11_ai_evaluation.py` — regime-adaptive weights
- `dashboard/pages/layer_evaluator.py` — pass threshold fix, direction propagation
- `dashboard/pages/ai_evaluator.py` — fix L3 method call, direction propagation
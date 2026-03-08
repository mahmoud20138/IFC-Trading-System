"""Quick test of all new components."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

errors = []

# === Test sentiment for all categories ===
print("=== Test Sentiment per category ===")
try:
    from analysis.layer10_sentiment import compute_sentiment_composite
    from config.instruments import WATCHLIST

    cats = {}
    for inst in WATCHLIST:
        if inst.active:
            cats.setdefault(inst.category, []).append(inst)

    for cat, insts in cats.items():
        inst = insts[0]
        try:
            result = compute_sentiment_composite(inst.mt5_symbol, inst.category, {})
            zone = result["zone"]
            src = result["sources_available"]
            total = result["sources_total"]
            print(f"  {cat:12s} {inst.mt5_symbol:12s} -> zone={zone:10s} sources={src}/{total}")
        except Exception as e:
            print(f"  {cat:12s} {inst.mt5_symbol:12s} -> ERROR: {type(e).__name__}: {e}")
            errors.append((f"sentiment_{cat}", e))
except Exception as e:
    print(f"  Import error: {e}")
    errors.append(("sentiment_import", e))
try:
    from analysis.layer9_correlation import CorrelationLayer
    sig = CorrelationLayer().analyze("EURUSDm", {})
    print(f"  L9: score={sig.score}, dir={sig.direction}, conf={sig.confidence}")
except Exception as e:
    print(f"  L9 ERROR: {e}")
    errors.append(("L9", e))

# === Layer 10 ===
print("\n=== Test Layer 10: Sentiment ===")
try:
    from analysis.layer10_sentiment import SentimentLayer, compute_sentiment_composite
    sig = SentimentLayer().analyze("EURUSDm", "forex", {})
    print(f"  L10: score={sig.score}, dir={sig.direction}, conf={sig.confidence}")
except Exception as e:
    print(f"  L10 ERROR: {e}")
    errors.append(("L10", e))

# === compute_sentiment_composite ===
print("\n=== Test compute_sentiment_composite ===")
try:
    result = compute_sentiment_composite("EURUSDm", "forex", {})
    print(f"  composite: {result}")
except Exception as e:
    print(f"  composite ERROR: {type(e).__name__}: {e}")
    errors.append(("composite", e))

# === Layer 11 ===
print("\n=== Test Layer 11: AI Evaluation ===")
try:
    from analysis.layer11_ai_evaluation import AIEvaluationLayer
    import pandas as pd, numpy as np
    dates = pd.date_range("2025-01-01", periods=60, freq="D")
    df = pd.DataFrame({
        "open": np.random.uniform(1.05, 1.10, 60),
        "high": np.random.uniform(1.10, 1.12, 60),
        "low": np.random.uniform(1.03, 1.05, 60),
        "close": np.random.uniform(1.05, 1.10, 60),
        "tick_volume": np.random.randint(1000, 5000, 60),
    }, index=dates)
    sig = AIEvaluationLayer().analyze(df, None, 18.0)
    print(f"  L11: score={sig.score}, dir={sig.direction}, conf={sig.confidence}")
except Exception as e:
    print(f"  L11 ERROR: {type(e).__name__}: {e}")
    errors.append(("L11", e))

# === Smart Orders ===
print("\n=== Test Smart Orders ===")
try:
    from execution.smart_orders import generate_recommendation, format_card_html
    from config.instruments import WATCHLIST
    from analysis.layer1_intermarket import LayerSignal
    from analysis.layer11_ai_evaluation import full_evaluation

    names = [
        "L1_Intermarket", "L2_Trend", "L3_VolumeProfile", "L4_CandleDensity",
        "L5_Liquidity", "L6_FVG_OrderBlock", "L7_OrderFlow", "L8_Killzone",
        "L9_Correlation", "L10_Sentiment", "L11_Regime",
    ]
    signals = [LayerSignal(n, "LONG", 8.5, 0.85, {}) for n in names]
    ev = full_evaluation(signals)
    print(f"  eval: grade={ev['grade']}, tradeable={ev['tradeable']}, tws={ev['tws']:.3f}, qas={ev['qas']:.3f}")

    inst = WATCHLIST[0]
    card = generate_recommendation(
        instrument=inst,
        current_price=1.0850,
        atr=0.0065,
        signals=signals,
        evaluation=ev,
        account_balance=10000,
    )
    if card:
        print(f"  Card: {card.instrument} {card.direction} grade={card.grade}")
        html = format_card_html(card)
        print(f"  HTML length: {len(html)} chars")
    else:
        grade = ev['grade']
        tradeable = ev['tradeable']
        print(f"  No card generated (grade={grade}, tradeable={tradeable})")
except Exception as e:
    import traceback
    print(f"  Smart Orders ERROR: {type(e).__name__}: {e}")
    traceback.print_exc()
    errors.append(("SmartOrders", e))

# === Confluence Scorer ===
print("\n=== Test Confluence Scorer (11L weighted) ===")
try:
    from analysis.confluence_scorer import ConfluenceScorer
    result = ConfluenceScorer().score(signals)
    grade = result['grade']
    tradeable = result['tradeable']
    wm = result.get('weighted_mode')
    print(f"  grade={grade}, tradeable={tradeable}, weighted={wm}")
except Exception as e:
    print(f"  Scorer ERROR: {e}")
    errors.append(("Scorer", e))

# === Correlation helpers ===
print("\n=== Test Correlation helpers ===")
try:
    from analysis.layer9_correlation import correlation_health_score, portfolio_correlation_risk
    health = correlation_health_score({})
    print(f"  health: {health['health']}, adj={health['size_adjustment']}")
    risk = portfolio_correlation_risk([])
    print(f"  portfolio risk: {risk}")
except Exception as e:
    print(f"  Correlation helpers ERROR: {e}")
    errors.append(("CorrHelpers", e))

# === Summary ===
print("\n" + "=" * 50)
if errors:
    print(f"FAILED: {len(errors)} error(s)")
    for name, e in errors:
        print(f"  {name}: {type(e).__name__}: {e}")
else:
    print("ALL TESTS PASSED")

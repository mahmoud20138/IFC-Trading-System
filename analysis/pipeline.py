"""
IFC Trading System — Analysis Pipeline Orchestrator
Chains all 11 layers (L1→L11) with correct data flow, regime detection,
and cross-layer wiring. Single entry point for both main.py and dashboard pages.

Enhancement Plan #1: Pipeline Orchestrator
"""

import time
import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List

from analysis.layer1_intermarket import IntermarketLayer, LayerSignal
from analysis.layer2_trend import TrendLayer
from analysis.layer3_volume_profile import VolumeProfileLayer, compute_volume_profile, VolumeProfile
from analysis.layer4_candle_density import CandleDensityLayer
from analysis.layer5_liquidity import LiquidityLayer
from analysis.layer6_fvg_ob import FVGOrderBlockLayer
from analysis.layer7_order_flow import OrderFlowLayer
from analysis.layer8_killzone import KillzoneLayer
from analysis.layer9_correlation import CorrelationLayer
from analysis.layer10_sentiment import SentimentLayer
from analysis.layer11_ai_evaluation import AIEvaluationLayer, full_evaluation
from analysis.regime_detector import RegimeDetector, compute_atr
from analysis.confluence_scorer import ConfluenceScorer

from config import settings
from config.instruments import Instrument
from utils.helpers import setup_logging

logger = setup_logging("ifc.pipeline")


@dataclass
class PipelineResult:
    """Complete result of an 11-layer pipeline run."""
    symbol: str
    instrument: Optional[Instrument] = None
    current_price: float = 0.0

    # Individual layer signals (ordered L1–L11)
    signals: List[LayerSignal] = field(default_factory=list)

    # Computed cross-layer data
    regime: Dict[str, Any] = field(default_factory=dict)
    volume_profile: Optional[VolumeProfile] = None
    atr: float = 0.0

    # Confluence / evaluation
    confluence: Dict[str, Any] = field(default_factory=dict)
    evaluation: Dict[str, Any] = field(default_factory=dict)

    # Setup & price context (for LLM deep analysis)
    setup: Optional[Any] = None
    price_context: Dict[str, Any] = field(default_factory=dict)

    # Metadata
    direction: str = "NEUTRAL"
    grade: str = "---"
    tradeable: bool = False
    elapsed_ms: float = 0.0
    errors: Dict[str, str] = field(default_factory=dict)

    def get_signal(self, layer_name: str) -> Optional[LayerSignal]:
        """Retrieve a specific layer's signal by name."""
        for s in self.signals:
            if s.layer_name == layer_name:
                return s
        return None


class AnalysisPipeline:
    """
    Orchestrator that chains L1→L11 with proper data flow.

    Data flow:
        RegimeDetector(D1, VP, VIX) → regime context for L8, L11
        L1(instrument, snapshot) → intermarket context
        L2(W1, D1, H4) → trend direction → feeds L4, L5, L6, L7
        L3(price, VP) → POC/VAH/VAL/HVN/LVN → feeds L4, L6
        L4(df, HVN, LVN, price, direction)
        L5(df, ATR, price, direction)
        L6(df, ATR, price, direction, confluence_levels from L3)
        L7(df, direction, key_level from L3.POC, ATR)
        L8(symbol) → killzone timing
        L9(symbol, snapshot) → correlation filter
        L10(symbol, category, snapshot) → sentiment
        L11(D1, VP, VIX) → AI/regime evaluation
    """

    def __init__(self):
        self.layer2 = TrendLayer()
        self.layer3 = VolumeProfileLayer()
        self.layer4 = CandleDensityLayer()
        self.layer5 = LiquidityLayer()
        self.layer6 = FVGOrderBlockLayer()
        self.layer7 = OrderFlowLayer()
        self.layer8 = KillzoneLayer()
        self.layer9 = CorrelationLayer()
        self.layer10 = SentimentLayer()
        self.layer11 = AIEvaluationLayer()
        self.regime_detector = RegimeDetector()
        self.scorer = ConfluenceScorer()

    def run(
        self,
        instrument: Instrument,
        intermarket_layer: IntermarketLayer,
        # Multi-TF DataFrames
        df_w1: Optional[pd.DataFrame] = None,
        df_d1: Optional[pd.DataFrame] = None,
        df_h4: Optional[pd.DataFrame] = None,
        df_h1: Optional[pd.DataFrame] = None,
        df_m15: Optional[pd.DataFrame] = None,
        df_m5: Optional[pd.DataFrame] = None,
        df_m1: Optional[pd.DataFrame] = None,
        # External data
        intermarket_snapshot: Optional[Dict] = None,
        sentiment_cache: Optional[Dict] = None,
        # Portfolio state (for veto checks)
        portfolio_risk_pct: float = 0.0,
        daily_losses: int = 0,
        daily_drawdown_pct: float = 0.0,
        correlated_open_count: int = 0,
        open_positions: Optional[List[Dict]] = None,
    ) -> PipelineResult:
        """
        Run the full 11-layer analysis pipeline for one instrument.

        Returns PipelineResult with all signals, regime, confluence, and evaluation.
        """
        t0 = time.time()
        symbol = instrument.mt5_symbol
        result = PipelineResult(symbol=symbol, instrument=instrument)
        signals: List[LayerSignal] = []

        # Ensure we have at least D1 data
        if df_d1 is None or df_d1.empty:
            result.errors["data"] = "No D1 data available"
            result.elapsed_ms = (time.time() - t0) * 1000
            return result

        # Current price from best available TF
        for df in [df_m5, df_m15, df_h1, df_h4, df_d1]:
            if df is not None and not df.empty:
                result.current_price = float(df["close"].iloc[-1])
                break

        # ── ATR computation ──────────────────────────────────────────
        result.atr = compute_atr(df_d1) if len(df_d1) >= 14 else 0.0

        # ── Volume Profile (compute once, reuse across layers) ───────
        vp = None
        try:
            vp_df = df_m1 if (df_m1 is not None and not df_m1.empty and len(df_m1) >= 100) else df_d1
            vp = compute_volume_profile(vp_df)
            result.volume_profile = vp
        except Exception as e:
            result.errors["vp"] = str(e)

        # ── VIX level from snapshot ──────────────────────────────────
        vix_level = 20.0
        if intermarket_snapshot:
            vix_level = intermarket_snapshot.get("VIX", {}).get("level", 20.0)

        # ── Regime Detection (runs first — feeds L8 context, L11) ────
        try:
            result.regime = self.regime_detector.detect(
                daily_df=df_d1,
                volume_profile=vp,
                vix_level=vix_level,
            )
        except Exception as e:
            result.errors["regime"] = str(e)
            result.regime = {"regime": "NORMAL", "size_adjustment": 1.0}

        # ── L1: Intermarket & Macro Context ──────────────────────────
        try:
            sig1 = intermarket_layer.analyze(instrument, intermarket_snapshot)
        except Exception as e:
            result.errors["L1"] = str(e)
            sig1 = LayerSignal("L1_Intermarket", "NEUTRAL", 5.0, 0.3, {"error": str(e)})
        signals.append(sig1)

        # ── L2: Trend (multi-TF) ────────────────────────────────────
        try:
            w = df_w1 if (df_w1 is not None and not df_w1.empty) else df_d1
            sig2 = self.layer2.analyze(w, df_d1, df_h4 if df_h4 is not None else df_d1)
        except Exception as e:
            result.errors["L2"] = str(e)
            sig2 = LayerSignal("L2_Trend", "NEUTRAL", 5.0, 0.3, {"error": str(e)})
        signals.append(sig2)

        # Direction from L2 feeds into L4, L5, L6, L7
        trend_direction = sig2.direction if sig2.direction in ("LONG", "SHORT") else "NEUTRAL"

        # ── L3: Volume Profile Analysis ──────────────────────────────
        try:
            if vp is not None:
                sig3 = self.layer3.analyze(
                    current_price=result.current_price,
                    composite_profile=vp,
                    trade_direction=trend_direction,
                )
            else:
                sig3 = LayerSignal("L3_VolumeProfile", "NEUTRAL", 5.0, 0.3, {"note": "No VP data"})
        except Exception as e:
            result.errors["L3"] = str(e)
            sig3 = LayerSignal("L3_VolumeProfile", "NEUTRAL", 5.0, 0.3, {"error": str(e)})
        signals.append(sig3)

        # Extract VP levels for cross-layer wiring (L3 → L4, L6, L7)
        hvn_levels = list(vp.hvn) if vp else []
        lvn_levels = list(vp.lvn) if vp else []
        confluence_levels = None
        poc_level = None
        if vp is not None:
            confluence_levels = [vp.poc, vp.vah, vp.val] + hvn_levels[:5]
            poc_level = vp.poc

        # ── L4: Candle Density ───────────────────────────────────────
        try:
            l4_df = df_h1 if (df_h1 is not None and not df_h1.empty) else df_d1
            sig4 = self.layer4.analyze(
                l4_df,
                vp_hvn=hvn_levels,
                vp_lvn=lvn_levels,
                current_price=result.current_price,
                trade_direction=trend_direction,
            )
        except Exception as e:
            result.errors["L4"] = str(e)
            sig4 = LayerSignal("L4_CandleDensity", "NEUTRAL", 5.0, 0.3, {"error": str(e)})
        signals.append(sig4)

        # ── L5: Liquidity ────────────────────────────────────────────
        try:
            l5_df = df_h1 if (df_h1 is not None and not df_h1.empty) else df_d1
            sig5 = self.layer5.analyze(
                l5_df,
                atr=result.atr,
                current_price=result.current_price,
                trade_direction=trend_direction,
            )
        except Exception as e:
            result.errors["L5"] = str(e)
            sig5 = LayerSignal("L5_Liquidity", "NEUTRAL", 5.0, 0.3, {"error": str(e)})
        signals.append(sig5)

        # ── L6: FVG + Order Block (receives L2 direction + L3 VP levels) ──
        try:
            l6_df = df_h1 if (df_h1 is not None and not df_h1.empty) else df_d1
            sig6 = self.layer6.analyze(
                l6_df,
                atr=result.atr,
                current_price=result.current_price,
                trade_direction=trend_direction,
                confluence_levels=confluence_levels,
            )
        except Exception as e:
            result.errors["L6"] = str(e)
            sig6 = LayerSignal("L6_FVG_OrderBlock", "NEUTRAL", 5.0, 0.3, {"error": str(e)})
        signals.append(sig6)

        # ── L7: Order Flow (receives direction + POC key level) ──────
        try:
            l7_df = df_m15 if (df_m15 is not None and not df_m15.empty) else df_h1

            # Fetch supplementary futures data from yfinance (real volume)
            supp_df = None
            if instrument and instrument.yfinance_ticker:
                try:
                    import yfinance as yf
                    ticker = yf.Ticker(instrument.yfinance_ticker)
                    supp_df = ticker.history(period="5d", interval="1h")
                    if supp_df is not None and not supp_df.empty:
                        supp_df.columns = [c.lower() for c in supp_df.columns]
                        logger.debug("L7 supplementary data: %d bars from %s",
                                     len(supp_df), instrument.yfinance_ticker)
                except Exception as yf_err:
                    logger.debug("yfinance fetch failed for L7: %s", yf_err)

            sig7 = self.layer7.analyze(
                l7_df,
                trade_direction=trend_direction,
                key_level=poc_level,
                atr=result.atr,
                supplementary_df=supp_df,
            )
        except Exception as e:
            result.errors["L7"] = str(e)
            sig7 = LayerSignal("L7_OrderFlow", "NEUTRAL", 5.0, 0.3, {"error": str(e)})
        signals.append(sig7)

        # ── L8: Killzone (session timing — category-aware) ──────────
        try:
            sig8 = self.layer8.analyze(symbol, instrument=instrument)
        except Exception as e:
            result.errors["L8"] = str(e)
            sig8 = LayerSignal("L8_Killzone", "NEUTRAL", 5.0, 0.3, {"error": str(e)})
        signals.append(sig8)

        # ── L9: Correlation ──────────────────────────────────────────
        try:
            sig9 = self.layer9.analyze(
                instrument_key=symbol,
                snapshot=intermarket_snapshot,
                open_positions=open_positions,
            )
        except Exception as e:
            result.errors["L9"] = str(e)
            sig9 = LayerSignal("L9_Correlation", "NEUTRAL", 5.0, 0.3, {"error": str(e)})
        signals.append(sig9)

        # ── L10: Sentiment (with cot_name from instrument config) ────
        try:
            sig10 = self.layer10.analyze(
                instrument_key=symbol,
                category=instrument.category,
                snapshot=intermarket_snapshot,
                cot_name=getattr(instrument, "cot_name", None),
            )
        except Exception as e:
            result.errors["L10"] = str(e)
            sig10 = LayerSignal("L10_Sentiment", "NEUTRAL", 5.0, 0.3, {"error": str(e)})
        signals.append(sig10)

        # ── L11: AI / Regime Evaluation ──────────────────────────────
        try:
            sig11 = self.layer11.analyze(
                daily_df=df_d1,
                volume_profile=vp,
                vix_level=vix_level,
            )
        except Exception as e:
            result.errors["L11"] = str(e)
            sig11 = LayerSignal("L11_Regime", "NEUTRAL", 5.0, 0.3, {"error": str(e)})
        signals.append(sig11)

        # ── Confluence Scoring ───────────────────────────────────────
        result.signals = signals
        try:
            result.confluence = self.scorer.score(signals)
            result.direction = result.confluence.get("direction", "NEUTRAL")
            result.grade = result.confluence.get("grade", "---")
            result.tradeable = result.confluence.get("tradeable", False)
        except Exception as e:
            result.errors["confluence"] = str(e)

        # ── Full Evaluation (TWS/QAS + veto checks) ─────────────────
        try:
            from data.economic_calendar import is_news_blackout
            news_soon = is_news_blackout(symbol)
        except Exception:
            news_soon = False

        try:
            regime_name = result.regime.get("regime", "NORMAL")
            result.evaluation = full_evaluation(
                signals=signals,
                portfolio_risk_pct=portfolio_risk_pct,
                daily_losses=daily_losses,
                daily_drawdown_pct=daily_drawdown_pct,
                correlated_open_count=correlated_open_count,
                news_within_30min=news_soon,
                regime=regime_name,
            )
            # Override grade/direction from full evaluation if available
            if result.evaluation.get("grade"):
                result.grade = result.evaluation["grade"]
            if result.evaluation.get("direction"):
                result.direction = result.evaluation["direction"]
        except Exception as e:
            result.errors["evaluation"] = str(e)

        # ── Setup Detection (entry/SL/TP) ────────────────────────────
        try:
            from analysis.setup_detector import SetupDetector
            sd = SetupDetector()
            result.setup = sd.detect(
                confluence=result.confluence,
                layer_signals=signals,
                volume_profile=vp,
                current_price=result.current_price,
                atr=result.atr,
            )
        except Exception as e:
            result.errors["setup"] = str(e)

        # ── Price Context for LLM deep analysis ──────────────────────
        try:
            from analysis.llm_evaluator import build_price_context
            result.price_context = build_price_context(
                df_d1=df_d1, df_h4=df_h4, df_h1=df_h1, df_m15=df_m15,
                pip_size=instrument.pip_size,
            )
        except Exception:
            pass

        result.elapsed_ms = (time.time() - t0) * 1000
        logger.debug(
            "Pipeline %s: grade=%s dir=%s tradeable=%s (%.0fms)",
            symbol, result.grade, result.direction, result.tradeable, result.elapsed_ms,
        )
        return result

    def run_single_tf(
        self,
        instrument: Instrument,
        intermarket_layer: IntermarketLayer,
        df: pd.DataFrame,
        timeframe: str,
        intermarket_snapshot: Optional[Dict] = None,
        shared_l1: Optional[LayerSignal] = None,
        shared_l2: Optional[LayerSignal] = None,
        shared_l8: Optional[LayerSignal] = None,
        shared_l9: Optional[LayerSignal] = None,
        shared_l10: Optional[LayerSignal] = None,
        shared_l11: Optional[LayerSignal] = None,
        volume_profile: Optional[VolumeProfile] = None,
    ) -> Dict[str, Any]:
        """
        Lightweight single-TF evaluation for dashboard grid views.
        Reuses pre-computed shared layers (L1/L2/L8/L9/L10/L11) and only
        computes L3-L7 per timeframe.
        """
        result = {}
        price = float(df["close"].iloc[-1]) if df is not None and not df.empty else 0.0
        cur_atr = compute_atr(df) if df is not None and len(df) >= 14 else 0.0

        # Use shared layers
        if shared_l1:
            result["L1"] = shared_l1.score
            result["L1d"] = shared_l1.direction
        else:
            result["L1"] = 0.0
            result["L1d"] = "NEUTRAL"

        if shared_l2:
            result["L2"] = shared_l2.score
            result["L2d"] = shared_l2.direction
        else:
            result["L2"] = 0.0
            result["L2d"] = "NEUTRAL"

        trend_dir = result.get("L2d", "NEUTRAL")
        if trend_dir == "---":
            trend_dir = "NEUTRAL"

        # L3 — VP
        vp = volume_profile
        if vp is None and df is not None and not df.empty and len(df) >= 30:
            try:
                vp = compute_volume_profile(df)
            except Exception:
                pass

        if vp is not None:
            try:
                s = self.layer3.analyze(current_price=price, composite_profile=vp, trade_direction=trend_dir)
                result["L3"] = s.score
                result["L3d"] = s.direction
            except Exception:
                result["L3"] = 0.0
                result["L3d"] = "---"
        else:
            result["L3"] = 0.0
            result["L3d"] = "---"

        hvn = list(vp.hvn) if vp else []
        lvn = list(vp.lvn) if vp else []
        conf_levels = [vp.poc, vp.vah, vp.val] + hvn[:3] if vp else None

        # L4 — Candle Density
        try:
            s = self.layer4.analyze(df, vp_hvn=hvn, vp_lvn=lvn, current_price=price, trade_direction=trend_dir)
            result["L4"] = s.score
            result["L4d"] = s.direction
        except Exception:
            result["L4"] = 0.0
            result["L4d"] = "---"

        # L5 — Liquidity
        try:
            s = self.layer5.analyze(df, atr=cur_atr, current_price=price, trade_direction=trend_dir)
            result["L5"] = s.score
            result["L5d"] = s.direction
        except Exception:
            result["L5"] = 0.0
            result["L5d"] = "---"

        # L6 — FVG/OB with L2 direction and L3 confluence levels
        try:
            s = self.layer6.analyze(df, atr=cur_atr, current_price=price, trade_direction=trend_dir, confluence_levels=conf_levels)
            result["L6"] = s.score
            result["L6d"] = s.direction
        except Exception:
            result["L6"] = 0.0
            result["L6d"] = "---"

        # L7 — Order Flow with direction
        try:
            poc = vp.poc if vp else None
            s = self.layer7.analyze(df, trade_direction=trend_dir, key_level=poc, atr=cur_atr)
            result["L7"] = s.score
            result["L7d"] = s.direction
        except Exception:
            result["L7"] = 0.0
            result["L7d"] = "---"

        # Shared layers
        if shared_l8:
            result["L8"] = shared_l8.score
            result["L8d"] = shared_l8.direction
        else:
            result["L8"] = 0.0
            result["L8d"] = "NEUTRAL"

        if shared_l9:
            result["L9"] = shared_l9.score
            result["L9d"] = shared_l9.direction
        else:
            result["L9"] = 5.0
            result["L9d"] = "NEUTRAL"

        if shared_l10:
            result["L10"] = shared_l10.score
            result["L10d"] = shared_l10.direction
        else:
            result["L10"] = 5.0
            result["L10d"] = "NEUTRAL"

        if shared_l11:
            result["L11"] = shared_l11.score
            result["L11d"] = shared_l11.direction
        else:
            result["L11"] = 5.0
            result["L11d"] = "NEUTRAL"

        return result

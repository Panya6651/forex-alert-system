"""
Multi-Timeframe Analyzer
========================
คำนวณ indicator ต่อ timeframe แล้วรวมเป็น confluence score
"""
from dataclasses import dataclass, field
from typing import Dict, List

import pandas as pd
import numpy as np

from config import settings
from core.logger import get_logger

logger = get_logger(__name__)


# ── Indicator calculations (ไม่ต้องพึ่ง ta-lib ภายนอก ลดปัญหาติดตั้งใน production) ──

def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def macd(series: pd.Series, fast=12, slow=26, signal=9):
    ema_fast = ema(series, fast)
    ema_slow = ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


@dataclass
class TimeframeAnalysis:
    timeframe: str
    trend: str          # "bullish" | "bearish" | "neutral"
    rsi_value: float
    rsi_state: str       # "overbought" | "oversold" | "neutral"
    macd_cross: str      # "bullish_cross" | "bearish_cross" | "none"
    atr_value: float
    score: float          # -1.0 (bearish สุด) ถึง +1.0 (bullish สุด)


@dataclass
class ConfluenceResult:
    symbol: str
    per_timeframe: Dict[str, TimeframeAnalysis]
    overall_direction: str   # "BUY" | "SELL" | "HOLD"
    confidence: float          # 0.0 - 1.0
    reasons: List[str] = field(default_factory=list)


class MTFAnalyzer:
    def analyze_timeframe(self, tf_key: str, df: pd.DataFrame) -> TimeframeAnalysis:
        close = df["close"]

        ema_fast = ema(close, settings.EMA_FAST).iloc[-1]
        ema_mid = ema(close, settings.EMA_MID).iloc[-1]
        ema_slow = ema(close, settings.EMA_SLOW).iloc[-1] if len(df) >= settings.EMA_SLOW else ema_mid

        rsi_series = rsi(close, settings.RSI_PERIOD)
        rsi_val = rsi_series.iloc[-1]

        macd_line, signal_line, hist = macd(close, settings.MACD_FAST, settings.MACD_SLOW, settings.MACD_SIGNAL)
        macd_cross = "none"
        if len(hist) >= 2:
            if hist.iloc[-2] < 0 <= hist.iloc[-1]:
                macd_cross = "bullish_cross"
            elif hist.iloc[-2] > 0 >= hist.iloc[-1]:
                macd_cross = "bearish_cross"

        atr_val = atr(df, settings.ATR_PERIOD).iloc[-1]

        # ── Trend determination จาก EMA alignment ──
        if ema_fast > ema_mid > ema_slow:
            trend = "bullish"
        elif ema_fast < ema_mid < ema_slow:
            trend = "bearish"
        else:
            trend = "neutral"

        rsi_state = "neutral"
        if rsi_val >= settings.RSI_OVERBOUGHT:
            rsi_state = "overbought"
        elif rsi_val <= settings.RSI_OVERSOLD:
            rsi_state = "oversold"

        # ── Score รวมต่อ timeframe (-1 ถึง +1) ──
        score = 0.0
        score += 0.5 if trend == "bullish" else (-0.5 if trend == "bearish" else 0.0)
        score += 0.25 if macd_cross == "bullish_cross" else (-0.25 if macd_cross == "bearish_cross" else 0.0)
        if rsi_state == "oversold":
            score += 0.25
        elif rsi_state == "overbought":
            score -= 0.25

        return TimeframeAnalysis(
            timeframe=tf_key,
            trend=trend,
            rsi_value=round(float(rsi_val), 2) if not np.isnan(rsi_val) else 0.0,
            rsi_state=rsi_state,
            macd_cross=macd_cross,
            atr_value=round(float(atr_val), 5) if not np.isnan(atr_val) else 0.0,
            score=round(score, 3),
        )

    def analyze(self, symbol: str, candles_by_tf: Dict[str, pd.DataFrame]) -> ConfluenceResult:
        per_tf: Dict[str, TimeframeAnalysis] = {}
        weighted_score = 0.0
        total_weight = 0.0
        reasons = []

        for tf_key, df in candles_by_tf.items():
            if df is None or len(df) < 30:
                continue
            analysis = self.analyze_timeframe(tf_key, df)
            per_tf[tf_key] = analysis
            weight = settings.TIMEFRAMES[tf_key]["weight"]
            weighted_score += analysis.score * weight
            total_weight += weight

            if analysis.trend != "neutral":
                reasons.append(f"{tf_key}: เทรนด์ {analysis.trend}")
            if analysis.macd_cross != "none":
                reasons.append(f"{tf_key}: MACD {analysis.macd_cross}")
            if analysis.rsi_state != "neutral":
                reasons.append(f"{tf_key}: RSI {analysis.rsi_state} ({analysis.rsi_value})")

        if total_weight == 0:
            return ConfluenceResult(symbol=symbol, per_timeframe={}, overall_direction="HOLD", confidence=0.0)

        normalized_score = weighted_score / total_weight  # -1..+1
        confidence = min(abs(normalized_score), 1.0)

        if normalized_score > 0.15:
            direction = "BUY"
        elif normalized_score < -0.15:
            direction = "SELL"
        else:
            direction = "HOLD"

        return ConfluenceResult(
            symbol=symbol,
            per_timeframe=per_tf,
            overall_direction=direction,
            confidence=round(confidence, 3),
            reasons=reasons,
        )

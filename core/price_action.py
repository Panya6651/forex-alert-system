"""
Price Action Utilities
=======================
หา Support/Resistance จาก swing high/low และตรวจ candlestick pattern พื้นฐาน
ใช้เสริม indicator เชิงตัวเลข (EMA/RSI/MACD) ด้วยบริบทเชิงราคาจริง
ซึ่งช่วยเพิ่มความแม่นยำจุดเข้ามากกว่าใช้ indicator อย่างเดียว
"""
from dataclasses import dataclass
from typing import List, Optional

import pandas as pd
import numpy as np


@dataclass
class SwingLevel:
    price: float
    kind: str          # "high" | "low"
    index: int
    touches: int = 1     # จำนวนครั้งที่ราคาเคยเทสระดับนี้ (ยิ่งมาก ยิ่งเป็น S/R ที่แข็งแรง)


def find_swing_points(df: pd.DataFrame, left: int = 3, right: int = 3) -> List[SwingLevel]:
    """หา swing high/low แบบ fractal: จุดที่สูง/ต่ำกว่าเพื่อนบ้านซ้าย-ขวา `left`/`right` แท่ง"""
    highs = df["high"].values
    lows = df["low"].values
    n = len(df)
    swings: List[SwingLevel] = []

    for i in range(left, n - right):
        window_high = highs[i - left:i + right + 1]
        window_low = lows[i - left:i + right + 1]
        if highs[i] == window_high.max() and np.argmax(window_high) == left:
            swings.append(SwingLevel(price=float(highs[i]), kind="high", index=i))
        if lows[i] == window_low.min() and np.argmin(window_low) == left:
            swings.append(SwingLevel(price=float(lows[i]), kind="low", index=i))

    return swings


def cluster_levels(swings: List[SwingLevel], tolerance_pct: float = 0.05) -> List[SwingLevel]:
    """รวม swing point ที่ราคาใกล้กันมาก (ภายใน tolerance %) เป็นระดับเดียว นับ touches สะสม"""
    if not swings:
        return []

    sorted_swings = sorted(swings, key=lambda s: s.price)
    clustered: List[SwingLevel] = []
    current = sorted_swings[0]
    touches = 1

    for s in sorted_swings[1:]:
        pct_diff = abs(s.price - current.price) / current.price * 100
        if pct_diff <= tolerance_pct:
            # รวมเข้าด้วยกัน ใช้ราคาเฉลี่ยถ่วงน้ำหนัก
            current = SwingLevel(
                price=(current.price * touches + s.price) / (touches + 1),
                kind=current.kind,
                index=max(current.index, s.index),
                touches=touches + 1,
            )
            touches += 1
        else:
            current.touches = touches
            clustered.append(current)
            current = s
            touches = 1

    current.touches = touches
    clustered.append(current)
    return clustered


def nearest_support_resistance(df: pd.DataFrame, current_price: float,
                                left: int = 3, right: int = 3) -> dict:
    """คืนระดับ support ที่ใกล้ที่สุดด้านล่าง และ resistance ที่ใกล้ที่สุดด้านบนราคาปัจจุบัน"""
    swings = find_swing_points(df, left, right)
    clustered = cluster_levels(swings)

    supports = sorted(
        [s for s in clustered if s.price < current_price],
        key=lambda s: current_price - s.price,
    )
    resistances = sorted(
        [s for s in clustered if s.price > current_price],
        key=lambda s: s.price - current_price,
    )

    return {
        "nearest_support": supports[0] if supports else None,
        "nearest_resistance": resistances[0] if resistances else None,
    }


def is_near_level(current_price: float, level: Optional[SwingLevel], atr_value: float,
                   proximity_atr_multiple: float = 0.5) -> bool:
    """เช็คว่าราคาปัจจุบันอยู่ใกล้ระดับ S/R มากพอไหม (ใช้ ATR เป็นหน่วยวัดแทน % คงที่ เพื่อปรับตามความผันผวนของแต่ละคู่)"""
    if level is None or atr_value <= 0:
        return False
    return abs(current_price - level.price) <= atr_value * proximity_atr_multiple


# ── Candlestick Patterns ─────────────────────────────────────

def _body(row) -> float:
    return abs(row["close"] - row["open"])


def _range(row) -> float:
    return row["high"] - row["low"]


def detect_candlestick_pattern(df: pd.DataFrame) -> str:
    """ตรวจ pattern บนแท่งล่าสุดที่ปิดแล้ว (index -1) เทียบกับแท่งก่อนหน้า
    คืนค่า: 'bullish_pin_bar' | 'bearish_pin_bar' | 'bullish_engulfing' | 'bearish_engulfing' | 'none'
    """
    if len(df) < 2:
        return "none"

    last = df.iloc[-1]
    prev = df.iloc[-2]

    last_range = _range(last)
    if last_range <= 0:
        return "none"

    body = _body(last)
    upper_wick = last["high"] - max(last["close"], last["open"])
    lower_wick = min(last["close"], last["open"]) - last["low"]

    # ── Pin bar (หางยาว body สั้น บ่งบอกการปฏิเสธราคา) ──
    if lower_wick >= body * 2 and lower_wick >= last_range * 0.5 and upper_wick < body:
        return "bullish_pin_bar"
    if upper_wick >= body * 2 and upper_wick >= last_range * 0.5 and lower_wick < body:
        return "bearish_pin_bar"

    # ── Engulfing (แท่งปัจจุบันกลืนแท่งก่อนหน้าทั้งหมด) ──
    prev_bullish = prev["close"] > prev["open"]
    curr_bullish = last["close"] > last["open"]

    if (not prev_bullish and curr_bullish
            and last["close"] >= prev["open"] and last["open"] <= prev["close"]):
        return "bullish_engulfing"
    if (prev_bullish and not curr_bullish
            and last["open"] >= prev["close"] and last["close"] <= prev["open"]):
        return "bearish_engulfing"

    return "none"


# ── Bollinger Bands & Stochastic (บริบทเสริม) ────────────────

def bollinger_bands(series: pd.Series, period: int = 20, std_mult: float = 2.0):
    mid = series.rolling(period).mean()
    std = series.rolling(period).std()
    upper = mid + std_mult * std
    lower = mid - std_mult * std
    return upper, mid, lower


def stochastic(df: pd.DataFrame, k_period: int = 14, d_period: int = 3):
    low_min = df["low"].rolling(k_period).min()
    high_max = df["high"].rolling(k_period).max()
    denom = (high_max - low_min).replace(0, np.nan)
    percent_k = 100 * (df["close"] - low_min) / denom
    percent_d = percent_k.rolling(d_period).mean()
    return percent_k, percent_d

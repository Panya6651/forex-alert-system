"""
Entry Signal Engine
====================
แยกการตัดสินใจเป็น 2 ชั้นเพื่อเพิ่มความแม่นยำ:

  ชั้น 1 - TREND BIAS (จาก MTFAnalyzer เดิม): timeframe ใหญ่บอกทิศทางหลัก (BUY/SELL/HOLD)
  ชั้น 2 - ENTRY TRIGGER (โมดูลนี้): timeframe เข้าเทรดจริง ต้องผ่านเงื่อนไขทั้งหมดนี้ก่อนยิงสัญญาณ:
      1. ราคาต้อง "พักตัว" กลับมาใกล้ EMA หรือ S/R ไม่ใช่ไล่ราคาที่วิ่งไปไกลแล้ว (ป้องกันเข้าตอน overextended)
      2. RSI ต้องไม่อยู่ในโซน overbought (ฝั่ง BUY) หรือ oversold (ฝั่ง SELL) — เพราะถ้า RSI extreme
         สวนทางกับทิศทางที่จะเข้า แปลว่าไล่ราคาสุดโต่งเกินไป มีความเสี่ยง pullback แรง
      3. มี candlestick pattern ยืนยันที่จุดเข้า (pin bar / engulfing ตรงทิศทาง)
      4. ราคาอยู่ใกล้ระดับ Support (ฝั่ง BUY) หรือ Resistance (ฝั่ง SELL) ที่มีนัยสำคัญ (เคยเทสมาแล้ว)
      5. Stochastic ยืนยันทิศทาง (K ตัดขึ้นจากโซน oversold / ตัดลงจากโซน overbought)

  ระบบให้คะแนนถ่วงน้ำหนักแต่ละเงื่อนไข แทนที่จะบังคับผ่านครบทุกข้อ (ยืดหยุ่นกว่าและ
  สอดคล้องกับสภาพตลาดจริงที่ไม่ได้เพอร์เฟกต์ทุกเงื่อนไขพร้อมกันเสมอ) แต่ตั้ง threshold
  ขั้นต่ำไว้ป้องกันสัญญาณอ่อนเกินไป
"""
from dataclasses import dataclass, field
from typing import List, Optional

import pandas as pd
import numpy as np

from config import settings
from core.logger import get_logger
from core.mtf_analyzer import ema, rsi
from core.price_action import (
    nearest_support_resistance, is_near_level, detect_candlestick_pattern,
    bollinger_bands, stochastic,
)

logger = get_logger(__name__)

# น้ำหนักของแต่ละเงื่อนไข รวมกันได้สูงสุด 1.0
WEIGHT_PULLBACK = 0.25
WEIGHT_RSI_NOT_EXTREME = 0.15
WEIGHT_CANDLESTICK = 0.25
WEIGHT_SR_PROXIMITY = 0.20
WEIGHT_STOCHASTIC = 0.15

MIN_ENTRY_SCORE = 0.5  # ต้องผ่านอย่างน้อย 50% ของน้ำหนักรวมถึงจะถือว่าเป็นจุดเข้าที่ดี


@dataclass
class EntrySignal:
    symbol: str
    direction: str            # "BUY" | "SELL"
    is_valid_entry: bool
    entry_score: float          # 0.0 - 1.0
    entry_price: float
    suggested_stop: float
    triggers: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


class EntrySignalEngine:
    def evaluate(self, symbol: str, direction: str, entry_df: pd.DataFrame,
                 atr_value: float) -> Optional[EntrySignal]:
        """
        direction: ทิศทางที่ต้องการเข้า (มาจาก trend bias ของ MTFAnalyzer แล้ว)
        entry_df: แท่งเทียนของ timeframe ที่ใช้หาจังหวะเข้าจริง (แนะนำ M15 หรือ H1)
        """
        if direction not in ("BUY", "SELL"):
            return None
        if len(entry_df) < 30:
            logger.debug(f"{symbol}: ข้อมูลไม่พอสำหรับประเมิน entry ({len(entry_df)} แท่ง)")
            return None

        close = entry_df["close"]
        current_price = float(close.iloc[-1])

        score = 0.0
        triggers = []
        warnings = []

        # ── 1. Pullback check: ราคาต้องไม่ห่างจาก EMA20 เกินไป (วัดเป็นสัดส่วนของ ATR) ──
        ema_fast = ema(close, settings.EMA_FAST).iloc[-1]
        distance_from_ema = abs(current_price - ema_fast)
        if atr_value > 0 and distance_from_ema <= atr_value * 1.0:
            score += WEIGHT_PULLBACK
            triggers.append(f"ราคาอยู่ใกล้ EMA{settings.EMA_FAST} (พักตัวแล้ว ไม่ไล่ราคา)")
        else:
            warnings.append(f"ราคาห่างจาก EMA{settings.EMA_FAST} เกินไป ({distance_from_ema:.5f}) — อาจเป็นการไล่ราคา")

        # ── 2. RSI ไม่สุดโต่งสวนทางทิศทางที่จะเข้า ──
        rsi_val = rsi(close, settings.RSI_PERIOD).iloc[-1]
        if direction == "BUY" and rsi_val < settings.RSI_OVERBOUGHT:
            score += WEIGHT_RSI_NOT_EXTREME
            triggers.append(f"RSI ({rsi_val:.1f}) ยังไม่ overbought — ยังมีพื้นที่ให้ขึ้นต่อ")
        elif direction == "SELL" and rsi_val > settings.RSI_OVERSOLD:
            score += WEIGHT_RSI_NOT_EXTREME
            triggers.append(f"RSI ({rsi_val:.1f}) ยังไม่ oversold — ยังมีพื้นที่ให้ลงต่อ")
        else:
            warnings.append(f"RSI ({rsi_val:.1f}) อยู่ในโซนสุดโต่งสวนทาง — ความเสี่ยง pullback แรง")

        # ── 3. Candlestick pattern ยืนยัน ──
        pattern = detect_candlestick_pattern(entry_df)
        bullish_patterns = {"bullish_pin_bar", "bullish_engulfing"}
        bearish_patterns = {"bearish_pin_bar", "bearish_engulfing"}
        if (direction == "BUY" and pattern in bullish_patterns) or \
           (direction == "SELL" and pattern in bearish_patterns):
            score += WEIGHT_CANDLESTICK
            triggers.append(f"Candlestick pattern ยืนยัน: {pattern}")
        elif pattern != "none":
            warnings.append(f"Candlestick pattern ({pattern}) สวนทางกับสัญญาณ")

        # ── 4. ใกล้ระดับ S/R ที่มีนัยสำคัญ ──
        sr = nearest_support_resistance(entry_df, current_price)
        if direction == "BUY":
            level = sr["nearest_support"]
            if is_near_level(current_price, level, atr_value) and level and level.touches >= 2:
                score += WEIGHT_SR_PROXIMITY
                triggers.append(f"ใกล้แนวรับที่เทสมาแล้ว {level.touches} ครั้ง (~{level.price:.5f})")
            elif level:
                warnings.append(f"ไม่ได้อยู่ใกล้แนวรับที่แข็งแรง (ใกล้สุด: {level.price:.5f})")
        else:
            level = sr["nearest_resistance"]
            if is_near_level(current_price, level, atr_value) and level and level.touches >= 2:
                score += WEIGHT_SR_PROXIMITY
                triggers.append(f"ใกล้แนวต้านที่เทสมาแล้ว {level.touches} ครั้ง (~{level.price:.5f})")
            elif level:
                warnings.append(f"ไม่ได้อยู่ใกล้แนวต้านที่แข็งแรง (ใกล้สุด: {level.price:.5f})")

        # ── 5. Stochastic ยืนยันจังหวะกลับตัว ──
        k, d = stochastic(entry_df)
        if len(k) >= 2 and not np.isnan(k.iloc[-1]) and not np.isnan(k.iloc[-2]):
            k_cross_up = k.iloc[-2] < d.iloc[-2] and k.iloc[-1] >= d.iloc[-1] and k.iloc[-1] < 50
            k_cross_down = k.iloc[-2] > d.iloc[-2] and k.iloc[-1] <= d.iloc[-1] and k.iloc[-1] > 50
            if direction == "BUY" and k_cross_up:
                score += WEIGHT_STOCHASTIC
                triggers.append("Stochastic ตัดขึ้นจากโซนล่าง")
            elif direction == "SELL" and k_cross_down:
                score += WEIGHT_STOCHASTIC
                triggers.append("Stochastic ตัดลงจากโซนบน")

        # ── สรุปผล + คำนวณ suggested stop จากโครงสร้างราคาจริง (ไม่ใช่แค่ ATR อย่างเดียว) ──
        is_valid = score >= MIN_ENTRY_SCORE

        if direction == "BUY":
            structural_stop = sr["nearest_support"].price if sr["nearest_support"] else current_price - atr_value * settings.RISK.atr_sl_multiplier
            suggested_stop = min(structural_stop - atr_value * 0.2, current_price - atr_value * 0.5)
        else:
            structural_stop = sr["nearest_resistance"].price if sr["nearest_resistance"] else current_price + atr_value * settings.RISK.atr_sl_multiplier
            suggested_stop = max(structural_stop + atr_value * 0.2, current_price + atr_value * 0.5)

        return EntrySignal(
            symbol=symbol,
            direction=direction,
            is_valid_entry=is_valid,
            entry_score=round(score, 3),
            entry_price=current_price,
            suggested_stop=round(suggested_stop, 5),
            triggers=triggers,
            warnings=warnings,
        )

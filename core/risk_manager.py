"""
Risk Manager
============
คำนวณ lot size, SL/TP และบังคับกฎความเสี่ยง (max drawdown, max concurrent trades)
"""
from dataclasses import dataclass
from typing import Optional

from config import settings
from core.logger import get_logger

logger = get_logger(__name__)


@dataclass
class TradePlan:
    symbol: str
    direction: str      # "BUY" | "SELL"
    lot_size: float
    entry_price: float
    stop_loss: float
    take_profit: float
    risk_amount: float


class RiskManager:
    def __init__(self):
        self._daily_start_equity: Optional[float] = None
        self._trades_today = 0

    def set_daily_baseline(self, equity: float) -> None:
        self._daily_start_equity = equity

    def check_daily_drawdown_ok(self, current_equity: float) -> bool:
        if self._daily_start_equity is None:
            self.set_daily_baseline(current_equity)
            return True
        drawdown_pct = (self._daily_start_equity - current_equity) / self._daily_start_equity * 100
        if drawdown_pct >= settings.RISK.max_daily_drawdown_pct:
            logger.warning(f"เกิน max daily drawdown: {drawdown_pct:.2f}% — หยุดเทรดวันนี้")
            return False
        return True

    def check_concurrent_trades_ok(self, current_open_trades: int) -> bool:
        if current_open_trades >= settings.RISK.max_concurrent_trades:
            logger.info(f"เต็ม max concurrent trades ({current_open_trades})")
            return False
        return True

    def check_spread_ok(self, spread_points: int) -> bool:
        if spread_points > settings.RISK.max_spread_points:
            logger.info(f"Spread กว้างเกินไป: {spread_points} points")
            return False
        return True

    def calculate_position(
        self,
        symbol: str,
        direction: str,
        entry_price: float,
        atr_value: float,
        account_equity: float,
        pip_value_per_lot: float = 10.0,  # ค่าเริ่มต้นสำหรับคู่ USD quote, ควรปรับตาม symbol จริง
        point_size: float = 0.0001,
        custom_stop_loss: float = None,
        custom_take_profit: float = None,
    ) -> TradePlan:
        """คำนวณ lot size ตาม % risk ต่อ trade
        ถ้าไม่ระบุ custom_stop_loss/take_profit จะคำนวณจาก ATR อย่างเดียว (fallback เดิม)
        แนะนำให้ส่ง custom_stop_loss จาก EntrySignal.suggested_stop เพื่อ SL ที่อิงโครงสร้างราคาจริง
        (เช่น ใต้แนวรับ) แทนที่จะเป็นระยะ ATR คงที่ ซึ่งแม่นยำกว่าในตลาดจริง
        """

        sl_distance = atr_value * settings.RISK.atr_sl_multiplier
        tp_distance = atr_value * settings.RISK.atr_tp_multiplier

        if direction == "BUY":
            stop_loss = custom_stop_loss if custom_stop_loss is not None else entry_price - sl_distance
            take_profit = custom_take_profit if custom_take_profit is not None else entry_price + tp_distance
        else:
            stop_loss = custom_stop_loss if custom_stop_loss is not None else entry_price + sl_distance
            take_profit = custom_take_profit if custom_take_profit is not None else entry_price - tp_distance

        # Risk:Reward ขั้นต่ำ — ถ้า custom stop loss ทำให้ RR แย่เกินไป ให้ปรับ TP ตาม RR ที่ตั้งไว้แทน
        actual_sl_distance = abs(entry_price - stop_loss)
        min_rr = settings.RISK.atr_tp_multiplier / settings.RISK.atr_sl_multiplier
        if actual_sl_distance > 0:
            implied_tp_distance = actual_sl_distance * min_rr
            if direction == "BUY" and custom_take_profit is None:
                take_profit = entry_price + implied_tp_distance
            elif direction == "SELL" and custom_take_profit is None:
                take_profit = entry_price - implied_tp_distance

        risk_amount = account_equity * (settings.RISK.risk_per_trade_pct / 100)

        sl_pips = actual_sl_distance / point_size / 10  # แปลงเป็น pip มาตรฐาน (5 digit broker)
        if sl_pips <= 0:
            lot_size = settings.RISK.min_lot_size
        else:
            lot_size = risk_amount / (sl_pips * pip_value_per_lot)

        lot_size = max(settings.RISK.min_lot_size, min(lot_size, settings.RISK.max_lot_size))
        lot_size = round(lot_size, 2)

        return TradePlan(
            symbol=symbol,
            direction=direction,
            lot_size=lot_size,
            entry_price=entry_price,
            stop_loss=round(stop_loss, 5),
            take_profit=round(take_profit, 5),
            risk_amount=round(risk_amount, 2),
        )

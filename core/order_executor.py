"""
Order Executor
==============
ส่งคำสั่งซื้อขายจริงเข้า MT5 พร้อม SL/TP และจัดการปิด/แก้ไข position
"""
from typing import Optional

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

from core.logger import get_logger
from core.risk_manager import TradePlan

logger = get_logger(__name__)


class OrderExecutionError(Exception):
    pass


class OrderExecutor:
    def send_market_order(self, plan: TradePlan, magic_number: int = 123456, comment: str = "auto-system") -> dict:
        if mt5 is None:
            raise OrderExecutionError("MetaTrader5 package ไม่พร้อมใช้งาน")

        order_type = mt5.ORDER_TYPE_BUY if plan.direction == "BUY" else mt5.ORDER_TYPE_SELL
        tick = mt5.symbol_info_tick(plan.symbol)
        price = tick.ask if plan.direction == "BUY" else tick.bid

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": plan.symbol,
            "volume": plan.lot_size,
            "type": order_type,
            "price": price,
            "sl": plan.stop_loss,
            "tp": plan.take_profit,
            "deviation": 10,
            "magic": magic_number,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        result = mt5.order_send(request)

        if result is None:
            raise OrderExecutionError(f"order_send คืนค่า None: {mt5.last_error()}")

        if result.retcode != mt5.TRADE_RETCODE_DONE:
            logger.error(f"ส่งออเดอร์ล้มเหลว: retcode={result.retcode} comment={result.comment}")
            raise OrderExecutionError(f"ส่งออเดอร์ล้มเหลว: {result.comment} (code {result.retcode})")

        logger.info(f"ส่งออเดอร์สำเร็จ: {plan.symbol} {plan.direction} {plan.lot_size} lot @ {price}")
        return {
            "ticket": result.order,
            "symbol": plan.symbol,
            "direction": plan.direction,
            "volume": plan.lot_size,
            "price": price,
            "sl": plan.stop_loss,
            "tp": plan.take_profit,
        }

    def close_position(self, ticket: int) -> bool:
        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            logger.warning(f"ไม่พบ position ticket={ticket}")
            return False

        pos = positions[0]
        close_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
        tick = mt5.symbol_info_tick(pos.symbol)
        price = tick.bid if close_type == mt5.ORDER_TYPE_SELL else tick.ask

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": pos.symbol,
            "volume": pos.volume,
            "type": close_type,
            "position": ticket,
            "price": price,
            "deviation": 10,
            "magic": pos.magic,
            "comment": "close-by-system",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            logger.error(f"ปิด position ล้มเหลว: {result}")
            return False
        logger.info(f"ปิด position {ticket} สำเร็จ")
        return True

    def get_open_positions(self, symbol: Optional[str] = None) -> list:
        positions = mt5.positions_get(symbol=symbol) if symbol else mt5.positions_get()
        return list(positions) if positions else []

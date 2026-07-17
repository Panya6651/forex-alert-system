"""
Data Fetcher
============
เชื่อมต่อ MT5 terminal และดึงราคา/แท่งเทียนหลาย timeframe
หมายเหตุ: ต้องรันบนเครื่องที่มี MetaTrader5 terminal ติดตั้งและ login ไว้แล้ว (Windows)
"""
import time
from datetime import datetime
from typing import Dict, Optional

import pandas as pd

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None  # ให้ import ได้แม้ไม่มี MT5 (เช่นตอน dev บน Linux) แต่ใช้งานจริงไม่ได้

from config import settings
from core.logger import get_logger

logger = get_logger(__name__)


class MT5ConnectionError(Exception):
    pass


class DataFetcher:
    def __init__(self):
        self._connected = False

    def connect(self) -> None:
        if mt5 is None:
            raise MT5ConnectionError(
                "ไม่พบ MetaTrader5 package หรือระบบปฏิบัติการไม่รองรับ (ต้องเป็น Windows)"
            )

        kwargs = {}
        if settings.MT5_PATH:
            kwargs["path"] = settings.MT5_PATH

        if not mt5.initialize(**kwargs):
            raise MT5ConnectionError(f"mt5.initialize() ล้มเหลว: {mt5.last_error()}")

        if settings.MT5_LOGIN:
            authorized = mt5.login(
                settings.MT5_LOGIN,
                password=settings.MT5_PASSWORD,
                server=settings.MT5_SERVER,
            )
            if not authorized:
                raise MT5ConnectionError(f"Login ล้มเหลว: {mt5.last_error()}")

        self._connected = True
        logger.info("เชื่อมต่อ MT5 สำเร็จ")

    def disconnect(self) -> None:
        if mt5 is not None and self._connected:
            mt5.shutdown()
            self._connected = False
            logger.info("ตัดการเชื่อมต่อ MT5 แล้ว")

    def ensure_symbol(self, symbol: str) -> bool:
        info = mt5.symbol_info(symbol)
        if info is None:
            logger.warning(f"ไม่พบ symbol {symbol}")
            return False
        if not info.visible:
            mt5.symbol_select(symbol, True)
        return True

    def get_candles(self, symbol: str, timeframe_key: str, count: int = None) -> Optional[pd.DataFrame]:
        """ดึงแท่งเทียนของ symbol/timeframe ที่กำหนด คืนเป็น DataFrame พร้อม index เป็นเวลา"""
        if not self._connected:
            raise MT5ConnectionError("ยังไม่ได้เชื่อมต่อ MT5 กรุณาเรียก connect() ก่อน")

        tf_const_name = settings.TIMEFRAMES[timeframe_key]["mt5_const"]
        tf_const = getattr(mt5, tf_const_name)
        n = count or settings.CANDLES_TO_FETCH

        rates = mt5.copy_rates_from_pos(symbol, tf_const, 0, n)
        if rates is None or len(rates) == 0:
            logger.warning(f"ดึงข้อมูล {symbol} {timeframe_key} ไม่สำเร็จ: {mt5.last_error()}")
            return None

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df.set_index("time", inplace=True)
        return df

    def get_all_timeframes(self, symbol: str) -> Dict[str, pd.DataFrame]:
        """ดึงทุก timeframe ที่ตั้งไว้ใน settings สำหรับ symbol เดียว"""
        result = {}
        for tf_key in settings.TIMEFRAMES:
            df = self.get_candles(symbol, tf_key)
            if df is not None:
                result[tf_key] = df
        return result

    def get_current_tick(self, symbol: str) -> Optional[dict]:
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return None
        return {
            "bid": tick.bid,
            "ask": tick.ask,
            "spread_points": round((tick.ask - tick.bid) / mt5.symbol_info(symbol).point),
            "time": datetime.fromtimestamp(tick.time),
        }

    def get_account_info(self) -> Optional[dict]:
        info = mt5.account_info()
        if info is None:
            return None
        return {
            "balance": info.balance,
            "equity": info.equity,
            "margin": info.margin,
            "margin_free": info.margin_free,
            "profit": info.profit,
        }


if __name__ == "__main__":
    # ทดสอบเบื้องต้น
    fetcher = DataFetcher()
    fetcher.connect()
    for sym in settings.SYMBOLS:
        fetcher.ensure_symbol(sym)
        candles = fetcher.get_candles(sym, "M15", 10)
        print(sym, candles.tail() if candles is not None else "ไม่มีข้อมูล")
    fetcher.disconnect()

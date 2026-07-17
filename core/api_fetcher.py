"""
API Data Fetcher (ไม่ต้องใช้ MT5)
====================================
ดึงราคา Forex จาก Twelve Data API (ฟรี 800 requests/วัน)
ไม่ต้องเปิด MetaTrader 5 บนคอม — รันได้ทุกที่

ลงทะเบียนรับ API Key ฟรีที่: https://twelvedata.com/register
"""
import time
from typing import Dict, Optional

import pandas as pd
import requests

from config import settings
from core.logger import get_logger

logger = get_logger(__name__)

# แปลง timeframe key → Twelve Data interval
TIMEFRAME_MAP = {
    "M1":  "1min",
    "M5":  "5min",
    "M15": "15min",
    "H1":  "1h",
    "H4":  "4h",
    "D1":  "1day",
}

BASE_URL = "https://api.twelvedata.com"


class APIConnectionError(Exception):
    pass


class APIFetcher:
    """ดึงข้อมูลราคาผ่าน Twelve Data REST API"""

    def __init__(self):
        self.api_key = settings.TWELVEDATA_API_KEY
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"apikey {self.api_key}"})

    def connect(self) -> None:
        """ตรวจสอบว่า API Key ใช้งานได้"""
        if not self.api_key:
            raise APIConnectionError(
                "ไม่พบ TWELVEDATA_API_KEY — ลงทะเบียนฟรีที่ https://twelvedata.com/register "
                "แล้วใส่ key ใน .env"
            )
        # ทดสอบเรียก API ง่ายๆ
        try:
            resp = self.session.get(f"{BASE_URL}/price", params={"symbol": "EUR/USD"}, timeout=10)
            data = resp.json()
            if "price" not in data:
                raise APIConnectionError(f"API Key ไม่ถูกต้องหรือเกิน limit: {data.get('message', data)}")
            logger.info("เชื่อมต่อ Twelve Data API สำเร็จ")
        except requests.RequestException as e:
            raise APIConnectionError(f"เชื่อมต่อ API ไม่ได้: {e}")

    def disconnect(self) -> None:
        self.session.close()
        logger.info("ปิด API session แล้ว")

    def _symbol_to_api(self, symbol: str) -> str:
        """แปลง EURUSD → EUR/USD, XAUUSD → XAU/USD"""
        if len(symbol) == 6:
            return f"{symbol[:3]}/{symbol[3:]}"
        return symbol

    def get_candles(self, symbol: str, timeframe_key: str, count: int = None) -> Optional[pd.DataFrame]:
        """ดึงแท่งเทียนของ symbol/timeframe ที่กำหนด คืนเป็น DataFrame"""
        interval = TIMEFRAME_MAP.get(timeframe_key)
        if not interval:
            logger.warning(f"ไม่รู้จัก timeframe: {timeframe_key}")
            return None

        n = count or settings.CANDLES_TO_FETCH
        api_symbol = self._symbol_to_api(symbol)

        try:
            resp = self.session.get(
                f"{BASE_URL}/time_series",
                params={
                    "symbol": api_symbol,
                    "interval": interval,
                    "outputsize": n,
                    "order": "ASC",
                },
                timeout=15,
            )
            data = resp.json()

            if data.get("status") == "error":
                logger.warning(f"API error สำหรับ {symbol} {timeframe_key}: {data.get('message')}")
                return None

            values = data.get("values", [])
            if not values:
                logger.warning(f"ไม่มีข้อมูลสำหรับ {symbol} {timeframe_key}")
                return None

            df = pd.DataFrame(values)
            df["time"] = pd.to_datetime(df["datetime"])
            df = df.rename(columns={
                "open": "open", "high": "high", "low": "low", "close": "close"
            })
            for col in ["open", "high", "low", "close"]:
                df[col] = df[col].astype(float)

            # สร้าง volume ปลอมถ้าไม่มี (indicator บางตัวต้องการ)
            if "volume" not in df.columns:
                df["volume"] = 0

            df.set_index("time", inplace=True)
            return df

        except requests.RequestException as e:
            logger.error(f"เรียก API ไม่สำเร็จสำหรับ {symbol} {timeframe_key}: {e}")
            return None

    def get_all_timeframes(self, symbol: str) -> Dict[str, pd.DataFrame]:
        """ดึงทุก timeframe ที่ตั้งไว้ใน settings สำหรับ symbol เดียว"""
        result = {}
        for tf_key in settings.TIMEFRAMES:
            df = self.get_candles(symbol, tf_key)
            if df is not None:
                result[tf_key] = df
            # หน่วง 8 วินาทีต่อ request เพื่อไม่เกิน 8 req/นาที (free plan)
            time.sleep(8)
        return result

    def get_current_price(self, symbol: str) -> Optional[dict]:
        """ดึงราคาปัจจุบัน (bid/ask ประมาณการ)"""
        api_symbol = self._symbol_to_api(symbol)
        try:
            resp = self.session.get(
                f"{BASE_URL}/price",
                params={"symbol": api_symbol},
                timeout=10,
            )
            data = resp.json()
            price = float(data.get("price", 0))
            if price == 0:
                return None
            # Twelve Data free plan ไม่มี bid/ask แยก — ประมาณการ spread
            spread_estimate = 0.00020 if "JPY" not in symbol else 0.020
            return {
                "bid": price - spread_estimate / 2,
                "ask": price + spread_estimate / 2,
                "mid": price,
            }
        except Exception as e:
            logger.error(f"ดึงราคาปัจจุบัน {symbol} ไม่สำเร็จ: {e}")
            return None

    def ensure_symbol(self, symbol: str) -> bool:
        """ตรวจสอบว่า symbol ใช้งานได้ (API version ไม่ต้องทำอะไรพิเศษ)"""
        return True

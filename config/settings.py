"""
Forex Auto-Trading System - Configuration
==========================================
ตั้งค่าทั้งหมดของระบบไว้ที่นี่ที่เดียว เปลี่ยนพฤติกรรมระบบได้โดยไม่ต้องแก้โค้ด core
"""
import os
from dataclasses import dataclass, field
from typing import List

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv ยังไม่ได้ติดตั้ง — ระบบยังใช้ os.environ ได้ตามปกติ

# ── MT5 Connection (ใช้สำหรับ main.py โหมดเต็ม) ────────────
MT5_LOGIN = int(os.getenv("MT5_LOGIN", "0"))
MT5_PASSWORD = os.getenv("MT5_PASSWORD", "")
MT5_SERVER = os.getenv("MT5_SERVER", "")
MT5_PATH = os.getenv("MT5_PATH", "")  # path ไปยัง terminal64.exe ถ้าจำเป็น

# ── Twelve Data API (ใช้สำหรับ main_alert.py โหมดแจ้งเตือน) ─
# ลงทะเบียนฟรีที่ https://twelvedata.com/register (800 req/วัน)
TWELVEDATA_API_KEY = os.getenv("TWELVEDATA_API_KEY", "")

# ── Telegram ─────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_IDS: List[int] = [
    int(x) for x in os.getenv("TELEGRAM_CHAT_IDS", "").split(",") if x
]

# ── LINE Notify ───────────────────────────────────────
# สมัครฟรีและรับ Token ที่ https://notify-bot.line.me/my/
LINE_NOTIFY_TOKEN = os.getenv("LINE_NOTIFY_TOKEN", "")

# ── Symbols & Timeframes ─────────────────────────────────────
SYMBOLS: List[str] = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD"]

TIMEFRAMES = {
    "M1": {"mt5_const": "TIMEFRAME_M1", "weight": 0.05},
    "M5": {"mt5_const": "TIMEFRAME_M5", "weight": 0.10},
    "M15": {"mt5_const": "TIMEFRAME_M15", "weight": 0.15},
    "H1": {"mt5_const": "TIMEFRAME_H1", "weight": 0.25},
    "H4": {"mt5_const": "TIMEFRAME_H4", "weight": 0.25},
    "D1": {"mt5_const": "TIMEFRAME_D1", "weight": 0.20},
}

CANDLES_TO_FETCH = 300  # จำนวนแท่งเทียนย้อนหลังที่ดึงต่อ timeframe
ENTRY_TIMEFRAME = "M15"  # timeframe ที่ใช้หาจังหวะเข้าจริง (entry trigger) แยกจาก trend bias

# ── Indicators ───────────────────────────────────────────────
EMA_FAST = 20
EMA_MID = 50
EMA_SLOW = 200
RSI_PERIOD = 14
RSI_OVERBOUGHT = 70
RSI_OVERSOLD = 30
ATR_PERIOD = 14
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

# ── Signal / Decision ───────────────────────────────────────
CONFIDENCE_THRESHOLD_AUTO = 0.75   # เกินนี้ = auto ส่งออเดอร์ (ถ้าเปิด AUTO_TRADE_ENABLED)
CONFIDENCE_THRESHOLD_ALERT = 0.55  # เกินนี้ = แจ้งเตือนแต่รอ manual confirm
AUTO_TRADE_ENABLED = False          # ต้องเปิดเองอย่างชัดเจนเท่านั้น (safety default)

# ── News Filter ──────────────────────────────────────────────
NEWS_BLACKOUT_MINUTES_BEFORE = 30
NEWS_BLACKOUT_MINUTES_AFTER = 15
HIGH_IMPACT_ONLY = True
ECONOMIC_CALENDAR_SOURCE = "forexfactory"  # "forexfactory" (default, free) หรือ "tradingeconomics" (ต้องมี API key)
TRADINGECONOMICS_API_KEY = os.getenv("TRADINGECONOMICS_API_KEY", "")

# ── Risk Management ──────────────────────────────────────────
@dataclass
class RiskConfig:
    risk_per_trade_pct: float = 1.0        # % ของ equity ต่อ trade
    max_daily_drawdown_pct: float = 5.0    # หยุดเทรดถ้า drawdown เกินนี้ในวันเดียว
    max_concurrent_trades: int = 3
    max_lot_size: float = 1.0
    min_lot_size: float = 0.01
    atr_sl_multiplier: float = 1.5
    atr_tp_multiplier: float = 3.0          # RR ~ 1:2
    max_spread_points: int = 30             # ห้ามเข้าออเดอร์ถ้า spread กว้างเกินนี้

RISK = RiskConfig()

# ── System / Infra ────────────────────────────────────────────
POLL_INTERVAL_SECONDS = 5
LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "logs")
DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "trades.db")
TIMEZONE = "Asia/Bangkok"

# ── Sentiment (optional Claude API) ──────────────────────────
ENABLE_NEWS_SENTIMENT = False
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

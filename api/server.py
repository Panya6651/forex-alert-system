"""
FastAPI Server & Background Signal Analyzer
===========================================
รันระบบวิเคราะห์สัญญาณและให้บริการ Web API / Web Push Notification
ไม่ต้องเปิด MT5 หรือ Telegram เลย รัน 24 ชม. บน Cloud ได้อย่างสมบูรณ์แบบ
"""
import asyncio
import os
import sqlite3
from datetime import datetime
from typing import List, Dict, Any

from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from config import settings
from core.logger import get_logger
from core.api_fetcher import APIFetcher
from core.mtf_analyzer import MTFAnalyzer
from core.entry_signal import EntrySignalEngine
from core.news_filter import NewsFilter
from api.push_sender import send_web_push, VAPID_PUBLIC_KEY

logger = get_logger("web_server")

app = FastAPI(title="Forex Alert Web App API")

# เปิดใช้งาน CORS เพื่อให้ Frontend (GitHub Pages) สามารถเรียก API ได้
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── ฐานข้อมูลสำหรับเก็บข้อมูล Push Subscription ────────────────────
DB_DIR = os.path.dirname(settings.DB_PATH)
os.makedirs(DB_DIR, exist_ok=True)

def init_web_db():
    conn = sqlite3.connect(settings.DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS push_subscriptions (
            endpoint TEXT PRIMARY KEY,
            p256dh TEXT NOT NULL,
            auth TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

init_web_db()

# ── Data Models ────────────────────────────────────────────────
class KeyModel(BaseModel):
    p256dh: str
    auth: str

class SubscriptionModel(BaseModel):
    endpoint: str
    keys: KeyModel

# ── API Endpoints ──────────────────────────────────────────────
@app.get("/api/vapid-key")
def get_vapid_key():
    """ส่ง VAPID Public Key กลับไปให้ Frontend ใช้ขอบัญชีแจ้งเตือน"""
    return {"publicKey": VAPID_PUBLIC_KEY}

@app.post("/api/subscribe")
def subscribe(sub: SubscriptionModel):
    """รับข้อมูลการแจ้งเตือนจากหน้าเว็บเข้ามาเก็บไว้ใน DB"""
    try:
        conn = sqlite3.connect(settings.DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO push_subscriptions (endpoint, p256dh, auth) VALUES (?, ?, ?)",
            (sub.endpoint, sub.keys.p256dh, sub.keys.auth)
        )
        conn.commit()
        conn.close()
        logger.info("เพิ่ม Subscriber ใหม่สำเร็จ")
        return {"status": "success", "message": "ลงทะเบียนรับแจ้งเตือนสำเร็จ"}
    except Exception as e:
        logger.error(f"ลงทะเบียน Subscriber ล้มเหลว: {e}")
        raise HTTPException(status_code=500, detail="ไม่สามารถลงทะเบียนได้")

@app.get("/api/signals")
def get_signals(limit: int = 30):
    """ส่งสัญญาณซื้อขายล่าสุดไปแสดงผลบน Dashboard"""
    try:
        conn = sqlite3.connect(settings.DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, symbol, direction, confidence, reasons, timestamp FROM signals ORDER BY id DESC LIMIT ?",
            (limit,)
        )
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"ดึงสัญญาณใน DB ล้มเหลว: {e}")
        return []

# ── Background Loop Engine ─────────────────────────────────────
class ForexEngineTask:
    def __init__(self):
        self.fetcher = APIFetcher()
        self.analyzer = MTFAnalyzer()
        self.entry_engine = EntrySignalEngine()
        self.news_filter = NewsFilter()
        self.is_running = False

    def notify_all_subscribers(self, payload: Dict[str, Any]):
        """ส่ง Push Notification แจ้งเตือนไปยังสมาชิกทุกคนที่มีสิทธิ์"""
        conn = sqlite3.connect(settings.DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT endpoint, p256dh, auth FROM push_subscriptions")
        subscribers = cursor.fetchall()
        conn.close()

        if not subscribers:
            return

        logger.info(f"เริ่มส่ง Push แจ้งเตือนไปยังอุปกรณ์ {len(subscribers)} เครื่อง")
        expired_endpoints = []

        for sub in subscribers:
            sub_info = {
                "endpoint": sub["endpoint"],
                "keys": {
                    "p256dh": sub["p256dh"],
                    "auth": sub["auth"]
                }
            }
            # ส่งการแจ้งเตือน
            ok = send_web_push(sub_info, payload)
            if not ok:
                expired_endpoints.append(sub["endpoint"])

        # ลบ Endpoint ที่หมดอายุหรือถูกยกเลิกแล้วออกจากระบบ
        if expired_endpoints:
            conn = sqlite3.connect(settings.DB_PATH)
            cursor = conn.cursor()
            cursor.executemany("DELETE FROM push_subscriptions WHERE endpoint = ?", [(e,) for e in expired_endpoints])
            conn.commit()
            conn.close()
            logger.info(f"ลบ {len(expired_endpoints)} Subscriber ที่หมดอายุออกจากระบบ")

    async def run_loop(self):
        self.is_running = True
        try:
            self.fetcher.connect()
        except Exception as e:
            logger.error(f"Engine เริ่มเชื่อมต่อราคาไม่ได้: {e}")
            self.is_running = False
            return

        self.news_filter.fetch_calendar()
        logger.info("Forex Auto-Analyzer Web Engine เริ่มรันแล้ว!")

        news_counter = 0
        while self.is_running:
            for symbol in settings.SYMBOLS:
                if not self.is_running:
                    break
                try:
                    candles_by_tf = self.fetcher.get_all_timeframes(symbol)
                    if not candles_by_tf:
                        continue

                    # ── วิเคราะห์ Trend Bias ──
                    result = self.analyzer.analyze(symbol, candles_by_tf)
                    
                    # บันทึกสัญญาณลง SQLite
                    conn = sqlite3.connect(settings.DB_PATH)
                    cursor = conn.cursor()
                    cursor.execute(
                        "INSERT INTO signals (symbol, direction, confidence, reasons, timestamp) VALUES (?, ?, ?, ?, ?)",
                        (symbol, result.overall_direction, result.confidence, "; ".join(result.reasons), datetime.now().isoformat())
                    )
                    conn.commit()
                    conn.close()

                    if result.overall_direction == "HOLD" or result.confidence < settings.CONFIDENCE_THRESHOLD_ALERT:
                        continue

                    # ── เช็คช่วงเวลาข่าว ──
                    if self.news_filter.is_blackout(symbol[:3]):
                        logger.info(f"{symbol}: ข้ามเนื่องจากช่วงข่าว")
                        continue

                    # ── เช็คจุดเข้าเทรด ──
                    entry_tf_df = candles_by_tf.get(settings.ENTRY_TIMEFRAME)
                    if entry_tf_df is None:
                        continue

                    entry_tf_analysis = result.per_timeframe.get(settings.ENTRY_TIMEFRAME)
                    atr_for_entry = entry_tf_analysis.atr_value if entry_tf_analysis else 0.0

                    entry_signal = self.entry_engine.evaluate(
                        symbol, result.overall_direction, entry_tf_df, atr_for_entry
                    )

                    if entry_signal and entry_signal.is_valid_entry:
                        # สร้างข้อความสำหรับแจ้งเตือน
                        direction_emoji = "🟢" if result.overall_direction == "BUY" else "🔴"
                        payload = {
                            "title": f"{direction_emoji} สัญญาณ {result.overall_direction}: {symbol}",
                            "body": f"Entry: {entry_signal.entry_price:.5f} | SL: {entry_signal.suggested_stop:.5f}\nความมั่นใจ: {result.confidence*100:.1f}%",
                            "symbol": symbol,
                            "direction": result.overall_direction
                        }
                        # ส่งแจ้งเตือนตรงไปเบราว์เซอร์
                        self.notify_all_subscribers(payload)
                        logger.info(f"📢 ส่งสัญญาณแจ้งเตือน Web Push: {symbol} {result.overall_direction}")

                except Exception as e:
                    logger.error(f"เกิดข้อผิดพลาดในการวิเคราะห์ {symbol}: {e}")

            # อัปเดตตารางข่าวทุก 1 ชม.
            news_counter += 1
            if news_counter >= 12:  # ทุกๆ ~1 ชั่วโมง
                try:
                    self.news_filter.fetch_calendar()
                except Exception as e:
                    logger.warning(f"รีเฟรชข่าวล้มเหลว: {e}")
                news_counter = 0

            await asyncio.sleep(settings.POLL_INTERVAL_SECONDS)

# ── เริ่มวิเคราะห์สัญญาณแบบเป็น Background Task ──────────────────
engine = ForexEngineTask()

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(engine.run_loop())

@app.on_event("shutdown")
def shutdown_event():
    engine.is_running = False
    engine.fetcher.disconnect()

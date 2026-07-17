"""
Forex Signal Alert System (ไม่ต้องใช้ MT5)
==========================================
โหมดแจ้งเตือนอย่างเดียว — ไม่มีการส่งออเดอร์อัตโนมัติ
ดึงราคาจาก Twelve Data API → วิเคราะห์ → แจ้งเตือนผ่าน Telegram

วิธีรัน:
    python main_alert.py
"""
import asyncio
import signal
import sys

from config import settings
from core.logger import get_logger
from core.api_fetcher import APIFetcher, APIConnectionError
from core.mtf_analyzer import MTFAnalyzer
from core.entry_signal import EntrySignalEngine
from core.news_filter import NewsFilter
from core import database
from bot.alert_bot import ForexAlertBot

logger = get_logger("main_alert")


class ForexAlertSystem:
    def __init__(self):
        self.fetcher = APIFetcher()
        self.analyzer = MTFAnalyzer()
        self.entry_engine = EntrySignalEngine()
        self.news_filter = NewsFilter()
        self.bot = ForexAlertBot()
        self._running = False

    async def process_symbol(self, symbol: str):
        try:
            candles_by_tf = self.fetcher.get_all_timeframes(symbol)
            if not candles_by_tf:
                logger.warning(f"{symbol}: ดึงข้อมูลไม่ได้")
                return

            # ── ชั้น 1: Trend Bias จากหลาย timeframe ──
            result = self.analyzer.analyze(symbol, candles_by_tf)
            database.log_signal(symbol, result.overall_direction, result.confidence, "; ".join(result.reasons))

            if result.overall_direction == "HOLD" or result.confidence < settings.CONFIDENCE_THRESHOLD_ALERT:
                logger.info(f"{symbol}: ยังไม่มีสัญญาณ (confidence={result.confidence:.2f})")
                return

            # ── กรองข่าว ──
            base_currency = symbol[:3]
            if self.news_filter.is_blackout(base_currency):
                logger.info(f"{symbol}: อยู่ในช่วง news blackout — ข้ามสัญญาณนี้")
                return

            # ── ชั้น 2: Entry Trigger ──
            entry_tf_df = candles_by_tf.get(settings.ENTRY_TIMEFRAME)
            if entry_tf_df is None:
                return

            entry_tf_analysis = result.per_timeframe.get(settings.ENTRY_TIMEFRAME)
            atr_for_entry = entry_tf_analysis.atr_value if entry_tf_analysis else 0.0

            entry_signal = self.entry_engine.evaluate(
                symbol, result.overall_direction, entry_tf_df, atr_for_entry
            )

            if entry_signal is None or not entry_signal.is_valid_entry:
                logger.info(
                    f"{symbol}: trend {result.overall_direction} แต่ยังไม่ถึงจังหวะเข้า "
                    f"(entry_score={entry_signal.entry_score if entry_signal else 0:.2f})"
                )
                return

            # ── ส่งแจ้งเตือน Telegram (แจ้งเตือนเฉยๆ ไม่มีปุ่มกด) ──
            chart_df = candles_by_tf.get("H1")
            await self.bot.send_signal_alert(result, chart_df, entry_signal=entry_signal)
            logger.info(f"✅ ส่งสัญญาณ {symbol} {result.overall_direction} ไปยัง Telegram แล้ว")

        except Exception:
            logger.exception(f"เกิดข้อผิดพลาดตอนประมวลผล {symbol}")

    async def main_loop(self):
        self._running = True
        # รีเฟรช news calendar ทุกชั่วโมง
        news_refresh_count = 0

        while self._running:
            if not self.bot.is_paused():
                for symbol in settings.SYMBOLS:
                    if not self._running:
                        break
                    await self.process_symbol(symbol)

            news_refresh_count += 1
            if news_refresh_count >= 720:  # ทุก ~1 ชั่วโมง (720 × 5 วินาที)
                self.news_filter.fetch_calendar()
                news_refresh_count = 0

            await asyncio.sleep(settings.POLL_INTERVAL_SECONDS)

    async def start(self):
        database.init_db()
        try:
            self.fetcher.connect()
        except APIConnectionError as e:
            logger.error(f"เชื่อมต่อ API ไม่สำเร็จ: {e}")
            sys.exit(1)

        self.news_filter.fetch_calendar()
        await self.bot.run()
        await self.bot.send_text(
            "🚀 Forex Alert System เริ่มทำงานแล้ว!\n"
            f"📊 ติดตามคู่เงิน: {', '.join(settings.SYMBOLS)}\n"
            f"⏱ วิเคราะห์ทุก {settings.POLL_INTERVAL_SECONDS} วินาที\n"
            "📌 โหมด: แจ้งเตือนอย่างเดียว (ไม่มีการเปิดออเดอร์อัตโนมัติ)"
        )
        logger.info("เริ่ม main loop")
        await self.main_loop()

    async def stop(self):
        self._running = False
        self.fetcher.disconnect()
        await self.bot.stop()
        logger.info("ระบบหยุดทำงานเรียบร้อย")


async def run():
    system = ForexAlertSystem()

    def handle_sigint(sig, frame):
        logger.info("ได้รับสัญญาณหยุดระบบ...")
        asyncio.create_task(system.stop())

    signal.signal(signal.SIGINT, handle_sigint)
    await system.start()


if __name__ == "__main__":
    asyncio.run(run())

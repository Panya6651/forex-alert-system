"""
Forex Signal Alert — LINE Notify Version
=========================================
ดึงราคาจาก Twelve Data API → วิเคราะห์ → แจ้งเตือนผ่าน LINE
ไม่ต้องใช้ MT5 ไม่ต้องเปิดคอม — รันบน Cloud ได้เลย

วิธีรัน:
    python main_line.py
"""
import asyncio
import io
import signal
import sys
import time

import matplotlib
matplotlib.use("Agg")
import mplfinance as mpf

from config import settings
from core.logger import get_logger
from core.api_fetcher import APIFetcher, APIConnectionError
from core.mtf_analyzer import MTFAnalyzer
from core.entry_signal import EntrySignalEngine
from core.news_filter import NewsFilter
from core import database
from bot.line_notify import LineNotify

logger = get_logger("main_line")


def render_chart(symbol: str, df) -> io.BytesIO:
    """วาดกราฟแท่งเทียนส่ง LINE"""
    buf = io.BytesIO()
    try:
        mpf.plot(
            df.tail(60),
            type="candle",
            style="charles",
            title=f"{symbol} - H1",
            volume=False,
            savefig=dict(fname=buf, dpi=100, bbox_inches="tight"),
        )
        buf.seek(0)
    except Exception as e:
        logger.warning(f"วาดกราฟไม่สำเร็จ: {e}")
        buf = None
    return buf


def send_signal_to_line(line: LineNotify, result, entry_signal=None, chart_df=None):
    """ส่งสัญญาณเทรดไปยัง LINE"""
    direction_emoji = "🟢" if result.overall_direction == "BUY" else "🔴"

    msg = (
        f"\n{direction_emoji} สัญญาณ {result.overall_direction}\n"
        f"💱 คู่เงิน: {result.symbol}\n"
        f"📊 ความมั่นใจ: {result.confidence * 100:.1f}%\n"
    )

    if entry_signal is not None:
        msg += (
            f"\n🎯 จุดเข้า (Entry)\n"
            f"• Entry: {entry_signal.entry_price:.5f}\n"
            f"• SL แนะนำ: {entry_signal.suggested_stop:.5f}\n"
            f"• Entry Score: {entry_signal.entry_score * 100:.0f}%\n"
        )
        if entry_signal.triggers:
            msg += "\n✅ เงื่อนไขที่ผ่าน:\n"
            msg += "\n".join(f"  • {t}" for t in entry_signal.triggers)
        if entry_signal.warnings:
            msg += "\n\n⚠️ ข้อควรระวัง:\n"
            msg += "\n".join(f"  • {w}" for w in entry_signal.warnings)

    msg += "\n\n📈 Trend:\n"
    msg += "\n".join(f"  • {r}" for r in result.reasons[:4])
    msg += "\n\n💡 ดูกราฟใน MT5 แล้วตัดสินใจเองได้เลย"

    # ส่งพร้อมกราฟถ้ามี
    if chart_df is not None:
        chart_buf = render_chart(result.symbol, chart_df)
        if chart_buf:
            line.send_image(msg, chart_buf)
            return

    line.send_text(msg)


class ForexLineAlertSystem:
    def __init__(self):
        self.fetcher = APIFetcher()
        self.analyzer = MTFAnalyzer()
        self.entry_engine = EntrySignalEngine()
        self.news_filter = NewsFilter()
        self.line = LineNotify(token=settings.LINE_NOTIFY_TOKEN)
        self._running = False

    def process_symbol(self, symbol: str):
        try:
            candles_by_tf = self.fetcher.get_all_timeframes(symbol)
            if not candles_by_tf:
                logger.warning(f"{symbol}: ดึงข้อมูลไม่ได้")
                return

            result = self.analyzer.analyze(symbol, candles_by_tf)
            database.log_signal(
                symbol, result.overall_direction,
                result.confidence, "; ".join(result.reasons)
            )

            if result.overall_direction == "HOLD" or result.confidence < settings.CONFIDENCE_THRESHOLD_ALERT:
                logger.info(f"{symbol}: ยังไม่มีสัญญาณ (confidence={result.confidence:.2f})")
                return

            base_currency = symbol[:3]
            if self.news_filter.is_blackout(base_currency):
                logger.info(f"{symbol}: อยู่ในช่วง news blackout")
                return

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
                    f"{symbol}: trend ถูก แต่ยังไม่ถึงจังหวะ "
                    f"(score={entry_signal.entry_score if entry_signal else 0:.2f})"
                )
                return

            chart_df = candles_by_tf.get("H1")
            send_signal_to_line(self.line, result, entry_signal, chart_df)
            logger.info(f"✅ ส่งสัญญาณ {symbol} {result.overall_direction} ไป LINE แล้ว")

        except Exception:
            logger.exception(f"เกิดข้อผิดพลาดตอนประมวลผล {symbol}")

    def run(self):
        database.init_db()

        try:
            self.fetcher.connect()
        except APIConnectionError as e:
            logger.error(f"เชื่อมต่อ API ไม่สำเร็จ: {e}")
            sys.exit(1)

        self.news_filter.fetch_calendar()
        self._running = True

        self.line.send_text(
            "\n🚀 Forex Alert System เริ่มทำงานแล้ว!\n"
            f"📊 ติดตาม: {', '.join(settings.SYMBOLS)}\n"
            "📌 โหมด: แจ้งเตือน LINE อย่างเดียว\n"
            "✅ ไม่มีการเปิดออเดอร์อัตโนมัติ"
        )
        logger.info("เริ่ม main loop (LINE Notify mode)")

        news_tick = 0
        while self._running:
            for symbol in settings.SYMBOLS:
                if not self._running:
                    break
                self.process_symbol(symbol)

            # รีเฟรช news calendar ทุก ~1 ชั่วโมง
            news_tick += 1
            if news_tick >= 60:
                self.news_filter.fetch_calendar()
                news_tick = 0

            logger.info(f"รอ {settings.POLL_INTERVAL_SECONDS} วินาทีก่อนรอบถัดไป...")
            time.sleep(settings.POLL_INTERVAL_SECONDS)

    def stop(self):
        self._running = False
        self.fetcher.disconnect()
        self.line.send_text("\n⛔ Forex Alert System หยุดทำงานแล้ว")
        logger.info("ระบบหยุดทำงาน")


def main():
    system = ForexLineAlertSystem()

    def handle_sigint(sig, frame):
        logger.info("ได้รับสัญญาณหยุดระบบ...")
        system.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_sigint)
    system.run()


if __name__ == "__main__":
    main()

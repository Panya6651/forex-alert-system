"""
Main Orchestrator
=================
รวมทุกโมดูลเข้าด้วยกัน: ดึงข้อมูล → วิเคราะห์ → กรองข่าว → ตัดสินใจ → แจ้งเตือน/ส่งออเดอร์
รันแบบ async loop ต่อเนื่อง

วิธีรัน:
    python main.py

ต้องตั้งค่า environment variables ก่อน (ดู .env.example)
"""
import asyncio
import signal
import sys
from datetime import datetime

from config import settings
from core.logger import get_logger
from core.data_fetcher import DataFetcher, MT5ConnectionError
from core.mtf_analyzer import MTFAnalyzer
from core.entry_signal import EntrySignalEngine
from core.news_filter import NewsFilter
from core.risk_manager import RiskManager
from core.order_executor import OrderExecutor, OrderExecutionError
from core import database
from bot.telegram_bot import ForexTelegramBot

logger = get_logger("main")


class ForexSystem:
    def __init__(self):
        self.fetcher = DataFetcher()
        self.analyzer = MTFAnalyzer()
        self.entry_engine = EntrySignalEngine()
        self.news_filter = NewsFilter()
        self.risk_manager = RiskManager()
        self.executor = OrderExecutor()
        self.bot = ForexTelegramBot(on_confirm=self.handle_confirm, on_reject=self.handle_reject)
        self._pending_signals = {}  # (symbol, direction) -> ConfluenceResult + candles
        self._running = False

    async def handle_confirm(self, symbol: str, direction: str):
        key = (symbol, direction)
        payload = self._pending_signals.pop(key, None)
        if not payload:
            logger.warning(f"ไม่พบสัญญาณค้างสำหรับ {key}")
            return
        await self._execute_trade(payload["result"], payload["candles"], payload["entry_signal"])

    async def handle_reject(self, symbol: str, direction: str):
        self._pending_signals.pop((symbol, direction), None)
        logger.info(f"ผู้ใช้ปฏิเสธสัญญาณ {symbol} {direction}")

    async def _execute_trade(self, result, candles_by_tf, entry_signal=None):
        try:
            account = self.fetcher.get_account_info()
            if account is None:
                await self.bot.send_text("⚠️ ดึงข้อมูลบัญชีไม่สำเร็จ ยกเลิกการเข้าออเดอร์")
                return

            if not self.risk_manager.check_daily_drawdown_ok(account["equity"]):
                await self.bot.send_text("🛑 หยุดเทรดวันนี้: เกิน max daily drawdown")
                return

            open_positions = self.executor.get_open_positions(result.symbol)
            if not self.risk_manager.check_concurrent_trades_ok(len(open_positions)):
                await self.bot.send_text(f"⚠️ {result.symbol}: เต็มจำนวน concurrent trades สูงสุด")
                return

            tick = self.fetcher.get_current_tick(result.symbol)
            if tick is None or not self.risk_manager.check_spread_ok(tick["spread_points"]):
                await self.bot.send_text(f"⚠️ {result.symbol}: spread กว้างเกินไป ยกเลิกการเข้าออเดอร์")
                return

            entry_price = tick["ask"] if result.overall_direction == "BUY" else tick["bid"]
            atr_val = result.per_timeframe.get("H1", list(result.per_timeframe.values())[0]).atr_value

            # ใช้ suggested_stop จาก entry signal (อิงโครงสร้างราคาจริง) ถ้ามี แม่นยำกว่า ATR อย่างเดียว
            custom_stop = entry_signal.suggested_stop if entry_signal else None

            plan = self.risk_manager.calculate_position(
                symbol=result.symbol,
                direction=result.overall_direction,
                entry_price=entry_price,
                atr_value=atr_val,
                account_equity=account["equity"],
                custom_stop_loss=custom_stop,
            )

            order_result = self.executor.send_market_order(plan)
            database.log_trade_open(
                ticket=order_result["ticket"], symbol=plan.symbol, direction=plan.direction,
                lot_size=plan.lot_size, entry_price=plan.entry_price,
                stop_loss=plan.stop_loss, take_profit=plan.take_profit,
            )
            await self.bot.send_text(
                f"✅ เข้าออเดอร์สำเร็จ: {plan.symbol} {plan.direction} {plan.lot_size} lot\n"
                f"Entry: {plan.entry_price} | SL: {plan.stop_loss} | TP: {plan.take_profit}"
            )
        except OrderExecutionError as e:
            logger.error(f"เข้าออเดอร์ล้มเหลว: {e}")
            await self.bot.send_text(f"❌ เข้าออเดอร์ล้มเหลว: {e}")
        except Exception as e:
            logger.exception("เกิดข้อผิดพลาดไม่คาดคิดตอนเข้าออเดอร์")
            await self.bot.send_text(f"❌ เกิดข้อผิดพลาด: {e}")

    async def process_symbol(self, symbol: str):
        try:
            self.fetcher.ensure_symbol(symbol)
            candles_by_tf = self.fetcher.get_all_timeframes(symbol)
            if not candles_by_tf:
                return

            # ── ชั้น 1: Trend Bias จากหลาย timeframe ──
            result = self.analyzer.analyze(symbol, candles_by_tf)
            database.log_signal(symbol, result.overall_direction, result.confidence, "; ".join(result.reasons))

            if result.overall_direction == "HOLD" or result.confidence < settings.CONFIDENCE_THRESHOLD_ALERT:
                return

            base_currency = symbol[:3]
            if self.news_filter.is_blackout(base_currency):
                logger.info(f"{symbol}: อยู่ในช่วง news blackout — ข้ามสัญญาณนี้")
                return

            # ── ชั้น 2: Entry Trigger — หาจังหวะเข้าจริงบน timeframe ย่อย ──
            entry_tf_df = candles_by_tf.get(settings.ENTRY_TIMEFRAME)
            if entry_tf_df is None:
                logger.warning(f"{symbol}: ไม่มีข้อมูล {settings.ENTRY_TIMEFRAME} สำหรับประเมิน entry")
                return

            entry_tf_analysis = result.per_timeframe.get(settings.ENTRY_TIMEFRAME)
            atr_for_entry = entry_tf_analysis.atr_value if entry_tf_analysis else 0.0

            entry_signal = self.entry_engine.evaluate(
                symbol, result.overall_direction, entry_tf_df, atr_for_entry
            )

            if entry_signal is None or not entry_signal.is_valid_entry:
                logger.info(
                    f"{symbol}: มี trend bias {result.overall_direction} แต่ยังไม่ผ่านเงื่อนไข entry "
                    f"(score={entry_signal.entry_score if entry_signal else 0:.2f}) — รอจังหวะดีกว่านี้"
                )
                return

            chart_df = candles_by_tf.get("H1")

            if settings.AUTO_TRADE_ENABLED and result.confidence >= settings.CONFIDENCE_THRESHOLD_AUTO:
                await self.bot.send_signal_alert(result, chart_df, require_confirm=False, entry_signal=entry_signal)
                await self._execute_trade(result, candles_by_tf, entry_signal)
            else:
                self._pending_signals[(symbol, result.overall_direction)] = {
                    "result": result, "candles": candles_by_tf, "entry_signal": entry_signal,
                }
                await self.bot.send_signal_alert(result, chart_df, require_confirm=True, entry_signal=entry_signal)

        except Exception as e:
            logger.exception(f"เกิดข้อผิดพลาดตอนประมวลผล {symbol}")

    async def main_loop(self):
        self._running = True
        while self._running:
            if not self.bot.is_paused():
                for symbol in settings.SYMBOLS:
                    await self.process_symbol(symbol)
            await asyncio.sleep(settings.POLL_INTERVAL_SECONDS)

    async def start(self):
        database.init_db()
        try:
            self.fetcher.connect()
        except MT5ConnectionError as e:
            logger.error(f"เชื่อมต่อ MT5 ไม่สำเร็จ: {e}")
            sys.exit(1)

        self.news_filter.fetch_calendar()
        await self.bot.run()
        await self.bot.send_text("🚀 ระบบเริ่มทำงานแล้ว")
        logger.info("เริ่ม main loop")
        await self.main_loop()

    async def stop(self):
        self._running = False
        self.fetcher.disconnect()
        await self.bot.stop()
        logger.info("ระบบหยุดทำงานเรียบร้อย")


async def run():
    system = ForexSystem()

    def handle_sigint(sig, frame):
        logger.info("ได้รับสัญญาณหยุดระบบ...")
        asyncio.create_task(system.stop())

    signal.signal(signal.SIGINT, handle_sigint)
    await system.start()


if __name__ == "__main__":
    asyncio.run(run())

"""
Telegram Bot
============
แจ้งเตือนสัญญาณเทรด + ปุ่มยืนยัน/ปฏิเสธ + คำสั่งควบคุมระบบพื้นฐาน
ใช้ python-telegram-bot (v20+, async)
"""
import io
from typing import Callable, Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import mplfinance as mpf
import pandas as pd

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes,
)

from config import settings
from core.logger import get_logger
from core.mtf_analyzer import ConfluenceResult

logger = get_logger(__name__)


class ForexTelegramBot:
    def __init__(self, on_confirm: Optional[Callable] = None, on_reject: Optional[Callable] = None):
        self.app = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()
        self.on_confirm = on_confirm
        self.on_reject = on_reject
        self._paused = False
        self._register_handlers()

    def _register_handlers(self):
        self.app.add_handler(CommandHandler("start", self.cmd_start))
        self.app.add_handler(CommandHandler("status", self.cmd_status))
        self.app.add_handler(CommandHandler("pause", self.cmd_pause))
        self.app.add_handler(CommandHandler("resume", self.cmd_resume))
        self.app.add_handler(CommandHandler("positions", self.cmd_positions))
        self.app.add_handler(CallbackQueryHandler(self.handle_button))

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "ระบบ Forex Signal Bot พร้อมทำงาน\n"
            "/status - สถานะระบบ\n"
            "/positions - ออเดอร์ที่เปิดอยู่\n"
            "/pause - หยุดส่งสัญญาณชั่วคราว\n"
            "/resume - เปิดใช้งานต่อ"
        )

    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        state = "หยุดชั่วคราว" if self._paused else "ทำงานปกติ"
        mode = "AUTO TRADE" if settings.AUTO_TRADE_ENABLED else "MANUAL CONFIRM"
        await update.message.reply_text(f"สถานะ: {state}\nโหมด: {mode}")

    async def cmd_pause(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self._paused = True
        await update.message.reply_text("หยุดส่งสัญญาณชั่วคราวแล้ว")

    async def cmd_resume(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self._paused = False
        await update.message.reply_text("เปิดใช้งานระบบต่อแล้ว")

    async def cmd_positions(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        # ผูกกับ OrderExecutor.get_open_positions() จาก main orchestrator
        await update.message.reply_text("ฟังก์ชันนี้ต้องเชื่อมกับ order_executor ใน main.py")

    async def handle_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        data = query.data  # format: "confirm:SYMBOL:DIRECTION" หรือ "reject:SYMBOL:DIRECTION"
        action, symbol, direction = data.split(":")

        if action == "confirm" and self.on_confirm:
            await self.on_confirm(symbol, direction)
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text(f"✅ ยืนยันเข้าออเดอร์ {symbol} {direction} แล้ว")
        elif action == "reject" and self.on_reject:
            await self.on_reject(symbol, direction)
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text(f"❌ ปฏิเสธสัญญาณ {symbol} {direction}")

    def is_paused(self) -> bool:
        return self._paused

    def _render_chart(self, symbol: str, df: pd.DataFrame) -> io.BytesIO:
        buf = io.BytesIO()
        mpf.plot(
            df.tail(80),
            type="candle",
            style="charles",
            title=symbol,
            volume=False,
            savefig=dict(fname=buf, dpi=100, bbox_inches="tight"),
        )
        buf.seek(0)
        return buf

    async def send_signal_alert(self, result: ConfluenceResult, chart_df: Optional[pd.DataFrame] = None,
                                 require_confirm: bool = True, entry_signal=None):
        text = (
            f"📊 สัญญาณ: {result.symbol}\n"
            f"ทิศทาง: {result.overall_direction}\n"
            f"ความมั่นใจ (Trend Bias): {result.confidence * 100:.1f}%\n"
        )

        if entry_signal is not None:
            text += (
                f"ความแม่นยำจุดเข้า (Entry Score): {entry_signal.entry_score * 100:.0f}%\n"
                f"Entry: {entry_signal.entry_price:.5f} | SL แนะนำ: {entry_signal.suggested_stop:.5f}\n"
                f"\n✅ เงื่อนไขที่ผ่าน:\n" + "\n".join(f"• {t}" for t in entry_signal.triggers)
            )
            if entry_signal.warnings:
                text += "\n\n⚠️ ข้อควรระวัง:\n" + "\n".join(f"• {w}" for w in entry_signal.warnings)

        text += "\n\n📈 บริบท Trend Bias:\n" + "\n".join(f"• {r}" for r in result.reasons[:6])

        keyboard = None
        if require_confirm and result.overall_direction in ("BUY", "SELL"):
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ ยืนยันเข้าออเดอร์", callback_data=f"confirm:{result.symbol}:{result.overall_direction}"),
                InlineKeyboardButton("❌ ไม่เอา", callback_data=f"reject:{result.symbol}:{result.overall_direction}"),
            ]])

        for chat_id in settings.TELEGRAM_CHAT_IDS:
            if chart_df is not None:
                try:
                    img = self._render_chart(result.symbol, chart_df)
                    await self.app.bot.send_photo(chat_id=chat_id, photo=img, caption=text, reply_markup=keyboard)
                    continue
                except Exception as e:
                    logger.warning(f"สร้างกราฟไม่สำเร็จ: {e} — ส่งเป็นข้อความแทน")
            await self.app.bot.send_message(chat_id=chat_id, text=text, reply_markup=keyboard)

    async def send_text(self, text: str):
        for chat_id in settings.TELEGRAM_CHAT_IDS:
            await self.app.bot.send_message(chat_id=chat_id, text=text)

    async def run(self):
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling()
        logger.info("Telegram bot เริ่มทำงานแล้ว")

    async def stop(self):
        await self.app.updater.stop()
        await self.app.stop()
        await self.app.shutdown()

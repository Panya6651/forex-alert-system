"""
Forex Alert Bot (แจ้งเตือนเฉยๆ ไม่มีปุ่มกด)
==============================================
ส่งสัญญาณ BUY/SELL พร้อมราคา Entry, SL, TP ไปยัง Telegram
ผู้ใช้ดูสัญญาณแล้วตัดสินใจเองว่าจะกดตามใน MT5 มือถือหรือไม่
"""
import io
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import mplfinance as mpf
import pandas as pd

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from config import settings
from core.logger import get_logger
from core.mtf_analyzer import ConfluenceResult

logger = get_logger(__name__)


class ForexAlertBot:
    def __init__(self):
        self.app = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()
        self._paused = False
        self._register_handlers()

    def _register_handlers(self):
        self.app.add_handler(CommandHandler("start", self.cmd_start))
        self.app.add_handler(CommandHandler("status", self.cmd_status))
        self.app.add_handler(CommandHandler("pause", self.cmd_pause))
        self.app.add_handler(CommandHandler("resume", self.cmd_resume))
        self.app.add_handler(CommandHandler("symbols", self.cmd_symbols))

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "🤖 Forex Signal Alert Bot พร้อมทำงาน!\n\n"
            "📌 โหมด: แจ้งเตือนสัญญาณเฉยๆ\n"
            "💡 ดูสัญญาณแล้วตัดสินใจเองใน MT5\n\n"
            "คำสั่ง:\n"
            "/status — สถานะระบบ\n"
            "/symbols — คู่เงินที่ติดตาม\n"
            "/pause — หยุดส่งสัญญาณชั่วคราว\n"
            "/resume — เปิดใช้งานต่อ"
        )

    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        state = "⏸ หยุดชั่วคราว" if self._paused else "✅ ทำงานปกติ"
        await update.message.reply_text(
            f"สถานะ: {state}\n"
            f"โหมด: แจ้งเตือนอย่างเดียว\n"
            f"คู่เงิน: {', '.join(settings.SYMBOLS)}"
        )

    async def cmd_pause(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self._paused = True
        await update.message.reply_text("⏸ หยุดส่งสัญญาณชั่วคราวแล้ว")

    async def cmd_resume(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self._paused = False
        await update.message.reply_text("▶️ เปิดใช้งานต่อแล้ว")

    async def cmd_symbols(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "📊 คู่เงินที่ติดตาม:\n" + "\n".join(f"• {s}" for s in settings.SYMBOLS)
        )

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

    async def send_signal_alert(
        self,
        result: ConfluenceResult,
        chart_df: Optional[pd.DataFrame] = None,
        entry_signal=None,
    ):
        """ส่งสัญญาณแจ้งเตือน ไม่มีปุ่มกด — ผู้ใช้ตัดสินใจเองใน MT5"""
        direction_emoji = "🟢" if result.overall_direction == "BUY" else "🔴"

        text = (
            f"{direction_emoji} *สัญญาณ {result.overall_direction}*\n"
            f"💱 คู่เงิน: `{result.symbol}`\n"
            f"📊 ความมั่นใจ: `{result.confidence * 100:.1f}%`\n"
        )

        if entry_signal is not None:
            text += (
                f"\n🎯 *จุดเข้า (Entry)*\n"
                f"• Entry: `{entry_signal.entry_price:.5f}`\n"
                f"• SL แนะนำ: `{entry_signal.suggested_stop:.5f}`\n"
                f"• Entry Score: `{entry_signal.entry_score * 100:.0f}%`\n"
            )

            if entry_signal.triggers:
                text += "\n✅ *เงื่อนไขที่ผ่าน:*\n"
                text += "\n".join(f"  • {t}" for t in entry_signal.triggers)

            if entry_signal.warnings:
                text += "\n\n⚠️ *ข้อควรระวัง:*\n"
                text += "\n".join(f"  • {w}" for w in entry_signal.warnings)

        text += "\n\n📈 *บริบท Trend:*\n"
        text += "\n".join(f"  • {r}" for r in result.reasons[:5])

        text += "\n\n💡 _ดูกราฟใน MT5 แล้วตัดสินใจเองได้เลย_"

        for chat_id in settings.TELEGRAM_CHAT_IDS:
            if chart_df is not None:
                try:
                    img = self._render_chart(result.symbol, chart_df)
                    await self.app.bot.send_photo(
                        chat_id=chat_id,
                        photo=img,
                        caption=text,
                        parse_mode="Markdown",
                    )
                    continue
                except Exception as e:
                    logger.warning(f"สร้างกราฟไม่สำเร็จ: {e} — ส่งเป็นข้อความแทน")
            await self.app.bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode="Markdown",
            )

    async def send_text(self, text: str):
        for chat_id in settings.TELEGRAM_CHAT_IDS:
            await self.app.bot.send_message(chat_id=chat_id, text=text)

    async def run(self):
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling()
        logger.info("Forex Alert Bot เริ่มทำงานแล้ว")

    async def stop(self):
        await self.app.updater.stop()
        await self.app.stop()
        await self.app.shutdown()

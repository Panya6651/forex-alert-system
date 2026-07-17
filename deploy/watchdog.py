"""
Watchdog
========
เช็คว่าไฟล์ log ของระบบหลักมีการอัปเดตล่าสุดเมื่อไหร่ ถ้าเงียบนานเกินไป
(เช่น โปรแกรมค้าง, MT5 หลุด, เครื่อง Windows ปิดตัว) จะส่งข้อความเตือนผ่าน Telegram

แนะนำให้ตั้ง Task Scheduler รันสคริปต์นี้แยกทุก 5-10 นาที เป็นอิสระจาก service หลัก
เพื่อให้ยังแจ้งเตือนได้แม้ service หลัก crash ไปแล้วจริงๆ
"""
import os
import sys
import time
from datetime import datetime, timedelta

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import settings

STALE_THRESHOLD_MINUTES = 15
LOG_FILE = os.path.join(settings.LOG_DIR, "system.log")


def send_telegram_alert(text: str) -> None:
    if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_IDS:
        print("ไม่มีการตั้งค่า Telegram — ข้ามการแจ้งเตือน")
        return
    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
    for chat_id in settings.TELEGRAM_CHAT_IDS:
        try:
            requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=10)
        except Exception as e:
            print(f"ส่ง Telegram alert ล้มเหลว: {e}")


def check_log_freshness() -> bool:
    if not os.path.exists(LOG_FILE):
        return False
    mtime = datetime.fromtimestamp(os.path.getmtime(LOG_FILE))
    age = datetime.now() - mtime
    return age <= timedelta(minutes=STALE_THRESHOLD_MINUTES)


def main():
    if check_log_freshness():
        print(f"[{datetime.now()}] ระบบทำงานปกติ")
        sys.exit(0)
    else:
        msg = (
            f"🚨 WATCHDOG ALERT 🚨\n"
            f"ไม่มีการอัปเดต log จากระบบหลักเกิน {STALE_THRESHOLD_MINUTES} นาที\n"
            f"กรุณาตรวจสอบ: Windows Service ยังทำงานอยู่ไหม / MT5 terminal ยังเปิดอยู่ไหม"
        )
        print(msg)
        send_telegram_alert(msg)
        sys.exit(1)


if __name__ == "__main__":
    main()

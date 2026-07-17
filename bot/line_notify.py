"""
LINE Notify Sender
==================
ส่งแจ้งเตือนสัญญาณเทรดผ่าน LINE Notify (ฟรี)
ลงทะเบียนรับ Token ที่: https://notify-bot.line.me/my/

วิธีใช้:
    notifier = LineNotify(token="YOUR_TOKEN")
    notifier.send_text("ข้อความ")
    notifier.send_image("ข้อความ", image_bytes)
"""
import io
from typing import Optional

import requests

from core.logger import get_logger

logger = get_logger(__name__)

LINE_NOTIFY_URL = "https://notify-api.line.me/api/notify"


class LineNotify:
    def __init__(self, token: str):
        if not token:
            raise ValueError(
                "ไม่พบ LINE_NOTIFY_TOKEN — สมัครฟรีที่ https://notify-bot.line.me/my/"
            )
        self.token = token
        self.headers = {"Authorization": f"Bearer {token}"}

    def send_text(self, message: str) -> bool:
        """ส่งข้อความ"""
        try:
            resp = requests.post(
                LINE_NOTIFY_URL,
                headers=self.headers,
                data={"message": message},
                timeout=10,
            )
            if resp.status_code == 200:
                return True
            logger.error(f"LINE Notify error: {resp.status_code} {resp.text}")
            return False
        except Exception as e:
            logger.error(f"ส่ง LINE Notify ไม่สำเร็จ: {e}")
            return False

    def send_image(self, message: str, image_bytes: io.BytesIO) -> bool:
        """ส่งข้อความพร้อมรูปภาพ (กราฟแท่งเทียน)"""
        try:
            image_bytes.seek(0)
            resp = requests.post(
                LINE_NOTIFY_URL,
                headers=self.headers,
                data={"message": message},
                files={"imageFile": ("chart.png", image_bytes, "image/png")},
                timeout=15,
            )
            if resp.status_code == 200:
                return True
            logger.error(f"LINE Notify (image) error: {resp.status_code} {resp.text}")
            return False
        except Exception as e:
            logger.error(f"ส่งรูป LINE Notify ไม่สำเร็จ: {e}")
            return False

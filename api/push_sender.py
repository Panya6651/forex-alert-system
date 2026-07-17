"""
Web Push Notification Sender
============================
ใช้สำหรับส่ง Push Notification ผ่าน Web Push Protocol ไปยังเว็บเบราว์เซอร์บนมือถือหรือคอมพิวเตอร์
"""
import json
from typing import Dict, Any
from pywebpush import webpush, WebPushException
from core.logger import get_logger

logger = get_logger(__name__)

# คีย์ VAPID สำหรับระบุตัวตนของผู้ส่ง (สร้างขึ้นเพื่อใช้กับแอปนี้โดยเฉพาะ)
VAPID_PUBLIC_KEY = "BCPDkLzeFQuNyA8RWFILxETP71Tn3nBnK-J7WbUCKSax58yTB1-w1wvzJeSFsS76h5hKAXdde_XICrBKR2bhaRM="
# Private key ที่ถอดรหัสออกมาจาก base64 ด้านบน
VAPID_PRIVATE_KEY_PEM = (
    "-----BEGIN PRIVATE KEY-----\n"
    "MIGHAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBG0wawIBAQQg+bQ2rSCmuN0IHMCb\n"
    "UrGqQXeeBRLTkyVd1Vk1TJza+YmhRANDAQAQjw5C83hULjcgPEVhSC8REz+9U595\n"
    "wZyvie1m1AikmsefMkwdfsNcL8yXkhbEu+oeYSgF3XXv1yAqwSkdm4WkT\n"
    "-----END PRIVATE KEY-----\n"
)
VAPID_CLAIMS = {
    "sub": "mailto:admin@forexalertapp.com"
}

def send_web_push(subscription_info: Dict[str, Any], data: Dict[str, Any]) -> bool:
    """ส่ง Push Notification ไปยัง Subscriber รายบุคคล"""
    try:
        webpush(
            subscription_info=subscription_info,
            data=json.dumps(data),
            vapid_private_key=VAPID_PRIVATE_KEY_PEM,
            vapid_claims=VAPID_CLAIMS,
            ttl=86400  # เก็บข้อความไว้บน Server สูงสุด 24 ชม. หากอุปกรณ์ปิดอยู่
        )
        return True
    except WebPushException as e:
        logger.warning(f"ส่ง Web Push ไม่สำเร็จ: {e}")
        # โค้ด 410 หรือ 404 แปลว่าสิทธิ์การรับแจ้งเตือนของคนนี้ถูกยกเลิกแล้วหรือหมดอายุ
        if e.response is not None and e.response.status_code in [404, 410]:
            logger.info("Subscription หมดอายุหรือถูกลบออกแล้ว")
        return False
    except Exception as e:
        logger.error(f"เกิดข้อผิดพลาดที่ไม่คาดคิดในการส่ง Web Push: {e}")
        return False

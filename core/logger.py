"""ตั้งค่า logging กลาง ใช้ร่วมกันทุกโมดูล — เขียนลงไฟล์และ console พร้อมกัน"""
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

from config import settings


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:  # ป้องกันการ add handler ซ้ำ
        return logger

    logger.setLevel(logging.INFO)
    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    os.makedirs(settings.LOG_DIR, exist_ok=True)

    file_handler = RotatingFileHandler(
        os.path.join(settings.LOG_DIR, "system.log"),
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(fmt)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    return logger

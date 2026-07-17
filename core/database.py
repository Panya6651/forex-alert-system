"""
Database
========
เก็บประวัติสัญญาณและออเดอร์ลง SQLite เพื่อตรวจสอบย้อนหลัง/ทำสถิติ
"""
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Optional

from config import settings
from core.logger import get_logger

logger = get_logger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL,
    confidence REAL NOT NULL,
    reasons TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket INTEGER,
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL,
    lot_size REAL NOT NULL,
    entry_price REAL NOT NULL,
    stop_loss REAL,
    take_profit REAL,
    status TEXT DEFAULT 'open',
    opened_at TEXT NOT NULL,
    closed_at TEXT,
    pnl REAL
);
"""


@contextmanager
def get_connection():
    import os
    os.makedirs(os.path.dirname(settings.DB_PATH), exist_ok=True)
    conn = sqlite3.connect(settings.DB_PATH)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript(SCHEMA)
    logger.info("Database พร้อมใช้งาน")


def log_signal(symbol: str, direction: str, confidence: float, reasons: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO signals (symbol, direction, confidence, reasons, created_at) VALUES (?, ?, ?, ?, ?)",
            (symbol, direction, confidence, reasons, datetime.utcnow().isoformat()),
        )


def log_trade_open(ticket: int, symbol: str, direction: str, lot_size: float,
                    entry_price: float, stop_loss: float, take_profit: float) -> None:
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO trades (ticket, symbol, direction, lot_size, entry_price, stop_loss, take_profit, opened_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (ticket, symbol, direction, lot_size, entry_price, stop_loss, take_profit, datetime.utcnow().isoformat()),
        )


def log_trade_close(ticket: int, pnl: float) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE trades SET status='closed', closed_at=?, pnl=? WHERE ticket=?",
            (datetime.utcnow().isoformat(), pnl, ticket),
        )

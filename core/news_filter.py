"""
News Filter
===========
ดึง economic calendar และตรวจว่าช่วงเวลาปัจจุบันอยู่ใน "news blackout" หรือไม่
(ป้องกันไม่ให้ระบบเข้าออเดอร์ช่วงข่าวแรงเพราะ spread กว้าง+ราคาแกว่งผิดปกติ)

Provider หลัก: Forex Factory public JSON feed (nfs.faireconomy.media)
  - เป็น endpoint public ที่ widget ปฏิทินของ ForexFactory ใช้เอง ไม่ต้องใช้ API key
  - อัปเดตข้อมูลล่วงหน้าเป็นรายสัปดาห์ (this week / next week)
  - ไม่มี SLA รับประกันความเสถียร จึงมี TradingEconomics เป็น fallback (ต้อง API key)

หากต้องการความเสถียรระดับ production จริงจัง แนะนำสมัคร paid API เช่น
TradingEconomics หรือ Finnhub economic calendar แทน/เสริม เพราะ SLA ชัดเจนกว่า
"""
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional

import requests

from config import settings
from core.logger import get_logger

logger = get_logger(__name__)

FOREX_FACTORY_THIS_WEEK = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
FOREX_FACTORY_NEXT_WEEK = "https://nfs.faireconomy.media/ff_calendar_nextweek.json"

# Forex Factory ใช้คำว่า "High"/"Medium"/"Low" ใน field "impact"
IMPACT_MAP = {"High": "high", "Medium": "medium", "Low": "low", "Holiday": "low"}


@dataclass
class NewsEvent:
    title: str
    currency: str
    impact: str  # "high" | "medium" | "low"
    event_time: datetime


class NewsFilter:
    def __init__(self):
        self._events: List[NewsEvent] = []
        self._last_fetch: Optional[datetime] = None

    def fetch_calendar(self) -> None:
        """ดึง economic calendar สัปดาห์นี้ + สัปดาห์หน้าจาก Forex Factory"""
        events: List[NewsEvent] = []
        for url in (FOREX_FACTORY_THIS_WEEK, FOREX_FACTORY_NEXT_WEEK):
            try:
                events.extend(self._fetch_and_parse(url))
            except Exception as e:
                logger.error(f"ดึง economic calendar จาก {url} ล้มเหลว: {e}")

        if events:
            self._events = events
            self._last_fetch = datetime.utcnow()
            logger.info(f"ดึง economic calendar สำเร็จ: {len(self._events)} events")
        elif settings.ECONOMIC_CALENDAR_SOURCE == "tradingeconomics":
            self._fetch_tradingeconomics_fallback()
        else:
            logger.warning("ดึง economic calendar ไม่สำเร็จเลย — จะไม่มีการกรองข่าวรอบนี้")

    def _fetch_and_parse(self, url: str, retries: int = 2) -> List[NewsEvent]:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://www.forexfactory.com/",
        }
        last_error = None
        for attempt in range(retries + 1):
            try:
                resp = requests.get(url, timeout=10, headers=headers)
                resp.raise_for_status()
                raw = resp.json()
                break
            except Exception as e:
                last_error = e
                if attempt < retries:
                    logger.debug(f"ลองใหม่ครั้งที่ {attempt + 1} สำหรับ {url}")
                    continue
                # หมด retry แล้วยังล้มเหลว — โยน error ออกไปให้ caller จัดการ fallback
                # หมายเหตุสำคัญ: Forex Factory เป็น free/unofficial feed อาจบล็อก IP บาง
                # datacenter หรือเปลี่ยนโครงสร้างได้โดยไม่แจ้งล่วงหน้า สำหรับ production
                # ที่ต้องพึ่งพาความเสถียรสูง แนะนำสมัคร paid provider (TradingEconomics/Finnhub)
                raise last_error

        parsed = []
        for item in raw:
            try:
                impact = IMPACT_MAP.get(item.get("impact", ""), "low")
                # Forex Factory ส่ง field "date" เป็น ISO8601 string พร้อม timezone
                event_time = datetime.fromisoformat(item["date"].replace("Z", "+00:00"))
                event_time = event_time.replace(tzinfo=None)  # เก็บเป็น naive UTC ให้ตรงกับ datetime.utcnow()
                parsed.append(NewsEvent(
                    title=item.get("title", "unknown"),
                    currency=item.get("country", ""),  # field นี้จริงๆ คือ currency code เช่น USD, EUR
                    impact=impact,
                    event_time=event_time,
                ))
            except (KeyError, ValueError) as e:
                logger.debug(f"ข้าม event ที่ parse ไม่ได้: {e}")
                continue
        return parsed

    def _fetch_tradingeconomics_fallback(self) -> None:
        """Fallback provider — ต้องมี TRADINGECONOMICS_API_KEY ตั้งไว้ใน settings/env"""
        api_key = getattr(settings, "TRADINGECONOMICS_API_KEY", "")
        if not api_key:
            logger.warning("ไม่มี TRADINGECONOMICS_API_KEY — ข้าม fallback provider")
            return
        try:
            url = f"https://api.tradingeconomics.com/calendar?c={api_key}"
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            raw = resp.json()
            parsed = []
            for item in raw:
                impact_raw = item.get("Importance", 0)
                impact = "high" if impact_raw >= 3 else ("medium" if impact_raw == 2 else "low")
                event_time = datetime.fromisoformat(item["Date"].replace("Z", ""))
                parsed.append(NewsEvent(
                    title=item.get("Event", "unknown"),
                    currency=item.get("Currency", ""),
                    impact=impact,
                    event_time=event_time,
                ))
            self._events = parsed
            self._last_fetch = datetime.utcnow()
            logger.info(f"ดึง economic calendar จาก TradingEconomics สำเร็จ: {len(parsed)} events")
        except Exception as e:
            logger.error(f"TradingEconomics fallback ล้มเหลว: {e}")

    def is_blackout(self, currency: str, now: Optional[datetime] = None) -> bool:
        """เช็คว่าตอนนี้อยู่ในช่วงห้ามเทรดเพราะข่าวหรือไม่ สำหรับ currency ที่ระบุ"""
        now = now or datetime.utcnow()
        relevant = [
            e for e in self._events
            if e.currency == currency and (not settings.HIGH_IMPACT_ONLY or e.impact == "high")
        ]
        for event in relevant:
            window_start = event.event_time - timedelta(minutes=settings.NEWS_BLACKOUT_MINUTES_BEFORE)
            window_end = event.event_time + timedelta(minutes=settings.NEWS_BLACKOUT_MINUTES_AFTER)
            if window_start <= now <= window_end:
                logger.info(f"อยู่ในช่วง news blackout: {event.title} ({currency})")
                return True
        return False

    def get_upcoming_high_impact(self, currency: str, within_hours: int = 24) -> List[NewsEvent]:
        now = datetime.utcnow()
        cutoff = now + timedelta(hours=within_hours)
        return [
            e for e in self._events
            if e.currency == currency and e.impact == "high" and now <= e.event_time <= cutoff
        ]

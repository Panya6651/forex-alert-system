# Forex Auto-Trading System (MT5 + Telegram)

ระบบวิเคราะห์กราฟหลาย timeframe แจ้งเตือนผ่าน Telegram และเข้าออเดอร์อัตโนมัติผ่าน MetaTrader 5

## โครงสร้างโปรเจกต์

```
forex_system/
├── main.py                 # จุดเริ่มรันระบบทั้งหมด
├── requirements.txt
├── .env.example             # ตัวอย่างไฟล์ตั้งค่า credentials
├── config/
│   └── settings.py          # ค่าตั้งค่าทั้งหมด (symbol, risk, threshold ฯลฯ)
├── core/
│   ├── data_fetcher.py       # เชื่อมต่อ MT5 ดึงราคา
│   ├── mtf_analyzer.py        # วิเคราะห์ indicator หลาย timeframe
│   ├── news_filter.py         # กรองช่วงข่าวแรง (blackout)
│   ├── risk_manager.py        # คำนวณ lot size / SL / TP
│   ├── order_executor.py      # ส่งออเดอร์เข้า MT5
│   ├── database.py            # เก็บ log สัญญาณ/ออเดอร์ (SQLite)
│   └── logger.py              # logging กลาง
└── bot/
    └── telegram_bot.py         # แจ้งเตือน + ปุ่มยืนยัน + คำสั่งควบคุม
```

## ข้อกำหนดระบบ (สำคัญ)

- **ต้องรันบน Windows** (หรือ Windows VPS) เพราะ `MetaTrader5` Python package ผูกกับ MT5 terminal โดยตรง ใช้บน Linux/Mac ไม่ได้ยกเว้นผ่าน Wine (ไม่แนะนำสำหรับ production)
- ต้องติดตั้ง MT5 terminal และ login บัญชีไว้ก่อนรันสคริปต์
- Python 3.10+

## การติดตั้ง

```bash
pip install -r requirements.txt
cp .env.example .env
# แก้ไข .env ใส่ค่า MT5 login, Telegram token, chat id จริง
python main.py
```

## การตั้งค่าที่ควรปรับก่อนใช้งานจริง

เปิดไฟล์ `config/settings.py`:

| ตัวแปร | ความหมาย |
|---|---|
| `SYMBOLS` | รายชื่อคู่เงินที่ต้องการติดตาม |
| `AUTO_TRADE_ENABLED` | **False ตามค่าเริ่มต้น** ต้องเปิดเองหลังทดสอบแล้วมั่นใจ |
| `RISK.risk_per_trade_pct` | % ความเสี่ยงต่อ trade ต่อ equity |
| `RISK.max_daily_drawdown_pct` | หยุดเทรดถ้าขาดทุนเกินนี้ในวันเดียว |
| `CONFIDENCE_THRESHOLD_AUTO` | ค่าความมั่นใจขั้นต่ำที่จะส่งออเดอร์อัตโนมัติ |

## ขั้นตอนแนะนำก่อนใช้เงินจริง

1. **ทดสอบด้วย Demo Account ก่อนเสมอ** — เปลี่ยนค่า `MT5_LOGIN/PASSWORD/SERVER` เป็นบัญชีทดลอง
2. รันโดยเปิด `AUTO_TRADE_ENABLED = False` ก่อน เพื่อดูว่าสัญญาณที่ระบบส่งมาสมเหตุสมผลหรือไม่ (โหมด manual confirm ผ่านปุ่ม Telegram)
3. Backtest กลยุทธ์เพิ่มเติมด้วยข้อมูลย้อนหลัง ก่อนตัดสินใจเปิด auto trade
4. เมื่อพร้อมค่อยเปิด `AUTO_TRADE_ENABLED = True` และเริ่มด้วย lot size เล็กที่สุด

## ความแม่นยำจุดเข้า (Entry Signal Engine)

ระบบแยกการตัดสินใจเป็น 2 ชั้น เพื่อแก้ปัญหา "รู้ทิศทางถูกแต่เข้าผิดจังหวะ" (เช่น เข้าซื้อตอนราคาวิ่งขึ้นสุดโต่งแล้ว/RSI overbought):

**ชั้น 1 — Trend Bias** (`core/mtf_analyzer.py`): รวมสัญญาณจากหลาย timeframe (M1-D1) บอกทิศทางหลัก

**ชั้น 2 — Entry Trigger** (`core/entry_signal.py` + `core/price_action.py`): ประเมินจังหวะเข้าจริงบน `ENTRY_TIMEFRAME` (ค่าเริ่มต้น M15) โดยให้คะแนนถ่วงน้ำหนัก 5 เงื่อนไข:

| เงื่อนไข | น้ำหนัก | เหตุผล |
|---|---|---|
| Pullback ใกล้ EMA20 | 25% | ป้องกันไล่ราคาที่วิ่งไปไกลแล้ว |
| RSI ไม่สุดโต่งสวนทาง | 15% | ถ้า RSI overbought แต่จะ BUY = เสี่ยง pullback แรง |
| Candlestick pattern ยืนยัน | 25% | Pin bar / engulfing ที่จุดเข้า |
| ใกล้ Support/Resistance ที่แข็งแรง | 20% | หาจาก swing point ที่เคยเทสมาแล้ว ≥2 ครั้ง |
| Stochastic ยืนยัน | 15% | ตัดขึ้น/ลงตรงทิศทาง |

ต้องได้คะแนนรวม ≥ 50% (`MIN_ENTRY_SCORE` ใน `core/entry_signal.py`) ถึงจะถือเป็นจุดเข้าที่ดี — สัญญาณที่มี trend bias ถูกทิศแต่ entry score ต่ำจะถูกระงับไว้ก่อน (ระบบ log เหตุผลไว้ให้ตรวจสอบได้)

Stop Loss ก็เปลี่ยนจากใช้ ATR อย่างเดียว เป็นอิงโครงสร้างราคาจริง (ใต้แนวรับ/เหนือแนวต้าน) ผ่าน `EntrySignal.suggested_stop` ซึ่งแม่นยำกว่าในสถานการณ์จริง

**ทดสอบแล้ว**: กรณีจำลองราคาไล่ขึ้นต่อเนื่องไม่มี pullback → ระบบให้ entry score = 0 และระงับสัญญาณถูกต้อง ส่วนกรณี pullback มาที่ EMA พร้อม pin bar ยืนยัน → entry score 65% ผ่านเกณฑ์



ทดสอบกลยุทธ์ย้อนหลังก่อนใช้เงินจริงเสมอ:

```bash
pip install -r requirements-backtest.txt
python -m backtest.backtest_engine --csv data/EURUSD_H1.csv --symbol EURUSD --confidence 0.4
```

CSV ต้องมีคอลัมน์ `time, open, high, low, close` — export จาก MT5 (Tools > History Center) หรือดาวน์โหลดจาก HistData.com/Dukascopy

**ข้อจำกัดของ backtest นี้**: เป็นแบบ single-timeframe walk-forward อย่างง่าย ไม่ได้จำลอง multi-timeframe confluence เต็มรูปแบบเหมือนระบบจริง (เพราะต้องมีข้อมูลทุก timeframe ที่ time-align กันแม่นยำ) ผลลัพธ์จึงเป็นตัวชี้วัด "แนวโน้ม" ของกลยุทธ์ ไม่ใช่ผลจริงที่ระบบเต็มรูปแบบจะทำได้ ควรใช้ประกอบกับการ forward-test บน demo account เสมอก่อนขึ้นเงินจริง

รันผ่าน Docker ก็ได้ (ไม่ต้องติดตั้ง Python บนเครื่อง):
```bash
docker compose -f deploy/docker-compose.yml run backtest --csv data/EURUSD_H1.csv --symbol EURUSD
```

## Deployment (Production)

ระบบหลัก (`main.py`) ต้องรันบน **Windows** เท่านั้น เพราะพึ่ง MT5 terminal โดยตรง — รันใน Docker/Linux ไม่ได้

### วิธี deploy บน Windows Server/VPS

1. ติดตั้ง MT5 terminal, login บัญชี, ติดตั้ง Python 3.10+
2. `pip install -r requirements.txt`
3. ตั้งค่า `.env` ให้ครบ
4. ดาวน์โหลด [NSSM](https://nssm.cc/download) วางไว้ใน PATH
5. รัน `deploy\install_windows_service.bat` ด้วยสิทธิ์ Administrator
6. `nssm start ForexAutoTradeSystem`

Service จะ auto-restart เองถ้า crash และ auto-start ตอนเครื่อง reboot

### Watchdog (แนะนำอย่างยิ่งสำหรับระบบเทรดจริง)

`deploy/watchdog.py` เช็คว่า log ของระบบหลักเงียบไปนานผิดปกติหรือไม่ (เช่น MT5 หลุด, เครื่องดับ) แล้วแจ้งเตือนผ่าน Telegram แยกอิสระจาก service หลัก — ตั้งให้รันทุก 5-10 นาทีผ่าน **Windows Task Scheduler**:

```
Program: python
Arguments: C:\path\to\forex_system\deploy\watchdog.py
Trigger: Repeat every 5 minutes
```

## จุดที่ยังต้องเติมก่อนใช้งานจริง (Production Checklist)

- [x] `core/news_filter.py`: เชื่อมต่อ Forex Factory public JSON feed แล้ว — **แต่เป็น free/unofficial feed ไม่มี SLA** อาจโดนบล็อกหรือเปลี่ยนโครงสร้างได้โดยไม่แจ้งล่วงหน้า สำหรับ production จริงจังแนะนำสมัคร TradingEconomics API key (มี fallback code รองรับแล้วใน `_fetch_tradingeconomics_fallback`) — ตั้ง `TRADINGECONOMICS_API_KEY` ใน `.env` และเปลี่ยน `ECONOMIC_CALENDAR_SOURCE = "tradingeconomics"`
- [x] Backtesting module — ทดสอบแล้วรันได้ถูกต้อง แต่เป็น single-timeframe (ดูข้อจำกัดด้านบน)
- [x] Deployment script (Windows Service + Watchdog) — พร้อมใช้
- [ ] `pip_value_per_lot` ใน `risk_manager.calculate_position()`: ค่าเริ่มต้น 10.0 ใช้ได้กับคู่ที่ quote เป็น USD เท่านั้น ต้องคำนวณแยกตาม symbol จริง (เช่น XAUUSD ต่างจาก EURUSD)
- [ ] เพิ่ม unit test ครอบคลุม edge case (ราคากระโดด, ข้อมูลขาดหาย, MT5 disconnect กลางทาง)
- [ ] เพิ่มการเข้ารหัสหรือใช้ secret manager แทนการเก็บ password ใน `.env` แบบ plain text บน production server
- [ ] ทดสอบภายใต้ภาวะตลาดผันผวนสูง (news event จริง) ก่อน deploy
- [ ] Multi-timeframe backtest แบบเต็มรูปแบบ (ถ้าต้องการความแม่นยำสูงกว่านี้)

## คำสั่ง Telegram

- `/start` — แสดงเมนู
- `/status` — สถานะระบบ (ทำงาน/หยุด, โหมด auto/manual)
- `/pause` — หยุดส่งสัญญาณชั่วคราว
- `/resume` — เปิดใช้งานต่อ
- `/positions` — ออเดอร์ที่เปิดอยู่ (ต้องเชื่อมต่อเพิ่มใน main.py)

## ⚠️ คำเตือนความเสี่ยง

การเทรด Forex มีความเสี่ยงสูงและอาจสูญเสียเงินทุนทั้งหมด ระบบนี้เป็นเครื่องมือช่วยวิเคราะห์และดำเนินการเท่านั้น ไม่ได้รับประกันผลกำไร ผู้ใช้ต้องรับผิดชอบผลลัพธ์การเทรดด้วยตนเองทั้งหมด ควรทดสอบบน Demo Account อย่างละเอียดก่อนใช้เงินจริง

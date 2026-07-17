"""
Backtest Engine
===============
รันกลยุทธ์ (MTFAnalyzer + RiskManager) ย้อนหลังกับข้อมูลในอดีต เพื่อประเมินผลก่อนใช้เงินจริง

วิธีใช้:
    python -m backtest.backtest_engine --symbol EURUSD --csv data/EURUSD_H1.csv

ข้อมูล CSV ต้องมีคอลัมน์: time, open, high, low, close (tick_volume ถ้ามี ยิ่งดี)
หาข้อมูลได้จาก MT5 (Tools > History Center > Export) หรือ Dukascopy/HistData.com

หมายเหตุสำคัญ: backtest นี้เป็นแบบ single-timeframe walk-forward อย่างง่าย
(ใช้ timeframe เดียวเป็นหลักในการ simulate เพราะการ sync หลาย timeframe แบบ
เรียลไทม์ย้อนหลังต้องมีข้อมูลทุก timeframe ที่ time-align กันแม่นยำ ซึ่งซับซ้อนกว่านี้
มาก — ผลลัพธ์จาก backtest นี้จึงเป็น "แนวโน้ม" ไม่ใช่ผลจริงที่ระบบ multi-timeframe
เต็มรูปแบบจะทำได้ ควรใช้ประกอบการตัดสินใจร่วมกับ forward-test บน demo account เสมอ
"""
import argparse
from dataclasses import dataclass, field
from typing import List, Optional

import pandas as pd
import numpy as np

from core.mtf_analyzer import MTFAnalyzer, ema, rsi, macd, atr
from core.logger import get_logger
from config import settings

logger = get_logger(__name__)


@dataclass
class BacktestTrade:
    direction: str
    entry_time: pd.Timestamp
    entry_price: float
    exit_time: Optional[pd.Timestamp] = None
    exit_price: Optional[float] = None
    stop_loss: float = 0.0
    take_profit: float = 0.0
    result: Optional[str] = None  # "win" | "loss" | "open"
    pnl_pips: float = 0.0


@dataclass
class BacktestReport:
    trades: List[BacktestTrade] = field(default_factory=list)

    @property
    def total_trades(self) -> int:
        return len(self.trades)

    @property
    def wins(self) -> int:
        return sum(1 for t in self.trades if t.result == "win")

    @property
    def losses(self) -> int:
        return sum(1 for t in self.trades if t.result == "loss")

    @property
    def win_rate(self) -> float:
        return self.wins / self.total_trades * 100 if self.total_trades else 0.0

    @property
    def total_pips(self) -> float:
        return sum(t.pnl_pips for t in self.trades)

    @property
    def avg_win_pips(self) -> float:
        wins = [t.pnl_pips for t in self.trades if t.result == "win"]
        return float(np.mean(wins)) if wins else 0.0

    @property
    def avg_loss_pips(self) -> float:
        losses = [t.pnl_pips for t in self.trades if t.result == "loss"]
        return float(np.mean(losses)) if losses else 0.0

    @property
    def profit_factor(self) -> float:
        gross_win = sum(t.pnl_pips for t in self.trades if t.result == "win")
        gross_loss = abs(sum(t.pnl_pips for t in self.trades if t.result == "loss"))
        return gross_win / gross_loss if gross_loss > 0 else float("inf")

    @property
    def max_drawdown_pips(self) -> float:
        equity_curve = np.cumsum([t.pnl_pips for t in self.trades])
        if len(equity_curve) == 0:
            return 0.0
        running_max = np.maximum.accumulate(equity_curve)
        drawdown = running_max - equity_curve
        return float(np.max(drawdown))

    def summary(self) -> str:
        return (
            f"เทรดทั้งหมด: {self.total_trades} | ชนะ: {self.wins} | แพ้: {self.losses}\n"
            f"Win rate: {self.win_rate:.1f}%\n"
            f"กำไรรวม: {self.total_pips:.1f} pips\n"
            f"กำไรเฉลี่ยต่อไม้ชนะ: {self.avg_win_pips:.1f} pips | ขาดทุนเฉลี่ยต่อไม้แพ้: {self.avg_loss_pips:.1f} pips\n"
            f"Profit Factor: {self.profit_factor:.2f}\n"
            f"Max Drawdown: {self.max_drawdown_pips:.1f} pips"
        )


class BacktestEngine:
    def __init__(self, point_size: float = 0.0001, warmup_bars: int = 250):
        self.analyzer = MTFAnalyzer()
        self.point_size = point_size
        self.warmup_bars = warmup_bars  # จำนวนแท่งขั้นต่ำก่อนเริ่มคำนวณ indicator ได้แม่นยำ (รอ EMA200)

    def _simplified_score(self, window_df: pd.DataFrame) -> tuple:
        """ใช้ analyze_timeframe ตรงๆ กับ window ข้อมูล ณ จุดเวลานั้น (single timeframe)"""
        analysis = self.analyzer.analyze_timeframe("BT", window_df)
        if analysis.score > 0.15:
            return "BUY", analysis
        elif analysis.score < -0.15:
            return "SELL", analysis
        return "HOLD", analysis

    def run(self, df: pd.DataFrame, confidence_threshold: float = 0.4) -> BacktestReport:
        report = BacktestReport()
        open_trade: Optional[BacktestTrade] = None

        for i in range(self.warmup_bars, len(df)):
            window = df.iloc[:i + 1]
            current_bar = df.iloc[i]

            # ── จัดการไม้ที่เปิดอยู่ก่อน (เช็คว่าโดน SL/TP หรือยัง) ──
            if open_trade is not None:
                hit_sl = (
                    current_bar["low"] <= open_trade.stop_loss if open_trade.direction == "BUY"
                    else current_bar["high"] >= open_trade.stop_loss
                )
                hit_tp = (
                    current_bar["high"] >= open_trade.take_profit if open_trade.direction == "BUY"
                    else current_bar["low"] <= open_trade.take_profit
                )
                if hit_sl or hit_tp:
                    exit_price = open_trade.stop_loss if hit_sl else open_trade.take_profit
                    pnl_price = (
                        exit_price - open_trade.entry_price if open_trade.direction == "BUY"
                        else open_trade.entry_price - exit_price
                    )
                    open_trade.exit_time = current_bar.name
                    open_trade.exit_price = exit_price
                    open_trade.result = "loss" if hit_sl else "win"
                    open_trade.pnl_pips = pnl_price / self.point_size / 10
                    report.trades.append(open_trade)
                    open_trade = None
                continue  # มีไม้เปิดอยู่ ไม่เปิดไม้ใหม่ซ้อน

            # ── หาสัญญาณใหม่ ──
            direction, analysis = self._simplified_score(window)
            if direction == "HOLD" or abs(analysis.score) < confidence_threshold:
                continue

            entry_price = current_bar["close"]
            sl_distance = analysis.atr_value * settings.RISK.atr_sl_multiplier
            tp_distance = analysis.atr_value * settings.RISK.atr_tp_multiplier

            if sl_distance <= 0:
                continue

            if direction == "BUY":
                sl = entry_price - sl_distance
                tp = entry_price + tp_distance
            else:
                sl = entry_price + sl_distance
                tp = entry_price - tp_distance

            open_trade = BacktestTrade(
                direction=direction, entry_time=current_bar.name, entry_price=entry_price,
                stop_loss=sl, take_profit=tp,
            )

        return report


def load_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["time"] = pd.to_datetime(df["time"])
    df.set_index("time", inplace=True)
    required = {"open", "high", "low", "close"}
    if not required.issubset(df.columns):
        raise ValueError(f"CSV ต้องมีคอลัมน์อย่างน้อย: {required}")
    return df


def main():
    parser = argparse.ArgumentParser(description="Backtest กลยุทธ์ MTF Analyzer")
    parser.add_argument("--csv", required=True, help="path ไปยังไฟล์ CSV ข้อมูลราคาย้อนหลัง")
    parser.add_argument("--symbol", default="UNKNOWN")
    parser.add_argument("--point-size", type=float, default=0.0001)
    parser.add_argument("--confidence", type=float, default=0.4)
    args = parser.parse_args()

    df = load_csv(args.csv)
    logger.info(f"โหลดข้อมูล {args.symbol}: {len(df)} แท่ง ({df.index[0]} ถึง {df.index[-1]})")

    engine = BacktestEngine(point_size=args.point_size)
    report = engine.run(df, confidence_threshold=args.confidence)

    print(f"\n=== ผล Backtest: {args.symbol} ===")
    print(report.summary())


if __name__ == "__main__":
    main()

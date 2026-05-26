"""
Market data helpers for advisory.

Goal: derive a chart-like summary from real candle/quote data so the advisory
panel can reason from facts (trend, momentum, range) without reading the
embedded TradingView iframe.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

from angel_client import angel


def _ist_now() -> datetime:
    # Server runs in UTC by default; SmartAPI candle API expects exchange-local strings.
    # We send naive timestamps formatted as "YYYY-MM-DD HH:MM" in IST.
    ist = timezone(timedelta(hours=5, minutes=30))
    return datetime.now(tz=ist)


def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M")


@dataclass(frozen=True)
class Candle:
    ts: datetime
    o: float
    h: float
    l: float
    c: float
    v: float


def _to_candles(rows: list[list]) -> list[Candle]:
    out: list[Candle] = []
    for r in rows:
        # row: [timestamp, open, high, low, close, volume]
        ts = r[0]
        if isinstance(ts, str):
            # Common format: "2026-05-27T09:15:00+05:30" or "2026-05-27 09:15"
            try:
                ts_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except Exception:
                ts_dt = datetime.strptime(ts, "%Y-%m-%d %H:%M")
        else:
            ts_dt = datetime.fromtimestamp(float(ts))
        out.append(
            Candle(
                ts=ts_dt,
                o=float(r[1]),
                h=float(r[2]),
                l=float(r[3]),
                c=float(r[4]),
                v=float(r[5]) if len(r) > 5 else 0.0,
            )
        )
    return out


def _ema(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    alpha = 2.0 / (period + 1.0)
    e = values[0]
    for x in values[1:]:
        e = alpha * x + (1 - alpha) * e
    return float(e)


def _rsi(closes: list[float], period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    gains = 0.0
    losses = 0.0
    for i in range(1, period + 1):
        d = closes[i] - closes[i - 1]
        if d >= 0:
            gains += d
        else:
            losses -= d
    avg_gain = gains / period
    avg_loss = losses / period
    for i in range(period + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        gain = d if d > 0 else 0.0
        loss = -d if d < 0 else 0.0
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return float(100.0 - (100.0 / (1.0 + rs)))


def _atr(candles: list[Candle], period: int = 14) -> float | None:
    if len(candles) < period + 1:
        return None
    trs: list[float] = []
    prev_close = candles[0].c
    for c in candles[1:]:
        tr = max(c.h - c.l, abs(c.h - prev_close), abs(c.l - prev_close))
        trs.append(float(tr))
        prev_close = c.c
    if len(trs) < period:
        return None
    # Wilder's smoothing
    a = sum(trs[:period]) / period
    for tr in trs[period:]:
        a = (a * (period - 1) + tr) / period
    return float(a)


def _vwap(candles: list[Candle]) -> float | None:
    num = 0.0
    den = 0.0
    for c in candles:
        tp = (c.h + c.l + c.c) / 3.0
        num += tp * c.v
        den += c.v
    if den <= 0:
        return None
    return float(num / den)


def nifty_spot_snapshot() -> dict:
    """
    Returns a snapshot for the NIFTY 50 index:
    - spot LTP
    - last 1D (rolling) 1-minute candles
    - indicator summary
    """
    angel.require_session()

    idx = angel.resolve_nifty_index()
    # 1D candles: request 2 days to be safe (covers gaps), then compute summary on last ~24h.
    now = _ist_now()
    start = now - timedelta(days=2)
    rows = angel.candles(
        exchange="NSE",
        token=idx["token"],
        interval="ONE_MINUTE",
        fromdate=_fmt(start),
        todate=_fmt(now),
    )
    candles = _to_candles(rows)
    if not candles:
        raise RuntimeError("No candle data returned for NIFTY spot.")

    # Keep last ~24h worth of points by timestamp, not count.
    cutoff = now - timedelta(hours=24)
    tail = [c for c in candles if c.ts.replace(tzinfo=None) >= cutoff.replace(tzinfo=None)]
    if len(tail) < 30:
        tail = candles[-390:]  # at least ~1 trading day worth of minutes fallback

    closes = [c.c for c in tail]
    highs = [c.h for c in tail]
    lows = [c.l for c in tail]

    last = closes[-1]
    first = closes[0]
    hi = max(highs)
    lo = min(lows)
    chg = last - first
    chg_pct = (chg / first * 100.0) if first else 0.0

    ema9 = _ema(closes[-120:], 9)
    ema21 = _ema(closes[-240:], 21)
    rsi14 = _rsi(closes[-500:], 14)
    atr14 = _atr(tail[-500:], 14)
    vwap1d = _vwap(tail)

    trend = "sideways"
    if ema9 is not None and ema21 is not None:
        if ema9 > ema21 and last >= ema9:
            trend = "up"
        elif ema9 < ema21 and last <= ema9:
            trend = "down"

    return {
        "instrument": idx,
        "spot": last,
        "range_24h": {"high": hi, "low": lo, "change": chg, "change_pct": chg_pct},
        "indicators": {
            "ema9": ema9,
            "ema21": ema21,
            "rsi14": rsi14,
            "atr14": atr14,
            "vwap_1d": vwap1d,
            "trend": trend,
        },
        "candles_1m_count": len(tail),
        "asof": now.isoformat(timespec="seconds"),
    }


def option_snapshot(*, symbol: str, expiry: str, strike: int, opt_type: str) -> dict:
    angel.require_session()
    inst = angel.resolve_option(symbol, expiry, strike, opt_type)
    ltp = angel.ltp("NFO", inst["tradingsymbol"], inst["token"])
    return {"instrument": inst, "ltp": ltp}


import asyncio
import random
import time
import math
from typing import AsyncGenerator, Dict
from app.models import Tick
from app.config import SYMBOLS, SEED_PRICES, FEED_INTERVAL_MS


class MockFeed:
    """
    Generates realistic market ticks using geometric Brownian motion
    with mean reversion, momentum, and volume spikes.
    """

    def __init__(self):
        self._state: Dict[str, dict] = {}
        self._running = False
        for sym in SYMBOLS:
            seed = SEED_PRICES.get(sym, 1000.0)
            self._state[sym] = {
                "price": seed,
                "open": seed,
                "high": seed,
                "low": seed,
                "base": seed,
                "momentum": 0.0,
                "volume_base": 50000 if seed > 10000 else 5000,
            }

    def _next_tick(self, symbol: str) -> Tick:
        s = self._state[symbol]
        now = time.time()

        # Mean-reverting GBM
        drift = -0.0001 * (s["price"] - s["base"]) / s["base"]  # pull toward base
        vol = 0.0008 if s["price"] > 10000 else 0.0015  # indices less volatile pct-wise
        shock = random.gauss(0, 1)

        # Momentum factor (autocorrelation)
        s["momentum"] = 0.3 * s["momentum"] + 0.7 * shock
        ret = drift + vol * s["momentum"]

        new_price = round(s["price"] * (1 + ret), 2)
        s["price"] = new_price
        s["high"] = max(s["high"], new_price)
        s["low"] = min(s["low"], new_price)

        # Volume with occasional spikes
        vol_mult = random.choices([1.0, 2.5, 5.0], weights=[85, 12, 3])[0]
        volume = int(s["volume_base"] * vol_mult * random.uniform(0.5, 1.5))

        return Tick(
            symbol=symbol,
            price=new_price,
            open=s["open"],
            high=s["high"],
            low=s["low"],
            volume=volume,
            timestamp=now,
        )

    async def stream(self) -> AsyncGenerator[Tick, None]:
        self._running = True
        interval = FEED_INTERVAL_MS / 1000.0
        while self._running:
            for sym in SYMBOLS:
                yield self._next_tick(sym)
            await asyncio.sleep(interval)

    def stop(self):
        self._running = False

    def reset_day(self):
        """Reset OHLC for new session."""
        for sym in SYMBOLS:
            s = self._state[sym]
            s["open"] = s["price"]
            s["high"] = s["price"]
            s["low"] = s["price"]

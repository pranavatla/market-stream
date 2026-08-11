import asyncio
from datetime import datetime, time as datetime_time
from zoneinfo import ZoneInfo
import logging
import os
import random
import threading
import time
import math
from typing import AsyncGenerator, Dict, Optional
from app.models import Tick
from app.config import SYMBOLS, SEED_PRICES, FEED_INTERVAL_MS

log = logging.getLogger(__name__)


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


# =============================================================================
# ANGEL ONE LIVE FEED
# =============================================================================

# Instrument map. exchange_type: 1=NSE, 2=NFO, 3=BSE, 5=MCX.
# Tokens are Angel One's SmartAPI instrument tokens.
ANGELONE_INSTRUMENTS = {
    "NIFTY50": {"exchange_type": 1, "token": "99926000"},
    "BANKNIFTY": {"exchange_type": 1, "token": "99926009"},
}

# SmartWebSocketV2 subscription modes
MODE_LTP = 1
MODE_QUOTE = 2
MODE_SNAP_QUOTE = 3

# Angel One sends prices as integers in paise (1/100 rupee).
PAISE = 100.0


class AngelOneFeed:
    """
    Live market feed backed by Angel One SmartAPI.

    Authenticates with SmartConnect (TOTP-based login), then streams ticks
    over SmartWebSocketV2 in SNAP_QUOTE mode. Emits the same Tick shape as
    MockFeed so the rest of the app is feed-agnostic.

    The SmartAPI websocket client is callback-driven and blocking, so it runs
    on a background thread. Ticks cross into asyncio via a bounded queue.
    """

    def __init__(self, symbols: Optional[list] = None):
        # Only stream symbols we have a token for.
        requested = symbols if symbols is not None else SYMBOLS
        self.symbols = [s for s in requested if s in ANGELONE_INSTRUMENTS]
        unknown = [s for s in requested if s not in ANGELONE_INSTRUMENTS]
        if unknown:
            log.warning("No Angel One token for %s — not subscribing", ", ".join(unknown))

        # token -> symbol, for decoding inbound ticks
        self._token_to_symbol = {
            ANGELONE_INSTRUMENTS[s]["token"]: s for s in self.symbols
        }

        self._running = False
        self._ws = None
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._queue: Optional[asyncio.Queue] = None
        self._dropped = 0
        self._auth_lock = threading.Lock()
        self._auth_cache: Optional[dict] = None
        self._auth_cache_at = 0.0

        # Per-symbol OHLC carry-forward, for when a tick omits fields.
        self._state: Dict[str, dict] = {}

        # Credentials
        self.client_id = os.getenv("ANGELONE_CLIENT_ID")
        self.api_key = os.getenv("ANGELONE_API_KEY")
        self.totp_secret = os.getenv("ANGELONE_TOTP_SECRET")
        # SmartConnect.generateSession() requires the account PIN/password in
        # addition to the TOTP. Accept either name.
        self.pin = os.getenv("ANGELONE_PIN") or os.getenv("ANGELONE_PASSWORD")

    def get_intraday_history(self, symbol: str) -> list[Tick]:
        """Fetch current-session one-minute candles from Angel One REST."""
        symbol = symbol.upper()
        instrument = ANGELONE_INSTRUMENTS.get(symbol)
        if not instrument:
            return []

        creds = self._authenticate()
        client = creds["client"]
        ist = ZoneInfo("Asia/Kolkata")
        now = datetime.now(ist)
        session_start = datetime.combine(now.date(), datetime_time(9, 15), tzinfo=ist)
        session_end = min(now, datetime.combine(now.date(), datetime_time(15, 30), tzinfo=ist))

        if session_end <= session_start:
            return []

        payload = {
            "exchange": "NSE",
            "symboltoken": instrument["token"],
            "interval": "ONE_MINUTE",
            "fromdate": session_start.strftime("%Y-%m-%d %H:%M"),
            "todate": session_end.strftime("%Y-%m-%d %H:%M"),
        }
        response = client.getCandleData(payload)
        if not response or not response.get("status"):
            log.warning("Angel One candle fetch failed for %s: %s", symbol, response)
            return []

        ticks: list[Tick] = []
        for candle in response.get("data") or []:
            if len(candle) < 6:
                continue
            timestamp, open_price, high, low, close, volume = candle[:6]
            try:
                dt = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=ist)
                ticks.append(
                    Tick(
                        symbol=symbol,
                        price=float(close),
                        open=float(open_price),
                        high=float(high),
                        low=float(low),
                        volume=int(volume or 0),
                        timestamp=dt.timestamp(),
                    )
                )
            except (TypeError, ValueError):
                log.debug("Skipping malformed candle for %s: %s", symbol, candle)

        return ticks

    # -------------------------------------------------------------------------
    # AUTH
    # -------------------------------------------------------------------------
    def _authenticate(self) -> dict:
        """Log in via SmartConnect and return the tokens the websocket needs."""
        from SmartApi import SmartConnect
        import pyotp

        with self._auth_lock:
            if self._auth_cache and time.time() - self._auth_cache_at < 240:
                return self._auth_cache

            missing = [
                name
                for name, val in (
                    ("ANGELONE_CLIENT_ID", self.client_id),
                    ("ANGELONE_API_KEY", self.api_key),
                    ("ANGELONE_TOTP_SECRET", self.totp_secret),
                    ("ANGELONE_PIN", self.pin),
                )
                if not val
            ]
            if missing:
                raise RuntimeError(
                    "Angel One feed is missing required env vars: " + ", ".join(missing)
                )

            totp = pyotp.TOTP(self.totp_secret).now()
            client = SmartConnect(api_key=self.api_key)
            session = client.generateSession(self.client_id, self.pin, totp)

            if not session or not session.get("status"):
                raise RuntimeError(
                    f"Angel One login failed: {session.get('message') if session else 'no response'}"
                )

            self._auth_cache = {
                "auth_token": session["data"]["jwtToken"],
                "feed_token": client.getfeedToken(),
                "client": client,
            }
            self._auth_cache_at = time.time()
            return self._auth_cache

    # -------------------------------------------------------------------------
    # TICK DECODING
    # -------------------------------------------------------------------------
    def _to_tick(self, msg: dict) -> Optional[Tick]:
        """Convert a SmartWebSocketV2 SNAP_QUOTE payload into a Tick."""
        token = str(msg.get("token") or "").strip()
        symbol = self._token_to_symbol.get(token)
        if not symbol:
            return None

        ltp = msg.get("last_traded_price")
        if ltp is None:
            return None
        price = round(ltp / PAISE, 2)

        s = self._state.setdefault(
            symbol, {"open": price, "high": price, "low": price, "volume": 0}
        )

        def paise(key, fallback):
            v = msg.get(key)
            return round(v / PAISE, 2) if v else fallback

        s["open"] = paise("open_price_of_the_day", s["open"])
        s["high"] = max(paise("high_price_of_the_day", s["high"]), price)
        s["low"] = min(paise("low_price_of_the_day", s["low"]), price)
        # Indices report no traded volume; keep the last known value.
        s["volume"] = int(msg.get("volume_trade_for_the_day") or s["volume"])

        # exchange_timestamp is epoch millis; fall back to local clock.
        ts = msg.get("exchange_timestamp")
        timestamp = (ts / 1000.0) if ts else time.time()

        return Tick(
            symbol=symbol,
            price=price,
            open=s["open"],
            high=s["high"],
            low=s["low"],
            volume=s["volume"],
            timestamp=timestamp,
        )

    def _publish(self, tick: Tick):
        """Hand a tick from the websocket thread to the asyncio loop."""
        if not (self._loop and self._queue and self._running):
            return

        def put():
            try:
                self._queue.put_nowait(tick)
            except asyncio.QueueFull:
                # Shed the oldest tick — a live feed favours fresh data.
                try:
                    self._queue.get_nowait()
                    self._queue.put_nowait(tick)
                except Exception:
                    pass
                self._dropped += 1
                if self._dropped % 100 == 1:
                    log.warning("Tick queue saturated, dropped %d ticks", self._dropped)

        try:
            self._loop.call_soon_threadsafe(put)
        except RuntimeError:
            pass  # loop closed during shutdown

    # -------------------------------------------------------------------------
    # WEBSOCKET THREAD (with reconnect supervision)
    # -------------------------------------------------------------------------
    def _run_socket(self):
        from SmartApi.smartWebSocketV2 import SmartWebSocketV2

        backoff = 1.0
        max_backoff = 60.0

        while self._running:
            try:
                creds = self._authenticate()

                ws = SmartWebSocketV2(
                    creds["auth_token"],
                    self.api_key,
                    self.client_id,
                    creds["feed_token"],
                    max_retry_attempt=5,
                )
                self._ws = ws

                token_list = [
                    {
                        "exchangeType": meta["exchange_type"],
                        "tokens": [
                            ANGELONE_INSTRUMENTS[s]["token"]
                            for s in self.symbols
                            if ANGELONE_INSTRUMENTS[s]["exchange_type"]
                            == meta["exchange_type"]
                        ],
                    }
                    for meta in {
                        ANGELONE_INSTRUMENTS[s]["exchange_type"]: ANGELONE_INSTRUMENTS[s]
                        for s in self.symbols
                    }.values()
                ]

                def on_open(wsapp):
                    log.info("Angel One websocket open — subscribing %s", self.symbols)
                    backoff_reset[0] = True
                    ws.subscribe("market-stream", MODE_SNAP_QUOTE, token_list)

                def on_data(wsapp, message):
                    if not isinstance(message, dict):
                        return
                    try:
                        tick = self._to_tick(message)
                    except Exception:
                        log.exception("Failed to decode Angel One tick")
                        return
                    if tick:
                        self._publish(tick)

                def on_error(wsapp, error):
                    log.error("Angel One websocket error: %s", error)

                def on_close(wsapp):
                    log.warning("Angel One websocket closed")

                backoff_reset = [False]
                ws.on_open = on_open
                ws.on_data = on_data
                ws.on_error = on_error
                ws.on_close = on_close

                ws.connect()  # blocks until the socket drops

                if backoff_reset[0]:
                    backoff = 1.0

            except Exception:
                log.exception("Angel One feed crashed")

            if not self._running:
                break

            log.info("Reconnecting to Angel One in %.0fs", backoff)
            # Sleep in slices so stop() takes effect promptly.
            slept = 0.0
            while slept < backoff and self._running:
                time.sleep(0.5)
                slept += 0.5
            backoff = min(backoff * 2, max_backoff)

    # -------------------------------------------------------------------------
    # PUBLIC API (mirrors MockFeed)
    # -------------------------------------------------------------------------
    async def stream(self) -> AsyncGenerator[Tick, None]:
        if not self.symbols:
            raise RuntimeError(
                "AngelOneFeed has no subscribable symbols. Known: "
                + ", ".join(ANGELONE_INSTRUMENTS)
            )

        self._running = True
        self._loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue(maxsize=2000)

        self._thread = threading.Thread(
            target=self._run_socket, name="angelone-ws", daemon=True
        )
        self._thread.start()

        try:
            while self._running:
                tick = await self._queue.get()
                yield tick
        finally:
            self.stop()

    def stop(self):
        self._running = False
        ws = self._ws
        if ws is not None:
            try:
                ws.close_connection()
            except Exception:
                pass
            self._ws = None

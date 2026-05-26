"""
Angel One SmartAPI session wrapper.

Handles login (api_key + client_id + mpin + live TOTP), token refresh,
and instrument-master lookup so we can resolve a NIFTY CE/PE strike into
the exact tradingsymbol + token the order API needs.
"""
import logging
import time
from datetime import datetime, timedelta

import pyotp
import requests

try:
    from SmartApi import SmartConnect
    from SmartApi.smartWebSocketV2 import SmartWebSocketV2
except ImportError:  # allow scaffold to import without the lib installed yet
    SmartConnect = None
    SmartWebSocketV2 = None

from config import settings

log = logging.getLogger("angel")

INSTRUMENT_URL = (
    "https://margincalculator.angelbroking.com/"
    "OpenAPI_File/files/OpenAPIScripMaster.json"
)


class AngelClient:
    def __init__(self):
        self.smart: SmartConnect | None = None
        self.session = None
        self.feed_token = None
        self._instruments: list[dict] = []
        self._instruments_loaded_at: datetime | None = None

    def require_session(self):
        if self.smart is None or self.session is None:
            raise RuntimeError("Not logged in. POST /login first.")

    # ---------- auth ----------
    def login(self) -> dict:
        missing = settings.creds.validate()
        if missing:
            raise RuntimeError(f"Missing credentials in .env: {', '.join(missing)}")
        if SmartConnect is None:
            raise RuntimeError("smartapi-python not installed. pip install smartapi-python")

        self.smart = SmartConnect(api_key=settings.creds.api_key)
        totp = pyotp.TOTP(settings.creds.totp_seed).now()
        data = self.smart.generateSession(
            settings.creds.client_id, settings.creds.mpin, totp
        )
        if not data.get("status"):
            raise RuntimeError(f"Login failed: {data.get('message')}")
        self.session = data["data"]
        self.feed_token = self.smart.getfeedToken()
        log.info("Angel session established for %s", settings.creds.client_id)
        return {"status": "ok", "client": settings.creds.client_id}

    def profile(self) -> dict:
        self.require_session()
        return self.smart.getProfile(self.session["refreshToken"])

    # ---------- instrument master ----------
    def _ensure_instruments(self):
        fresh = (
            self._instruments_loaded_at
            and datetime.now() - self._instruments_loaded_at < timedelta(hours=12)
        )
        if self._instruments and fresh:
            return
        log.info("Downloading instrument master ...")
        self._instruments = requests.get(INSTRUMENT_URL, timeout=30).json()
        self._instruments_loaded_at = datetime.now()
        log.info("Loaded %d instruments", len(self._instruments))

    def resolve_option(self, symbol: str, expiry: str, strike: int, opt_type: str) -> dict:
        """
        symbol   e.g. 'NIFTY'
        expiry   e.g. '29MAY2025' (as in scrip master, uppercase)
        strike   e.g. 24500
        opt_type 'CE' or 'PE'
        Returns {'token','tradingsymbol','lotsize'} or raises.
        """
        self._ensure_instruments()
        opt_type = opt_type.upper()
        strike_x100 = str(strike * 100)  # scrip master stores strike * 100
        for ins in self._instruments:
            if (
                ins.get("name") == symbol
                and ins.get("exch_seg") == "NFO"
                and ins.get("expiry") == expiry
                and ins.get("strike") == strike_x100 + ".000000"
                and ins.get("symbol", "").endswith(opt_type)
            ):
                return {
                    "token": ins["token"],
                    "tradingsymbol": ins["symbol"],
                    "lotsize": int(ins.get("lotsize", settings.nifty_lot_size)),
                }
        raise LookupError(
            f"No instrument for {symbol} {expiry} {strike} {opt_type}. "
            "Check expiry format (e.g. 29MAY2025) and strike."
        )

    def ltp(self, exchange: str, tradingsymbol: str, token: str) -> float:
        self.require_session()
        r = self.smart.ltpData(exchange, tradingsymbol, token)
        return float(r["data"]["ltp"])


angel = AngelClient()

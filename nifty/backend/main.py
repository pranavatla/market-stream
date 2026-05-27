"""
FastAPI backend tying it together.

Flow for a trade (manual mode):
  1. POST /quote        -> see strike LTP
  2. POST /analyze      -> Claude advisory read (optional)
  3. POST /order/prepare-> dry-run, returns the exact order + risk verdict
  4. POST /order/execute-> actually sends it (only after you confirm)

Safety endpoints: /kill, /unkill, /squareoff, /risk
"""
import logging
import os
import subprocess

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import settings
from angel_client import angel
from risk import risk_engine
import orders
import analysis
import market

logging.basicConfig(level=logging.INFO)
app = FastAPI(title="NIFTY Options Console")

app.add_middleware(GZipMiddleware, minimum_size=1000)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class NoStoreHTMLMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        # Avoid stale dashboards on browsers/proxies when we push updates.
        if request.url.path in ("/", "/index.html"):
            response.headers["Cache-Control"] = "no-store"
        return response

app.add_middleware(NoStoreHTMLMiddleware)

def _compute_build_id() -> str:
    try:
        # Repo root is two levels up from nifty/backend.
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo_root,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
        ).strip()
        return out or ""
    except Exception:
        return ""

BUILD_ID = settings.build_id or _compute_build_id() or "unknown"

def _require_trader(request: Request):
    """
    Second factor for LIVE actions, on top of Nginx basic-auth.
    Set `TRADER_TOKEN` in `.env` to enable. If unset, no extra check is applied.
    """
    if not settings.trader_token:
        return
    got = request.headers.get("X-Trader-Token", "")
    if got != settings.trader_token:
        raise HTTPException(401, "Missing/invalid X-Trader-Token")


def _ensure_market_session():
    if angel.session is not None:
        return
    try:
        angel.login()
    except Exception as e:
        raise HTTPException(400, f"Market data login failed: {e}")


class OptionRef(BaseModel):
    symbol: str = "NIFTY"
    expiry: str            # e.g. 29MAY2025
    strike: int
    opt_type: str          # CE | PE


class OrderReq(OptionRef):
    side: str = "BUY"      # BUY entry / SELL exit
    lots: int = 1
    order_type: str = "MARKET"
    price: float = 0.0


class AnalyzeReq(BaseModel):
    context: dict


@app.get("/health")
def health():
    return {"ok": True, "logged_in": angel.session is not None,
            "confirm_mode": settings.confirm_mode,
            "trader_token_required": bool(settings.trader_token),
            "build_id": BUILD_ID}


@app.post("/login")
def login(request: Request):
    try:
        _require_trader(request)
        return angel.login()
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/quote")
def quote(ref: OptionRef):
    try:
        inst = angel.resolve_option(ref.symbol, ref.expiry, ref.strike, ref.opt_type)
        ltp = angel.ltp(settings.exchange, inst["tradingsymbol"], inst["token"])
        return {"instrument": inst, "ltp": ltp}
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/analyze")
def analyze(req: AnalyzeReq):
    return analysis.review_setup(req.context)

class AutoAdviceReq(BaseModel):
    symbol: str = "NIFTY"
    expiry: str
    strike: int
    opt_type: str  # CE | PE
    thesis: str = ""


class SetupReq(BaseModel):
    symbol: str = "NIFTY"
    expiry: str
    strike: int


@app.post("/market/setup")
def market_setup(req: SetupReq):
    """
    Factual setup snapshot for the console. No order placement and no advisory text.
    """
    _ensure_market_session()
    snap = market.nifty_spot_snapshot()
    pair = market.option_pair_snapshot(symbol=req.symbol, expiry=req.expiry, strike=req.strike)
    return {
        "spot": snap["spot"],
        "range_24h": snap["range_24h"],
        "momentum": snap.get("momentum"),
        "spot_levels": snap.get("spot_levels"),
        "indicators": snap["indicators"],
        "candles_1m_count": snap.get("candles_1m_count"),
        "asof": snap.get("asof"),
        "options": {
            "ce": {
                "ltp": pair["ce"]["ltp"],
                "symbol": pair["ce"]["instrument"]["tradingsymbol"],
                "lotsize": pair["ce"]["instrument"]["lotsize"],
            },
            "pe": {
                "ltp": pair["pe"]["ltp"],
                "symbol": pair["pe"]["instrument"]["tradingsymbol"],
                "lotsize": pair["pe"]["instrument"]["lotsize"],
            },
            "premium_spread": pair["premium_spread"],
        },
    }


@app.get("/market/spot")
def market_spot():
    _ensure_market_session()
    snap = market.nifty_spot_snapshot()
    return {
        "spot": snap["spot"],
        "range_24h": snap["range_24h"],
        "momentum": snap.get("momentum"),
        "indicators": snap["indicators"],
        "asof": snap.get("asof"),
    }


@app.post("/advisory/auto")
def advisory_auto(req: AutoAdviceReq):
    """
    Advisory powered by real market data:
    - NIFTY spot snapshot (1m candles + indicators)
    - option LTP for chosen strike
    This still does NOT place orders.
    """
    if angel.session is None:
        raise HTTPException(400, "Not logged in. Click Login first.")

    snap = market.nifty_spot_snapshot()
    pair = market.option_pair_snapshot(symbol=req.symbol, expiry=req.expiry, strike=req.strike)
    ctx = {
        "thesis": req.thesis,
        "spot": snap["spot"],
        "range_24h": snap["range_24h"],
        "momentum": snap.get("momentum"),
        "spot_levels": snap.get("spot_levels"),
        "indicators": snap["indicators"],
        "candidate": f"{req.strike}{req.opt_type.upper()} {req.expiry}",
        "options": {
            "ce_ltp": pair["ce"]["ltp"],
            "pe_ltp": pair["pe"]["ltp"],
            "premium_spread": pair["premium_spread"],
        },
        "rules": [
            "buy options only",
            "do not enter outside entry window",
            "respect max loss per trade/day",
            "prefer waiting if chart state is unclear",
        ],
    }
    out = analysis.review_setup(ctx)
    # Attach factual snapshot for UI display (does not affect order flow).
    try:
        out["_facts"] = {
            "spot": snap["spot"],
            "trend": snap["indicators"].get("trend"),
            "m5_pct": (snap.get("momentum") or {}).get("m5", {}).get("delta_pct"),
            "m15_pct": (snap.get("momentum") or {}).get("m15", {}).get("delta_pct"),
            "rsi14": snap["indicators"].get("rsi14"),
            "vwap_1d": snap["indicators"].get("vwap_1d"),
            "ce_ltp": pair["ce"]["ltp"],
            "pe_ltp": pair["pe"]["ltp"],
            "spread": pair["premium_spread"],
            "asof": snap.get("asof"),
        }
    except Exception:
        pass
    return out


@app.get("/market/nifty/candles")
def market_nifty_candles(hours: int = 24):
    # Chart should render even before explicit Login. We only use this for market data.
    _ensure_market_session()
    return market.nifty_candles_1m(hours=hours)


@app.post("/order/prepare")
def prepare(req: OrderReq):
    return orders.place_option(
        symbol=req.symbol, expiry=req.expiry, strike=req.strike,
        opt_type=req.opt_type, side=req.side, lots=req.lots,
        order_type=req.order_type, price=req.price, dry_run=True,
    )


@app.post("/order/execute")
def execute(req: OrderReq, request: Request):
    _require_trader(request)
    res = orders.place_option(
        symbol=req.symbol, expiry=req.expiry, strike=req.strike,
        opt_type=req.opt_type, side=req.side, lots=req.lots,
        order_type=req.order_type, price=req.price, dry_run=False,
    )
    if not res.get("ok"):
        raise HTTPException(400, res.get("reason") or res.get("error") or "rejected")
    return res


@app.get("/positions")
def get_positions():
    try:
        return orders.positions()
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/squareoff")
def squareoff(request: Request, execute: bool = False):
    if execute:
        _require_trader(request)
    return orders.square_off_all(dry_run=not execute)


@app.get("/risk")
def risk():
    try:
        if angel.session is not None:
            orders.sync_risk_state()
    except Exception:
        pass
    return risk_engine.snapshot()


@app.post("/kill")
def kill(request: Request):
    _require_trader(request)
    risk_engine.kill("manual kill from dashboard")
    return risk_engine.snapshot()


@app.post("/unkill")
def unkill(request: Request):
    _require_trader(request)
    risk_engine.reset_kill()
    return risk_engine.snapshot()


# serve the dashboard
app.mount("/", StaticFiles(directory="../frontend", html=True), name="static")

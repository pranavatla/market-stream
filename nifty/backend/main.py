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

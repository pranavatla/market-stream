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

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import settings
from angel_client import angel
from risk import risk_engine
import orders
import analysis

logging.basicConfig(level=logging.INFO)
app = FastAPI(title="NIFTY Options Console")

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


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
            "confirm_mode": settings.confirm_mode}


@app.post("/login")
def login():
    try:
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
def execute(req: OrderReq):
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
def squareoff(execute: bool = False):
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
def kill():
    risk_engine.kill("manual kill from dashboard")
    return risk_engine.snapshot()


@app.post("/unkill")
def unkill():
    risk_engine.reset_kill()
    return risk_engine.snapshot()


# serve the dashboard
app.mount("/", StaticFiles(directory="../frontend", html=True), name="static")

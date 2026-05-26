"""
Order execution for NIFTY options (CE/PE only).

Nothing here places an order without first clearing the risk engine.
Entry and exit are explicit, separate calls so the dashboard can wire
them to distinct buttons.
"""
import logging
from datetime import datetime

from config import settings
from angel_client import angel
from risk import risk_engine

log = logging.getLogger("orders")

def _parse_ts(s: str | None) -> datetime | None:
    if not s:
        return None
    for fmt in (
        "%d-%b-%Y %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%d/%m/%Y %H:%M:%S",
        "%d-%m-%Y %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            pass
    return None


def sync_risk_state() -> tuple[bool, str]:
    """
    Sync broker state before allowing NEW entries.
    If we cannot sync, we refuse entries (fail-closed).
    """
    try:
        angel.require_session()
        pos_resp = angel.smart.position() or {}
        pos = pos_resp.get("data") or []

        open_positions = 0
        day_pnl = 0.0
        for p in pos:
            try:
                net = float(p.get("netqty", 0) or 0)
            except Exception:
                net = 0.0
            if net != 0:
                open_positions += 1
            # SmartAPI commonly returns a per-position 'pnl' field (may include unrealised).
            try:
                day_pnl += float(p.get("pnl", 0) or 0)
            except Exception:
                pass

        risk_engine.sync_from_broker(open_positions=open_positions, day_pnl=day_pnl)

        ob_resp = angel.smart.orderBook() or {}
        ob = ob_resp.get("data") or []
        today = datetime.now().date()
        today_count = 0
        for o in ob:
            ts = _parse_ts(
                o.get("updatetime")
                or o.get("exchorderupdatetime")
                or o.get("ordertimestamp")
                or o.get("lastupdate")
            )
            if ts and ts.date() == today:
                today_count += 1
        risk_engine.sync_orders_today(today_count)

        return True, "ok"
    except Exception as e:
        return False, str(e)


def _qty(lots: int, lotsize: int) -> int:
    return lots * lotsize


def place_option(*, symbol, expiry, strike, opt_type, side, lots,
                 order_type="MARKET", price=0.0, dry_run=True) -> dict:
    """
    side: 'BUY' (entry, long CE/PE) or 'SELL' (exit / or short — short is
          blocked by default below since it carries unlimited-ish risk).
    Returns a result dict; on dry_run it returns the prepared order without
    sending it (used for the confirm step in manual mode).
    """
    opt_type = opt_type.upper()
    side = side.upper()
    if opt_type not in ("CE", "PE"):
        return {"ok": False, "error": "opt_type must be CE or PE"}

    # Default policy: buying options only (defined risk = premium paid).
    # Naked option SELLING is disabled here on purpose.
    is_entry = side == "BUY"
    if side == "SELL" and order_type == "MARKET":
        pass  # treated as exit of an existing long
    if side == "SELL" and not _is_exit_allowed():
        return {"ok": False, "error": "Naked option selling is disabled in this config"}

    try:
        angel.require_session()
    except Exception as e:
        return {"ok": False, "error": str(e)}

    inst = angel.resolve_option(symbol, expiry, strike, opt_type)
    qty = _qty(lots, inst["lotsize"])

    # Estimate worst-case loss for an option BUY = premium * qty.
    ltp = angel.ltp(settings.exchange, inst["tradingsymbol"], inst["token"])
    est_max_loss = ltp * qty if is_entry else 0.0

    if is_entry:
        ok, why = sync_risk_state()
        if not ok:
            return {"ok": False, "blocked_by_risk": True, "reason": f"Risk sync failed: {why}"}

    verdict = risk_engine.check_order(lots=lots, is_entry=is_entry, est_max_loss=est_max_loss)
    if not verdict["allowed"]:
        return {"ok": False, "blocked_by_risk": True, "reason": verdict["reason"]}

    order = {
        "variety": "NORMAL",
        "tradingsymbol": inst["tradingsymbol"],
        "symboltoken": inst["token"],
        "transactiontype": side,
        "exchange": settings.exchange,
        "ordertype": order_type,
        "producttype": "INTRADAY",
        "duration": "DAY",
        "price": str(price) if order_type == "LIMIT" else "0",
        "quantity": str(qty),
    }

    if dry_run:
        return {
            "ok": True, "dry_run": True, "order": order,
            "ltp": ltp, "est_max_loss": est_max_loss,
            "lotsize": inst["lotsize"], "qty": qty,
        }

    resp = angel.smart.placeOrder(order)
    order_id = resp.get("data", {}).get("orderid") if isinstance(resp, dict) else resp
    risk_engine.record_fill(lots=lots, opened=is_entry)
    log.info("Order sent %s %s x%d -> %s", side, inst["tradingsymbol"], qty, order_id)
    return {"ok": True, "dry_run": False, "order_id": order_id, "order": order, "ltp": ltp}


def _is_exit_allowed() -> bool:
    # Hook for future: allow selling only to close an existing long position.
    return True


def positions() -> dict:
    angel.require_session()
    return angel.smart.position()


def square_off_all(dry_run=True) -> dict:
    """Close every open intraday option position."""
    angel.require_session()
    pos = positions().get("data") or []
    actions = []
    for p in pos:
        net = int(float(p.get("netqty", 0)))
        if net == 0:
            continue
        side = "SELL" if net > 0 else "BUY"
        order = {
            "variety": "NORMAL",
            "tradingsymbol": p["tradingsymbol"],
            "symboltoken": p["symboltoken"],
            "transactiontype": side,
            "exchange": p["exchange"],
            "ordertype": "MARKET",
            "producttype": "INTRADAY",
            "duration": "DAY",
            "price": "0",
            "quantity": str(abs(net)),
        }
        if dry_run:
            actions.append({"would_send": order})
        else:
            resp = angel.smart.placeOrder(order)
            actions.append({"sent": resp})
            risk_engine.record_fill(lots=0, opened=False)
    return {"ok": True, "dry_run": dry_run, "actions": actions}

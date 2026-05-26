"""
Risk engine — the part that says NO.

Every order proposal passes through check_order() before it can be placed.
Tracks realised + open P&L for the day, counts orders, enforces the kill
switch and the trading window. There is intentionally no code path that
bypasses these limits.
"""
import logging
from datetime import datetime, time as dtime

from config import settings

log = logging.getLogger("risk")


def _parse(hhmm: str) -> dtime:
    h, m = hhmm.split(":")
    return dtime(int(h), int(m))


class RiskEngine:
    def __init__(self):
        self.realised_pnl: float = 0.0
        self.orders_today: int = 0
        self.open_positions: int = 0
        self.killed: bool = False
        self.kill_reason: str = ""
        self.broker_synced_at: str | None = None
        self._day = datetime.now().date()

    def _rollover(self):
        today = datetime.now().date()
        if today != self._day:
            self.realised_pnl = 0.0
            self.orders_today = 0
            self.open_positions = 0
            self.killed = False
            self.kill_reason = ""
            self._day = today

    def kill(self, reason: str):
        self.killed = True
        self.kill_reason = reason
        log.warning("KILL SWITCH ENGAGED: %s", reason)

    def reset_kill(self):
        self.killed = False
        self.kill_reason = ""

    def record_fill(self, lots: int, opened: bool):
        self.orders_today += 1
        self.open_positions += 1 if opened else -1
        self.open_positions = max(0, self.open_positions)

    def record_pnl(self, pnl: float):
        self.realised_pnl += pnl
        r = settings.risk
        if self.realised_pnl <= -abs(r.max_loss_per_day):
            self.kill(f"Daily loss limit hit ({self.realised_pnl:.0f})")

    def sync_from_broker(self, *, open_positions: int, day_pnl: float | None):
        """
        Fail-closed helper: orders.py should sync live broker state before entries.
        We treat broker P&L as the source of truth for day loss checks.
        """
        self._rollover()
        self.open_positions = max(0, int(open_positions))
        if day_pnl is not None:
            self.realised_pnl = float(day_pnl)
            r = settings.risk
            if self.realised_pnl <= -abs(r.max_loss_per_day):
                self.kill(f"Daily loss limit hit ({self.realised_pnl:.0f})")
        self.broker_synced_at = datetime.now().isoformat(timespec="seconds")

    def sync_orders_today(self, orders_today: int):
        self._rollover()
        self.orders_today = max(0, int(orders_today))

    def within_window(self, for_entry: bool) -> tuple[bool, str]:
        now = datetime.now().time()
        r = settings.risk
        if for_entry:
            if now < _parse(r.entry_start):
                return False, f"Before entry window ({r.entry_start})"
            if now >= _parse(r.entry_cutoff):
                return False, f"Past entry cutoff ({r.entry_cutoff})"
        if now >= _parse(r.square_off) and for_entry:
            return False, f"Square-off window ({r.square_off})"
        return True, ""

    def check_order(self, *, lots: int, is_entry: bool, est_max_loss: float) -> dict:
        """Returns {'allowed': bool, 'reason': str}."""
        self._rollover()
        r = settings.risk

        if self.killed:
            return {"allowed": False, "reason": f"Kill switch active: {self.kill_reason}"}

        ok, why = self.within_window(for_entry=is_entry)
        if not ok:
            return {"allowed": False, "reason": why}

        if is_entry:
            if lots > r.max_lots_per_order:
                return {"allowed": False, "reason": f"Lots {lots} > cap {r.max_lots_per_order}"}
            if self.open_positions >= r.max_open_positions:
                return {"allowed": False, "reason": f"Max open positions ({r.max_open_positions}) reached"}
            if self.orders_today >= r.max_orders_per_day:
                return {"allowed": False, "reason": f"Max orders/day ({r.max_orders_per_day}) reached"}
            if est_max_loss > r.max_loss_per_trade:
                return {"allowed": False, "reason": f"Est. risk {est_max_loss:.0f} > per-trade cap {r.max_loss_per_trade:.0f}"}
            if self.realised_pnl - est_max_loss <= -abs(r.max_loss_per_day):
                return {"allowed": False, "reason": "Would breach daily loss limit"}

        return {"allowed": True, "reason": "ok"}

    def snapshot(self) -> dict:
        self._rollover()
        r = settings.risk
        return {
            "realised_pnl": self.realised_pnl,
            "orders_today": self.orders_today,
            "open_positions": self.open_positions,
            "killed": self.killed,
            "kill_reason": self.kill_reason,
            "broker_synced_at": self.broker_synced_at,
            "limits": {
                "max_loss_per_day": r.max_loss_per_day,
                "max_loss_per_trade": r.max_loss_per_trade,
                "max_lots_per_order": r.max_lots_per_order,
                "max_open_positions": r.max_open_positions,
                "max_orders_per_day": r.max_orders_per_day,
                "window": f"{r.entry_start}-{r.entry_cutoff}, square-off {r.square_off}",
            },
        }


risk_engine = RiskEngine()

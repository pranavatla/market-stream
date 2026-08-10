from pydantic import BaseModel
from enum import Enum
from typing import Optional
import time


class Tick(BaseModel):
    symbol: str
    price: float
    open: float
    high: float
    low: float
    volume: int
    timestamp: float

    @property
    def ts_ms(self) -> int:
        return int(self.timestamp * 1000)


class AlertDirection(str, Enum):
    ABOVE = "above"
    BELOW = "below"


class AlertConfig(BaseModel):
    id: Optional[str] = None
    symbol: str
    threshold: float
    direction: AlertDirection
    active: bool = True


class AlertEvent(BaseModel):
    alert_id: str
    symbol: str
    threshold: float
    direction: AlertDirection
    triggered_price: float
    triggered_at: float


class TickSummary(BaseModel):
    symbol: str
    last_price: float
    open: float
    high: float
    low: float
    volume: int
    change: float
    change_pct: float
    tick_count: int

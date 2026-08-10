import uuid
import time
from typing import Dict, List, Optional
from app.models import AlertConfig, AlertEvent, AlertDirection, Tick


class AlertEngine:
    def __init__(self):
        self._alerts: Dict[str, AlertConfig] = {}
        self._last_triggered: Dict[str, float] = {}  # alert_id -> last trigger ts
        self._cooldown = 30.0  # seconds between re-fires of same alert

    def add(self, config: AlertConfig) -> AlertConfig:
        config.id = config.id or str(uuid.uuid4())[:8]
        self._alerts[config.id] = config
        return config

    def remove(self, alert_id: str) -> bool:
        return self._alerts.pop(alert_id, None) is not None

    def list_alerts(self) -> List[AlertConfig]:
        return list(self._alerts.values())

    def evaluate(self, tick: Tick) -> List[AlertEvent]:
        events = []
        now = time.time()
        for alert in self._alerts.values():
            if not alert.active or alert.symbol != tick.symbol:
                continue

            triggered = False
            if alert.direction == AlertDirection.ABOVE and tick.price >= alert.threshold:
                triggered = True
            elif alert.direction == AlertDirection.BELOW and tick.price <= alert.threshold:
                triggered = True

            if triggered:
                last = self._last_triggered.get(alert.id, 0)
                if now - last >= self._cooldown:
                    self._last_triggered[alert.id] = now
                    events.append(AlertEvent(
                        alert_id=alert.id,
                        symbol=alert.symbol,
                        threshold=alert.threshold,
                        direction=alert.direction,
                        triggered_price=tick.price,
                        triggered_at=now,
                    ))
        return events

"""
Central config. All secrets come from environment (.env), never hardcoded.
"""
import os
from dataclasses import dataclass, field
from dotenv import load_dotenv, find_dotenv

# Allow running from `nifty-bot/backend` while keeping `.env` in `nifty-bot/`.
load_dotenv(find_dotenv(usecwd=True))


def _f(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, default))
    except (TypeError, ValueError):
        return default


@dataclass
class AngelCreds:
    api_key: str = os.getenv("ANGEL_API_KEY", "")
    client_id: str = os.getenv("ANGEL_CLIENT_ID", "")
    mpin: str = os.getenv("ANGEL_MPIN", "")
    totp_seed: str = os.getenv("ANGEL_TOTP_SEED", "")

    def validate(self) -> list[str]:
        missing = [k for k, v in {
            "ANGEL_API_KEY": self.api_key,
            "ANGEL_CLIENT_ID": self.client_id,
            "ANGEL_MPIN": self.mpin,
            "ANGEL_TOTP_SEED": self.totp_seed,
        }.items() if not v]
        return missing


@dataclass
class RiskLimits:
    """Hard guardrails. The bot refuses to act outside these — no override in code."""
    max_loss_per_day: float = _f("MAX_LOSS_PER_DAY", 5000.0)       # rupees, absolute
    max_loss_per_trade: float = _f("MAX_LOSS_PER_TRADE", 2000.0)   # rupees
    max_lots_per_order: int = int(_f("MAX_LOTS_PER_ORDER", 2))      # safety cap
    max_open_positions: int = int(_f("MAX_OPEN_POSITIONS", 2))
    max_orders_per_day: int = int(_f("MAX_ORDERS_PER_DAY", 10))
    # Trading window (IST). No entries outside this.
    entry_start: str = os.getenv("ENTRY_START", "09:30")
    entry_cutoff: str = os.getenv("ENTRY_CUTOFF", "15:00")   # no new entries after
    square_off: str = os.getenv("SQUARE_OFF", "15:15")       # force-exit all


@dataclass
class Settings:
    creds: AngelCreds = field(default_factory=AngelCreds)
    risk: RiskLimits = field(default_factory=RiskLimits)
    anthropic_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest")
    # Optional: require a second secret for LIVE actions (execute/kill/squareoff).
    trader_token: str = os.getenv("TRADER_TOKEN", "")
    # NIFTY lot size — verify against current exchange spec before trading
    nifty_lot_size: int = int(_f("NIFTY_LOT_SIZE", 75))
    confirm_mode: str = os.getenv("CONFIRM_MODE", "manual")  # manual | auto
    exchange: str = "NFO"  # NSE F&O segment for options
    build_id: str = os.getenv("BUILD_ID", "")


settings = Settings()

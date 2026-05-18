"""
config.py — Central configuration loader.

Loads settings from .env file and provides validated defaults.
All per-account settings (pair, timeframe, lot size, SL/TP) are stored
in the database and editable from the dashboard GUI.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Load .env from project root
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(PROJECT_ROOT / ".env")

# ---------------------------------------------------------------------------
# Database path
# ---------------------------------------------------------------------------
DB_PATH = PROJECT_ROOT / "trading_bot.db"

# ---------------------------------------------------------------------------
# Timeframe mappings
# ---------------------------------------------------------------------------
TIMEFRAME_SECONDS = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
}

ALLOWED_TIMEFRAMES = list(TIMEFRAME_SECONDS.keys())

# MT5 timeframe constants (mapped at runtime to avoid import at module level)
MT5_TIMEFRAME_MAP = {
    "1m": "TIMEFRAME_M1",
    "5m": "TIMEFRAME_M5",
    "15m": "TIMEFRAME_M15",
    "30m": "TIMEFRAME_M30",
    "1h": "TIMEFRAME_H1",
    "4h": "TIMEFRAME_H4",
    "1d": "TIMEFRAME_D1",
}

# CCXT timeframe strings (already in CCXT format)
CCXT_TIMEFRAME_MAP = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1h",
    "4h": "4h",
    "1d": "1d",
}


# ---------------------------------------------------------------------------
# Global settings (from .env)
# ---------------------------------------------------------------------------
@dataclass
class GlobalSettings:
    """Settings loaded from .env — not per-account."""

    # Encryption
    master_key: str = ""

    # Defaults
    default_timeframe: str = "5m"
    poll_interval_divisor: int = 4  # poll every timeframe/divisor seconds

    # Webhook
    webhook_enabled: bool = False
    webhook_port: int = 8080
    webhook_secret: str = ""

    # Telegram (optional)
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    def __post_init__(self):
        if self.default_timeframe not in ALLOWED_TIMEFRAMES:
            self.default_timeframe = "1h"
        if self.poll_interval_divisor < 1:
            self.poll_interval_divisor = 4

    def get_poll_interval(self, timeframe: str) -> int:
        """Calculate poll interval in seconds for a given timeframe."""
        tf_seconds = TIMEFRAME_SECONDS.get(timeframe, 3600)
        interval = max(tf_seconds // self.poll_interval_divisor, 5)  # minimum 5s
        return interval


def load_global_settings() -> GlobalSettings:
    """Load global settings from environment variables."""
    return GlobalSettings(
        master_key=os.getenv("MASTER_KEY", ""),
        default_timeframe=os.getenv("DEFAULT_TIMEFRAME", "1h"),
        poll_interval_divisor=int(os.getenv("POLL_INTERVAL_DIVISOR", "4")),
        webhook_enabled=os.getenv("WEBHOOK_ENABLED", "false").lower() == "true",
        webhook_port=int(os.getenv("WEBHOOK_PORT", "8080")),
        webhook_secret=os.getenv("WEBHOOK_SECRET", ""),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
    )


# ---------------------------------------------------------------------------
# Per-account strategy defaults (used when creating new accounts)
# ---------------------------------------------------------------------------
DEFAULT_STRATEGY_PARAMS = {
    "hull_mode": "Hma",        # Hma | Ehma | Thma
    "hull_length_160": 160,
    "hull_length_80": 80,
    "atr_length": 2,
    "supertrend_factor": 3.3,
}

DEFAULT_RISK_PARAMS = {
    "lot_size": 0.1,
    "max_positions": 3,
    "stop_loss_pct": 2.0,
    "take_profit_pct": 4.0,
}

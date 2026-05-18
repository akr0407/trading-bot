"""
database.py — SQLite persistence layer.

Tables:
    accounts         — Broker connection profiles (MT5, CCXT)
    account_settings — Per-account trading & strategy parameters
    bot_state        — Kill switch, last candle time, status
    trades           — Executed trade log
    signal_log       — Every indicator calculation (for debugging)
"""

import sqlite3
import json
import logging
from datetime import datetime, timezone
from contextlib import contextmanager
from pathlib import Path

from config import DB_PATH, DEFAULT_STRATEGY_PARAMS, DEFAULT_RISK_PARAMS

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Connection helper
# ---------------------------------------------------------------------------

@contextmanager
def get_connection():
    """Yield a SQLite connection with WAL mode and foreign keys enabled."""
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Schema initialisation
# ---------------------------------------------------------------------------

def init_db():
    """Create all tables if they don't exist."""
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS accounts (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT    NOT NULL,
                broker_type TEXT    NOT NULL CHECK(broker_type IN ('mt5', 'ccxt')),
                credentials TEXT    NOT NULL,
                is_active   INTEGER NOT NULL DEFAULT 0,
                sandbox     INTEGER NOT NULL DEFAULT 1,
                created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS account_settings (
                account_id        INTEGER PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE,
                trading_pair      TEXT    NOT NULL DEFAULT 'EURUSD',
                timeframe         TEXT    NOT NULL DEFAULT '5m',
                htf_timeframe     TEXT    NOT NULL DEFAULT '15m',
                lot_size          REAL    NOT NULL DEFAULT 0.1,
                max_positions     INTEGER NOT NULL DEFAULT 3,
                stop_loss_pct     REAL    NOT NULL DEFAULT 2.0,
                take_profit_pct   REAL    NOT NULL DEFAULT 4.0,
                hull_mode         TEXT    NOT NULL DEFAULT 'Hma',
                hull_length_160   INTEGER NOT NULL DEFAULT 160,
                hull_length_80    INTEGER NOT NULL DEFAULT 80,
                atr_length        INTEGER NOT NULL DEFAULT 2,
                supertrend_factor REAL    NOT NULL DEFAULT 3.3
            );

            CREATE TABLE IF NOT EXISTS bot_state (
                account_id       INTEGER PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE,
                kill_switch      INTEGER NOT NULL DEFAULT 0,
                last_candle_time TEXT,
                status           TEXT    NOT NULL DEFAULT 'stopped',
                last_error       TEXT,
                updated_at       TEXT    NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS trades (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id  INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
                timestamp   TEXT    NOT NULL,
                pair        TEXT    NOT NULL,
                side        TEXT    NOT NULL CHECK(side IN ('BUY', 'SELL')),
                price       REAL    NOT NULL,
                quantity    REAL    NOT NULL,
                pnl         REAL,
                status      TEXT    NOT NULL DEFAULT 'open' CHECK(status IN ('open', 'closed', 'cancelled')),
                order_id    TEXT,
                source      TEXT    NOT NULL DEFAULT 'polling',
                created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS signal_log (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id      INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
                timestamp       TEXT    NOT NULL,
                pair            TEXT    NOT NULL,
                timeframe       TEXT    NOT NULL,
                hull_160        REAL,
                hull_80         REAL,
                hull_160_trend  TEXT,
                hull_80_trend   TEXT,
                supertrend      REAL,
                direction       INTEGER,
                prev_direction  INTEGER,
                htf_direction   INTEGER,
                htf_supertrend  REAL,
                filtered        INTEGER NOT NULL DEFAULT 0,
                signal          TEXT    NOT NULL CHECK(signal IN ('BUY', 'SELL', 'HOLD')),
                created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_trades_account
                ON trades(account_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_signal_log_account
                ON signal_log(account_id, created_at DESC);
        """)

        # ---------------------------------------------------------------
        # Migration: add columns that may not exist in older databases
        # ---------------------------------------------------------------
        _migrate_add_column(conn, "account_settings", "htf_timeframe",
                            "TEXT NOT NULL DEFAULT '15m'")
        _migrate_add_column(conn, "signal_log", "htf_direction", "INTEGER")
        _migrate_add_column(conn, "signal_log", "htf_supertrend", "REAL")
        _migrate_add_column(conn, "signal_log", "filtered",
                            "INTEGER NOT NULL DEFAULT 0")

    logger.info("Database initialised at %s", DB_PATH)


def _migrate_add_column(conn, table: str, column: str, col_type: str):
    """Add a column to a table if it doesn't already exist."""
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
        logger.info("Migration: added %s.%s", table, column)
    except sqlite3.OperationalError:
        pass  # column already exists


# ---------------------------------------------------------------------------
# Account CRUD
# ---------------------------------------------------------------------------

def create_account(name: str, broker_type: str, credentials_token: str,
                   sandbox: bool = True) -> int:
    """
    Create a new account and its related settings/state rows.

    Returns the new account ID.
    """
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO accounts (name, broker_type, credentials, sandbox) VALUES (?, ?, ?, ?)",
            (name, broker_type, credentials_token, int(sandbox)),
        )
        account_id = cur.lastrowid

        # Insert default settings
        conn.execute(
            """INSERT INTO account_settings (
                account_id, trading_pair, timeframe, htf_timeframe, lot_size,
                max_positions, stop_loss_pct, take_profit_pct, hull_mode,
                hull_length_160, hull_length_80, atr_length, supertrend_factor
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                account_id,
                "EURUSD",
                "5m",
                "15m",
                DEFAULT_RISK_PARAMS["lot_size"],
                DEFAULT_RISK_PARAMS["max_positions"],
                DEFAULT_RISK_PARAMS["stop_loss_pct"],
                DEFAULT_RISK_PARAMS["take_profit_pct"],
                DEFAULT_STRATEGY_PARAMS["hull_mode"],
                DEFAULT_STRATEGY_PARAMS["hull_length_160"],
                DEFAULT_STRATEGY_PARAMS["hull_length_80"],
                DEFAULT_STRATEGY_PARAMS["atr_length"],
                DEFAULT_STRATEGY_PARAMS["supertrend_factor"],
            ),
        )

        # Insert default bot state
        conn.execute(
            "INSERT INTO bot_state (account_id) VALUES (?)", (account_id,)
        )

    logger.info("Created account '%s' (id=%d, type=%s)", name, account_id, broker_type)
    return account_id


def get_accounts() -> list[dict]:
    """Return all accounts as a list of dicts."""
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT a.*, s.trading_pair, s.timeframe, b.status, b.kill_switch
               FROM accounts a
               LEFT JOIN account_settings s ON a.id = s.account_id
               LEFT JOIN bot_state b ON a.id = b.account_id
               ORDER BY a.created_at DESC"""
        ).fetchall()
    return [dict(r) for r in rows]


def get_account(account_id: int) -> dict | None:
    """Return a single account by ID, or None."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM accounts WHERE id = ?", (account_id,)
        ).fetchone()
    return dict(row) if row else None


def update_account(account_id: int, **kwargs):
    """Update account fields. Only allowed keys: name, credentials, sandbox."""
    allowed = {"name", "credentials", "sandbox"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [account_id]
    with get_connection() as conn:
        conn.execute(f"UPDATE accounts SET {set_clause} WHERE id = ?", values)


def delete_account(account_id: int):
    """Delete an account and all related data (cascading)."""
    with get_connection() as conn:
        conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
    logger.info("Deleted account id=%d", account_id)


# ---------------------------------------------------------------------------
# Account settings
# ---------------------------------------------------------------------------

def get_account_settings(account_id: int) -> dict | None:
    """Return settings for an account."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM account_settings WHERE account_id = ?", (account_id,)
        ).fetchone()
    return dict(row) if row else None


def update_account_settings(account_id: int, **kwargs):
    """Update any account_settings fields."""
    allowed = {
        "trading_pair", "timeframe", "htf_timeframe", "lot_size",
        "max_positions", "stop_loss_pct", "take_profit_pct", "hull_mode",
        "hull_length_160", "hull_length_80", "atr_length", "supertrend_factor",
    }
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [account_id]
    with get_connection() as conn:
        conn.execute(
            f"UPDATE account_settings SET {set_clause} WHERE account_id = ?", values
        )


# ---------------------------------------------------------------------------
# Bot state
# ---------------------------------------------------------------------------

def get_bot_state(account_id: int) -> dict | None:
    """Return the current bot state for an account."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM bot_state WHERE account_id = ?", (account_id,)
        ).fetchone()
    return dict(row) if row else None


def set_kill_switch(account_id: int, active: bool):
    """Toggle the kill switch for an account."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE bot_state SET kill_switch = ?, updated_at = datetime('now') WHERE account_id = ?",
            (int(active), account_id),
        )
    logger.warning("Kill switch %s for account %d", "ACTIVATED" if active else "deactivated", account_id)


def get_kill_switch(account_id: int) -> bool:
    """Check if the kill switch is active."""
    state = get_bot_state(account_id)
    return bool(state["kill_switch"]) if state else False


def set_bot_status(account_id: int, status: str, error: str | None = None):
    """Update bot running status. status in ('running', 'stopped', 'error')."""
    with get_connection() as conn:
        conn.execute(
            """UPDATE bot_state
               SET status = ?, last_error = ?, updated_at = datetime('now')
               WHERE account_id = ?""",
            (status, error, account_id),
        )


def get_last_candle_time(account_id: int) -> str | None:
    """Get the timestamp of the last processed candle."""
    state = get_bot_state(account_id)
    return state["last_candle_time"] if state else None


def set_last_candle_time(account_id: int, candle_time: str):
    """Store the timestamp of the last processed candle (double-trigger guard)."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE bot_state SET last_candle_time = ?, updated_at = datetime('now') WHERE account_id = ?",
            (candle_time, account_id),
        )


# ---------------------------------------------------------------------------
# Trade log
# ---------------------------------------------------------------------------

def log_trade(account_id: int, pair: str, side: str, price: float,
              quantity: float, order_id: str = None,
              source: str = "polling") -> int:
    """Log an executed trade. Returns the trade row ID."""
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        cur = conn.execute(
            """INSERT INTO trades
               (account_id, timestamp, pair, side, price, quantity, order_id, source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (account_id, now, pair, side, price, quantity, order_id, source),
        )
    return cur.lastrowid


def close_trade(trade_id: int, pnl: float):
    """Mark a trade as closed and record realised PnL."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE trades SET status = 'closed', pnl = ? WHERE id = ?",
            (pnl, trade_id),
        )


def get_trades(account_id: int, limit: int = 50) -> list[dict]:
    """Return recent trades for an account."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM trades WHERE account_id = ? ORDER BY created_at DESC LIMIT ?",
            (account_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def get_open_trades(account_id: int) -> list[dict]:
    """Return all open trades for an account."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM trades WHERE account_id = ? AND status = 'open' ORDER BY created_at DESC",
            (account_id,),
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Signal log
# ---------------------------------------------------------------------------

def log_signal(account_id: int, pair: str, timeframe: str,
               indicators: dict, signal: str,
               htf_indicators: dict | None = None, filtered: bool = False):
    """Log an indicator calculation snapshot with optional HTF context."""
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO signal_log
               (account_id, timestamp, pair, timeframe, hull_160, hull_80,
                hull_160_trend, hull_80_trend, supertrend, direction,
                prev_direction, htf_direction, htf_supertrend, filtered,
                signal)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                account_id, now, pair, timeframe,
                indicators.get("hull_160"),
                indicators.get("hull_80"),
                indicators.get("hull_160_trend"),
                indicators.get("hull_80_trend"),
                indicators.get("supertrend"),
                indicators.get("direction"),
                indicators.get("prev_direction"),
                htf_indicators.get("direction") if htf_indicators else None,
                htf_indicators.get("supertrend") if htf_indicators else None,
                int(filtered),
                signal,
            ),
        )


def get_signals(account_id: int, limit: int = 50) -> list[dict]:
    """Return recent signal log entries."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM signal_log WHERE account_id = ? ORDER BY created_at DESC LIMIT ?",
            (account_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def get_trade_stats(account_id: int) -> dict:
    """Calculate summary statistics for an account's closed trades."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT pnl FROM trades WHERE account_id = ? AND status = 'closed' AND pnl IS NOT NULL",
            (account_id,),
        ).fetchall()

    pnls = [r["pnl"] for r in rows]
    if not pnls:
        return {
            "total_trades": 0, "wins": 0, "losses": 0, "win_rate": 0.0,
            "total_pnl": 0.0, "avg_win": 0.0, "avg_loss": 0.0,
            "profit_factor": 0.0, "max_drawdown": 0.0,
        }

    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    total_wins = sum(wins) if wins else 0.0
    total_losses = abs(sum(losses)) if losses else 0.0

    # Max drawdown (peak-to-trough)
    cumulative = []
    running = 0.0
    for p in pnls:
        running += p
        cumulative.append(running)
    peak = cumulative[0]
    max_dd = 0.0
    for val in cumulative:
        if val > peak:
            peak = val
        dd = peak - val
        if dd > max_dd:
            max_dd = dd

    return {
        "total_trades": len(pnls),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(pnls) * 100 if pnls else 0.0,
        "total_pnl": sum(pnls),
        "avg_win": total_wins / len(wins) if wins else 0.0,
        "avg_loss": total_losses / len(losses) if losses else 0.0,
        "profit_factor": total_wins / total_losses if total_losses > 0 else float("inf"),
        "max_drawdown": max_dd,
    }

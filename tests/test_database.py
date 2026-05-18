"""
tests/test_database.py — Unit tests for database operations.

Tests:
    1. Database initialisation
    2. Account CRUD
    3. Kill switch toggle
    4. Double-trigger prevention (last candle time)
    5. Trade logging
    6. Signal logging
    7. Trade statistics
"""

import os
import pytest
from pathlib import Path

# Override DB path BEFORE importing database module
os.environ["TESTING"] = "1"

import database as db
from config import DB_PATH


# ===================================================================
# Fixtures
# ===================================================================

@pytest.fixture(autouse=True)
def clean_db(tmp_path):
    """Use a temporary database for each test."""
    test_db = tmp_path / "test_trading_bot.db"
    # Monkey-patch the DB_PATH
    original_path = db.DB_PATH
    import config
    config.DB_PATH = test_db
    db.DB_PATH = test_db  # Also update the reference in database module

    # Reinitialize with the test DB
    # We need to patch get_connection too
    original_get_conn = db.get_connection

    from contextlib import contextmanager
    import sqlite3

    @contextmanager
    def test_get_connection():
        conn = sqlite3.connect(str(test_db), timeout=10)
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

    db.get_connection = test_get_connection
    db.init_db()

    yield test_db

    db.get_connection = original_get_conn
    config.DB_PATH = original_path
    db.DB_PATH = original_path


# ===================================================================
# Account CRUD Tests
# ===================================================================

class TestAccountCRUD:

    def test_create_account(self):
        acc_id = db.create_account("Test MT5", "mt5", "encrypted_token")
        assert acc_id > 0

    def test_get_accounts(self):
        db.create_account("Account 1", "mt5", "token1")
        db.create_account("Account 2", "ccxt", "token2")
        accounts = db.get_accounts()
        assert len(accounts) == 2

    def test_get_account_by_id(self):
        acc_id = db.create_account("My Account", "mt5", "token")
        account = db.get_account(acc_id)
        assert account is not None
        assert account["name"] == "My Account"
        assert account["broker_type"] == "mt5"

    def test_update_account(self):
        acc_id = db.create_account("Old Name", "mt5", "token")
        db.update_account(acc_id, name="New Name")
        account = db.get_account(acc_id)
        assert account["name"] == "New Name"

    def test_delete_account(self):
        acc_id = db.create_account("Delete Me", "mt5", "token")
        db.delete_account(acc_id)
        assert db.get_account(acc_id) is None

    def test_delete_cascades(self):
        acc_id = db.create_account("Cascade Test", "mt5", "token")
        # Should have created settings and state rows
        assert db.get_account_settings(acc_id) is not None
        assert db.get_bot_state(acc_id) is not None

        db.delete_account(acc_id)
        assert db.get_account_settings(acc_id) is None
        assert db.get_bot_state(acc_id) is None

    def test_create_account_with_sandbox(self):
        acc_id = db.create_account("Demo", "mt5", "token", sandbox=True)
        account = db.get_account(acc_id)
        assert account["sandbox"] == 1


# ===================================================================
# Account Settings Tests
# ===================================================================

class TestAccountSettings:

    def test_default_settings_created(self):
        acc_id = db.create_account("Test", "mt5", "token")
        settings = db.get_account_settings(acc_id)
        assert settings is not None
        assert settings["trading_pair"] == "EURUSD"
        assert settings["timeframe"] == "5m"
        assert settings["htf_timeframe"] == "15m"
        assert settings["hull_mode"] == "Hma"

    def test_update_settings(self):
        acc_id = db.create_account("Test", "mt5", "token")
        db.update_account_settings(acc_id, trading_pair="GBPUSD", timeframe="4h")
        settings = db.get_account_settings(acc_id)
        assert settings["trading_pair"] == "GBPUSD"
        assert settings["timeframe"] == "4h"


# ===================================================================
# Bot State Tests
# ===================================================================

class TestBotState:

    def test_default_state_created(self):
        acc_id = db.create_account("Test", "mt5", "token")
        state = db.get_bot_state(acc_id)
        assert state is not None
        assert state["kill_switch"] == 0
        assert state["status"] == "stopped"

    def test_kill_switch_toggle(self):
        acc_id = db.create_account("Test", "mt5", "token")

        # Activate
        db.set_kill_switch(acc_id, True)
        assert db.get_kill_switch(acc_id) is True

        # Deactivate
        db.set_kill_switch(acc_id, False)
        assert db.get_kill_switch(acc_id) is False

    def test_bot_status_update(self):
        acc_id = db.create_account("Test", "mt5", "token")
        db.set_bot_status(acc_id, "running")
        state = db.get_bot_state(acc_id)
        assert state["status"] == "running"

    def test_bot_status_with_error(self):
        acc_id = db.create_account("Test", "mt5", "token")
        db.set_bot_status(acc_id, "error", "Connection timeout")
        state = db.get_bot_state(acc_id)
        assert state["status"] == "error"
        assert state["last_error"] == "Connection timeout"

    def test_last_candle_time(self):
        acc_id = db.create_account("Test", "mt5", "token")

        # Initially None
        assert db.get_last_candle_time(acc_id) is None

        # Set and retrieve
        db.set_last_candle_time(acc_id, "2025-01-01T12:00:00+00:00")
        assert db.get_last_candle_time(acc_id) == "2025-01-01T12:00:00+00:00"

        # Update
        db.set_last_candle_time(acc_id, "2025-01-01T13:00:00+00:00")
        assert db.get_last_candle_time(acc_id) == "2025-01-01T13:00:00+00:00"


# ===================================================================
# Trade Log Tests
# ===================================================================

class TestTradeLog:

    def test_log_trade(self):
        acc_id = db.create_account("Test", "mt5", "token")
        trade_id = db.log_trade(acc_id, "EURUSD", "BUY", 1.1050, 0.1, "12345")
        assert trade_id > 0

    def test_get_trades(self):
        acc_id = db.create_account("Test", "mt5", "token")
        db.log_trade(acc_id, "EURUSD", "BUY", 1.1050, 0.1)
        db.log_trade(acc_id, "EURUSD", "SELL", 1.1060, 0.1)
        trades = db.get_trades(acc_id)
        assert len(trades) == 2

    def test_get_open_trades(self):
        acc_id = db.create_account("Test", "mt5", "token")
        trade_id = db.log_trade(acc_id, "EURUSD", "BUY", 1.1050, 0.1)
        open_trades = db.get_open_trades(acc_id)
        assert len(open_trades) == 1

    def test_close_trade(self):
        acc_id = db.create_account("Test", "mt5", "token")
        trade_id = db.log_trade(acc_id, "EURUSD", "BUY", 1.1050, 0.1)
        db.close_trade(trade_id, pnl=25.50)
        trades = db.get_trades(acc_id)
        assert trades[0]["status"] == "closed"
        assert trades[0]["pnl"] == 25.50


# ===================================================================
# Signal Log Tests
# ===================================================================

class TestSignalLog:

    def test_log_signal(self):
        acc_id = db.create_account("Test", "mt5", "token")
        indicators = {
            "hull_160": 1.1050,
            "hull_80": 1.1045,
            "hull_160_trend": "bullish",
            "hull_80_trend": "bullish",
            "supertrend": 1.1000,
            "direction": 1,
            "prev_direction": -1,
        }
        db.log_signal(acc_id, "EURUSD", "5m", indicators, "BUY")
        signals = db.get_signals(acc_id)
        assert len(signals) == 1
        assert signals[0]["signal"] == "BUY"

    def test_log_signal_with_htf_context(self):
        acc_id = db.create_account("Test", "mt5", "token")
        ltf_indicators = {
            "hull_160": 1.1050, "hull_80": 1.1045,
            "hull_160_trend": "bullish", "hull_80_trend": "bullish",
            "supertrend": 1.1000, "direction": 1, "prev_direction": -1,
        }
        htf_indicators = {
            "direction": 1, "supertrend": 1.0950,
        }
        db.log_signal(acc_id, "EURUSD", "5m", ltf_indicators, "BUY",
                       htf_indicators=htf_indicators, filtered=False)
        signals = db.get_signals(acc_id)
        assert len(signals) == 1
        assert signals[0]["htf_direction"] == 1
        assert signals[0]["htf_supertrend"] == 1.0950
        assert signals[0]["filtered"] == 0

    def test_log_signal_filtered(self):
        acc_id = db.create_account("Test", "mt5", "token")
        ltf_indicators = {
            "hull_160": 1.1050, "hull_80": 1.1045,
            "hull_160_trend": "bullish", "hull_80_trend": "bullish",
            "supertrend": 1.1000, "direction": 1, "prev_direction": -1,
        }
        htf_indicators = {"direction": -1, "supertrend": 1.1100}
        db.log_signal(acc_id, "EURUSD", "5m", ltf_indicators, "HOLD",
                       htf_indicators=htf_indicators, filtered=True)
        signals = db.get_signals(acc_id)
        assert signals[0]["filtered"] == 1
        assert signals[0]["htf_direction"] == -1


# ===================================================================
# Trade Stats Tests
# ===================================================================

class TestTradeStats:

    def test_empty_stats(self):
        acc_id = db.create_account("Test", "mt5", "token")
        stats = db.get_trade_stats(acc_id)
        assert stats["total_trades"] == 0
        assert stats["win_rate"] == 0.0

    def test_stats_with_trades(self):
        acc_id = db.create_account("Test", "mt5", "token")

        # Create and close some trades
        t1 = db.log_trade(acc_id, "EURUSD", "BUY", 1.1050, 0.1)
        db.close_trade(t1, pnl=50.0)

        t2 = db.log_trade(acc_id, "EURUSD", "SELL", 1.1060, 0.1)
        db.close_trade(t2, pnl=-20.0)

        t3 = db.log_trade(acc_id, "EURUSD", "BUY", 1.1040, 0.1)
        db.close_trade(t3, pnl=30.0)

        stats = db.get_trade_stats(acc_id)
        assert stats["total_trades"] == 3
        assert stats["wins"] == 2
        assert stats["losses"] == 1
        assert abs(stats["win_rate"] - 66.67) < 0.1
        assert stats["total_pnl"] == 60.0

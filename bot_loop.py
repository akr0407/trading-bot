"""
bot_loop.py — Main polling engine & multi-account bot manager.

Manages one bot thread per active account. Each thread runs the
polling loop: fetch data → calculate indicators → check signal →
execute order → sleep → repeat.

Usage:
    from bot_loop import BotManager
    manager = BotManager()
    manager.start_bot(account_id=1)
    manager.stop_bot(account_id=1)
"""

import logging
import threading
import time
from datetime import datetime, timezone

import pandas as pd

import config
import database as db
from strategy import HullSupertrendStrategy, StrategyParams
from utils.encryption import decrypt_credentials

logger = logging.getLogger(__name__)


# ===================================================================
# Bridge Factory
# ===================================================================

def create_bridge(account: dict, master_key: str):
    """
    Create the appropriate ExchangeBridge for an account.

    Parameters
    ----------
    account : dict
        Account row from database (includes broker_type, credentials, sandbox).
    master_key : str
        The Fernet master key for decrypting credentials.

    Returns
    -------
    ExchangeBridge instance (MT5Bridge or CCXTBridge)
    """
    creds = decrypt_credentials(account["credentials"], master_key)
    broker_type = account["broker_type"]

    if broker_type == "mt5":
        from bridges.mt5_bridge import MT5Bridge
        return MT5Bridge(
            login=creds.get("login", 0),
            password=creds.get("password", ""),
            server=creds.get("server", ""),
            path=creds.get("path"),
        )
    elif broker_type == "ccxt":
        from bridges.ccxt_bridge import CCXTBridge
        return CCXTBridge(
            exchange_name=creds.get("exchange", "binance"),
            api_key=creds.get("api_key", ""),
            api_secret=creds.get("api_secret", ""),
            password=creds.get("password"),
            sandbox=bool(account.get("sandbox", 1)),
        )
    else:
        raise ValueError(f"Unknown broker type: {broker_type}")


# ===================================================================
# Single Account Bot Loop
# ===================================================================

class AccountBot:
    """
    Runs the polling loop for a single account in a dedicated thread.

    Lifecycle:
        1. Connect to broker
        2. Loop: fetch → calculate → signal → execute → sleep
        3. On stop: disconnect, clean up
    """

    def __init__(self, account_id: int, master_key: str):
        self.account_id = account_id
        self.master_key = master_key
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self.bridge = None
        self.strategy = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        """Start the bot loop in a background thread."""
        if self.is_running:
            logger.warning("Bot for account %d is already running", self.account_id)
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name=f"bot-account-{self.account_id}",
            daemon=True,
        )
        self._thread.start()
        db.set_bot_status(self.account_id, "running")
        logger.info("Bot started for account %d", self.account_id)

    def stop(self):
        """Signal the bot to stop gracefully."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=30)
        if self.bridge:
            try:
                self.bridge.disconnect()
            except Exception:
                pass
        self.bridge = None
        self.strategy = None
        db.set_bot_status(self.account_id, "stopped")
        logger.info("Bot stopped for account %d", self.account_id)

    def _run_loop(self):
        """Main polling loop — runs in a background thread."""
        try:
            # -------------------------------------------------------
            # Setup: load account, connect broker, init strategy
            # -------------------------------------------------------
            account = db.get_account(self.account_id)
            if not account:
                logger.error("Account %d not found", self.account_id)
                db.set_bot_status(self.account_id, "error", "Account not found")
                return

            settings = db.get_account_settings(self.account_id)
            if not settings:
                logger.error("Settings for account %d not found", self.account_id)
                db.set_bot_status(self.account_id, "error", "Settings not found")
                return

            # Create bridge and connect
            self.bridge = create_bridge(account, self.master_key)
            if not self.bridge.connect():
                db.set_bot_status(self.account_id, "error", "Failed to connect to broker")
                return

            # Create strategy
            params = StrategyParams.from_settings(settings)
            self.strategy = HullSupertrendStrategy(params)

            trading_pair = settings["trading_pair"]
            ltf = settings["timeframe"]           # entry timeframe (e.g. 5m)
            htf = settings.get("htf_timeframe", "15m")  # trend timeframe

            # Calculate poll interval based on the LTF (entry timeframe)
            global_settings = config.load_global_settings()
            poll_interval = global_settings.get_poll_interval(ltf)

            logger.info(
                "Bot loop started: account=%d pair=%s htf=%s ltf=%s poll=%ds",
                self.account_id, trading_pair, htf, ltf, poll_interval,
            )

            # -------------------------------------------------------
            # Main loop
            # -------------------------------------------------------
            consecutive_errors = 0
            max_consecutive_errors = 10

            while not self._stop_event.is_set():
                try:
                    # --- Step 1: Check kill switch ---
                    if db.get_kill_switch(self.account_id):
                        logger.warning("Kill switch ACTIVE for account %d — halting", self.account_id)
                        db.set_bot_status(self.account_id, "stopped", "Kill switch activated")
                        break

                    # --- Step 2: Reload settings (in case changed from GUI) ---
                    settings = db.get_account_settings(self.account_id)
                    if settings:
                        trading_pair = settings["trading_pair"]
                        ltf = settings["timeframe"]
                        htf = settings.get("htf_timeframe", "15m")
                        params = StrategyParams.from_settings(settings)
                        self.strategy = HullSupertrendStrategy(params)
                        poll_interval = global_settings.get_poll_interval(ltf)

                    # --- Step 3: Fetch OHLCV data for BOTH timeframes ---
                    df_ltf = self.bridge.fetch_ohlcv(trading_pair, ltf, limit=500)
                    df_htf = self.bridge.fetch_ohlcv(trading_pair, htf, limit=500)

                    if df_ltf is None or df_ltf.empty or len(df_ltf) < 50:
                        logger.warning("Insufficient LTF data: %d rows",
                                       len(df_ltf) if df_ltf is not None else 0)
                        self._sleep(poll_interval)
                        continue

                    if df_htf is None or df_htf.empty or len(df_htf) < 50:
                        logger.warning("Insufficient HTF data: %d rows",
                                       len(df_htf) if df_htf is not None else 0)
                        self._sleep(poll_interval)
                        continue

                    # --- Step 4: Double-trigger prevention (LTF candle) ---
                    last_closed_candle_time = str(df_ltf["timestamp"].iloc[-2])
                    stored_candle_time = db.get_last_candle_time(self.account_id)

                    if last_closed_candle_time == stored_candle_time:
                        self._sleep(poll_interval)
                        continue

                    # --- Step 5: Multi-timeframe calculation ---
                    df_ltf_closed = df_ltf.iloc[:-1].copy()
                    df_htf_closed = df_htf.iloc[:-1].copy()
                    result = self.strategy.calculate_mtf(df_htf_closed, df_ltf_closed)

                    signal = result["signal"]
                    ltf_indicators = result["ltf_indicators"]
                    htf_indicators = result["htf_indicators"]
                    filtered = result["filtered"]

                    # --- Step 6: Log signal with HTF context ---
                    db.log_signal(
                        account_id=self.account_id,
                        pair=trading_pair,
                        timeframe=ltf,
                        indicators=ltf_indicators,
                        signal=signal,
                        htf_indicators=htf_indicators,
                        filtered=filtered,
                    )

                    logger.info(
                        "[Account %d] %s %s | HTF(%s) dir:%s | LTF(%s) dir:%s→%s | ST:%.5f%s",
                        self.account_id, trading_pair, signal,
                        htf, htf_indicators.get("direction"),
                        ltf, ltf_indicators.get("prev_direction"),
                        ltf_indicators.get("direction"),
                        ltf_indicators.get("supertrend", 0),
                        " [FILTERED]" if filtered else "",
                    )

                    # --- Step 7: Execute if signal is BUY or SELL ---
                    if signal in ("BUY", "SELL"):
                        self._execute_signal(signal, trading_pair, settings)

                    # --- Step 8: Update last candle time ---
                    db.set_last_candle_time(self.account_id, last_closed_candle_time)

                    # Reset error counter on success
                    consecutive_errors = 0

                except ConnectionError as e:
                    consecutive_errors += 1
                    logger.error("Connection error (account %d, %d/%d): %s",
                                 self.account_id, consecutive_errors, max_consecutive_errors, e)
                    if consecutive_errors >= max_consecutive_errors:
                        db.set_bot_status(self.account_id, "error",
                                          f"Too many connection errors: {e}")
                        break
                    # Try to reconnect
                    try:
                        self.bridge.connect()
                    except Exception:
                        pass

                except Exception as e:
                    consecutive_errors += 1
                    logger.exception("Bot loop error (account %d, %d/%d): %s",
                                     self.account_id, consecutive_errors, max_consecutive_errors, e)
                    if consecutive_errors >= max_consecutive_errors:
                        db.set_bot_status(self.account_id, "error",
                                          f"Too many errors: {e}")
                        break

                # --- Step 9: Sleep until next poll ---
                self._sleep(poll_interval)

        except Exception as e:
            logger.exception("Fatal error in bot loop for account %d: %s", self.account_id, e)
            db.set_bot_status(self.account_id, "error", str(e))

        finally:
            if self.bridge:
                try:
                    self.bridge.disconnect()
                except Exception:
                    pass

    def _execute_signal(self, signal: str, pair: str, settings: dict):
        """Execute a BUY or SELL signal with risk management checks."""
        lot_size = settings.get("lot_size", 0.1)
        max_positions = settings.get("max_positions", 3)
        sl_pct = settings.get("stop_loss_pct", 0)
        tp_pct = settings.get("take_profit_pct", 0)

        # --- Risk check: max open positions ---
        open_trades = db.get_open_trades(self.account_id)
        if len(open_trades) >= max_positions:
            logger.info("Max positions reached (%d/%d) — skipping %s signal",
                        len(open_trades), max_positions, signal)
            return

        # --- Skip if we already have a same-direction position for this pair ---
        same_side = [t for t in open_trades
                     if t["pair"] == pair and t["side"] == signal]
        if same_side:
            # Already in the right direction — don't stack
            return

        # --- Close opposite positions if signal reverses ---
        for trade in open_trades:
            if trade["pair"] == pair and trade["side"] != signal:
                logger.info("Closing opposite %s position before %s", trade["side"], signal)
                if trade.get("order_id"):
                    close_result = self.bridge.close_position(trade["order_id"])
                    if close_result.get("success"):
                        db.close_trade(trade["id"], close_result.get("pnl", 0))

        # --- Calculate SL/TP prices ---
        sl_price = None
        tp_price = None
        try:
            balance_info = self.bridge.get_balance()
            tick = None

            # Get current price for SL/TP calculation
            positions_or_tick = self.bridge.get_positions()
            symbol_info = self.bridge.get_symbol_info(pair)

            if symbol_info and sl_pct > 0:
                # Fetch current price
                df_latest = self.bridge.fetch_ohlcv(pair, "1m", limit=1)
                if df_latest is not None and not df_latest.empty:
                    current_price = df_latest["close"].iloc[-1]
                    point = symbol_info.get("point", 0.00001)

                    if signal == "BUY":
                        sl_price = current_price * (1 - sl_pct / 100)
                        if tp_pct > 0:
                            tp_price = current_price * (1 + tp_pct / 100)
                    else:  # SELL
                        sl_price = current_price * (1 + sl_pct / 100)
                        if tp_pct > 0:
                            tp_price = current_price * (1 - tp_pct / 100)

                    # Round to symbol's digit precision
                    digits = symbol_info.get("digits", 5)
                    sl_price = round(sl_price, digits) if sl_price else None
                    tp_price = round(tp_price, digits) if tp_price else None

        except Exception as e:
            logger.warning("SL/TP calculation error: %s — proceeding without", e)

        # --- Place the order ---
        result = self.bridge.place_order(
            pair=pair,
            side=signal,
            volume=lot_size,
            sl=sl_price,
            tp=tp_price,
        )

        if result.get("success"):
            db.log_trade(
                account_id=self.account_id,
                pair=pair,
                side=signal,
                price=result.get("price", 0),
                quantity=lot_size,
                order_id=result.get("order_id"),
                source="polling",
            )
            logger.info("Trade executed: %s %s %.4f lots @ %.5f (SL: %s, TP: %s)",
                        signal, pair, lot_size, result.get("price", 0), sl_price, tp_price)
        else:
            logger.error("Trade FAILED: %s %s — %s",
                         signal, pair, result.get("message", "Unknown error"))

    def _sleep(self, seconds: int):
        """Sleep in small increments so we can respond to stop events quickly."""
        for _ in range(seconds):
            if self._stop_event.is_set():
                break
            time.sleep(1)


# ===================================================================
# Bot Manager — manages multiple account bots
# ===================================================================

class BotManager:
    """
    Manages bot instances for multiple accounts.

    Usage:
        manager = BotManager()
        manager.start_bot(account_id=1)
        manager.stop_bot(account_id=1)
        manager.stop_all()
    """

    def __init__(self):
        self._bots: dict[int, AccountBot] = {}
        self._lock = threading.Lock()
        self._settings = config.load_global_settings()

    def start_bot(self, account_id: int) -> tuple[bool, str]:
        """
        Start the bot for an account.

        Returns (success: bool, message: str)
        """
        with self._lock:
            if account_id in self._bots and self._bots[account_id].is_running:
                return False, f"Bot for account {account_id} is already running"

            if not self._settings.master_key:
                return False, "MASTER_KEY not set in .env — cannot decrypt credentials"

            # Verify account exists
            account = db.get_account(account_id)
            if not account:
                return False, f"Account {account_id} not found"

            # Deactivate kill switch if it was on
            db.set_kill_switch(account_id, False)

            bot = AccountBot(account_id, self._settings.master_key)
            bot.start()
            self._bots[account_id] = bot

            # Mark account as active
            with db.get_connection() as conn:
                conn.execute(
                    "UPDATE accounts SET is_active = 1 WHERE id = ?",
                    (account_id,),
                )

            return True, f"Bot started for account {account_id}"

    def stop_bot(self, account_id: int) -> tuple[bool, str]:
        """Stop the bot for an account."""
        with self._lock:
            bot = self._bots.get(account_id)
            if not bot or not bot.is_running:
                db.set_bot_status(account_id, "stopped")
                return False, f"Bot for account {account_id} is not running"

            bot.stop()
            self._bots.pop(account_id, None)

            # Mark account as inactive
            with db.get_connection() as conn:
                conn.execute(
                    "UPDATE accounts SET is_active = 0 WHERE id = ?",
                    (account_id,),
                )

            return True, f"Bot stopped for account {account_id}"

    def kill_bot(self, account_id: int) -> tuple[bool, str]:
        """Activate kill switch and stop the bot immediately."""
        db.set_kill_switch(account_id, True)
        return self.stop_bot(account_id)

    def get_status(self, account_id: int) -> dict:
        """Get the current status of a bot."""
        bot = self._bots.get(account_id)
        state = db.get_bot_state(account_id)
        return {
            "account_id": account_id,
            "is_running": bot.is_running if bot else False,
            "status": state.get("status", "stopped") if state else "stopped",
            "kill_switch": bool(state.get("kill_switch", 0)) if state else False,
            "last_candle_time": state.get("last_candle_time") if state else None,
            "last_error": state.get("last_error") if state else None,
        }

    def get_all_statuses(self) -> list[dict]:
        """Get status for all known accounts."""
        accounts = db.get_accounts()
        return [self.get_status(a["id"]) for a in accounts]

    def stop_all(self):
        """Stop all running bots."""
        with self._lock:
            for account_id in list(self._bots.keys()):
                try:
                    self._bots[account_id].stop()
                except Exception as e:
                    logger.error("Error stopping bot %d: %s", account_id, e)
            self._bots.clear()
        logger.info("All bots stopped")


# ===================================================================
# Singleton manager (shared across Streamlit sessions)
# ===================================================================

_manager_instance: BotManager | None = None
_manager_lock = threading.Lock()


def get_bot_manager() -> BotManager:
    """Get or create the global BotManager singleton."""
    global _manager_instance
    with _manager_lock:
        if _manager_instance is None:
            _manager_instance = BotManager()
        return _manager_instance

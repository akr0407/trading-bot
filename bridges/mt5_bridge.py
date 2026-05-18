"""
bridges/mt5_bridge.py — MetaTrader 5 broker adapter.

Works with ANY MT5 broker (Finex, ICMarkets, Exness, FXTM, etc.).
Auto-detects the correct filling mode per broker.

Requirements:
    - MT5 terminal must be installed and running on the machine
    - pip install MetaTrader5
"""

import time
import logging
from datetime import datetime, timezone

import pandas as pd

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False

from exchange_bridge import ExchangeBridge
from config import MT5_TIMEFRAME_MAP

logger = logging.getLogger(__name__)

# Map our timeframe strings to MT5 constants
_TF_MAP = {}
if MT5_AVAILABLE:
    _TF_MAP = {
        "1m": mt5.TIMEFRAME_M1,
        "5m": mt5.TIMEFRAME_M5,
        "15m": mt5.TIMEFRAME_M15,
        "30m": mt5.TIMEFRAME_M30,
        "1h": mt5.TIMEFRAME_H1,
        "4h": mt5.TIMEFRAME_H4,
        "1d": mt5.TIMEFRAME_D1,
    }


class MT5Bridge(ExchangeBridge):
    """
    MetaTrader 5 broker adapter.

    Usage:
        bridge = MT5Bridge(
            login=12345678,
            password="your_password",
            server="Finex-Demo",
        )
        bridge.connect()
        df = bridge.fetch_ohlcv("EURUSD", "1h", 500)
    """

    MAX_RETRIES = 3
    RETRY_DELAY = 2  # seconds

    def __init__(self, login: int, password: str, server: str,
                 path: str | None = None):
        """
        Parameters
        ----------
        login    : MT5 account number
        password : MT5 account password
        server   : Broker server name (e.g., "Finex-Demo", "ICMarketsSC-Demo")
        path     : Optional path to MT5 terminal executable
        """
        if not MT5_AVAILABLE:
            raise ImportError(
                "MetaTrader5 package not installed. Run: pip install MetaTrader5\n"
                "Note: MT5 Python library only works on Windows."
            )
        self.login = int(login)
        self.password = str(password)
        self.server = str(server)
        self.path = path
        self._connected = False

    def connect(self) -> bool:
        """Initialise MT5 and log into the account."""
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                # Initialise MT5 terminal
                init_kwargs = {}
                if self.path:
                    init_kwargs["path"] = self.path

                if not mt5.initialize(**init_kwargs):
                    error = mt5.last_error()
                    logger.error("MT5 initialize failed (attempt %d/%d): %s",
                                 attempt, self.MAX_RETRIES, error)
                    if attempt < self.MAX_RETRIES:
                        time.sleep(self.RETRY_DELAY * attempt)
                        continue
                    return False

                # Wait for the terminal's IPC channel to be ready.
                # Without this delay, the first login attempt often fails
                # with "IPC timeout" (-10005) on some brokers/setups.
                time.sleep(1)

                # Login to the account
                if not mt5.login(
                    login=self.login,
                    password=self.password,
                    server=self.server,
                ):
                    error = mt5.last_error()
                    logger.error("MT5 login failed (attempt %d/%d): %s",
                                 attempt, self.MAX_RETRIES, error)
                    mt5.shutdown()
                    if attempt < self.MAX_RETRIES:
                        time.sleep(self.RETRY_DELAY * attempt)
                        continue
                    return False

                # Success
                info = mt5.account_info()
                self._connected = True
                logger.info(
                    "MT5 connected: Account #%d @ %s | Balance: %.2f %s",
                    info.login, info.server, info.balance, info.currency,
                )
                return True

            except Exception as e:
                logger.exception("MT5 connect error (attempt %d/%d): %s",
                                 attempt, self.MAX_RETRIES, e)
                if attempt < self.MAX_RETRIES:
                    time.sleep(self.RETRY_DELAY * attempt)

        return False

    def disconnect(self) -> None:
        """Shutdown the MT5 connection."""
        if MT5_AVAILABLE:
            mt5.shutdown()
        self._connected = False
        logger.info("MT5 disconnected")

    def is_connected(self) -> bool:
        """Check if MT5 terminal is responsive."""
        if not self._connected:
            return False
        try:
            info = mt5.terminal_info()
            return info is not None and info.connected
        except Exception:
            self._connected = False
            return False

    def _ensure_connected(self):
        """Reconnect if connection was lost."""
        if not self.is_connected():
            logger.warning("MT5 connection lost — attempting reconnect...")
            self.connect()
            if not self.is_connected():
                raise ConnectionError("Failed to reconnect to MT5")

    def fetch_ohlcv(self, pair: str, timeframe: str, limit: int = 500) -> pd.DataFrame:
        """Fetch OHLCV candles from MT5."""
        self._ensure_connected()

        tf = _TF_MAP.get(timeframe)
        if tf is None:
            raise ValueError(f"Unsupported timeframe: {timeframe}")

        # Ensure symbol is visible in Market Watch
        if not mt5.symbol_select(pair, True):
            raise ValueError(f"Symbol '{pair}' not found or cannot be selected")

        rates = mt5.copy_rates_from_pos(pair, tf, 0, limit)
        if rates is None or len(rates) == 0:
            error = mt5.last_error()
            raise RuntimeError(f"Failed to fetch OHLCV for {pair}: {error}")

        df = pd.DataFrame(rates)
        df["timestamp"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df = df.rename(columns={
            "open": "open",
            "high": "high",
            "low": "low",
            "close": "close",
            "tick_volume": "volume",  # MT5 uses tick_volume for forex
        })
        df = df[["timestamp", "open", "high", "low", "close", "volume"]]
        return df

    def get_balance(self) -> dict:
        """Get account balance information."""
        self._ensure_connected()
        info = mt5.account_info()
        if info is None:
            raise RuntimeError("Failed to get account info")
        return {
            "balance": info.balance,
            "equity": info.equity,
            "margin": info.margin,
            "free_margin": info.margin_free,
            "profit": info.profit,
            "currency": info.currency,
            "leverage": info.leverage,
        }

    def get_positions(self) -> list[dict]:
        """Get all open positions."""
        self._ensure_connected()
        positions = mt5.positions_get()
        if positions is None:
            return []

        result = []
        for pos in positions:
            result.append({
                "ticket": pos.ticket,
                "pair": pos.symbol,
                "side": "BUY" if pos.type == mt5.ORDER_TYPE_BUY else "SELL",
                "volume": pos.volume,
                "open_price": pos.price_open,
                "current_price": pos.price_current,
                "profit": pos.profit,
                "sl": pos.sl,
                "tp": pos.tp,
                "open_time": datetime.fromtimestamp(pos.time, tz=timezone.utc).isoformat(),
                "magic": pos.magic,
                "comment": pos.comment,
            })
        return result

    def _detect_filling_mode(self, pair: str) -> int:
        """
        Auto-detect the correct filling mode for a broker.

        Different MT5 brokers support different filling modes:
        - IOC (Immediate Or Cancel) — most common
        - FOK (Fill Or Kill)
        - RETURN
        """
        info = mt5.symbol_info(pair)
        if info is None:
            return mt5.ORDER_FILLING_IOC  # fallback

        filling = info.filling_mode

        if filling & mt5.SYMBOL_FILLING_FOK:
            return mt5.ORDER_FILLING_FOK
        elif filling & mt5.SYMBOL_FILLING_IOC:
            return mt5.ORDER_FILLING_IOC
        else:
            return mt5.ORDER_FILLING_RETURN

    def place_order(self, pair: str, side: str, volume: float,
                    sl: float | None = None, tp: float | None = None) -> dict:
        """Place a market order."""
        self._ensure_connected()

        # Ensure symbol is available
        if not mt5.symbol_select(pair, True):
            return {"success": False, "order_id": None, "price": 0,
                    "message": f"Symbol '{pair}' not available"}

        # Get current price
        tick = mt5.symbol_info_tick(pair)
        if tick is None:
            return {"success": False, "order_id": None, "price": 0,
                    "message": "Failed to get price tick"}

        order_type = mt5.ORDER_TYPE_BUY if side.upper() == "BUY" else mt5.ORDER_TYPE_SELL
        price = tick.ask if side.upper() == "BUY" else tick.bid

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": pair,
            "volume": float(volume),
            "type": order_type,
            "price": price,
            "deviation": 20,  # slippage tolerance in points
            "magic": 202505,  # unique bot identifier
            "comment": "TradingBot",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": self._detect_filling_mode(pair),
        }

        if sl is not None:
            request["sl"] = float(sl)
        if tp is not None:
            request["tp"] = float(tp)

        # Send order with retry
        for attempt in range(1, self.MAX_RETRIES + 1):
            result = mt5.order_send(request)

            if result is None:
                error = mt5.last_error()
                logger.error("Order send returned None (attempt %d): %s", attempt, error)
                if attempt < self.MAX_RETRIES:
                    time.sleep(self.RETRY_DELAY)
                    # Refresh price before retry
                    tick = mt5.symbol_info_tick(pair)
                    if tick:
                        request["price"] = tick.ask if side.upper() == "BUY" else tick.bid
                    continue
                return {"success": False, "order_id": None, "price": 0,
                        "message": f"Order send failed: {error}"}

            if result.retcode == mt5.TRADE_RETCODE_DONE:
                logger.info(
                    "Order executed: %s %s %.4f lots @ %.5f (ticket: %d)",
                    side, pair, volume, result.price, result.order,
                )
                return {
                    "success": True,
                    "order_id": str(result.order),
                    "price": result.price,
                    "message": "Order executed successfully",
                }

            logger.warning(
                "Order failed (attempt %d, retcode=%d): %s",
                attempt, result.retcode, result.comment,
            )
            if attempt < self.MAX_RETRIES:
                time.sleep(self.RETRY_DELAY)
                tick = mt5.symbol_info_tick(pair)
                if tick:
                    request["price"] = tick.ask if side.upper() == "BUY" else tick.bid

        return {
            "success": False,
            "order_id": None,
            "price": 0,
            "message": f"Order failed after {self.MAX_RETRIES} attempts: {result.comment}",
        }

    def close_position(self, ticket: int | str) -> dict:
        """Close a specific position by ticket number."""
        self._ensure_connected()
        ticket = int(ticket)

        # Find the position
        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            return {"success": False, "price": 0, "pnl": 0,
                    "message": f"Position {ticket} not found"}

        pos = positions[0]
        close_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
        tick = mt5.symbol_info_tick(pos.symbol)
        if tick is None:
            return {"success": False, "price": 0, "pnl": 0,
                    "message": "Failed to get price for close"}

        price = tick.bid if pos.type == mt5.ORDER_TYPE_BUY else tick.ask

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": pos.symbol,
            "volume": pos.volume,
            "type": close_type,
            "position": ticket,
            "price": price,
            "deviation": 20,
            "magic": 202505,
            "comment": "TradingBot Close",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": self._detect_filling_mode(pos.symbol),
        }

        result = mt5.order_send(request)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            logger.info("Position %d closed @ %.5f (PnL: %.2f)",
                        ticket, result.price, pos.profit)
            return {
                "success": True,
                "price": result.price,
                "pnl": pos.profit,
                "message": "Position closed",
            }

        msg = result.comment if result else str(mt5.last_error())
        return {"success": False, "price": 0, "pnl": 0, "message": msg}

    def close_all_positions(self, pair: str | None = None) -> list[dict]:
        """Close all open positions, optionally filtered by symbol."""
        self._ensure_connected()

        if pair:
            positions = mt5.positions_get(symbol=pair)
        else:
            positions = mt5.positions_get()

        if not positions:
            return []

        results = []
        for pos in positions:
            result = self.close_position(pos.ticket)
            results.append(result)
        return results

    def get_symbol_info(self, pair: str) -> dict | None:
        """Get symbol metadata."""
        self._ensure_connected()

        if not mt5.symbol_select(pair, True):
            return None

        info = mt5.symbol_info(pair)
        if info is None:
            return None

        return {
            "name": info.name,
            "min_lot": info.volume_min,
            "max_lot": info.volume_max,
            "lot_step": info.volume_step,
            "point": info.point,
            "digits": info.digits,
            "spread": info.spread,
            "trade_mode": info.trade_mode,
            "currency_base": info.currency_base,
            "currency_profit": info.currency_profit,
        }

    def get_available_symbols(self) -> list[str]:
        """Get all available trading symbols from the broker."""
        self._ensure_connected()
        symbols = mt5.symbols_get()
        if symbols is None:
            return []
        return sorted([s.name for s in symbols if s.visible])

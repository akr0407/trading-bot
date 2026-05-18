"""
bridges/ccxt_bridge.py — CCXT exchange adapter (Binance, Bybit, OKX, etc.)

This is a STUB prepared for future use. The interface is fully implemented
but marked for Phase 2 completion. Swap in by setting broker_type='ccxt'
on an account.
"""

import time
import logging
from datetime import datetime, timezone

import pandas as pd

try:
    import ccxt
    CCXT_AVAILABLE = True
except ImportError:
    CCXT_AVAILABLE = False

from exchange_bridge import ExchangeBridge
from config import CCXT_TIMEFRAME_MAP

logger = logging.getLogger(__name__)


class CCXTBridge(ExchangeBridge):
    """
    CCXT exchange adapter.

    Supports any CCXT-compatible exchange (Binance, Bybit, OKX, etc.)

    Usage:
        bridge = CCXTBridge(
            exchange_name="binance",
            api_key="...",
            api_secret="...",
            sandbox=True,
        )
        bridge.connect()
        df = bridge.fetch_ohlcv("BTC/USDT", "1h", 500)
    """

    MAX_RETRIES = 3
    RETRY_DELAY = 2

    def __init__(self, exchange_name: str, api_key: str, api_secret: str,
                 password: str | None = None, sandbox: bool = True):
        if not CCXT_AVAILABLE:
            raise ImportError(
                "CCXT package not installed. Run: pip install ccxt"
            )

        self.exchange_name = exchange_name.lower()
        self.api_key = api_key
        self.api_secret = api_secret
        self.password = password
        self.sandbox = sandbox
        self.exchange = None
        self._connected = False

    def connect(self) -> bool:
        """Initialise the CCXT exchange connection."""
        try:
            exchange_class = getattr(ccxt, self.exchange_name, None)
            if exchange_class is None:
                logger.error("Exchange '%s' not supported by CCXT", self.exchange_name)
                return False

            self.exchange = exchange_class({
                "apiKey": self.api_key,
                "secret": self.api_secret,
                "password": self.password,
                "enableRateLimit": True,
                "options": {"defaultType": "spot"},
            })

            if self.sandbox:
                self.exchange.set_sandbox_mode(True)
                logger.info("CCXT sandbox mode enabled for %s", self.exchange_name)

            # Test connection by loading markets
            self.exchange.load_markets()
            self._connected = True

            balance = self.exchange.fetch_balance()
            logger.info(
                "CCXT connected: %s | Free USDT: %s",
                self.exchange_name,
                balance.get("free", {}).get("USDT", "N/A"),
            )
            return True

        except Exception as e:
            logger.exception("CCXT connect error: %s", e)
            return False

    def disconnect(self) -> None:
        """Close the CCXT connection."""
        self.exchange = None
        self._connected = False
        logger.info("CCXT disconnected from %s", self.exchange_name)

    def is_connected(self) -> bool:
        """Check if the exchange instance is initialised."""
        return self._connected and self.exchange is not None

    def _ensure_connected(self):
        """Reconnect if needed."""
        if not self.is_connected():
            logger.warning("CCXT connection lost — reconnecting...")
            self.connect()
            if not self.is_connected():
                raise ConnectionError(f"Failed to connect to {self.exchange_name}")

    def fetch_ohlcv(self, pair: str, timeframe: str, limit: int = 500) -> pd.DataFrame:
        """Fetch OHLCV candles from the exchange."""
        self._ensure_connected()

        tf = CCXT_TIMEFRAME_MAP.get(timeframe, timeframe)

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                ohlcv = self.exchange.fetch_ohlcv(pair, tf, limit=limit)
                break
            except Exception as e:
                logger.warning("CCXT fetch_ohlcv attempt %d failed: %s", attempt, e)
                if attempt == self.MAX_RETRIES:
                    raise
                time.sleep(self.RETRY_DELAY * attempt)

        df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        return df

    def get_balance(self) -> dict:
        """Get account balance."""
        self._ensure_connected()
        balance = self.exchange.fetch_balance()
        total = balance.get("total", {})
        free = balance.get("free", {})
        return {
            "balance": sum(total.values()) if total else 0,
            "equity": sum(total.values()) if total else 0,
            "margin": 0,
            "free_margin": sum(free.values()) if free else 0,
            "profit": 0,
            "currency": "USDT",
            "leverage": 1,
        }

    def get_positions(self) -> list[dict]:
        """Get open positions (for futures/margin)."""
        self._ensure_connected()
        try:
            positions = self.exchange.fetch_positions()
        except Exception:
            return []

        result = []
        for pos in positions:
            if float(pos.get("contracts", 0)) == 0:
                continue
            result.append({
                "ticket": pos.get("id", ""),
                "pair": pos.get("symbol", ""),
                "side": pos.get("side", "").upper(),
                "volume": float(pos.get("contracts", 0)),
                "open_price": float(pos.get("entryPrice", 0)),
                "current_price": float(pos.get("markPrice", 0)),
                "profit": float(pos.get("unrealizedPnl", 0)),
                "sl": None,
                "tp": None,
                "open_time": pos.get("timestamp", ""),
            })
        return result

    def place_order(self, pair: str, side: str, volume: float,
                    sl: float | None = None, tp: float | None = None) -> dict:
        """Place a market order."""
        self._ensure_connected()

        try:
            order = self.exchange.create_market_order(
                symbol=pair,
                side=side.lower(),
                amount=volume,
            )

            logger.info(
                "CCXT order executed: %s %s %.6f @ %s (id: %s)",
                side, pair, volume, order.get("average", "market"), order.get("id"),
            )

            return {
                "success": True,
                "order_id": str(order.get("id", "")),
                "price": float(order.get("average", 0) or order.get("price", 0) or 0),
                "message": "Order executed",
            }

        except Exception as e:
            logger.error("CCXT order failed: %s", e)
            return {
                "success": False,
                "order_id": None,
                "price": 0,
                "message": str(e),
            }

    def close_position(self, ticket: int | str) -> dict:
        """Close a position (for futures). For spot, sell the asset."""
        # Futures close would need opposite order
        return {"success": False, "price": 0, "pnl": 0,
                "message": "CCXT close_position: implement per exchange type"}

    def close_all_positions(self, pair: str | None = None) -> list[dict]:
        """Close all positions."""
        positions = self.get_positions()
        results = []
        for pos in positions:
            if pair and pos["pair"] != pair:
                continue
            # Place opposite order to close
            opposite = "SELL" if pos["side"] == "BUY" else "BUY"
            result = self.place_order(pos["pair"], opposite, pos["volume"])
            result["pnl"] = pos["profit"]
            results.append(result)
        return results

    def get_symbol_info(self, pair: str) -> dict | None:
        """Get symbol metadata from CCXT."""
        self._ensure_connected()
        try:
            self.exchange.load_markets()
            market = self.exchange.market(pair)
            if market is None:
                return None
            limits = market.get("limits", {})
            amount = limits.get("amount", {})
            return {
                "name": market.get("symbol", pair),
                "min_lot": amount.get("min", 0),
                "max_lot": amount.get("max", 0),
                "lot_step": market.get("precision", {}).get("amount", 0),
                "point": market.get("precision", {}).get("price", 0),
                "digits": market.get("precision", {}).get("price", 8),
                "spread": 0,
            }
        except Exception as e:
            logger.error("CCXT get_symbol_info error: %s", e)
            return None

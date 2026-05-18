"""
exchange_bridge.py — Abstract base class for broker/exchange adapters.

All broker integrations (MT5, CCXT) implement this interface so the
bot loop and dashboard can work with any broker without code changes.
"""

from abc import ABC, abstractmethod
import pandas as pd


class ExchangeBridge(ABC):
    """
    Unified interface for broker/exchange operations.

    Implementations:
        - bridges/mt5_bridge.py  → MetaTrader 5 (any broker: Finex, ICMarkets, etc.)
        - bridges/ccxt_bridge.py → CCXT (Binance, Bybit, OKX, etc.)
    """

    @abstractmethod
    def connect(self) -> bool:
        """
        Establish connection to the broker/exchange.
        Returns True if successful.
        """
        ...

    @abstractmethod
    def disconnect(self) -> None:
        """Close the connection gracefully."""
        ...

    @abstractmethod
    def is_connected(self) -> bool:
        """Check if the connection is still alive."""
        ...

    @abstractmethod
    def fetch_ohlcv(self, pair: str, timeframe: str, limit: int = 500) -> pd.DataFrame:
        """
        Fetch historical OHLCV candle data.

        Returns DataFrame with columns:
            timestamp (datetime), open, high, low, close, volume
        """
        ...

    @abstractmethod
    def get_balance(self) -> dict:
        """
        Get account balance info.

        Returns dict with keys: balance, equity, margin, free_margin, profit
        """
        ...

    @abstractmethod
    def get_positions(self) -> list[dict]:
        """
        Get open positions.

        Returns list of dicts, each with:
            ticket, pair, side, volume, open_price, current_price,
            profit, sl, tp, open_time
        """
        ...

    @abstractmethod
    def place_order(self, pair: str, side: str, volume: float,
                    sl: float | None = None, tp: float | None = None) -> dict:
        """
        Place a market order.

        Parameters
        ----------
        pair : str       — Trading pair/symbol
        side : str       — 'BUY' or 'SELL'
        volume : float   — Lot size
        sl : float       — Stop loss price (optional)
        tp : float       — Take profit price (optional)

        Returns dict with: success (bool), order_id (str), price (float), message (str)
        """
        ...

    @abstractmethod
    def close_position(self, ticket: int | str) -> dict:
        """
        Close a specific position by ticket/ID.

        Returns dict with: success (bool), price (float), pnl (float), message (str)
        """
        ...

    @abstractmethod
    def close_all_positions(self, pair: str | None = None) -> list[dict]:
        """
        Close all open positions, optionally filtered by pair.

        Returns list of close results.
        """
        ...

    @abstractmethod
    def get_symbol_info(self, pair: str) -> dict | None:
        """
        Get symbol/pair metadata.

        Returns dict with: min_lot, max_lot, lot_step, point, digits, spread
        Or None if symbol not found.
        """
        ...

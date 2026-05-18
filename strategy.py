"""
strategy.py — Hull Suite + Supertrend signal engine.

Translates the "Kaya" PineScript indicator into pure Python/pandas_ta.
This module has NO side effects — it takes a DataFrame of OHLCV data
and returns a signal dict. Easy to test, easy to swap.

PineScript source: feed/pinescript.md
"""

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd
import pandas_ta as ta

logger = logging.getLogger(__name__)


# ===================================================================
# Hull Moving Average Variants
# ===================================================================

def hma(src: pd.Series, length: int) -> pd.Series:
    """
    Hull Moving Average.

    PineScript equivalent:
        HMA(_src, _length) =>
            ta.wma(2 * ta.wma(_src, _length/2) - ta.wma(_src, _length),
                   math.round(math.sqrt(_length)))
    """
    half_len = max(int(length / 2), 1)
    sqrt_len = max(round(np.sqrt(length)), 1)

    wma_half = ta.wma(src, length=half_len)
    wma_full = ta.wma(src, length=length)
    return ta.wma(2 * wma_half - wma_full, length=sqrt_len)


def ehma(src: pd.Series, length: int) -> pd.Series:
    """
    Exponential Hull Moving Average.

    PineScript equivalent:
        EHMA(_src, _length) =>
            ta.ema(2 * ta.ema(_src, _length/2) - ta.ema(_src, _length),
                   math.round(math.sqrt(_length)))
    """
    half_len = max(int(length / 2), 1)
    sqrt_len = max(round(np.sqrt(length)), 1)

    ema_half = ta.ema(src, length=half_len)
    ema_full = ta.ema(src, length=length)
    return ta.ema(2 * ema_half - ema_full, length=sqrt_len)


def thma(src: pd.Series, length: int) -> pd.Series:
    """
    Triple Hull Moving Average.

    PineScript equivalent:
        THMA(_src, _length) =>
            ta.wma(ta.wma(_src, _length/3)*3
                   - ta.wma(_src, _length/2)
                   - ta.wma(_src, _length), _length)
    """
    third_len = max(int(length / 3), 1)
    half_len = max(int(length / 2), 1)

    wma_third = ta.wma(src, length=third_len)
    wma_half = ta.wma(src, length=half_len)
    wma_full = ta.wma(src, length=length)
    return ta.wma(wma_third * 3 - wma_half - wma_full, length=length)


def hull_mode(mode: str, src: pd.Series, length: int) -> pd.Series:
    """
    Select Hull MA variant.

    PineScript equivalent:
        Mode(_mode, _src, _length) =>
            if _mode == "Ehma"  → EHMA(_src, _length)
            else if "Thma"     → THMA(_src, _length / 2)   ← note: /2 here
            else               → HMA(_src, _length)
    """
    if mode == "Ehma":
        return ehma(src, length)
    elif mode == "Thma":
        # PineScript passes length/2 to THMA in the Mode() function
        return thma(src, length // 2)
    else:  # "Hma" (default)
        return hma(src, length)


# ===================================================================
# Strategy Class
# ===================================================================

@dataclass
class StrategyParams:
    """Parameters matching the PineScript inputs."""
    hull_mode_name: str = "Hma"       # "Hma" | "Ehma" | "Thma"
    hull_length_160: int = 160
    hull_length_80: int = 80
    atr_length: int = 2
    supertrend_factor: float = 3.3

    @classmethod
    def from_settings(cls, settings: dict) -> "StrategyParams":
        """Create from account_settings dict (database row)."""
        return cls(
            hull_mode_name=settings.get("hull_mode", "Hma"),
            hull_length_160=settings.get("hull_length_160", 160),
            hull_length_80=settings.get("hull_length_80", 80),
            atr_length=settings.get("atr_length", 2),
            supertrend_factor=settings.get("supertrend_factor", 3.3),
        )


class HullSupertrendStrategy:
    """
    Translates the "Kaya" PineScript indicator to Python.

    Calculates:
        1. Hull Suite (160 & 80) — trend direction of the Hull MA
        2. Supertrend — trend direction + reversal signals
        3. Signal — BUY/SELL on Supertrend direction change

    Usage:
        strategy = HullSupertrendStrategy(params)
        result = strategy.calculate(df)
        # result['signal'] → 'BUY' | 'SELL' | 'HOLD'
        # result['indicators'] → dict of all computed values
    """

    def __init__(self, params: StrategyParams | None = None):
        self.params = params or StrategyParams()

    def calculate(self, df: pd.DataFrame) -> dict:
        """
        Run the full indicator stack on OHLCV data.

        Parameters
        ----------
        df : pd.DataFrame
            Must have columns: open, high, low, close, volume
            Should have at least 500 rows for indicator warmup.

        Returns
        -------
        dict with keys:
            'signal'     : 'BUY' | 'SELL' | 'HOLD'
            'indicators' : {
                'hull_160': float,       # Current Hull 160 value
                'hull_80': float,        # Current Hull 80 value
                'hull_160_trend': str,   # 'bullish' | 'bearish'
                'hull_80_trend': str,    # 'bullish' | 'bearish'
                'supertrend': float,     # Current Supertrend line value
                'direction': int,        # 1 (uptrend) or -1 (downtrend)
                'prev_direction': int,   # Previous bar's direction
            }
        """
        if len(df) < 50:
            logger.warning("Insufficient data: %d rows (need >= 50)", len(df))
            return {
                "signal": "HOLD",
                "indicators": self._empty_indicators(),
            }

        p = self.params
        close = df["close"]

        # -----------------------------------------------------------------
        # 1. Hull Suite
        # -----------------------------------------------------------------
        # Hull 160
        hull_160_series = hull_mode(p.hull_mode_name, close, p.hull_length_160)
        # MHULL160 = current bar, SHULL160 = 2 bars ago
        mhull_160 = hull_160_series.iloc[-1] if hull_160_series is not None else np.nan
        shull_160 = hull_160_series.iloc[-3] if (hull_160_series is not None and len(hull_160_series) >= 3) else np.nan
        hull_160_trend = "bullish" if mhull_160 > shull_160 else "bearish"

        # Hull 80
        hull_80_series = hull_mode(p.hull_mode_name, close, p.hull_length_80)
        mhull_80 = hull_80_series.iloc[-1] if hull_80_series is not None else np.nan
        shull_80 = hull_80_series.iloc[-3] if (hull_80_series is not None and len(hull_80_series) >= 3) else np.nan
        hull_80_trend = "bullish" if mhull_80 > shull_80 else "bearish"

        # -----------------------------------------------------------------
        # 2. Supertrend
        # -----------------------------------------------------------------
        st_df = df.ta.supertrend(
            length=p.atr_length,
            multiplier=p.supertrend_factor,
        )

        if st_df is None or st_df.empty:
            logger.warning("Supertrend calculation returned empty")
            return {
                "signal": "HOLD",
                "indicators": self._empty_indicators(),
            }

        # Column names generated by pandas_ta
        dir_col = f"SUPERTd_{p.atr_length}_{p.supertrend_factor}"
        st_col = f"SUPERT_{p.atr_length}_{p.supertrend_factor}"

        # Fallback: find columns by prefix if exact name doesn't match
        if dir_col not in st_df.columns:
            dir_cols = [c for c in st_df.columns if c.startswith("SUPERTd_")]
            st_cols = [c for c in st_df.columns if c.startswith("SUPERT_")]
            dir_col = dir_cols[0] if dir_cols else None
            st_col = st_cols[0] if st_cols else None

        if dir_col is None or st_col is None:
            logger.error("Could not find Supertrend columns in %s", list(st_df.columns))
            return {
                "signal": "HOLD",
                "indicators": self._empty_indicators(),
            }

        direction_series = st_df[dir_col]
        supertrend_series = st_df[st_col]

        # Current and previous direction
        # pandas_ta convention: 1 = uptrend (bullish), -1 = downtrend (bearish)
        curr_direction = int(direction_series.iloc[-1]) if not pd.isna(direction_series.iloc[-1]) else 0
        prev_direction = int(direction_series.iloc[-2]) if len(direction_series) >= 2 and not pd.isna(direction_series.iloc[-2]) else 0
        curr_supertrend = float(supertrend_series.iloc[-1]) if not pd.isna(supertrend_series.iloc[-1]) else 0.0

        # -----------------------------------------------------------------
        # 3. Signal generation
        # -----------------------------------------------------------------
        # PineScript:
        #   bullTrigger = direction[1] > direction  → downtrend→uptrend
        #   bearTrigger = direction[1] < direction  → uptrend→downtrend
        #
        # In PineScript, direction < 0 = uptrend, > 0 = downtrend
        # In pandas_ta,  direction  1  = uptrend, -1  = downtrend
        #
        # BUY:  prev was downtrend (-1), now uptrend (1)
        # SELL: prev was uptrend (1), now downtrend (-1)

        signal = "HOLD"
        if prev_direction == -1 and curr_direction == 1:
            signal = "BUY"
        elif prev_direction == 1 and curr_direction == -1:
            signal = "SELL"

        indicators = {
            "hull_160": round(mhull_160, 5) if not np.isnan(mhull_160) else None,
            "hull_80": round(mhull_80, 5) if not np.isnan(mhull_80) else None,
            "hull_160_trend": hull_160_trend,
            "hull_80_trend": hull_80_trend,
            "supertrend": round(curr_supertrend, 5),
            "direction": curr_direction,
            "prev_direction": prev_direction,
        }

        if signal != "HOLD":
            logger.info("Signal: %s | Direction: %d → %d | ST: %.5f",
                        signal, prev_direction, curr_direction, curr_supertrend)

        return {"signal": signal, "indicators": indicators}

    def calculate_mtf(self, df_htf: pd.DataFrame, df_ltf: pd.DataFrame) -> dict:
        """
        Multi-timeframe signal: trade when both timeframes agree on trend.

        Logic:
            1. Run indicators on HTF (e.g. 15m) → get Supertrend direction
            2. Run indicators on LTF (e.g. 5m) → get Supertrend direction
            3. If both directions match → trade in that direction:
               - Both bullish (1)  → BUY
               - Both bearish (-1) → SELL
               - Disagree          → HOLD

        Parameters
        ----------
        df_htf : pd.DataFrame
            Higher-timeframe OHLCV data (e.g. 15m).
        df_ltf : pd.DataFrame
            Lower-timeframe OHLCV data (e.g. 5m).

        Returns
        -------
        dict with keys:
            'signal'         : 'BUY' | 'SELL' | 'HOLD'
            'htf_indicators' : dict (HTF indicator values)
            'ltf_indicators' : dict (LTF indicator values)
            'filtered'       : bool (True if trends disagree)
        """
        htf_result = self.calculate(df_htf)
        ltf_result = self.calculate(df_ltf)

        htf_direction = htf_result["indicators"].get("direction", 0)
        ltf_direction = ltf_result["indicators"].get("direction", 0)

        filtered = False
        final_signal = "HOLD"

        if htf_direction == 1 and ltf_direction == 1:
            # Both bullish → BUY
            final_signal = "BUY"
        elif htf_direction == -1 and ltf_direction == -1:
            # Both bearish → SELL
            final_signal = "SELL"
        else:
            # Trends disagree → no trade
            filtered = True
            logger.info(
                "MTF trends disagree: HTF dir=%d, LTF dir=%d → HOLD",
                htf_direction, ltf_direction,
            )

        if final_signal != "HOLD":
            logger.info(
                "MTF aligned: %s | HTF dir: %d | LTF dir: %d",
                final_signal, htf_direction, ltf_direction,
            )

        return {
            "signal": final_signal,
            "htf_indicators": htf_result["indicators"],
            "ltf_indicators": ltf_result["indicators"],
            "filtered": filtered,
        }

    @staticmethod
    def _empty_indicators() -> dict:
        """Return an indicator dict with all None values."""
        return {
            "hull_160": None, "hull_80": None,
            "hull_160_trend": None, "hull_80_trend": None,
            "supertrend": None, "direction": None, "prev_direction": None,
        }

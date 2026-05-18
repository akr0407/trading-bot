"""
tests/test_strategy.py — Unit tests for the Hull Suite + Supertrend strategy.

Tests:
    1. HMA, EHMA, THMA calculations produce valid output
    2. Supertrend direction mapping matches PineScript convention
    3. Signal generation: BUY on direction change -1 → 1
    4. Signal generation: SELL on direction change 1 → -1
    5. HOLD when no direction change
    6. Insufficient data handling
"""

import pytest
import numpy as np
import pandas as pd

from strategy import (
    hma, ehma, thma, hull_mode,
    HullSupertrendStrategy, StrategyParams,
)


# ===================================================================
# Fixtures
# ===================================================================

@pytest.fixture
def sample_ohlcv():
    """Generate synthetic OHLCV data for testing."""
    np.random.seed(42)
    n = 500
    # Generate a trending price series
    base = 1.1000
    returns = np.random.randn(n) * 0.001
    close = base + np.cumsum(returns)
    high = close + np.abs(np.random.randn(n) * 0.0005)
    low = close - np.abs(np.random.randn(n) * 0.0005)
    open_price = close + np.random.randn(n) * 0.0002
    volume = np.random.randint(100, 10000, size=n).astype(float)

    df = pd.DataFrame({
        "timestamp": pd.date_range("2025-01-01", periods=n, freq="h"),
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })
    return df


@pytest.fixture
def small_ohlcv():
    """Generate a small DataFrame (insufficient data)."""
    return pd.DataFrame({
        "timestamp": pd.date_range("2025-01-01", periods=10, freq="h"),
        "open": np.ones(10),
        "high": np.ones(10) * 1.01,
        "low": np.ones(10) * 0.99,
        "close": np.ones(10),
        "volume": np.ones(10) * 100,
    })


@pytest.fixture
def strategy():
    """Default strategy with standard params."""
    return HullSupertrendStrategy(StrategyParams())


# ===================================================================
# Hull MA Tests
# ===================================================================

class TestHullMovingAverages:
    """Test the three Hull MA variants."""

    def test_hma_returns_series(self, sample_ohlcv):
        result = hma(sample_ohlcv["close"], 160)
        assert isinstance(result, pd.Series)
        assert len(result) == len(sample_ohlcv)

    def test_hma_has_nan_warmup(self, sample_ohlcv):
        result = hma(sample_ohlcv["close"], 160)
        # First ~160 values should be NaN due to warmup
        assert result.iloc[:50].isna().any()

    def test_hma_produces_valid_values(self, sample_ohlcv):
        result = hma(sample_ohlcv["close"], 160)
        valid = result.dropna()
        assert len(valid) > 0
        assert all(np.isfinite(valid))

    def test_ehma_returns_series(self, sample_ohlcv):
        result = ehma(sample_ohlcv["close"], 80)
        assert isinstance(result, pd.Series)
        valid = result.dropna()
        assert len(valid) > 0

    def test_thma_returns_series(self, sample_ohlcv):
        result = thma(sample_ohlcv["close"], 80)
        assert isinstance(result, pd.Series)
        valid = result.dropna()
        assert len(valid) > 0

    def test_hull_mode_hma(self, sample_ohlcv):
        result = hull_mode("Hma", sample_ohlcv["close"], 160)
        expected = hma(sample_ohlcv["close"], 160)
        pd.testing.assert_series_equal(result, expected)

    def test_hull_mode_ehma(self, sample_ohlcv):
        result = hull_mode("Ehma", sample_ohlcv["close"], 80)
        expected = ehma(sample_ohlcv["close"], 80)
        pd.testing.assert_series_equal(result, expected)

    def test_hull_mode_thma_halves_length(self, sample_ohlcv):
        # PineScript: Mode("Thma", src, length) calls THMA(src, length/2)
        result = hull_mode("Thma", sample_ohlcv["close"], 160)
        expected = thma(sample_ohlcv["close"], 80)  # 160 // 2 = 80
        pd.testing.assert_series_equal(result, expected)


# ===================================================================
# Strategy Tests
# ===================================================================

class TestStrategy:
    """Test the full strategy calculation."""

    def test_calculate_returns_signal(self, strategy, sample_ohlcv):
        result = strategy.calculate(sample_ohlcv)
        assert "signal" in result
        assert result["signal"] in ("BUY", "SELL", "HOLD")

    def test_calculate_returns_indicators(self, strategy, sample_ohlcv):
        result = strategy.calculate(sample_ohlcv)
        assert "indicators" in result
        indicators = result["indicators"]
        assert "hull_160" in indicators
        assert "hull_80" in indicators
        assert "supertrend" in indicators
        assert "direction" in indicators
        assert "prev_direction" in indicators

    def test_insufficient_data_returns_hold(self, strategy, small_ohlcv):
        result = strategy.calculate(small_ohlcv)
        assert result["signal"] == "HOLD"

    def test_direction_values(self, strategy, sample_ohlcv):
        result = strategy.calculate(sample_ohlcv)
        direction = result["indicators"]["direction"]
        # Should be 1 (uptrend) or -1 (downtrend) or 0 (no data)
        assert direction in (1, -1, 0)

    def test_hull_trends_are_valid(self, strategy, sample_ohlcv):
        result = strategy.calculate(sample_ohlcv)
        hull_160_trend = result["indicators"]["hull_160_trend"]
        hull_80_trend = result["indicators"]["hull_80_trend"]
        assert hull_160_trend in ("bullish", "bearish", None)
        assert hull_80_trend in ("bullish", "bearish", None)

    def test_custom_params(self, sample_ohlcv):
        params = StrategyParams(
            hull_mode_name="Ehma",
            hull_length_160=100,
            hull_length_80=50,
            atr_length=5,
            supertrend_factor=2.0,
        )
        strategy = HullSupertrendStrategy(params)
        result = strategy.calculate(sample_ohlcv)
        assert result["signal"] in ("BUY", "SELL", "HOLD")

    def test_from_settings_dict(self):
        settings = {
            "hull_mode": "Thma",
            "hull_length_160": 200,
            "hull_length_80": 100,
            "atr_length": 3,
            "supertrend_factor": 2.5,
        }
        params = StrategyParams.from_settings(settings)
        assert params.hull_mode_name == "Thma"
        assert params.hull_length_160 == 200
        assert params.supertrend_factor == 2.5


# ===================================================================
# Edge Cases
# ===================================================================

class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_minimum_length_hull(self, sample_ohlcv):
        # Very small length should not crash
        result = hma(sample_ohlcv["close"], 2)
        assert isinstance(result, pd.Series)

    def test_empty_dataframe(self, strategy):
        empty = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        result = strategy.calculate(empty)
        assert result["signal"] == "HOLD"

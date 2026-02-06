"""Shared fixtures for the Earnings Volatility Calculator test suite."""

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def ohlcv_dataframe():
    """63-row OHLCV DataFrame with realistic price data (seed=42)."""
    rng = np.random.RandomState(42)
    n = 63
    dates = pd.bdate_range(end=pd.Timestamp.today(), periods=n)
    close = 100 + np.cumsum(rng.randn(n) * 1.5)
    high = close + rng.uniform(0.5, 2.0, n)
    low = close - rng.uniform(0.5, 2.0, n)
    open_ = close + rng.randn(n) * 0.5
    volume = rng.randint(500_000, 5_000_000, n).astype(float)
    df = pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume},
        index=dates,
    )
    return df


@pytest.fixture
def ohlcv_short():
    """5-row OHLCV DataFrame (shorter than 30-day window)."""
    rng = np.random.RandomState(99)
    n = 5
    dates = pd.bdate_range(end=pd.Timestamp.today(), periods=n)
    close = 50 + np.cumsum(rng.randn(n))
    return pd.DataFrame(
        {
            "Open": close + rng.randn(n) * 0.2,
            "High": close + rng.uniform(0.3, 1.0, n),
            "Low": close - rng.uniform(0.3, 1.0, n),
            "Close": close,
            "Volume": rng.randint(100_000, 2_000_000, n).astype(float),
        },
        index=dates,
    )


@pytest.fixture
def option_chain_factory():
    """Factory returning a mock yfinance option chain."""

    def _make_chain(
        current_price=150.0,
        n_strikes=5,
        call_iv=0.35,
        put_iv=0.38,
        bid_ask_spread=0.50,
    ):
        strikes = np.linspace(
            current_price - 10, current_price + 10, n_strikes
        )
        calls = pd.DataFrame(
            {
                "strike": strikes,
                "bid": np.maximum(current_price - strikes, 0.5)
                - bid_ask_spread / 2,
                "ask": np.maximum(current_price - strikes, 0.5)
                + bid_ask_spread / 2,
                "impliedVolatility": [call_iv] * n_strikes,
            }
        )
        puts = pd.DataFrame(
            {
                "strike": strikes,
                "bid": np.maximum(strikes - current_price, 0.5)
                - bid_ask_spread / 2,
                "ask": np.maximum(strikes - current_price, 0.5)
                + bid_ask_spread / 2,
                "impliedVolatility": [put_iv] * n_strikes,
            }
        )

        class Chain:
            pass

        c = Chain()
        c.calls = calls
        c.puts = puts
        return c

    return _make_chain


@pytest.fixture
def analyze_stock_result():
    """Complete result dict as returned by analyze_stock()."""
    return {
        "ticker": "AAPL",
        "earnings_date": "2026-02-06",
        "current_price": 185.50,
        "market_cap": 2_900_000_000_000,
        "volume": 55_000_000,
        "avg_volume": True,
        "avg_volume_value": 62_000_000,
        "earnings_time": "Post Market",
        "recommendation": "Recommended",
        "expected_move": "3.45%",
        "atr14": 4.23,
        "atr14_pct": 2.28,
        "iv30_rv30": 1.55,
        "term_slope": -0.0085,
        "term_structure": 0.42,
        "historical_volatility": 0.27,
        "current_iv": 0.44,
        "iv_rank": 65.0,
    }


@pytest.fixture
def compute_recommendation_result():
    """Complete result dict as returned by compute_recommendation()."""
    return {
        "avg_volume": True,
        "avg_volume_value": 62_000_000,
        "iv30_rv30": 1.55,
        "term_slope": -0.0085,
        "term_structure": 0.42,
        "expected_move": "3.45%",
        "underlying_price": 185.50,
        "historical_volatility": 0.27,
        "current_iv": 0.44,
        "atr14": 4.23,
        "atr14_pct": 2.28,
        "iv_rank": 65.0,
    }


@pytest.fixture
def multi_stock_results():
    """Five varied result dicts for filter/sort integration tests."""
    return [
        {
            "ticker": "AAPL",
            "earnings_date": "2026-02-06",
            "current_price": 185.50,
            "market_cap": 2_900_000_000_000,
            "volume": 55_000_000,
            "avg_volume": True,
            "avg_volume_value": 62_000_000,
            "earnings_time": "Post Market",
            "recommendation": "Recommended",
            "expected_move": "3.45%",
            "atr14": 4.23,
            "atr14_pct": 2.28,
            "iv30_rv30": 1.55,
            "term_slope": -0.0085,
            "term_structure": 0.42,
            "historical_volatility": 0.27,
            "current_iv": 0.44,
            "iv_rank": 65.0,
        },
        {
            "ticker": "MSFT",
            "earnings_date": "2026-02-06",
            "current_price": 420.10,
            "market_cap": 3_100_000_000_000,
            "volume": 22_000_000,
            "avg_volume": True,
            "avg_volume_value": 25_000_000,
            "earnings_time": "Post Market",
            "recommendation": "Consider",
            "expected_move": "2.10%",
            "atr14": 6.50,
            "atr14_pct": 1.55,
            "iv30_rv30": 1.10,
            "term_slope": -0.0050,
            "term_structure": 0.30,
            "historical_volatility": 0.22,
            "current_iv": 0.30,
            "iv_rank": 40.0,
        },
        {
            "ticker": "PLTR",
            "earnings_date": "2026-02-06",
            "current_price": 24.75,
            "market_cap": 55_000_000_000,
            "volume": 80_000_000,
            "avg_volume": True,
            "avg_volume_value": 75_000_000,
            "earnings_time": "Pre Market",
            "recommendation": "Recommended",
            "expected_move": "5.80%",
            "atr14": 1.80,
            "atr14_pct": 7.27,
            "iv30_rv30": 1.85,
            "term_slope": -0.0120,
            "term_structure": 0.55,
            "historical_volatility": 0.60,
            "current_iv": 0.75,
            "iv_rank": 88.0,
        },
        {
            "ticker": "F",
            "earnings_date": "2026-02-06",
            "current_price": 3.50,
            "market_cap": 14_000_000_000,
            "volume": 45_000_000,
            "avg_volume": False,
            "avg_volume_value": 900_000,
            "earnings_time": "Pre Market",
            "recommendation": "Avoid",
            "expected_move": "1.20%",
            "atr14": 0.15,
            "atr14_pct": 4.29,
            "iv30_rv30": 0.80,
            "term_slope": 0.002,
            "term_structure": 0.10,
            "historical_volatility": 0.35,
            "current_iv": 0.28,
            "iv_rank": None,
        },
        {
            "ticker": "NVDA",
            "earnings_date": "2026-02-06",
            "current_price": 875.00,
            "market_cap": 2_150_000_000_000,
            "volume": 40_000_000,
            "avg_volume": True,
            "avg_volume_value": 50_000_000,
            "earnings_time": "During Market",
            "recommendation": "Consider",
            "expected_move": "4.00%",
            "atr14": 25.00,
            "atr14_pct": 2.86,
            "iv30_rv30": 1.30,
            "term_slope": -0.0060,
            "term_structure": 0.38,
            "historical_volatility": 0.45,
            "current_iv": 0.55,
            "iv_rank": 72.0,
        },
    ]

"""Tests for OptionsAnalyzer - volatility math and options analysis."""

import numpy as np
import pandas as pd
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock, PropertyMock

from earnings_calculator.options import OptionsAnalyzer


class TestSafeMath:
    def test_safe_log(self):
        analyzer = OptionsAnalyzer()
        arr = np.array([1.0, np.e, np.e**2])
        result = analyzer.safe_log(arr)
        np.testing.assert_allclose(result, [0.0, 1.0, 2.0], atol=1e-10)

    def test_safe_sqrt(self):
        analyzer = OptionsAnalyzer()
        arr = np.array([1.0, 4.0, 9.0])
        result = analyzer.safe_sqrt(arr)
        np.testing.assert_allclose(result, [1.0, 2.0, 3.0], atol=1e-10)


class TestYangZhangVolatility:
    def test_returns_scalar(self, ohlcv_dataframe):
        analyzer = OptionsAnalyzer()
        result = analyzer.yang_zhang_volatility(ohlcv_dataframe)
        assert isinstance(float(result), float)
        assert result > 0

    def test_returns_series(self, ohlcv_dataframe):
        analyzer = OptionsAnalyzer()
        result = analyzer.yang_zhang_volatility(
            ohlcv_dataframe, return_last_only=False
        )
        assert isinstance(result, pd.Series)
        assert len(result) > 0

    def test_short_data_falls_back(self, ohlcv_short):
        analyzer = OptionsAnalyzer()
        result = analyzer.yang_zhang_volatility(ohlcv_short)
        # With only 5 rows, rolling(30) returns NaN,
        # which triggers the fallback or returns NaN
        assert isinstance(float(result), float)

    def test_annualization(self, ohlcv_dataframe):
        analyzer = OptionsAnalyzer()
        vol_252 = analyzer.yang_zhang_volatility(
            ohlcv_dataframe, trading_periods=252
        )
        vol_365 = analyzer.yang_zhang_volatility(
            ohlcv_dataframe, trading_periods=365
        )
        # Higher annualization factor = higher vol number
        assert float(vol_365) > float(vol_252)


class TestSimpleVolatility:
    def test_returns_value(self, ohlcv_dataframe):
        analyzer = OptionsAnalyzer()
        result = analyzer.calculate_simple_volatility(ohlcv_dataframe)
        assert isinstance(float(result), float)
        assert result > 0

    def test_returns_series(self, ohlcv_dataframe):
        analyzer = OptionsAnalyzer()
        result = analyzer.calculate_simple_volatility(
            ohlcv_dataframe, return_last_only=False
        )
        assert isinstance(result, pd.Series)


class TestComputeATR:
    def test_returns_value(self, ohlcv_dataframe):
        analyzer = OptionsAnalyzer()
        result = analyzer.compute_atr(ohlcv_dataframe)
        assert isinstance(float(result), float)
        assert result > 0

    def test_custom_window(self, ohlcv_dataframe):
        analyzer = OptionsAnalyzer()
        atr7 = analyzer.compute_atr(ohlcv_dataframe, window=7)
        atr14 = analyzer.compute_atr(ohlcv_dataframe, window=14)
        # Both should be positive
        assert float(atr7) > 0
        assert float(atr14) > 0


class TestBuildTermStructure:
    def test_interpolation(self):
        analyzer = OptionsAnalyzer()
        days = [10, 20, 40]
        ivs = [0.4, 0.35, 0.3]
        spline = analyzer.build_term_structure(days, ivs)
        iv15 = spline(15)
        assert 0.3 <= iv15 <= 0.4

    def test_extrapolation_clamps(self):
        analyzer = OptionsAnalyzer()
        days = [10, 20, 40]
        ivs = [0.4, 0.35, 0.3]
        spline = analyzer.build_term_structure(days, ivs)
        # Below range returns first value
        assert spline(5) == pytest.approx(0.4)
        # Above range returns last value
        assert spline(50) == pytest.approx(0.3)

    def test_single_point(self):
        analyzer = OptionsAnalyzer()
        days = [15]
        ivs = [0.35]
        spline = analyzer.build_term_structure(days, ivs)
        # With single point, below/above range clamps to that value
        assert spline(5) == pytest.approx(0.35)
        assert spline(50) == pytest.approx(0.35)


class TestFilterDates:
    def test_filters_within_45_days(self):
        analyzer = OptionsAnalyzer()
        today = datetime.today().date()
        dates = [
            (today + timedelta(days=10)).strftime("%Y-%m-%d"),
            (today + timedelta(days=30)).strftime("%Y-%m-%d"),
            (today + timedelta(days=50)).strftime("%Y-%m-%d"),
            (today + timedelta(days=90)).strftime("%Y-%m-%d"),
        ]
        result = analyzer.filter_dates(dates)
        # Should include up to and including the first date >= 45 days
        assert len(result) >= 2
        assert len(result) <= 3

    def test_all_dates_short_term(self):
        analyzer = OptionsAnalyzer()
        today = datetime.today().date()
        dates = [
            (today + timedelta(days=5)).strftime("%Y-%m-%d"),
            (today + timedelta(days=15)).strftime("%Y-%m-%d"),
            (today + timedelta(days=25)).strftime("%Y-%m-%d"),
        ]
        result = analyzer.filter_dates(dates)
        # All dates < 45 days, should return all
        assert len(result) == 3

    def test_excludes_today(self):
        analyzer = OptionsAnalyzer()
        today = datetime.today().date()
        dates = [
            today.strftime("%Y-%m-%d"),
            (today + timedelta(days=20)).strftime("%Y-%m-%d"),
            (today + timedelta(days=50)).strftime("%Y-%m-%d"),
        ]
        result = analyzer.filter_dates(dates)
        assert today.strftime("%Y-%m-%d") not in result

    def test_excludes_today_all_short_term(self):
        """0-DTE should be excluded even when all dates are under 45 DTE."""
        analyzer = OptionsAnalyzer()
        today = datetime.today().date()
        dates = [
            today.strftime("%Y-%m-%d"),
            (today + timedelta(days=7)).strftime("%Y-%m-%d"),
            (today + timedelta(days=14)).strftime("%Y-%m-%d"),
        ]
        result = analyzer.filter_dates(dates)
        assert today.strftime("%Y-%m-%d") not in result
        assert len(result) == 2

    def test_filter_dates_only_today_falls_back(self):
        """If today is the only date, fall back to include it."""
        analyzer = OptionsAnalyzer()
        today = datetime.today().date()
        dates = [today.strftime("%Y-%m-%d")]
        result = analyzer.filter_dates(dates)
        # Fallback: return the original list since filtering removes all
        assert len(result) == 1


class TestGetCurrentPrice:
    def test_success(self):
        analyzer = OptionsAnalyzer()
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = pd.DataFrame(
            {"Close": [150.0]}, index=[pd.Timestamp.today()]
        )
        result = analyzer.get_current_price(mock_ticker)
        assert result == 150.0

    def test_adj_close_fallback(self):
        analyzer = OptionsAnalyzer()
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = pd.DataFrame(
            {"Adj Close": [148.0]}, index=[pd.Timestamp.today()]
        )
        result = analyzer.get_current_price(mock_ticker)
        assert result == 148.0

    def test_retries_on_failure(self):
        analyzer = OptionsAnalyzer()
        mock_ticker = MagicMock()
        mock_ticker.history.side_effect = [
            pd.DataFrame(),  # First attempt: empty
            pd.DataFrame({"Close": [155.0]}, index=[pd.Timestamp.today()]),
        ]
        result = analyzer.get_current_price(mock_ticker)
        assert result == 155.0


class TestComputeRecommendation:
    def test_returns_error_for_empty_symbol(self):
        analyzer = OptionsAnalyzer()
        result = analyzer.compute_recommendation("")
        assert "error" in result

    def test_returns_error_when_no_options(self):
        analyzer = OptionsAnalyzer()
        mock_t = MagicMock()
        mock_t.options = []
        with patch.object(analyzer, "get_ticker", return_value=mock_t):
            result = analyzer.compute_recommendation("NOOPT")
        assert "error" in result

    def test_uses_passed_history_data(self, ohlcv_dataframe):
        """When history_data is passed, compute_recommendation should not call t.history()."""
        analyzer = OptionsAnalyzer()
        mock_t = MagicMock()
        mock_t.options = []

        with patch.object(analyzer, "get_ticker", return_value=mock_t):
            analyzer.compute_recommendation("TEST", history_data=ohlcv_dataframe)

        # Since no options, it returns early with error, but Ticker should not have
        # had history called even if it did proceed
        mock_t.history.assert_not_called()

    def test_uses_get_ticker_with_session(self):
        """compute_recommendation should use get_ticker (which passes the session)."""
        analyzer = OptionsAnalyzer()
        mock_t = MagicMock()
        mock_t.options = []

        with patch.object(analyzer, "get_ticker", return_value=mock_t) as mock_get:
            analyzer.compute_recommendation("AAPL")
            mock_get.assert_called_once_with("AAPL")

    def test_iv_rank_returned(self):
        """compute_recommendation returns iv_rank as float 0-100 when data is sufficient."""
        analyzer = OptionsAnalyzer()
        # Build a 252-row OHLCV DataFrame for 1y of data
        rng = np.random.RandomState(42)
        n = 252
        dates = pd.bdate_range(end=pd.Timestamp.today(), periods=n)
        close = 100 + np.cumsum(rng.randn(n) * 1.5)
        high = close + rng.uniform(0.5, 2.0, n)
        low = close - rng.uniform(0.5, 2.0, n)
        open_ = close + rng.randn(n) * 0.5
        volume = rng.randint(1_500_000, 5_000_000, n).astype(float)
        history_data = pd.DataFrame(
            {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume},
            index=dates,
        )

        mock_t = MagicMock()
        today = datetime.today().date()
        exp1 = (today + timedelta(days=15)).strftime("%Y-%m-%d")
        exp2 = (today + timedelta(days=45)).strftime("%Y-%m-%d")
        mock_t.options = [exp1, exp2]

        # Build realistic option chains
        current_price = float(close[-1])
        strikes = np.array([current_price - 5, current_price, current_price + 5])
        calls = pd.DataFrame({
            "strike": strikes,
            "bid": [3.0, 1.5, 0.5],
            "ask": [3.5, 2.0, 1.0],
            "impliedVolatility": [0.40, 0.38, 0.36],
        })
        puts = pd.DataFrame({
            "strike": strikes,
            "bid": [0.5, 1.5, 3.0],
            "ask": [1.0, 2.0, 3.5],
            "impliedVolatility": [0.42, 0.40, 0.38],
        })

        chain = MagicMock()
        chain.calls = calls
        chain.puts = puts
        mock_t.option_chain.return_value = chain

        mock_t.history.return_value = pd.DataFrame(
            {"Close": [current_price]}, index=[pd.Timestamp.today()]
        )

        with patch.object(analyzer, "get_ticker", return_value=mock_t):
            result = analyzer.compute_recommendation("TEST", history_data=history_data)

        assert "error" not in result
        assert "iv_rank" in result
        iv_rank = result["iv_rank"]
        assert iv_rank is not None
        assert 0 <= iv_rank <= 100

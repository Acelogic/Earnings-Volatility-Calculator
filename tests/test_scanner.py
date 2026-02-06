"""Tests for EnhancedEarningsScanner - recommendation logic and batch processing."""

import pytest
from unittest.mock import patch, MagicMock, PropertyMock
import pandas as pd

from earnings_calculator.options import OptionsAnalyzer
from earnings_calculator.scanner import EnhancedEarningsScanner


def _make_od(avg_volume, iv30_rv30, term_slope):
    """Helper: build a compute_recommendation result dict."""
    return {
        "avg_volume": avg_volume,
        "avg_volume_value": 2_000_000 if avg_volume else 500_000,
        "iv30_rv30": iv30_rv30,
        "term_slope": term_slope,
        "term_structure": 0.40,
        "expected_move": "3%",
        "underlying_price": 150.0,
        "historical_volatility": 0.25,
        "current_iv": 0.38,
        "atr14": 3.5,
        "atr14_pct": 2.33,
    }


class TestRecommendationLogic:
    """Test all 8 branch combinations of the recommendation classification."""

    @pytest.mark.parametrize(
        "vol,iv,slope,expected",
        [
            (True, 1.30, -0.0085, "Recommended"),
            (True, 1.30, 0.001, "Avoid"),
            (True, 1.10, -0.0085, "Consider"),
            (False, 1.30, -0.0085, "Consider"),
            (True, 1.10, 0.001, "Avoid"),
            (False, 1.30, 0.001, "Avoid"),
            (False, 1.10, -0.0085, "Avoid"),
            (False, 1.10, 0.001, "Avoid"),
        ],
    )
    def test_recommendation_branches(self, vol, iv, slope, expected, ohlcv_dataframe):
        analyzer = OptionsAnalyzer()
        scanner = EnhancedEarningsScanner(analyzer)
        od = _make_od(avg_volume=vol, iv30_rv30=iv, term_slope=slope)

        mock_ticker = MagicMock()
        mock_ticker.info = {"exchange": "NMS", "marketCap": 1_000_000_000}
        mock_ticker.history.return_value = ohlcv_dataframe

        with patch.object(analyzer, "get_ticker", return_value=mock_ticker), \
             patch.object(analyzer, "compute_recommendation", return_value=od), \
             patch.object(analyzer, "yang_zhang_volatility", return_value=0.25):
            result = scanner.analyze_stock("TEST", ohlcv_dataframe)

        assert result is not None
        assert result["recommendation"] == expected

    def test_boundary_iv30_rv30_exact(self, ohlcv_dataframe):
        """iv30_rv30 == 1.25 exactly should pass the check."""
        analyzer = OptionsAnalyzer()
        scanner = EnhancedEarningsScanner(analyzer)
        od = _make_od(avg_volume=True, iv30_rv30=1.25, term_slope=-0.0085)

        mock_ticker = MagicMock()
        mock_ticker.info = {"exchange": "NMS", "marketCap": 1_000_000_000}

        with patch.object(analyzer, "get_ticker", return_value=mock_ticker), \
             patch.object(analyzer, "compute_recommendation", return_value=od), \
             patch.object(analyzer, "yang_zhang_volatility", return_value=0.25):
            result = scanner.analyze_stock("TEST", ohlcv_dataframe)

        assert result["recommendation"] == "Recommended"

    def test_boundary_term_slope_exact(self, ohlcv_dataframe):
        """term_slope == -0.00406 exactly should pass the check."""
        analyzer = OptionsAnalyzer()
        scanner = EnhancedEarningsScanner(analyzer)
        od = _make_od(avg_volume=True, iv30_rv30=1.30, term_slope=-0.00406)

        mock_ticker = MagicMock()
        mock_ticker.info = {"exchange": "NMS", "marketCap": 1_000_000_000}

        with patch.object(analyzer, "get_ticker", return_value=mock_ticker), \
             patch.object(analyzer, "compute_recommendation", return_value=od), \
             patch.object(analyzer, "yang_zhang_volatility", return_value=0.25):
            result = scanner.analyze_stock("TEST", ohlcv_dataframe)

        assert result["recommendation"] == "Recommended"


class TestAnalyzeStock:
    def test_skips_otc_exchange(self, ohlcv_dataframe):
        analyzer = OptionsAnalyzer()
        scanner = EnhancedEarningsScanner(analyzer)
        mock_ticker = MagicMock()
        mock_ticker.info = {"exchange": "PNK"}

        with patch.object(analyzer, "get_ticker", return_value=mock_ticker):
            result = scanner.analyze_stock("OTCSTOCK", ohlcv_dataframe)
        assert result is None

    def test_skip_otc_check_flag(self, ohlcv_dataframe):
        analyzer = OptionsAnalyzer()
        scanner = EnhancedEarningsScanner(analyzer)
        od = _make_od(avg_volume=False, iv30_rv30=0.5, term_slope=0.01)
        mock_ticker = MagicMock()
        mock_ticker.info = {"exchange": "PNK", "marketCap": 0}

        with patch.object(analyzer, "get_ticker", return_value=mock_ticker), \
             patch.object(analyzer, "compute_recommendation", return_value=od), \
             patch.object(analyzer, "yang_zhang_volatility", return_value=0.20):
            result = scanner.analyze_stock(
                "OTCSTOCK", ohlcv_dataframe, skip_otc_check=True
            )
        assert result is not None
        assert result["ticker"] == "OTCSTOCK"

    def test_multiindex_columns(self):
        """Test handling of MultiIndex columns from yf.download."""
        analyzer = OptionsAnalyzer()
        scanner = EnhancedEarningsScanner(analyzer)
        od = _make_od(avg_volume=False, iv30_rv30=0.5, term_slope=0.01)

        # Create MultiIndex DataFrame
        arrays = [
            ["Price", "Price", "Price", "Price", "Price"],
            ["Open", "High", "Low", "Close", "Volume"],
        ]
        tuples = list(zip(*arrays))
        index = pd.MultiIndex.from_tuples(tuples)
        data = pd.DataFrame(
            [[100, 105, 95, 102, 1000000]] * 40,
            columns=index,
            index=pd.bdate_range(end=pd.Timestamp.today(), periods=40),
        )

        mock_ticker = MagicMock()
        mock_ticker.info = {"exchange": "NMS", "marketCap": 1_000_000}

        with patch.object(analyzer, "get_ticker", return_value=mock_ticker), \
             patch.object(analyzer, "compute_recommendation", return_value=od), \
             patch.object(analyzer, "yang_zhang_volatility", return_value=0.20):
            result = scanner.analyze_stock("TEST", data, skip_otc_check=True)

        assert result is not None

    def test_returns_none_on_error(self):
        analyzer = OptionsAnalyzer()
        scanner = EnhancedEarningsScanner(analyzer)

        with patch.object(
            analyzer, "get_ticker", side_effect=Exception("API error")
        ):
            result = scanner.analyze_stock("FAIL", None)
        assert result is None

    def test_error_in_recommendation_returns_avoid(self, ohlcv_dataframe):
        analyzer = OptionsAnalyzer()
        scanner = EnhancedEarningsScanner(analyzer)
        mock_ticker = MagicMock()
        mock_ticker.info = {"exchange": "NMS", "marketCap": 0}

        with patch.object(analyzer, "get_ticker", return_value=mock_ticker), \
             patch.object(
                 analyzer,
                 "compute_recommendation",
                 return_value={"error": "No options"},
             ), \
             patch.object(analyzer, "yang_zhang_volatility", return_value=0.20):
            result = scanner.analyze_stock("NOOPT", ohlcv_dataframe)

        assert result["recommendation"] == "Avoid"


class TestAnalyzeStockPassesHistory:
    def test_passes_history_to_compute_recommendation(self, ohlcv_dataframe):
        """analyze_stock should forward history_data to compute_recommendation."""
        analyzer = OptionsAnalyzer()
        scanner = EnhancedEarningsScanner(analyzer)
        od = _make_od(avg_volume=True, iv30_rv30=1.30, term_slope=-0.0085)

        mock_ticker = MagicMock()
        mock_ticker.info = {"exchange": "NMS", "marketCap": 1_000_000_000}

        with patch.object(analyzer, "get_ticker", return_value=mock_ticker), \
             patch.object(
                 analyzer, "compute_recommendation", return_value=od
             ) as mock_rec, \
             patch.object(analyzer, "yang_zhang_volatility", return_value=0.25):
            scanner.analyze_stock("TEST", ohlcv_dataframe)

        # Verify history_data kwarg was passed through
        mock_rec.assert_called_once_with("TEST", history_data=ohlcv_dataframe)


class TestScanEarningsDateRange:
    def test_aggregates_across_dates(self):
        """scan_earnings_date_range loops over business days and injects earnings_date."""
        from datetime import datetime

        analyzer = OptionsAnalyzer()
        scanner = EnhancedEarningsScanner(analyzer)

        def fake_scan(dt, cb=None):
            ds = dt.strftime("%Y-%m-%d")
            if cb:
                cb(100)
            return [{"ticker": f"T-{ds}", "recommendation": "Recommended"}]

        scanner.scan_earnings_stocks = MagicMock(side_effect=fake_scan)

        start = datetime(2026, 2, 2)  # Monday
        end = datetime(2026, 2, 6)    # Friday
        results = scanner.scan_earnings_date_range(start, end)

        assert len(results) == 5
        dates = [r["earnings_date"] for r in results]
        assert dates == [
            "2026-02-02",
            "2026-02-03",
            "2026-02-04",
            "2026-02-05",
            "2026-02-06",
        ]
        for r in results:
            assert "earnings_date" in r

    def test_empty_range(self):
        """Weekend-only range returns empty list."""
        from datetime import datetime

        analyzer = OptionsAnalyzer()
        scanner = EnhancedEarningsScanner(analyzer)
        # Saturday to Sunday
        results = scanner.scan_earnings_date_range(
            datetime(2026, 2, 7), datetime(2026, 2, 8)
        )
        assert results == []

    def test_progress_callback(self):
        """Progress callback receives values up to 100."""
        from datetime import datetime

        analyzer = OptionsAnalyzer()
        scanner = EnhancedEarningsScanner(analyzer)
        scanner.scan_earnings_stocks = MagicMock(return_value=[])
        progress_values = []
        results = scanner.scan_earnings_date_range(
            datetime(2026, 2, 2),
            datetime(2026, 2, 3),
            progress_callback=lambda v: progress_values.append(v),
        )
        assert progress_values[-1] == 100


class TestBatchDownloadHistory:
    @patch("earnings_calculator.scanner.yf.download")
    def test_single_ticker(self, mock_download, ohlcv_dataframe):
        analyzer = OptionsAnalyzer()
        scanner = EnhancedEarningsScanner(analyzer)
        mock_download.return_value = ohlcv_dataframe
        result = scanner.batch_download_history(["AAPL"])
        assert "AAPL" in result

    @patch("earnings_calculator.scanner.yf.download")
    def test_returns_empty_on_error(self, mock_download):
        analyzer = OptionsAnalyzer()
        scanner = EnhancedEarningsScanner(analyzer)
        mock_download.side_effect = Exception("Network error")
        result = scanner.batch_download_history(["AAPL"])
        assert result == {}

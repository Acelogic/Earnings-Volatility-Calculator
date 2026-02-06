"""Tests for GUI helper functions (pure logic, no Tk required)."""

import inspect

from earnings_calculator.gui import EarningsTkApp


class TestThreadSafety:
    """Verify worker thread callbacks use root.after() instead of direct widget calls."""

    def test_worker_threads_use_root_after_for_set_status(self):
        """set_status calls inside worker() functions should go through root.after()."""
        source = inspect.getsource(EarningsTkApp.on_analyze_stock)
        # Inside the worker closure, set_status should be wrapped in root.after
        assert "root.after" in source
        # The raw self.set_status should NOT appear outside root.after in the worker
        # Check that the worker's set_status is wrapped
        assert "lambda: self.set_status(" in source

    def test_scan_worker_uses_root_after_for_set_status(self):
        """set_status calls inside the worker() closure should use root.after()."""
        source = inspect.getsource(EarningsTkApp._scan_single_day)
        # Extract just the worker() inner function body
        in_worker = False
        worker_lines = []
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith("def worker"):
                in_worker = True
                continue
            if in_worker:
                if stripped and not stripped.startswith("#") and not line[0].isspace():
                    break
                worker_lines.append(stripped)
        # All set_status calls inside worker should go through root.after
        for line in worker_lines:
            if "set_status" in line:
                assert "root.after" in line

    def test_progress_callback_uses_root_after(self):
        """Progress var updates should go through root.after()."""
        source = inspect.getsource(EarningsTkApp._scan_single_day)
        assert "root.after(0, lambda" in source
        assert "progress_var.set" in source


class TestBuildRowValues:
    """Test build_row_values formatting without a Tk root."""

    def _build(self, row):
        """Call build_row_values as a static method (it only uses the row dict)."""
        # build_row_values is a bound method but only uses `row`
        return EarningsTkApp.build_row_values(None, row)

    def test_complete_data(self, analyze_stock_result):
        vals = self._build(analyze_stock_result)
        assert vals[0] == "AAPL"
        assert vals[1] == "2026-02-06"  # earnings_date
        assert vals[2] == "$185.50"
        assert vals[5] == "PASS"
        assert vals[8] == "Recommended"

    def test_missing_data(self):
        row = {
            "ticker": "XYZ",
            "current_price": 0,
            "market_cap": 0,
            "volume": 0,
            "avg_volume": False,
            "avg_volume_value": 0,
            "earnings_time": "Unknown",
            "recommendation": "Avoid",
            "expected_move": "N/A",
            "atr14": 0,
            "atr14_pct": 0,
            "iv30_rv30": 0,
            "term_slope": 0,
            "term_structure": 0,
            "historical_volatility": 0,
            "current_iv": None,
        }
        vals = self._build(row)
        assert vals[0] == "XYZ"
        assert vals[1] == "N/A"   # no earnings_date
        assert vals[2] == "$0.00"
        assert vals[3] == "N/A"   # market_cap == 0
        assert vals[4] == "N/A"   # volume == 0
        assert vals[5] == "FAIL"
        assert vals[8] == "Avoid"
        assert vals[9] == "N/A"
        assert vals[16] == "N/A"  # current_iv is None

    def test_price_formatting(self):
        row = {
            "ticker": "T",
            "current_price": 1234.5678,
            "market_cap": 5_000_000_000,
            "volume": 12345678,
            "avg_volume": True,
            "avg_volume_value": 9876543,
            "earnings_time": "Pre Market",
            "recommendation": "Consider",
            "expected_move": "4.5%",
            "atr14": 15.123,
            "atr14_pct": 1.225,
            "iv30_rv30": 2.345,
            "term_slope": -0.01234,
            "term_structure": 0.5678,
            "historical_volatility": 0.3456,
            "current_iv": 0.5123,
        }
        vals = self._build(row)
        assert vals[2] == "$1234.57"
        assert "$5,000,000,000" in vals[3]
        assert vals[11] == "1.23%"
        assert vals[12] == "2.35"
        assert vals[13] == "-0.0123"
        assert "56.78%" in vals[14]

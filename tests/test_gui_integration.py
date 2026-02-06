"""Automated Tkinter GUI integration tests.

These tests create a real Tk window with mocked network/API calls so they
run fast, offline, and with no user interaction.  A display server is
required (macOS provides one; CI needs Xvfb).
"""

import csv
import time
import tkinter as tk
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

# Skip the whole module if Tk cannot be initialised (headless CI)
try:
    _test_root = tk.Tk()
    _test_root.destroy()
except tk.TclError:
    pytest.skip("No display available for Tkinter tests", allow_module_level=True)

from earnings_calculator.gui import EarningsTkApp


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def pump_events(root, timeout_ms=200):
    """Process the Tk event loop for *timeout_ms* without entering mainloop."""
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        try:
            root.update()
        except tk.TclError:
            break
        time.sleep(0.01)


def get_table_rows(app):
    """Return a list of row-value tuples currently in the treeview."""
    return [app.tree.item(iid, "values") for iid in app.tree.get_children()]


class _SynchronousThread:
    """Drop-in replacement for threading.Thread that runs target synchronously."""

    def __init__(self, target=None, args=(), kwargs=None, daemon=None, **kw):
        self._target = target
        self._args = args
        self._kwargs = kwargs or {}

    def start(self):
        if self._target:
            self._target(*self._args, **self._kwargs)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tk_app():
    """Create a real EarningsTkApp with all network I/O mocked out."""
    with patch("earnings_calculator.gui.update_otc_tickers"):
        root = tk.Tk()
        root.withdraw()
        app = EarningsTkApp(root)
    yield app
    try:
        root.destroy()
    except tk.TclError:
        pass  # already destroyed (e.g. exit test)


@pytest.fixture
def sync_threads():
    """Patch threading.Thread in the gui module so workers run synchronously.

    This avoids the 'main thread is not in main loop' RuntimeError that
    occurs when a worker thread calls root.after() without an active
    mainloop.  After the synchronous worker completes, we pump the Tk event
    loop once so that any queued root.after(0, ...) callbacks execute.
    """
    with patch("earnings_calculator.gui.threading.Thread", _SynchronousThread):
        yield


# ===================================================================
# A. Initialization
# ===================================================================

class TestInitialization:
    def test_app_launches(self, tk_app):
        """Window created, status Ready, table has 18 columns."""
        assert tk_app.lbl_status.cget("text") == "Status: Ready"
        assert len(tk_app.headings) == 18
        cols = tk_app.tree["columns"]
        assert len(cols) == 18

    def test_initial_proxy_status(self, tk_app):
        """Proxy label shows 'Enabled (N proxies)' on startup."""
        text = tk_app.lbl_proxy_status.cget("text")
        assert text.startswith("Enabled (")
        assert "proxies)" in text

    def test_table_columns_match_headings(self, tk_app):
        """All 18 column headings present and in order."""
        expected = [
            "Ticker", "Earnings Date", "Price", "Market Cap", "Volume 1d",
            "Avg Vol Check", "30D Volume", "Earnings Time", "Recommendation",
            "Expected Move", "ATR 14d", "ATR 14d %", "IV30/RV30",
            "Term Slope", "Term Structure", "Historical Vol", "Current IV",
            "IV Rank",
        ]
        actual = [tk_app.tree.heading(col, "text") for col in tk_app.tree["columns"]]
        assert actual == expected


# ===================================================================
# B. Single Stock Analysis
# ===================================================================

class TestSingleStockAnalysis:
    def test_analyze_empty_symbol(self, tk_app):
        """Empty entry shows 'Please enter a stock symbol.'"""
        tk_app.entry_symbol.delete(0, "end")
        tk_app.on_analyze_stock()
        assert "Please enter a stock symbol" in tk_app.lbl_status.cget("text")

    def test_analyze_stock_success(self, tk_app, sync_threads, analyze_stock_result):
        """Enter 'AAPL', mock result -> table has 1 row."""
        tk_app.entry_symbol.delete(0, "end")
        tk_app.entry_symbol.insert(0, "AAPL")
        tk_app.scanner.batch_download_history = MagicMock(
            return_value={"AAPL": pd.DataFrame()}
        )
        tk_app.scanner.analyze_stock = MagicMock(return_value=analyze_stock_result)
        tk_app.on_analyze_stock()
        pump_events(tk_app.root)
        rows = get_table_rows(tk_app)
        assert len(rows) == 1
        assert rows[0][0] == "AAPL"
        assert "complete" in tk_app.lbl_status.cget("text").lower()

    def test_analyze_stock_no_result(self, tk_app, sync_threads):
        """Mock returns None -> table empty, status 'complete'."""
        tk_app.entry_symbol.delete(0, "end")
        tk_app.entry_symbol.insert(0, "ZZZZ")
        tk_app.scanner.batch_download_history = MagicMock(
            return_value={"ZZZZ": pd.DataFrame()}
        )
        tk_app.scanner.analyze_stock = MagicMock(return_value=None)
        tk_app.on_analyze_stock()
        pump_events(tk_app.root)
        assert len(get_table_rows(tk_app)) == 0
        assert "complete" in tk_app.lbl_status.cget("text").lower()

    def test_analyze_stock_uppercases_symbol(
        self, tk_app, sync_threads, analyze_stock_result
    ):
        """Enter 'aapl' -> batch_download_history called with ['AAPL']."""
        tk_app.entry_symbol.delete(0, "end")
        tk_app.entry_symbol.insert(0, "aapl")
        mock_bdh = MagicMock(return_value={"AAPL": pd.DataFrame()})
        tk_app.scanner.batch_download_history = mock_bdh
        tk_app.scanner.analyze_stock = MagicMock(return_value=analyze_stock_result)
        tk_app.on_analyze_stock()
        pump_events(tk_app.root)
        mock_bdh.assert_called_once_with(["AAPL"])


# ===================================================================
# C. Earnings Scan
# ===================================================================

class TestEarningsScan:
    def _run_scan(self, tk_app, results):
        """Helper: mock scan_earnings_stocks and trigger a Selected Date scan."""
        tk_app.scanner.scan_earnings_stocks = MagicMock(return_value=results)
        tk_app.scan_mode_var.set("Selected Date")
        tk_app.on_scan()
        pump_events(tk_app.root)

    def test_scan_earnings_success(self, tk_app, sync_threads, multi_stock_results):
        results = multi_stock_results[:3]
        self._run_scan(tk_app, results)
        rows = get_table_rows(tk_app)
        assert len(rows) == 3
        assert "Found 3" in tk_app.lbl_status.cget("text")

    def test_scan_earnings_empty(self, tk_app, sync_threads):
        self._run_scan(tk_app, [])
        assert len(get_table_rows(tk_app)) == 0
        assert "Found 0" in tk_app.lbl_status.cget("text")

    def test_scan_earnings_clears_previous(
        self, tk_app, sync_threads, multi_stock_results
    ):
        """Scanning twice replaces previous results."""
        self._run_scan(tk_app, multi_stock_results[:2])
        assert len(get_table_rows(tk_app)) == 2
        self._run_scan(tk_app, multi_stock_results[2:5])
        assert len(get_table_rows(tk_app)) == 3

    def test_scan_earnings_injects_earnings_date(
        self, tk_app, sync_threads, multi_stock_results
    ):
        """Single-day scan populates earnings_date from the date entry."""
        results = [dict(r) for r in multi_stock_results[:1]]
        # Remove earnings_date so _scan_single_day injects it via setdefault
        for r in results:
            r.pop("earnings_date", None)
        tk_app.scanner.scan_earnings_stocks = MagicMock(return_value=results)
        tk_app.scan_mode_var.set("Selected Date")
        tk_app.on_scan()
        pump_events(tk_app.root)
        rows = get_table_rows(tk_app)
        assert len(rows) == 1
        # Column index 1 is Earnings Date
        assert rows[0][1] != "N/A"

    def test_range_scan_this_week(self, tk_app, sync_threads, multi_stock_results):
        """This Week mode triggers scan_earnings_date_range and populates table."""
        tk_app.scanner.scan_earnings_date_range = MagicMock(
            return_value=multi_stock_results[:2]
        )
        tk_app.scan_mode_var.set("This Week")
        tk_app.on_scan()
        pump_events(tk_app.root)
        rows = get_table_rows(tk_app)
        assert len(rows) == 2
        assert "Range scan complete" in tk_app.lbl_status.cget("text")


# ===================================================================
# D. Filtering
# ===================================================================

class TestFiltering:
    @pytest.fixture(autouse=True)
    def _populate(self, tk_app, multi_stock_results):
        """Pre-populate the table with 5 varied rows."""
        tk_app.raw_results = list(multi_stock_results)
        tk_app.fill_table()
        assert len(get_table_rows(tk_app)) == 5

    def test_filter_by_earnings_time(self, tk_app):
        """'Pre Market' filter keeps only PLTR and F."""
        tk_app.filter_time_var.set("Pre Market")
        tk_app.fill_table()
        rows = get_table_rows(tk_app)
        tickers = {r[0] for r in rows}
        assert tickers == {"PLTR", "F"}

    def test_filter_by_recommendation(self, tk_app):
        """'Recommended' filter keeps only AAPL and PLTR."""
        tk_app.filter_rec_var.set("Recommended")
        tk_app.fill_table()
        rows = get_table_rows(tk_app)
        tickers = {r[0] for r in rows}
        assert tickers == {"AAPL", "PLTR"}

    def test_filter_by_min_price(self, tk_app):
        """Min price 5.00 excludes F ($3.50)."""
        tk_app.filter_price_var.set("5.00")
        tk_app.fill_table()
        rows = get_table_rows(tk_app)
        tickers = {r[0] for r in rows}
        assert "F" not in tickers
        assert len(rows) == 4

    def test_filter_combined(self, tk_app):
        """Pre Market + price >= 5.00 -> only PLTR ($24.75)."""
        tk_app.filter_time_var.set("Pre Market")
        tk_app.filter_price_var.set("5.00")
        tk_app.fill_table()
        rows = get_table_rows(tk_app)
        assert len(rows) == 1
        assert rows[0][0] == "PLTR"

    def test_filter_does_not_mutate_raw_results(self, tk_app):
        """Filter, then reset to 'All' -> all 5 rows return."""
        tk_app.filter_rec_var.set("Recommended")
        tk_app.fill_table()
        assert len(get_table_rows(tk_app)) == 2
        # Reset
        tk_app.filter_rec_var.set("All")
        tk_app.fill_table()
        assert len(get_table_rows(tk_app)) == 5


# ===================================================================
# E. Sorting
# ===================================================================

class TestSorting:
    @pytest.fixture(autouse=True)
    def _populate(self, tk_app, multi_stock_results):
        tk_app.raw_results = list(multi_stock_results)
        tk_app.fill_table()

    def test_sort_by_ticker_ascending(self, tk_app):
        """Click Ticker -> rows sorted A-Z."""
        tk_app.on_column_heading_click("Ticker")
        rows = get_table_rows(tk_app)
        tickers = [r[0] for r in rows]
        assert tickers == sorted(tickers)

    def test_sort_by_price_descending(self, tk_app):
        """Click Price twice -> highest first."""
        tk_app.on_column_heading_click("Price")   # asc
        tk_app.on_column_heading_click("Price")   # desc
        rows = get_table_rows(tk_app)
        prices = [float(r[2].replace("$", "").replace(",", "")) for r in rows]
        assert prices == sorted(prices, reverse=True)

    def test_sort_toggle(self, tk_app):
        """Click same header twice -> order flips, status shows direction."""
        tk_app.on_column_heading_click("Ticker")
        assert "(asc)" in tk_app.lbl_status.cget("text")
        tk_app.on_column_heading_click("Ticker")
        assert "(desc)" in tk_app.lbl_status.cget("text")


# ===================================================================
# F. Table Rendering
# ===================================================================

class TestTableRendering:
    @pytest.fixture(autouse=True)
    def _populate(self, tk_app, multi_stock_results):
        tk_app.raw_results = list(multi_stock_results)
        tk_app.fill_table()

    def test_row_tags_recommended_green(self, tk_app):
        """Recommended rows have tag 'Recommended'."""
        for iid in tk_app.tree.get_children():
            vals = tk_app.tree.item(iid, "values")
            tags = tk_app.tree.item(iid, "tags")
            if vals[8] == "Recommended":
                assert "Recommended" in tags

    def test_row_tags_avoid_red(self, tk_app):
        """Avoid rows have tag 'Avoid'."""
        for iid in tk_app.tree.get_children():
            vals = tk_app.tree.item(iid, "values")
            tags = tk_app.tree.item(iid, "tags")
            if vals[8] == "Avoid":
                assert "Avoid" in tags

    def test_row_values_formatted(self, tk_app):
        """AAPL row: earnings_date, price='$185.50', volume='55,000,000'."""
        for iid in tk_app.tree.get_children():
            vals = tk_app.tree.item(iid, "values")
            if vals[0] == "AAPL":
                assert vals[1] == "2026-02-06"
                assert vals[2] == "$185.50"
                assert vals[4] == "55,000,000"
                return
        pytest.fail("AAPL row not found")


# ===================================================================
# G. Export CSV
# ===================================================================

class TestExportCSV:
    def test_export_no_data(self, tk_app):
        """Empty table -> 'No data to export.'"""
        tk_app.on_export_csv()
        assert "No data to export" in tk_app.lbl_status.cget("text")

    def test_export_success(self, tk_app, multi_stock_results, tmp_path):
        """CSV written with correct headers and rows."""
        tk_app.raw_results = list(multi_stock_results)
        tk_app.fill_table()
        csv_path = str(tmp_path / "export.csv")
        with patch(
            "earnings_calculator.gui.filedialog.asksaveasfilename",
            return_value=csv_path,
        ):
            tk_app.on_export_csv()
        assert "Exported to" in tk_app.lbl_status.cget("text")
        with open(csv_path) as f:
            reader = csv.reader(f)
            header = next(reader)
            assert header == tk_app.headings
            data_rows = list(reader)
            assert len(data_rows) == 5

    def test_export_respects_filters(self, tk_app, multi_stock_results, tmp_path):
        """Filter to 2 rows -> CSV has 2 data rows."""
        tk_app.raw_results = list(multi_stock_results)
        tk_app.fill_table()
        tk_app.filter_rec_var.set("Recommended")
        csv_path = str(tmp_path / "filtered.csv")
        with patch(
            "earnings_calculator.gui.filedialog.asksaveasfilename",
            return_value=csv_path,
        ):
            tk_app.on_export_csv()
        with open(csv_path) as f:
            reader = csv.reader(f)
            next(reader)  # skip header
            data_rows = list(reader)
            assert len(data_rows) == 2


# ===================================================================
# H. Double-Click Chart
# ===================================================================

class TestDoubleClickChart:
    def test_double_click_opens_chart(self, tk_app, analyze_stock_result):
        """Double-click row -> show_interactive_chart called with ticker."""
        tk_app.raw_results = [analyze_stock_result]
        tk_app.fill_table()
        iid = tk_app.tree.get_children()[0]
        tk_app.tree.selection_set(iid)
        with patch("earnings_calculator.gui.show_interactive_chart") as mock_chart:
            event = MagicMock()
            tk_app.on_table_double_click(event)
            mock_chart.assert_called_once_with("AAPL", tk_app.analyzer.session_manager)

    def test_double_click_no_selection(self, tk_app):
        """Double-click empty table -> chart not called."""
        with patch("earnings_calculator.gui.show_interactive_chart") as mock_chart:
            event = MagicMock()
            tk_app.on_table_double_click(event)
            mock_chart.assert_not_called()


# ===================================================================
# I. Proxy Toggle
# ===================================================================

class TestProxyToggle:
    def test_toggle_proxy_off(self, tk_app):
        """Uncheck proxy -> 'Disabled (0 proxies)'."""
        tk_app.proxy_var.set(False)
        tk_app.on_toggle_proxy()
        assert tk_app.lbl_proxy_status.cget("text") == "Disabled (0 proxies)"

    def test_toggle_proxy_on(self, tk_app):
        """Check proxy -> 'Enabled (N proxies)'."""
        tk_app.proxy_var.set(False)
        tk_app.on_toggle_proxy()
        tk_app.proxy_var.set(True)
        tk_app.on_toggle_proxy()
        text = tk_app.lbl_proxy_status.cget("text")
        assert text.startswith("Enabled (")
        assert "proxies)" in text


# ===================================================================
# J. Exit
# ===================================================================

class TestExit:
    def test_exit_button(self, tk_app):
        """Click Exit -> root.destroy called."""
        with patch.object(tk_app.root, "destroy") as mock_destroy:
            tk_app.root.destroy()
            mock_destroy.assert_called_once()


# ===================================================================
# K. Quick Date Buttons
# ===================================================================

class TestQuickDateButtons:
    def test_today_button(self, tk_app):
        """set_date_entry(0) puts today's date in the entry."""
        from datetime import date
        tk_app.set_date_entry(0)
        assert tk_app.cal_date.get() == date.today().strftime("%Y-%m-%d")

    def test_tomorrow_button(self, tk_app):
        """set_date_entry(1) puts tomorrow's date in the entry."""
        from datetime import date, timedelta
        tk_app.set_date_entry(1)
        expected = (date.today() + timedelta(days=1)).strftime("%Y-%m-%d")
        assert tk_app.cal_date.get() == expected

    def test_next_week_button(self, tk_app):
        """set_date_entry(7) puts date 7 days out in the entry."""
        from datetime import date, timedelta
        tk_app.set_date_entry(7)
        expected = (date.today() + timedelta(days=7)).strftime("%Y-%m-%d")
        assert tk_app.cal_date.get() == expected

    def test_overwrites_existing_date(self, tk_app):
        """Quick date replaces whatever was in the entry."""
        from datetime import date
        tk_app.cal_date.delete(0, "end")
        tk_app.cal_date.insert(0, "2020-01-01")
        tk_app.set_date_entry(0)
        assert tk_app.cal_date.get() == date.today().strftime("%Y-%m-%d")


# ===================================================================
# L. IV Rank Column
# ===================================================================

class TestIVRankColumn:
    def test_iv_rank_displayed(self, tk_app, multi_stock_results):
        """IV Rank renders as 'NN%' or 'N/A' in column index 17."""
        tk_app.raw_results = list(multi_stock_results)
        tk_app.fill_table()
        rows = get_table_rows(tk_app)
        # AAPL has iv_rank=65.0 -> "65%"
        aapl_row = [r for r in rows if r[0] == "AAPL"][0]
        assert aapl_row[17] == "65%"
        # F has iv_rank=None -> "N/A"
        f_row = [r for r in rows if r[0] == "F"][0]
        assert f_row[17] == "N/A"

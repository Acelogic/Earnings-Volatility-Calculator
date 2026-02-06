"""Tkinter GUI for the Earnings Volatility Calculator."""

import importlib.resources
import math
import threading
from typing import Dict, List

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from earnings_calculator.chart import show_interactive_chart
from earnings_calculator.options import OptionsAnalyzer
from earnings_calculator.proxy import ProxyManager
from earnings_calculator.scanner import EnhancedEarningsScanner, update_otc_tickers


def _fmt(val, fmt_str, fallback="N/A"):
    """Format *val* using *fmt_str*, returning *fallback* for None/NaN."""
    try:
        if val is None or (isinstance(val, float) and math.isnan(val)):
            return fallback
        return fmt_str.format(val)
    except (ValueError, TypeError):
        return fallback


class EarningsTkApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Earnings Volatility Calculator (Tkinter)")
        self._set_icon()
        self.proxy_manager = ProxyManager()
        self.proxy_manager.proxy_enabled = True
        self.analyzer = OptionsAnalyzer(self.proxy_manager)
        self.scanner = EnhancedEarningsScanner(self.analyzer)
        self.raw_results: List[Dict] = []
        self.sort_orders: Dict[str, bool] = {}
        self.build_layout()
        threading.Thread(target=update_otc_tickers, daemon=True).start()

    def _set_icon(self):
        try:
            ref = importlib.resources.files("earnings_calculator.assets").joinpath("icon.png")
            with importlib.resources.as_file(ref) as icon_path:
                icon = tk.PhotoImage(file=str(icon_path))
                self.root.iconphoto(True, icon)
        except Exception:
            pass  # missing icon should never crash the app

    def build_layout(self):
        from datetime import date

        # ---------- Proxy Settings -----------
        proxy_frame = ttk.LabelFrame(self.root, text="Proxy Settings", padding=2)
        proxy_frame.pack(side="top", fill="x", padx=5, pady=(2, 0))
        self.proxy_var = tk.BooleanVar(value=self.proxy_manager.proxy_enabled)
        cb = ttk.Checkbutton(
            proxy_frame,
            text="Enable Proxy",
            variable=self.proxy_var,
            command=self.on_toggle_proxy,
        )
        cb.pack(side="left", padx=5, pady=0)
        btn_proxy_update = ttk.Button(
            proxy_frame, text="Update Proxies", command=self.on_update_proxies
        )
        btn_proxy_update.pack(side="left", padx=5, pady=0)
        self.lbl_proxy_status = ttk.Label(
            proxy_frame,
            text=f"Enabled ({len(self.proxy_manager.proxies)} proxies)",
        )
        self.lbl_proxy_status.pack(side="left", padx=5, pady=0)

        # ---------- Single Stock Analysis -----------
        single_frame = ttk.Frame(self.root, padding=2)
        single_frame.pack(side="top", fill="x", padx=5, pady=(0, 0))
        ttk.Label(single_frame, text="Enter Stock Symbol:").pack(
            side="left", padx=5, pady=0
        )
        self.entry_symbol = ttk.Entry(single_frame, width=12)
        self.entry_symbol.pack(side="left", padx=5, pady=0)
        btn_analyze = ttk.Button(
            single_frame, text="Analyze", command=self.on_analyze_stock
        )
        btn_analyze.pack(side="left", padx=5, pady=0)

        # ---------- Earnings Scan with calendar popup -----------
        scan_frame = ttk.Frame(self.root, padding=2)
        scan_frame.pack(side="top", fill="x", padx=5, pady=(0, 0))
        ttk.Label(scan_frame, text="Earnings Date:").pack(
            side="left", padx=5, pady=0
        )
        self.cal_date = ttk.Entry(scan_frame, width=12)
        self.cal_date.insert(0, date.today().strftime("%Y-%m-%d"))
        self.cal_date.pack(side="left", padx=2, pady=0)
        btn_cal = ttk.Button(
            scan_frame, text="\u25bc", width=2, command=self.open_calendar_popup
        )
        btn_cal.pack(side="left", padx=(0, 5), pady=0)
        self.scan_mode_var = tk.StringVar(value="Selected Date")
        scan_mode = ttk.Combobox(
            scan_frame,
            textvariable=self.scan_mode_var,
            values=["Selected Date", "Today", "Tomorrow", "This Week", "This Month"],
            width=14,
            state="readonly",
        )
        scan_mode.pack(side="left", padx=5, pady=0)
        ttk.Button(
            scan_frame, text="Scan", command=self.on_scan,
        ).pack(side="left", padx=5, pady=0)

        # ============ Filters + Threshold Label =============
        filter_and_threshold_frame = ttk.Frame(self.root, padding=2)
        filter_and_threshold_frame.pack(side="top", fill="x", padx=5, pady=(0, 0))
        filter_frame = ttk.LabelFrame(
            filter_and_threshold_frame, text="", padding=2
        )
        filter_frame.pack(side="left", fill="x", expand=True)
        ttk.Label(filter_frame, text="Earnings Time Filter:").pack(
            side="left", padx=(0, 5), pady=0
        )
        self.filter_time_var = tk.StringVar(value="All")
        cbox_time = ttk.Combobox(
            filter_frame,
            textvariable=self.filter_time_var,
            values=["All", "Pre Market", "Post Market", "During Market"],
            width=12,
        )
        cbox_time.pack(side="left", padx=5, pady=0)
        cbox_time.bind("<<ComboboxSelected>>", self.on_filter_changed)
        ttk.Label(filter_frame, text="Recommendation Filter:").pack(
            side="left", padx=(10, 5), pady=0
        )
        self.filter_rec_var = tk.StringVar(value="All")
        cbox_rec = ttk.Combobox(
            filter_frame,
            textvariable=self.filter_rec_var,
            values=["All", "Recommended", "Consider", "Avoid"],
            width=12,
        )
        cbox_rec.pack(side="left", padx=5, pady=0)
        cbox_rec.bind("<<ComboboxSelected>>", self.on_filter_changed)
        ttk.Label(filter_frame, text="Min Stock Price Filter:").pack(
            side="left", padx=(10, 5), pady=0
        )
        self.filter_price_var = tk.StringVar(value="All")
        cbox_price = ttk.Combobox(
            filter_frame,
            textvariable=self.filter_price_var,
            values=["All", "1.00", "2.50", "5.00", "10.00"],
            width=12,
        )
        cbox_price.pack(side="left", padx=5, pady=0)
        cbox_price.bind("<<ComboboxSelected>>", self.on_filter_changed)
        thresholds_text = (
            "Recommended If:\n"
            "- Avg. Daily Volume >= 1,500,000\n"
            "- IV30/RV30 >= 1.25\n"
            "- Term Slope <= -0.00406"
        )
        thresholds_label = ttk.Label(
            filter_and_threshold_frame, text=thresholds_text, justify="left"
        )
        thresholds_label.pack(
            side="right", padx=(10, 5), pady=(0, 0), anchor="n"
        )

        # ---------- The Table -----------
        table_frame = ttk.Frame(self.root, padding=0)
        table_frame.pack(side="top", fill="both", expand=True)
        self.headings = [
            "Ticker",
            "Earnings Date",
            "Price",
            "Market Cap",
            "Volume 1d",
            "Avg Vol Check",
            "30D Volume",
            "Earnings Time",
            "Recommendation",
            "Expected Move",
            "ATR 14d",
            "ATR 14d %",
            "IV30/RV30",
            "Term Slope",
            "Term Structure",
            "Historical Vol",
            "Current IV",
            "IV Rank",
        ]
        col_widths = {
            "Ticker": 70, "Earnings Date": 100, "Price": 80,
            "Market Cap": 100, "Volume 1d": 100, "Avg Vol Check": 70,
            "30D Volume": 100, "Earnings Time": 100, "Recommendation": 110,
            "Expected Move": 100, "ATR 14d": 70, "ATR 14d %": 80,
            "IV30/RV30": 80, "Term Slope": 90, "Term Structure": 100,
            "Historical Vol": 100, "Current IV": 80, "IV Rank": 70,
        }
        self.tree = ttk.Treeview(
            table_frame, columns=self.headings, show="headings"
        )
        for col in self.headings:
            self.sort_orders[col] = True
            self.tree.heading(
                col,
                text=col,
                command=lambda c=col: self.on_column_heading_click(c),
            )
            self.tree.column(col, width=col_widths.get(col, 100))
        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        table_frame.grid_rowconfigure(0, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        self.tree.tag_configure(
            "Recommended", background="green", foreground="white"
        )
        self.tree.tag_configure(
            "Consider", background="orange", foreground="black"
        )
        self.tree.tag_configure("Avoid", background="red", foreground="white")
        self.tree.bind("<Double-1>", self.on_table_double_click)

        # ---------- Bottom Row (Status/Progress/Export/Exit) -----------
        bottom_frame = ttk.Frame(self.root, padding=2)
        bottom_frame.pack(side="bottom", fill="x", padx=5, pady=(0, 2))
        self.lbl_status = ttk.Label(bottom_frame, text="Status: Ready")
        self.lbl_status.pack(side="left", padx=5, pady=0)
        btn_export = ttk.Button(
            bottom_frame, text="Export CSV", command=self.on_export_csv
        )
        btn_export.pack(side="right", padx=5, pady=0)
        btn_exit = ttk.Button(
            bottom_frame, text="Exit", command=self.root.destroy
        )
        btn_exit.pack(side="right", padx=5, pady=0)
        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(
            bottom_frame,
            orient="horizontal",
            variable=self.progress_var,
            maximum=100,
            length=150,
        )
        self.progress_bar.pack(side="right", padx=10, pady=0)

    # -------- Proxy Handlers --------
    def on_toggle_proxy(self):
        self.proxy_manager.proxy_enabled = self.proxy_var.get()
        self.update_proxy_status()

    def on_update_proxies(self):
        loading_win = tk.Toplevel(self.root)
        loading_win.title("Updating Proxies")
        loading_win.geometry("300x150")
        ttk.Label(loading_win, text="Fetching and validating proxies...").pack(
            pady=10
        )
        pb = ttk.Progressbar(loading_win, mode="indeterminate")
        pb.pack(pady=10, padx=20, fill="x")
        pb.start(10)
        cancel_btn = ttk.Button(
            loading_win,
            text="Cancel (keep found)",
            command=self.proxy_manager.cancel_validation,
        )
        cancel_btn.pack(pady=5)

        def progress_callback(msg):
            print(msg)
            self.root.after(0, lambda: self.set_status(msg))

        def update_task():
            try:
                self.proxy_manager.build_valid_proxy_pool(
                    max_proxies=50,
                    concurrency=20,
                    progress_callback=progress_callback,
                )
                self.root.after(0, lambda: self.update_proxy_status())
                self.root.after(0, lambda: self.set_status("Proxies updated."))
            except Exception as e:
                self.root.after(
                    0, lambda: self.set_status(f"Failed to update proxies: {e}")
                )
            finally:
                self.root.after(0, lambda: pb.stop())
                self.root.after(0, lambda: loading_win.destroy())

        threading.Thread(target=update_task, daemon=True).start()

    def update_proxy_status(self):
        if self.proxy_manager.proxy_enabled:
            c = len(self.proxy_manager.proxies)
            self.lbl_proxy_status.config(text=f"Enabled ({c} proxies)")
        else:
            self.lbl_proxy_status.config(text="Disabled (0 proxies)")

    # -------- Single Stock Analysis --------
    def on_analyze_stock(self):
        ticker = self.entry_symbol.get().strip().upper()
        if not ticker:
            self.set_status("Please enter a stock symbol.")
            return
        self.set_status("Analyzing single stock...")
        self.clear_table()
        self.raw_results.clear()

        def worker():
            hist_map = self.scanner.batch_download_history([ticker])
            r = self.scanner.analyze_stock(
                ticker, hist_map.get(ticker), skip_otc_check=True
            )
            if r:
                self.raw_results = [r]
            self.root.after(0, self.fill_table)
            self.root.after(0, lambda: self.set_status("Single stock analysis complete."))

        threading.Thread(target=worker, daemon=True).start()

    # -------- Earnings Scan --------
    def on_scan(self):
        """Unified scan dispatcher — reads scan_mode_var to decide what to scan."""
        import calendar as cal_mod
        from datetime import date, datetime, timedelta

        mode = self.scan_mode_var.get()
        today = date.today()

        if mode == "Today":
            self._scan_single_day(today)
        elif mode == "Tomorrow":
            self._scan_single_day(today + timedelta(days=1))
        elif mode == "This Week":
            days_until_friday = (4 - today.weekday()) % 7
            end = today + timedelta(days=days_until_friday) if days_until_friday > 0 else today
            self._scan_range(today, end)
        elif mode == "This Month":
            last_day = cal_mod.monthrange(today.year, today.month)[1]
            self._scan_range(today, date(today.year, today.month, last_day))
        else:
            # "Selected Date" — use the date entry
            raw = self.cal_date.get().strip()
            try:
                dt = datetime.strptime(raw, "%Y-%m-%d").date()
            except ValueError:
                self.set_status(f"Invalid date format: '{raw}'. Use YYYY-MM-DD.")
                return
            self._scan_single_day(dt)

    def _scan_single_day(self, scan_date):
        from datetime import datetime
        raw = scan_date.strftime("%Y-%m-%d")
        self.clear_table()
        self.raw_results.clear()
        self.progress_var.set(0)
        self.set_status(f"Scanning earnings for {raw}...")

        def progress_cb(val):
            self.root.after(0, lambda v=val: self.progress_var.set(v))

        def worker():
            results = self.scanner.scan_earnings_stocks(
                datetime.combine(scan_date, datetime.min.time()), progress_cb
            )
            for r in results:
                r.setdefault("earnings_date", raw)
            self.raw_results = results
            self.root.after(0, lambda msg=f"Scan complete. Found {len(results)} stocks.": self.set_status(msg))
            self.root.after(0, self.fill_table)

        threading.Thread(target=worker, daemon=True).start()

    def _scan_range(self, start_date, end_date):
        from datetime import datetime
        self.clear_table()
        self.raw_results.clear()
        self.progress_var.set(0)
        label = f"{start_date} to {end_date}"
        self.set_status(f"Scanning earnings {label}...")

        def progress_cb(val):
            self.root.after(0, lambda v=val: self.progress_var.set(v))

        def worker():
            start_dt = datetime.combine(start_date, datetime.min.time())
            end_dt = datetime.combine(end_date, datetime.min.time())
            results = self.scanner.scan_earnings_date_range(
                start_dt, end_dt, progress_cb
            )
            self.raw_results = results
            self.root.after(0, lambda msg=f"Range scan complete. Found {len(results)} stocks ({label}).": self.set_status(msg))
            self.root.after(0, self.fill_table)

        threading.Thread(target=worker, daemon=True).start()

    # -------- Filters --------
    def on_filter_changed(self, event):
        self.fill_table()

    def apply_filters(self, data: List[Dict]) -> List[Dict]:
        time_val = self.filter_time_var.get()
        rec_val = self.filter_rec_var.get()
        price_val = self.filter_price_var.get()
        filtered = []
        for row in data:
            et = row.get("earnings_time", "Unknown")
            if time_val != "All" and et != time_val:
                continue
            rv = row.get("recommendation", "Avoid")
            if rec_val != "All" and rv != rec_val:
                continue
            pv = row.get("current_price", "All")
            if price_val != "All" and pv < float(price_val):
                continue
            filtered.append(row)
        return filtered

    # -------- Table Helpers --------
    def fill_table(self):
        self.clear_table()
        filtered = self.apply_filters(self.raw_results)
        for row in filtered:
            rec = row.get("recommendation", "Avoid")
            row_vals = self.build_row_values(row)
            self.tree.insert("", "end", values=row_vals, tags=(rec,))

    def clear_table(self):
        for iid in self.tree.get_children():
            self.tree.delete(iid)

    def build_row_values(self, row: Dict) -> List[str]:
        return [
            row.get("ticker", "N/A"),
            row.get("earnings_date", "N/A"),
            _fmt(row.get("current_price", 0), "${:.2f}"),
            (
                f"${row.get('market_cap', 0):,}"
                if row.get("market_cap", 0)
                else "N/A"
            ),
            (
                f"{row.get('volume', 0):,}"
                if row.get("volume", 0)
                else "N/A"
            ),
            "PASS" if row.get("avg_volume") else "FAIL",
            (
                f"{int(row.get('avg_volume_value', 0)):,}"
                if row.get("avg_volume_value", 0)
                else "N/A"
            ),
            row.get("earnings_time", "Unknown"),
            row.get("recommendation", "Avoid"),
            row.get("expected_move", "N/A"),
            _fmt(row.get("atr14", 0), "{:.2f}"),
            _fmt(row.get("atr14_pct", 0), "{:.2f}%"),
            _fmt(row.get("iv30_rv30", 0), "{:.2f}"),
            _fmt(row.get("term_slope", 0), "{:.4f}"),
            (
                _fmt(row.get("term_structure", 0), "{:.2%}")
                if row.get("term_structure", 0)
                else "N/A"
            ),
            _fmt(row.get("historical_volatility", 0), "{:.2%}"),
            (
                _fmt(row.get("current_iv", 0), "{:.2%}")
                if row.get("current_iv", 0)
                else "N/A"
            ),
            (
                f"{row.get('iv_rank', 0):.0f}%"
                if row.get("iv_rank") is not None
                else "N/A"
            ),
        ]

    # -------- Sorting --------
    def on_column_heading_click(self, colname: str):
        ascending = self.sort_orders[colname]
        self.sort_orders[colname] = not ascending
        key_map = {
            "Ticker": "ticker",
            "Earnings Date": "earnings_date",
            "Price": "current_price",
            "Market Cap": "market_cap",
            "Volume 1d": "volume",
            "Avg Vol Check": "avg_volume",
            "30D Volume": "avg_volume_value",
            "Earnings Time": "earnings_time",
            "Recommendation": "recommendation",
            "Expected Move": "expected_move",
            "ATR 14d": "atr14",
            "ATR 14d %": "atr14_pct",
            "IV30/RV30": "iv30_rv30",
            "Term Slope": "term_slope",
            "Term Structure": "term_structure",
            "Historical Vol": "historical_volatility",
            "Current IV": "current_iv",
            "IV Rank": "iv_rank",
        }
        data_key = key_map.get(colname, colname)

        def transform_value(row: Dict):
            val = row.get(data_key, 0)
            if isinstance(val, str):
                if val.endswith("%"):
                    try:
                        return float(val[:-1])
                    except Exception:
                        return val
                if val.startswith("$"):
                    try:
                        return float(val.replace("$", "").replace(",", ""))
                    except Exception:
                        return val
                if val.replace(",", "").isdigit():
                    return float(val.replace(",", ""))
            return val

        self.raw_results.sort(
            key=lambda r: transform_value(r), reverse=not ascending
        )
        self.fill_table()
        adesc = "asc" if ascending else "desc"
        self.set_status(f"Sorted by {colname} ({adesc})")

    # -------- Double-Click => Chart --------
    def on_table_double_click(self, event):
        sel = self.tree.selection()
        if not sel:
            return
        item_id = sel[0]
        row_vals = self.tree.item(item_id, "values")
        if not row_vals:
            return
        ticker = row_vals[0]
        show_interactive_chart(ticker, self.analyzer.session_manager)

    # -------- Export CSV --------
    def on_export_csv(self):
        filtered = self.apply_filters(self.raw_results)
        if not filtered:
            self.set_status("No data to export.")
            return
        f = filedialog.asksaveasfilename(
            defaultextension=".csv", filetypes=[("CSV", "*.csv")]
        )
        if not f:
            return
        try:
            import csv

            with open(f, "w", newline="") as out:
                writer = csv.writer(out)
                writer.writerow(self.headings)
                for row in filtered:
                    rv = self.build_row_values(row)
                    writer.writerow(rv)
            self.set_status(f"Exported to {f}")
        except Exception as e:
            self.set_status(f"Export error: {e}")

    # -------- Calendar Popup --------
    def _is_dark_mode(self) -> bool:
        """Detect if macOS dark mode (or a dark theme) is active."""
        try:
            bg = self.root.cget("background")
            # Parse hex color to determine luminance
            if bg.startswith("#"):
                r, g, b = int(bg[1:3], 16), int(bg[3:5], 16), int(bg[5:7], 16)
            else:
                # Query Tk for RGB values (returns 16-bit per channel)
                r, g, b = [c >> 8 for c in self.root.winfo_rgb(bg)]
            return (0.299 * r + 0.587 * g + 0.114 * b) < 128
        except Exception:
            return False

    def open_calendar_popup(self):
        from tkcalendar import Calendar
        from datetime import datetime
        from tkinter.font import Font

        top = tk.Toplevel(self.root)
        top.title("Select Date")
        top.grab_set()
        raw = self.cal_date.get().strip()
        try:
            dt = datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError:
            dt = datetime.today().date()

        cal_font = Font(family="Helvetica", size=14)
        header_font = Font(family="Helvetica", size=16, weight="bold")

        dark = self._is_dark_mode()
        if dark:
            colors = dict(
                background="#3a3a3a",
                foreground="#e0e0e0",
                headersbackground="#2d2d2d",
                headersforeground="#e0e0e0",
                bordercolor="#555555",
                normalbackground="#3a3a3a",
                normalforeground="#e0e0e0",
                weekendbackground="#333333",
                weekendforeground="#c0c0c0",
                othermonthbackground="#2d2d2d",
                othermonthforeground="#666666",
                othermonthwebackground="#2d2d2d",
                othermonthweforeground="#555555",
                selectbackground="#4a90d9",
                selectforeground="white",
            )
            top.configure(bg="#2d2d2d")
        else:
            colors = dict(
                background="white",
                foreground="black",
                headersbackground="#f0f0f0",
                headersforeground="black",
                bordercolor="#cccccc",
                selectbackground="#4a90d9",
                selectforeground="white",
            )

        cal = Calendar(
            top, selectmode="day",
            year=dt.year, month=dt.month, day=dt.day,
            date_pattern="yyyy-mm-dd",
            font=cal_font,
            **colors,
        )
        # Override header/navigation fonts for readability on macOS
        cal._header.config(padding=4)
        for child in cal._header.winfo_children():
            try:
                child.configure(font=header_font)
            except tk.TclError:
                pass
        cal.pack(padx=15, pady=15)

        def on_select():
            self.cal_date.delete(0, "end")
            self.cal_date.insert(0, cal.get_date())
            top.destroy()

        ttk.Button(top, text="Select", command=on_select).pack(pady=(0, 15))

    def set_date_entry(self, days_offset: int):
        from datetime import date, timedelta

        target = date.today() + timedelta(days=days_offset)
        self.cal_date.delete(0, "end")
        self.cal_date.insert(0, target.strftime("%Y-%m-%d"))

    # -------- Helper --------
    def set_status(self, msg: str):
        self.lbl_status.config(text=f"Status: {msg}")


def main():
    root = tk.Tk()
    EarningsTkApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()

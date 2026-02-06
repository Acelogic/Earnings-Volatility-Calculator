# Architecture

## Project Structure

```
Earnings-Volatility-Calculator/
├── pyproject.toml                # Project metadata, dependencies, build config
├── uv.lock                       # Locked dependency versions
├── .python-version               # Python 3.10+
├── README.md                     # User-facing documentation
├── src/
│   └── earnings_calculator/      # Main Python package
│       ├── __init__.py           # Public API exports
│       ├── __main__.py           # python -m earnings_calculator entry
│       ├── logging_config.py     # Shared logging helpers
│       ├── proxy.py              # ProxyManager
│       ├── sessions.py           # SessionManager (requests + curl_cffi)
│       ├── options.py            # OptionsAnalyzer (volatility + options math)
│       ├── calendar.py           # EarningsCalendarFetcher
│       ├── cache.py              # DataCache (pickle-based)
│       ├── scanner.py            # EnhancedEarningsScanner + update_otc_tickers
│       ├── chart.py              # Candlestick chart rendering
│       ├── gui.py                # EarningsTkApp (Tkinter GUI) + main()
│       └── assets/
│           ├── __init__.py       # Package marker
│           └── icon.png          # App icon (256x256 candlestick chart)
├── tests/
│   ├── conftest.py               # Shared fixtures
│   ├── test_logging_config.py
│   ├── test_proxy.py
│   ├── test_sessions.py
│   ├── test_analyzer.py          # OptionsAnalyzer (pure math + mocked API)
│   ├── test_earnings.py          # EarningsCalendarFetcher
│   ├── test_cache.py
│   ├── test_scanner.py           # Recommendation logic + batch processing
│   ├── test_gui.py               # GUI helper functions
│   ├── test_gui_integration.py   # Full Tkinter integration tests
│   └── test_otc_updater.py
```

**Runtime artifacts** (gitignored, generated at runtime):
- `otc-tickers.txt` — Auto-generated OTC ticker blacklist
- `stock_cache/` — Pickle-based analysis cache
- `*_debug.log` — Per-component debug logs

---

## Module Dependency Graph

```
logging_config  (leaf - no internal deps)
    ↑
  proxy         (leaf + logging)
    ↑
  sessions      (proxy)
    ↑
  ┌─┴──────┬────────┐
options  calendar  cache  (each: logging + sessions or standalone)
  ↑        ↑        ↑
  └───┬────┴────┬───┘
   scanner    chart
      ↑         ↑
      └────┬────┘
          gui
```

All intra-package imports use absolute form: `from earnings_calculator.proxy import ProxyManager`

---

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     EarningsTkApp (GUI)                         │
│  Tkinter root window, table, filters, progress bar, controls   │
│                                                                 │
│  User Actions:                                                  │
│    Analyze Stock ─────► on_analyze_stock()                      │
│    Scan Earnings ─────► on_scan_earnings()                      │
│    Double-Click Row ──► show_interactive_chart()                │
│    Export CSV ────────► on_export_csv()                         │
│    Update Proxies ───► on_update_proxies()                     │
└──────────┬──────────────────────┬───────────────────────────────┘
           │                      │
           ▼                      ▼
┌─────────────────────┐  ┌────────────────────────┐
│ EnhancedEarnings-   │  │    OptionsAnalyzer      │
│ Scanner             │  │                         │
│                     │  │  Volatility math:       │
│  Orchestrates the   │  │   yang_zhang_volatility │
│  full scan pipeline │  │   compute_atr           │
│                     │  │   build_term_structure   │
│  batch_download     │  │                         │
│  _history()         │  │  Options analysis:      │
│  scan_earnings      │  │   compute_recommendation│
│  _stocks()          │  │   get_current_price     │
│  analyze_stock()    │  │   filter_dates          │
└──┬───────┬──────────┘  └──────────┬──────────────┘
   │       │                        │
   │       ▼                        │
   │  ┌──────────────────┐          │
   │  │  DataCache        │         │
   │  │  stock_cache/*.pkl│         │
   │  │  7-day expiry     │         │
   │  └──────────────────┘          │
   │                                │
   ▼                                ▼
┌──────────────────────┐   ┌─────────────────────┐
│ EarningsCalendar-    │   │   SessionManager     │
│ Fetcher              │   │                      │
│                      │   │  get_session()       │◄── requests.Session
│  Scrapes earnings    │   │    (HTTP scraping)   │    (investing.com, proxies)
│  from investing.com  │   │                      │
│  Extracts tickers +  │   │  get_yf_session()    │◄── curl_cffi.Session
│  timing (Pre/Post)   │   │    (yfinance calls)  │    (Yahoo Finance API)
└──────────────────────┘   └──────────┬──────────┘
                                      │
                                      ▼
                           ┌─────────────────────┐
                           │   ProxyManager       │
                           │                      │
                           │  5 proxy sources     │
                           │  Parallel validation │
                           │  Random rotation     │
                           └──────────────────────┘
```

---

## Component Details

### `EarningsTkApp` (`gui.py`)

The GUI layer. Owns all other components and coordinates user interactions.

- **Startup**: Sets the app icon via `_set_icon()` (loaded from `assets/icon.png` with `importlib.resources`), creates `ProxyManager` (enabled by default), `OptionsAnalyzer`, `EnhancedEarningsScanner`. Spawns a daemon thread to refresh `otc-tickers.txt` via `update_otc_tickers()`.
- **Threading model**: All data-fetching operations run on daemon threads to keep the UI responsive. All widget updates from worker threads (including `set_status()` and `progress_var.set()`) are marshalled back to the main thread via `root.after()` to maintain Tkinter thread safety.
- **Table**: A `ttk.Treeview` with 16 sortable columns. Rows are color-coded by recommendation tag (green/orange/red).
- **Filters**: Earnings time, recommendation, and min stock price. Applied client-side over `raw_results`.

### `EnhancedEarningsScanner` (`scanner.py`)

The orchestration layer for earnings scanning. Coordinates all other components to process a date's earnings.

| Method | Purpose |
|---|---|
| `scan_earnings_stocks()` | Full pipeline: fetch tickers, filter OTC, check cache, batch analyze |
| `batch_download_history()` | Downloads OHLCV for up to 10 tickers at once via `yf.download()` |
| `analyze_stock()` | Per-ticker analysis: price, volume, volatility, options recommendation. Passes history data through to `compute_recommendation()` to avoid redundant downloads. |

**Batch processing**: Tickers are processed in batches of 10. Within each batch, history is downloaded in a single `yf.download()` call, then individual analysis runs in a `ThreadPoolExecutor` (max 5 workers).

**Module constants** (defined at module level):
- `MIN_IV30_RV30_RATIO = 1.25` — minimum IV30/RV30 ratio for recommendation
- `MAX_TERM_SLOPE = -0.00406` — maximum term slope threshold

**Recommendation logic** (in `analyze_stock()`):

| Label | Criteria |
|---|---|
| **Recommended** | Avg volume >= `MIN_AVG_VOLUME` AND IV30/RV30 >= `MIN_IV30_RV30_RATIO` AND term slope <= `MAX_TERM_SLOPE` |
| **Consider** | Term slope passes AND one of (volume, IV ratio) passes |
| **Avoid** | Everything else |

### `OptionsAnalyzer` (`options.py`)

The quantitative analysis engine. Stateless math + Yahoo Finance API calls.

**Module constants** (defined at module level for easy tuning):
- `FILTER_MAX_DTE = 45` — maximum days-to-expiration for option chain filtering
- `IV_INTERPOLATION_DTE = 30` — target DTE for IV interpolation and rolling volume average
- `MIN_AVG_VOLUME = 1_500_000` — minimum 30-day average volume threshold

**Volatility calculations**:
- `yang_zhang_volatility()` - Primary estimator using Open/High/Low/Close. 30-day rolling window, annualized to 252 trading days. Falls back to `calculate_simple_volatility()` on error.
- `compute_atr()` - 14-day Average True Range.

**Options analysis** (`compute_recommendation(symbol, history_data=None)`):
1. Accepts optional `history_data` (3mo OHLCV DataFrame) to avoid redundant API calls when called from the scanner
2. Fetches option chains for expiration dates within `FILTER_MAX_DTE` days
3. Finds ATM strikes (closest to current price) for calls and puts
4. Averages call/put implied volatility per expiration
5. Builds a term structure spline via `scipy.interpolate.interp1d`
6. Interpolates IV at `IV_INTERPOLATION_DTE` days (IV30)
7. Computes term slope: `(IV_max_dte - IV_nearest) / days_between`
8. Computes expected move from front-month straddle mid prices
9. Derives volume, HV, avg volume, and ATR from the single 3mo history (no separate API calls)

### `EarningsCalendarFetcher` (`calendar.py`)

Scrapes the Investing.com earnings calendar API for a given date. Returns a list of ticker symbols and maps each to its earnings timing (Pre Market / Post Market / During Market).

Uses `requests.Session` (not yfinance), so this goes through `SessionManager.get_session()`.

### `DataCache` (`cache.py`)

Pickle-based file cache in `stock_cache/`. Cache key = MD5 of `"{date}_{sorted_tickers}"`.

- **Expiry**: 7 days
- **Missing data tracking**: Identifies entries with `N/A` fields and attempts to re-fetch them on subsequent scans
- **Operations**: `save_data()`, `get_data()`, `update_missing_data()`, `clear_expired()`

### `SessionManager` (`sessions.py`)

Manages two separate HTTP session types:

| Method | Session Type | Used For |
|---|---|---|
| `get_session()` | `requests.Session` | Investing.com scraping, proxy validation |
| `get_yf_session()` | `curl_cffi.Session` | All yfinance API calls (required since yfinance 1.x) |

Both session types are proxy-aware. `rotate_session()` closes the old sessions before recreating both with a new proxy from the pool, preventing resource leaks during proxy rotation.

### `ProxyManager` (`proxy.py`)

Fetches, validates, and rotates free HTTP proxies from 5 sources:

| Source | Method |
|---|---|
| ProxyScrape API | `fetch_proxyscrape()` |
| Geonode API | `fetch_geonode()` |
| PubProxy API | `fetch_pubproxy()` |
| proxy-list.download | `fetch_proxylist_download()` |
| Spys.one (HTML scrape) | `fetch_spys_one()` |

Validation: Tests each candidate against `httpbin.org/ip` in a thread pool (20 concurrent workers), keeps up to 50 valid proxies.

### `update_otc_tickers()` (`scanner.py`)

Standalone function that runs as a daemon thread at startup. Paginates through the StockAnalysis.com screener API to build a blocklist of OTC-listed tickers, written to `otc-tickers.txt` via atomic write (temp file + `os.replace()`) to prevent race conditions with concurrent reads from `scan_earnings_stocks()`. Used to filter out illiquid/OTC stocks before analysis.

### `show_interactive_chart()` (`chart.py`)

Standalone function triggered by double-clicking a table row. Creates a `yf.Ticker`, fetches 1 year of history, and renders a candlestick chart with volume via `mplfinance`.

---

## Data Flow: Earnings Scan

```
User clicks "Scan Earnings" for date D
         │
         ▼
EarningsCalendarFetcher.fetch_earnings_data(D)
    → POST to investing.com → parse HTML → [AAPL, MSFT, ...]
         │
         ▼
Filter out OTC tickers (from otc-tickers.txt)
         │
         ▼
DataCache.get_data(D, tickers)
    ├── Cache HIT → return cached results (re-fetch missing fields)
    └── Cache MISS ▼
         │
         ▼
For each batch of 10 tickers:
    │
    ├── yf.download(batch, period=3mo) → DataFrame per ticker
    │
    └── ThreadPoolExecutor(5 workers):
            │
            ├── analyze_stock(ticker, history_df)
            │     ├── Check exchange (skip OTC)
            │     ├── yang_zhang_volatility(history) → HV30
            │     ├── compute_recommendation(ticker)
            │     │     ├── Fetch option chains (≤45 DTE)
            │     │     ├── Find ATM IV per expiration
            │     │     ├── Build term structure spline
            │     │     ├── Interpolate IV30, compute slope
            │     │     ├── Compute expected move (straddle)
            │     │     └── Compute ATR 14d
            │     └── Classify: Recommended / Consider / Avoid
            │
            └── Collect results, update progress bar
         │
         ▼
DataCache.save_data(D, tickers, results)
         │
         ▼
GUI: fill_table() → apply filters → render Treeview rows
```

---

## External Dependencies

| Package | Purpose |
|---|---|
| `yfinance` | Yahoo Finance API (price history, options chains, ticker info) |
| `curl_cffi` | HTTP sessions for yfinance 1.x (anti-bot browser impersonation) |
| `requests` | HTTP client for non-yfinance calls (investing.com, proxy APIs) |
| `beautifulsoup4` | HTML parsing (earnings calendar, proxy scraping) |
| `pandas` / `numpy` | DataFrames, numerical computation |
| `scipy` | `interp1d` for IV term structure interpolation |
| `matplotlib` / `mplfinance` | Candlestick charting |
| `tkcalendar` | Date picker widget for Tkinter |

Dev dependencies: `pytest`, `freezegun`

---

## Testing

Run the test suite:

```bash
uv run pytest tests/ -v
```

Tests cover all modules with mocked external dependencies (no network calls). Key test areas:
- **Volatility math**: Yang-Zhang, simple volatility, ATR, term structure interpolation
- **Recommendation logic**: All 8 branch combinations + boundary values
- **Cache**: Roundtrip, expiry, missing data tracking, corrupt file handling
- **Earnings calendar**: HTML parsing, timing extraction, retry logic
- **Proxy management**: All 5 sources, validation, pool building, rotation
- **Sessions**: Dual session creation, proxy integration, rotation
- **GUI helpers**: Row formatting, filter logic

---

## Logging

Each major component writes to its own debug log file via `create_logger()`:

| Component | Log File |
|---|---|
| `ProxyManager` | `proxy_manager_debug.log` |
| `OptionsAnalyzer` | `options_analyzer_debug.log` |
| `EarningsCalendarFetcher` | `earnings_calendar_debug.log` |
| `EnhancedEarningsScanner` | `earnings_scanner_debug.log` |
| `DataCache` | `cache_debug.log` |

All loggers also output INFO-level messages to the console via `add_console_logging()`.

---

## Key Design Decisions

1. **Modular package structure**: Code split into focused modules with a clear dependency graph (no cycles). Each module has a single responsibility.

2. **Dual session types**: yfinance 1.x requires `curl_cffi` sessions (browser impersonation), while other HTTP calls use standard `requests`. `SessionManager` abstracts this.

3. **Batch + concurrent processing**: `yf.download()` handles multi-ticker downloads efficiently. Individual analysis then runs in thread pools to parallelize API-heavy option chain fetching.

4. **Cache-first strategy**: Results are cached for 7 days with missing-field tracking. Subsequent scans for the same date/tickers hit cache and only re-fetch incomplete entries.

5. **OTC filtering at two levels**: First via a static blocklist (`otc-tickers.txt`, refreshed on startup), then via exchange metadata from Yahoo Finance (`ticker.info['exchange']`).

6. **Proxy rotation on failure**: Every API call that can fail (price fetch, option chain, batch download) retries up to 3 times, rotating to a new proxy between attempts.

7. **uv for dependency management**: `pyproject.toml` defines all deps with `uv.lock` for reproducible installs. Dev dependencies (pytest, freezegun) are in a separate `[dependency-groups]`.

"""Earnings scanning orchestration and OTC ticker updater."""

import concurrent.futures
import os
import tempfile
from datetime import datetime
from typing import Callable, Dict, List, Optional

import pandas as pd
import requests
import yfinance as yf
import yfinance.shared as shared

MIN_IV30_RV30_RATIO = 1.25
MAX_TERM_SLOPE = -0.00406

from earnings_calculator.cache import DataCache
from earnings_calculator.calendar import EarningsCalendarFetcher
from earnings_calculator.logging_config import create_logger
from earnings_calculator.options import OptionsAnalyzer


def update_otc_tickers():
    """Download OTC tickers from StockAnalysis API and write to otc-tickers.txt."""
    base_url = "https://api.stockanalysis.com/api/screener/a/f"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:135.0) "
        "Gecko/20100101 Firefox/135.0",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.5",
        "Referer": "https://stockanalysis.com/",
        "Origin": "https://stockanalysis.com",
    }
    params = {
        "m": "marketCap",
        "s": "desc",
        "c": "no,s,n,marketCap,price,change,revenue",
        "cn": "1000",
        "f": "exchangeCode-is-OTC,subtype-is-stock",
        "i": "symbols",
    }
    all_tickers = []
    page = 1
    while True:
        params["p"] = page
        response = requests.get(base_url, headers=headers, params=params)
        response.raise_for_status()
        data = response.json()
        page_data = data.get("data", {}).get("data", [])
        if not page_data:
            break
        for item in page_data:
            full_symbol = item.get("s", "")
            ticker = full_symbol.split("/")[-1] if "/" in full_symbol else full_symbol
            all_tickers.append(ticker)
        print(f"Processed page {page}")
        page += 1
    with tempfile.NamedTemporaryFile(mode="w", suffix=".tmp", dir=".", delete=False) as tmp:
        for ticker in all_tickers:
            tmp.write(f"{ticker}\n")
        tmp_path = tmp.name
    os.replace(tmp_path, "otc-tickers.txt")
    print("Total OTC tickers count:", len(all_tickers))
    print("OTC tickers have been written to otc-tickers.txt")


class EnhancedEarningsScanner:
    def __init__(self, analyzer: OptionsAnalyzer):
        self.analyzer = analyzer
        self.calendar_fetcher = EarningsCalendarFetcher(self.analyzer.proxy_manager)
        self.data_cache = DataCache()
        self.batch_size = 10
        self.logger = create_logger(
            "EnhancedEarningsScanner", "earnings_scanner_debug.log"
        )

    def batch_download_history(self, tickers: List[str]) -> Dict[str, pd.DataFrame]:
        ticker_str = " ".join(tickers)
        try:
            for _ in range(3):
                data = yf.download(
                    tickers=ticker_str,
                    period="1y",
                    group_by="ticker",
                    auto_adjust=True,
                    prepost=True,
                    threads=True,
                    session=self.analyzer.session_manager.get_yf_session(),
                )

                if (
                    self.analyzer.session_manager.proxy_manager.proxy_enabled
                    and len(shared._ERRORS) > 0
                ):
                    self.analyzer.session_manager.rotate_session()
                else:
                    break

            res = {}
            if len(tickers) == 1:
                res[tickers[0]] = data
            else:
                for tk in tickers:
                    try:
                        df = data.xs(tk, axis=1, level=0)
                        if not df.empty:
                            res[tk] = df
                    except Exception as e:
                        self.logger.debug(f"Could not extract data for {tk}: {e}")
                        continue
            return res
        except Exception as e:
            self.logger.error(f"batch download error: {e}")
            return {}

    def scan_earnings_date_range(
        self,
        start_date: datetime,
        end_date: datetime,
        progress_callback: Optional[Callable] = None,
    ) -> List[Dict]:
        """Scan earnings across a range of business days.

        Loops over each business day from *start_date* to *end_date*
        (inclusive), calls ``scan_earnings_stocks`` per day, injects an
        ``earnings_date`` key, and aggregates all results.
        """
        dates = pd.bdate_range(start_date, end_date)
        if dates.empty:
            return []
        all_results: List[Dict] = []
        n_dates = len(dates)
        for idx, day in enumerate(dates):
            day_dt = day.to_pydatetime()
            day_str = day_dt.strftime("%Y-%m-%d")

            def day_progress(val, _idx=idx):
                if progress_callback:
                    base = _idx / n_dates * 100
                    progress_callback(base + val / n_dates)

            results = self.scan_earnings_stocks(day_dt, day_progress)
            for r in results:
                r["earnings_date"] = day_str
            all_results.extend(results)
        if progress_callback:
            progress_callback(100)
        return all_results

    def scan_earnings_stocks(
        self, date: datetime, progress_callback: Optional[Callable] = None
    ) -> List[Dict]:
        ds = date.strftime("%Y-%m-%d")
        self.logger.info(f"Scan earnings for {ds}")
        e_stocks = self.calendar_fetcher.fetch_earnings_data(ds)
        try:
            with open("otc-tickers.txt", "r") as f:
                otc_tickers = {line.strip().upper() for line in f if line.strip()}
        except FileNotFoundError:
            otc_tickers = set()
        original_count = len(e_stocks)
        e_stocks = [ticker for ticker in e_stocks if ticker.upper() not in otc_tickers]
        self.logger.info(
            f"Filtered out {original_count - len(e_stocks)} OTC tickers."
        )
        if not e_stocks:
            return []
        cached_data, missing_data = self.data_cache.get_data(ds, e_stocks)
        if cached_data:
            self.logger.info(f"Using cached data for {ds}")
            raw_results = cached_data
            if missing_data:
                self.logger.info(f"{len(missing_data)} missing, attempting fill.")
                missing_tickers = [m["ticker"] for m in missing_data]
                done = 0
                total = len(missing_tickers)
                batches = [
                    missing_tickers[i : i + self.batch_size]
                    for i in range(0, total, self.batch_size)
                ]
                for b in batches:
                    hist = self.batch_download_history(b)
                    with concurrent.futures.ThreadPoolExecutor(
                        max_workers=min(5, len(b))
                    ) as ex:
                        fut2stk = {
                            ex.submit(self.analyze_stock, st, hist.get(st)): st
                            for st in b
                        }
                        for fut in concurrent.futures.as_completed(fut2stk):
                            stsym = fut2stk[fut]
                            done += 1
                            if progress_callback:
                                val = 80 + (done / total * 20)
                                progress_callback(val)
                            try:
                                r = fut.result()
                                if r:
                                    self.data_cache.update_missing_data(
                                        ds, e_stocks, r
                                    )
                            except Exception as e_:
                                self.logger.error(f"Error updating {stsym}: {e_}")
                cached_data, _ = self.data_cache.get_data(ds, e_stocks)
                raw_results = cached_data
            if progress_callback:
                progress_callback(100)
            return raw_results
        recommended = []
        total_stocks = len(e_stocks)
        done = 0
        batches = [
            e_stocks[i : i + self.batch_size]
            for i in range(0, total_stocks, self.batch_size)
        ]
        for b in batches:
            hist_map = self.batch_download_history(b)
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=min(5, len(b))
            ) as ex:
                fut2stk = {
                    ex.submit(self.analyze_stock, st, hist_map.get(st)): st
                    for st in b
                }
                for ft in concurrent.futures.as_completed(fut2stk):
                    st = fut2stk[ft]
                    done += 1
                    if progress_callback:
                        pc = done / total_stocks * 80
                        progress_callback(pc)
                    try:
                        r = ft.result()
                        if r:
                            recommended.append(r)
                    except Exception as e_:
                        self.logger.error(f"Error processing future result: {e_}")
        recommended.sort(
            key=lambda x: (
                x["recommendation"] != "Recommended",
                x["earnings_time"] == "Unknown",
                x["earnings_time"],
                x["ticker"],
            )
        )
        self.data_cache.save_data(ds, e_stocks, recommended)
        if progress_callback:
            progress_callback(100)
        return recommended

    def analyze_stock(
        self,
        ticker: str,
        history_data: Optional[pd.DataFrame] = None,
        skip_otc_check: bool = False,
    ) -> Optional[Dict]:
        try:
            st2 = self.analyzer.get_ticker(ticker)
            if not skip_otc_check:
                exchange = st2.info.get("exchange", "")
                otc_exchanges = {"PNK", "Other OTC", "OTC", "GREY"}
                if exchange in otc_exchanges:
                    self.logger.info(
                        f"[SKIP] Ticker '{ticker}' is OTC (exchange='{exchange}')."
                    )
                    return None
            if history_data is None or history_data.empty:
                hd = st2.history(period="1y")
                if hd.empty:
                    hd = st2.history(period="1mo")
                if hd.empty:
                    self.logger.warning(f"No data for {ticker}; skipping.")
                    return None
                history_data = hd

            if isinstance(history_data.columns, pd.MultiIndex):
                history_data.columns = history_data.columns.get_level_values(1)
            if "Close" in history_data.columns:
                cp = history_data["Close"].iloc[-1]
            elif "Adj Close" in history_data.columns:
                cp = history_data["Adj Close"].iloc[-1]
            else:
                raise ValueError("No close price data available.")
            voldata = history_data["Volume"]
            hv = self.analyzer.yang_zhang_volatility(history_data)
            tv = voldata.iloc[-1] if not voldata.empty else 0
            od = self.analyzer.compute_recommendation(ticker, history_data=history_data)
            if isinstance(od, dict) and "error" not in od:
                avb = od["avg_volume"]
                ivcheck = od["iv30_rv30"] >= MIN_IV30_RV30_RATIO
                slopecheck = od["term_slope"] <= MAX_TERM_SLOPE
                if avb and ivcheck and slopecheck:
                    rec = "Recommended"
                elif slopecheck and ((avb and not ivcheck) or (ivcheck and not avb)):
                    rec = "Consider"
                else:
                    rec = "Avoid"
                return {
                    "ticker": ticker,
                    "current_price": cp,
                    "market_cap": st2.info.get("marketCap", 0),
                    "volume": tv,
                    "avg_volume": avb,
                    "avg_volume_value": od.get("avg_volume_value", 0),
                    "earnings_time": self.calendar_fetcher.get_earnings_time(ticker),
                    "recommendation": rec,
                    "expected_move": od.get("expected_move", "N/A"),
                    "atr14": od.get("atr14", 0),
                    "atr14_pct": od.get("atr14_pct", 0),
                    "iv30_rv30": od.get("iv30_rv30", 0),
                    "term_slope": od.get("term_slope", 0),
                    "term_structure": od.get("term_structure", 0),
                    "historical_volatility": hv,
                    "current_iv": od.get("current_iv", None),
                    "iv_rank": od.get("iv_rank", None),
                }
            return {
                "ticker": ticker,
                "current_price": cp,
                "market_cap": 0,
                "volume": tv,
                "avg_volume": False,
                "avg_volume_value": 0,
                "earnings_time": self.calendar_fetcher.get_earnings_time(ticker),
                "recommendation": "Avoid",
                "expected_move": "N/A",
                "atr14": 0,
                "atr14_pct": 0,
                "iv30_rv30": 0,
                "term_slope": 0,
                "term_structure": 0,
                "historical_volatility": hv,
                "current_iv": None,
                "iv_rank": None,
            }
        except Exception as e:
            self.logger.error(f"Analyze error for {ticker}: {e}")
            return None

"""
DISCLAIMER: 

This software is provided solely for educational and research purposes. 
It is not intended to provide investment advice, and no investment recommendations are made herein. 
The developers are not financial advisors and accept no responsibility for any financial decisions or losses resulting from the use of this software.
Always consult a professional financial advisor before making any investment decisions.
"""

import os
import random
import logging
import warnings
import json
import pickle
import hashlib
import threading
import concurrent.futures
from queue import Queue
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Callable

import requests
import pandas as pd
import numpy as np
import yfinance as yf
import yfinance.shared as shared
from bs4 import BeautifulSoup

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

try:
    from tkcalendar import DateEntry
except ImportError:
    messagebox.showerror("Missing Library",
                         "Please install tkcalendar:\n\n  pip install tkcalendar\n\nThen re-run.")
    raise SystemExit

import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
import mplfinance as mpf

# ====================== OTC Ticker Updater ======================
def update_otc_tickers():
    """
    Downloads OTC tickers from StockAnalysis API and writes them to otc-tickers.txt.
    This runs automatically at startup so that the earnings scan can filter out OTC stocks.
    """
    base_url = "https://api.stockanalysis.com/api/screener/a/f"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:135.0) Gecko/20100101 Firefox/135.0",
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
        "i": "symbols"
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
    with open("otc-tickers.txt", "w") as f:
        for ticker in all_tickers:
            f.write(f"{ticker}\n")
    print("Total OTC tickers count:", len(all_tickers))
    print("OTC tickers have been written to otc-tickers.txt")

# ====================== Utility to Add Console Logging ======================
def add_console_logging(logger: logging.Logger, level=logging.INFO):
    if not any(isinstance(h, logging.StreamHandler) for h in logger.handlers):
        ch = logging.StreamHandler()
        ch.setLevel(level)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        ch.setFormatter(formatter)
        logger.addHandler(ch)

# ====================== ProxyManager ======================
class ProxyManager:
    def __init__(self):
        self.proxies: List[Dict[str, str]] = []
        self.current_proxy: Optional[Dict[str, str]] = None
        self.proxy_enabled: bool = False
        self._initialize_logging()
    
    def _initialize_logging(self):
        self.logger = logging.getLogger('ProxyManager')
        self.logger.setLevel(logging.DEBUG)
        if not self.logger.handlers:
            fh = logging.FileHandler('proxy_manager_debug.log')
            fh.setLevel(logging.DEBUG)
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            fh.setFormatter(formatter)
            self.logger.addHandler(fh)
        add_console_logging(self.logger, level=logging.INFO)
    
    # ----- Fetching Proxies from Multiple Sources -----
    def fetch_proxyscrape(self) -> List[Dict[str, str]]:
        try:
            url = ("https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=10000"
                   "&country=all&ssl=all&anonymity=all")
            resp = requests.get(url, timeout=15)
            if resp.status_code == 200:
                lines = [x.strip() for x in resp.text.split('\n') if x.strip()]
                return [{'http': f"http://{line}", 'https': f"http://{line}"} for line in lines]
            return []
        except Exception as e:
            self.logger.error(f"Error from Proxyscrape: {e}")
            return []
    
    def fetch_geonode(self) -> List[Dict[str, str]]:
        try:
            url = ("https://proxylist.geonode.com/api/proxy-list?limit=100&page=1"
                   "&sort_by=lastChecked&sort_type=desc&protocols=http"
                   "&anonymityLevel=elite&anonymityLevel=anonymous")
            resp = requests.get(url, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                proxies = []
                for p in data.get('data', []):
                    ip = p['ip']
                    port = p['port']
                    proxies.append({'http': f"http://{ip}:{port}", 'https': f"http://{ip}:{port}"})
                return proxies
            return []
        except Exception as e:
            self.logger.error(f"Error from Geonode: {e}")
            return []
    
    def fetch_pubproxy(self) -> List[Dict[str, str]]:
        try:
            url = "http://pubproxy.com/api/proxy?limit=20&format=json&type=http"
            resp = requests.get(url, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                proxies = []
                for p in data.get('data', []):
                    ip = p['ip']
                    port = p['port']
                    proxies.append({'http': f"http://{ip}:{port}", 'https': f"http://{ip}:{port}"})
                return proxies
            return []
        except Exception as e:
            self.logger.error(f"Error from PubProxy: {e}")
            return []
    
    def fetch_proxylist_download(self) -> List[Dict[str, str]]:
        try:
            url = "https://www.proxy-list.download/api/v1/get?type=http"
            resp = requests.get(url, timeout=15)
            if resp.status_code == 200:
                lines = [x.strip() for x in resp.text.split('\n') if x.strip()]
                return [{'http': f"http://{line}", 'https': f"http://{line}"} for line in lines]
            return []
        except Exception as e:
            self.logger.error(f"Error from ProxyList.download: {e}")
            return []
    
    def fetch_spys_one(self) -> List[Dict[str, str]]:
        try:
            url = "https://spys.one/free-proxy-list/ALL/"
            headers = {'User-Agent': 'Mozilla/5.0'}
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, 'html.parser')
                rows = soup.find_all('tr', class_=['spy1x', 'spy1xx'])
                proxies = []
                for r in rows:
                    cols = r.find_all('td')
                    if len(cols) >= 2:
                        ip = cols[0].text.strip()
                        port = cols[1].text.strip()
                        proxies.append({'http': f"http://{ip}:{port}", 'https': f"http://{ip}:{port}"})
                return proxies
            return []
        except Exception as e:
            self.logger.error(f"Error from Spys.one: {e}")
            return []
    
    # ----- Parallel Proxy Validation with Feedback -----
    def validate_proxy(self, proxy: Dict[str, str], timeout=3) -> bool:
        """
        Quickly test a proxy by calling httpbin.org/ip.
        Returns True if successful within timeout; else False.
        """
        test_url = "https://httpbin.org/ip"
        try:
            resp = requests.get(test_url, proxies=proxy, timeout=timeout)
            if resp.status_code == 200:
                reported_ip = resp.json().get("origin", "")
                proxy_ip = proxy['http'].split("//")[-1].split(":")[0]
                if proxy_ip in reported_ip:
                    return True
        except Exception:
            return False
        return False
    
    def build_valid_proxy_pool(self, max_proxies=50, concurrency=20, progress_callback: Optional[Callable[[str], None]] = None) -> None:
        """
        Fetch candidate proxies and validate them in parallel.
        Only working proxies are kept in self.proxies.
        The progress_callback (if provided) receives status messages.
        """
        candidates = []
        sources = [
            self.fetch_proxyscrape,
            self.fetch_geonode,
            self.fetch_pubproxy,
            self.fetch_proxylist_download,
            self.fetch_spys_one
        ]
        for src in sources:
            src_candidates = src()
            candidates.extend(src_candidates)
            msg = f"Fetched {len(src_candidates)} from {src.__name__}"
            self.logger.info(msg)
            if progress_callback:
                progress_callback(msg)
        # Remove duplicates
        candidates = list({p['http']: p for p in candidates}.values())
        msg = f"{len(candidates)} unique candidate proxies after deduplication."
        self.logger.info(msg)
        if progress_callback:
            progress_callback(msg)
        self.logger.info("Starting parallel validation...")
        if progress_callback:
            progress_callback("Starting parallel validation of proxies...")
        valid = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
            future_to_proxy = {executor.submit(self.validate_proxy, p): p for p in candidates}
            for future in concurrent.futures.as_completed(future_to_proxy):
                p = future_to_proxy[future]
                try:
                    if future.result():
                        valid.append(p)
                        msg = f"Validated: {p['http']}"
                        self.logger.info(msg)
                        if progress_callback:
                            progress_callback(msg)
                        if len(valid) >= max_proxies:
                            break
                except Exception:
                    continue
        self.proxies = valid
        msg = f"Validation complete. {len(valid)} proxies are usable."
        self.logger.info(msg)
        if progress_callback:
            progress_callback(msg)
    
    def get_proxy(self):
        if not self.proxy_enabled or not self.proxies:
            return None
        self.current_proxy = random.choice(self.proxies)
        return self.current_proxy
    
    def rotate_proxy(self):
        if not self.proxy_enabled or len(self.proxies) <= 1:
            return None
        available = [p for p in self.proxies if p != self.current_proxy]
        if available:
            self.current_proxy = random.choice(available)
            return self.current_proxy
        return None

# ====================== SessionManager ======================
class SessionManager:
    def __init__(self, proxy_manager: ProxyManager):
        self.proxy_manager = proxy_manager
        self.session = self._create_session()
    
    def _create_session(self) -> requests.Session:
        s = requests.Session()
        if self.proxy_manager.proxy_enabled:
            p = self.proxy_manager.get_proxy()
            if p:
                s.proxies.update(p)
        return s
    
    def rotate_session(self):
        if self.proxy_manager.proxy_enabled:
            p = self.proxy_manager.rotate_proxy()
            if p:
                self.session = self._create_session()
    
    def get_session(self) -> requests.Session:
        return self.session

# ====================== OptionsAnalyzer ======================
NUMPY_VERSION = tuple(map(int, np.__version__.split('.')[:2]))
IS_NUMPY_2 = (NUMPY_VERSION[0] >= 2)

class OptionsAnalyzer:
    def __init__(self, proxy_manager=None):
        self.warnings_shown = False
        self.proxy_manager = proxy_manager or ProxyManager()
        self.session_manager = SessionManager(self.proxy_manager)
        self._init_log()
    
    def _init_log(self):
        self.logger = logging.getLogger('OptionsAnalyzer')
        self.logger.setLevel(logging.DEBUG)
        if not self.logger.handlers:
            fh = logging.FileHandler('options_analyzer_debug.log')
            fh.setLevel(logging.DEBUG)
            formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            fh.setFormatter(formatter)
            self.logger.addHandler(fh)
        add_console_logging(self.logger, level=logging.INFO)
    
    def safe_log(self, val: np.ndarray) -> np.ndarray:
        if IS_NUMPY_2:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                return np.log(val)
        return np.log(val)
    
    def safe_sqrt(self, val: np.ndarray) -> np.ndarray:
        if IS_NUMPY_2:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                return np.sqrt(val)
        return np.sqrt(val)
    
    def get_ticker(self, symbol: str) -> yf.Ticker:
        t = yf.Ticker(symbol)
        t.session = self.session_manager.get_session()
        return t
    
    def filter_dates(self, dates: List[str]) -> List[str]:
        today = datetime.today().date()
        cutoff = today + timedelta(days=45)
        sdates = sorted(datetime.strptime(d, "%Y-%m-%d").date() for d in dates)
        arr = []
        for i, d in enumerate(sdates):
            if d >= cutoff:
                arr = [x.strftime("%Y-%m-%d") for x in sdates[:i+1]]
                break
        if arr:
            if arr[0] == today.strftime("%Y-%m-%d") and len(arr) > 1:
                arr = arr[1:]
            return arr
        else:
            return [x.strftime("%Y-%m-%d") for x in sdates]
    
    def yang_zhang_volatility(self, pdf: pd.DataFrame,
                              window=30, trading_periods=252,
                              return_last_only=True):
        try:
            log_ho = self.safe_log(pdf['High']/pdf['Open'])
            log_lo = self.safe_log(pdf['Low']/pdf['Open'])
            log_co = self.safe_log(pdf['Close']/pdf['Open'])
            log_oc = self.safe_log(pdf['Open']/pdf['Close'].shift(1))
            log_oc_sq = log_oc**2
            log_cc = self.safe_log(pdf['Close']/pdf['Close'].shift(1))
            log_cc_sq = log_cc**2
            rs = log_ho*(log_ho - log_co) + log_lo*(log_lo - log_co)
            close_vol = log_cc_sq.rolling(window=window).sum()/(window-1.0)
            open_vol = log_oc_sq.rolling(window=window).sum()/(window-1.0)
            rs_ = rs.rolling(window=window).sum()/(window-1.0)
            k = 0.34/(1.34 + (window+1)/(window-1))
            out = self.safe_sqrt(open_vol + k*close_vol + (1-k)*rs_) * self.safe_sqrt(trading_periods)
            if return_last_only:
                return out.iloc[-1]
            else:
                return out.dropna()
        except Exception as e:
            if not self.warnings_shown:
                warnings.warn(f"Error in Yang-Zhang: {e}")
                self.warnings_shown = True
            return self.calculate_simple_volatility(pdf, window, trading_periods, return_last_only)
    
    def calculate_simple_volatility(self, pdf: pd.DataFrame,
                                    window=30, trading_periods=252,
                                    return_last_only=True):
        try:
            rets = pdf['Close'].pct_change().dropna()
            vol = rets.rolling(window=window).std()*np.sqrt(trading_periods)
            if return_last_only:
                return vol.iloc[-1]
            return vol
        except Exception as e:
            warnings.warn(f"Error in fallback volatility: {e}")
            return np.nan

    def compute_atr(self, pdf: pd.DataFrame, window=14):
        """
        Computes the Average True Range (ATR) over the given window.
        """
        high = pdf['High']
        low = pdf['Low']
        close = pdf['Close']
        prev_close = close.shift(1)
        tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
        atr = tr.rolling(window=window, min_periods=window).mean()
        return atr.iloc[-1] if not atr.empty else np.nan
    
    def build_term_structure(self, days: List[int], ivs: List[float]) -> callable:
        try:
            from scipy.interpolate import interp1d
            da = np.array(days)
            va = np.array(ivs)
            idx = da.argsort()
            da, va = da[idx], va[idx]
            f = interp1d(da, va, kind='linear', fill_value="extrapolate")
            def tspline(dte):
                if dte < da[0]:
                    return float(va[0])
                elif dte > da[-1]:
                    return float(va[-1])
                else:
                    return float(f(dte))
            return tspline
        except Exception as e:
            warnings.warn(f"Error building term structure: {e}")
            return lambda x: np.nan
    
    def get_current_price(self, ticker: yf.Ticker):
        for attempt in range(3):
            try:
                td = ticker.history(period='1d')
                if td.empty:
                    raise ValueError("No price data for 1d.")
                if 'Close' in td.columns:
                    return td['Close'].iloc[-1]
                elif 'Adj Close' in td.columns:
                    return td['Adj Close'].iloc[-1]
                else:
                    raise ValueError("No Close or Adj Close data found.")
            except Exception as e:
                if attempt < 2:
                    self.logger.warning(f"Failed to get price: {e}. Rotating proxy.")
                    self.session_manager.rotate_session()
                    ticker.session = self.session_manager.get_session()
                else:
                    raise ValueError(f"Cannot get price: {e}")
    
    def compute_recommendation(self, symbol: str) -> Dict:
        for attempt in range(3):
            try:
                s = symbol.strip().upper()
                if not s:
                    return {"error": "No symbol provided."}
                t = yf.Ticker(s)
                if not t.options:
                    return {"error": f"No options for {s}."}
                exps = list(t.options)
                exps = self.filter_dates(exps)
                oc = {}
                for e in exps:
                    try:
                        oc[e] = t.option_chain(e)
                    except Exception as ex_:
                        self.logger.warning(f"Couldn't get chain {e} for {s}: {ex_}")
                        self.session_manager.rotate_session()
                        t.session = self.session_manager.get_session()
                        oc[e] = t.option_chain(e)
                up = self.get_current_price(t)
                hist1 = t.history(period='1d')
                tv = hist1['Volume'].iloc[-1] if not hist1.empty else 0
                atm_ivs = {}
                stprice = None
                fi_iv = None
                i = 0
                for e, chain in oc.items():
                    calls, puts = chain.calls, chain.puts
                    if calls.empty or puts.empty:
                        continue
                    call_idx = (calls['strike'] - up).abs().idxmin()
                    put_idx = (puts['strike'] - up).abs().idxmin()
                    civ = calls.loc[call_idx, 'impliedVolatility']
                    piv = puts.loc[put_idx, 'impliedVolatility']
                    av = (civ + piv)/2
                    atm_ivs[e] = av
                    if i == 0:
                        cbid, cask = calls.loc[call_idx, 'bid'], calls.loc[call_idx, 'ask']
                        pbid, pask = puts.loc[put_idx, 'bid'], puts.loc[put_idx, 'ask']
                        if (cbid and cask and cbid > 0 and cask > 0 and
                            pbid and pask and pbid > 0 and pask > 0):
                            midc = (cbid + cask)/2
                            midp = (pbid + pask)/2
                            stprice = midc + midp
                    i += 1
                if atm_ivs:
                    sorted_exps = sorted(atm_ivs.keys())
                    fi_iv = atm_ivs[sorted_exps[0]]
                if not atm_ivs:
                    return {"error": "No ATM IV found."}
                today = datetime.today().date()
                ds, vs = [], []
                for exp_, iv_ in atm_ivs.items():
                    dtobj = datetime.strptime(exp_, "%Y-%m-%d").date()
                    dd = (dtobj - today).days
                    ds.append(dd)
                    vs.append(iv_)
                spline = self.build_term_structure(ds, vs)
                iv30 = spline(30)
                d0 = min(ds)
                if d0 == 45:
                    slope = 0
                else:
                    dden = (45 - d0) if (45 - d0) != 0 else 1
                    slope = (spline(45) - spline(d0))/dden
                h3 = t.history(period='3mo')
                hv = self.yang_zhang_volatility(h3)
                if hv == 0:
                    iv30_rv30 = 9999
                else:
                    iv30_rv30 = iv30/hv
                avgv = h3['Volume'].rolling(30).mean().dropna().iloc[-1] if not h3.empty else 0
                if stprice and up != 0:
                    exmo = f"{round(stprice/up*100,2)}%"
                else:
                    exmo = "N/A"
                # Compute ATR 14d using a 1mo history
                hist_atr = t.history(period='1mo')
                if hist_atr.empty:
                    atr14 = 0
                else:
                    atr14 = self.compute_atr(hist_atr, window=14)
                atr14_pct = (atr14/up) * 100 if up else 0
                return {
                    'avg_volume': avgv >= 1_500_000,
                    'avg_volume_value': avgv,
                    'iv30_rv30': iv30_rv30,
                    'term_slope': slope,
                    'term_structure': iv30,
                    'expected_move': exmo,
                    'underlying_price': up,
                    'historical_volatility': hv,
                    'current_iv': fi_iv,
                    'atr14': atr14,
                    'atr14_pct': atr14_pct
                }
            except Exception as e:
                if attempt < 2:
                    self.logger.warning(f"Attempt {attempt} for {symbol} failed: {e}. Rotating proxy.")
                    self.session_manager.rotate_session()
                else:
                    self.logger.error(f"All attempts for {symbol} failed: {str(e)}")
                    return {"error": f"Err: {e}"}

# ====================== EarningsCalendarFetcher ======================
class EarningsCalendarFetcher:
    def __init__(self, proxy_manager=None):
        self.data_queue = Queue()
        self.earnings_times = {}
        self.proxy_manager = proxy_manager or ProxyManager()
        self.session_manager = SessionManager(self.proxy_manager)
        self._init_log()
    
    def _init_log(self):
        self.logger = logging.getLogger('EarningsCalendarFetcher')
        self.logger.setLevel(logging.DEBUG)
        if not self.logger.handlers:
            fh = logging.FileHandler('earnings_calendar_debug.log')
            fh.setLevel(logging.DEBUG)
            formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            fh.setFormatter(formatter)
            self.logger.addHandler(fh)
        add_console_logging(self.logger, level=logging.INFO)
    
    def fetch_earnings_data(self, date: str) -> List[str]:
        max_retries = 3
        attempt = 0
        ret = []
        while attempt < max_retries:
            try:
                self.logger.info(f"Fetching earnings for {date}")
                url = "https://www.investing.com/earnings-calendar/Service/getCalendarFilteredData"
                hd = {
                    'User-Agent': 'Mozilla/5.0',
                    'X-Requested-With': 'XMLHttpRequest',
                    'Content-Type': 'application/x-www-form-urlencoded',
                    'Referer': 'https://www.investing.com/earnings-calendar/'
                }
                pl = {
                    'country[]': '5',
                    'dateFrom': date,
                    'dateTo': date,
                    'currentTab': 'custom',
                    'limit_from': 0
                }
                s = self.session_manager.get_session()
                r = s.post(url, headers=hd, data=pl)
                data = json.loads(r.text)
                soup = BeautifulSoup(data['data'], 'html.parser')
                rows = soup.find_all('tr')
                self.earnings_times.clear()
                for row in rows:
                    if not row.find('span', class_='earnCalCompanyName'):
                        continue
                    try:
                        ticker = row.find('a', class_='bold').text.strip()
                        timing_span = row.find('span', class_='genToolTip')
                        timing = "During Market"
                        if timing_span and 'data-tooltip' in timing_span.attrs:
                            tip = timing_span['data-tooltip']
                            if tip == 'Before market open':
                                timing = 'Pre Market'
                            elif tip == 'After market close':
                                timing = 'Post Market'
                        self.earnings_times[ticker] = timing
                        ret.append(ticker)
                    except Exception as e:
                        self.logger.warning(f"Error parsing row: {e}")
                        continue
                self.logger.info(f"Found {len(ret)} tickers for date {date}")
                return ret
            except Exception as e:
                attempt += 1
                if attempt < max_retries:
                    self.logger.warning(f"Retry {attempt}: {e}. Rotating proxy.")
                    self.session_manager.rotate_session()
                else:
                    self.logger.error(f"All attempts failed: {e}")
                    return []
        return ret
        
    def get_earnings_time(self, ticker: str) -> str:
        return self.earnings_times.get(ticker, 'Unknown')

# ====================== DataCache ======================
class DataCache:
    def __init__(self, cache_dir="stock_cache"):
        self.cache_dir = cache_dir
        self.cache_expiry_days = 7
        self._ensure_cache_dir()
        self._init_log()
    
    def _init_log(self):
        self.logger = logging.getLogger('DataCache')
        self.logger.setLevel(logging.DEBUG)
        if not self.logger.handlers:
            fh = logging.FileHandler('cache_debug.log')
            fh.setLevel(logging.DEBUG)
            formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            fh.setFormatter(formatter)
            self.logger.addHandler(fh)
        add_console_logging(self.logger, level=logging.INFO)
    
    def _ensure_cache_dir(self):
        if not os.path.exists(self.cache_dir):
            os.makedirs(self.cache_dir)
    
    def _get_cache_key(self, date: str, tks: List[str]) -> str:
        s = "_".join(sorted(tks))
        data_str = f"{date}_{s}"
        return hashlib.md5(data_str.encode()).hexdigest()
    
    def _get_cache_path(self, key: str) -> str:
        return os.path.join(self.cache_dir, f"{key}.pkl")
    
    def _identify_missing_data(self, data: List[Dict]) -> List[Dict]:
        missing = []
        for d in data:
            is_missing = False
            mf = []
            if d.get('expected_move') == 'N/A':
                mf.append('expected_move')
                is_missing = True
            if d.get('current_iv') is None:
                mf.append('current_iv')
                is_missing = True
            if d.get('term_structure') in [0, 'N/A']:
                mf.append('term_structure')
                is_missing = True
            if is_missing:
                missing.append({
                    'ticker': d['ticker'],
                    'missing_fields': mf,
                    'earnings_time': d.get('earnings_time', 'Unknown')
                })
        return missing
    
    def save_data(self, date: str, tickers: List[str], data: List[Dict]):
        ck = self._get_cache_key(date, tickers)
        cp = self._get_cache_path(ck)
        missing_data = self._identify_missing_data(data)
        cdata = {
            'timestamp': datetime.now(),
            'date': date,
            'tickers': tickers,
            'data': data,
            'missing_data': missing_data
        }
        with open(cp, 'wb') as f:
            pickle.dump(cdata, f)
        if missing_data:
            self.logger.info(f"Saved with {len(missing_data)} missing.")
    
    def get_data(self, date: str, tickers: List[str]) -> Tuple[Optional[List[Dict]], List[Dict]]:
        ck = self._get_cache_key(date, tickers)
        cp = self._get_cache_path(ck)
        if not os.path.exists(cp):
            return None, []
        try:
            with open(cp, 'rb') as f:
                c = pickle.load(f)
            age = datetime.now() - c['timestamp']
            if age.days >= self.cache_expiry_days:
                os.remove(cp)
                return None, []
            return c['data'], c['missing_data']
        except Exception as e:
            self.logger.error(f"Error reading cache: {e}")
            return None, []
    
    def update_missing_data(self, date: str, tickers: List[str], new_data: Dict):
        ck = self._get_cache_key(date, tickers)
        cp = self._get_cache_path(ck)
        try:
            with open(cp, 'rb') as f:
                c = pickle.load(f)
            for entry in c['data']:
                if entry['ticker'] == new_data['ticker']:
                    for k, v in new_data.items():
                        if (k in entry) and (entry[k] in [None, 'N/A', 0]):
                            entry[k] = v
            c['missing_data'] = self._identify_missing_data(c['data'])
            with open(cp, 'wb') as f:
                pickle.dump(c, f)
            self.logger.info(f"Updated cache for {new_data['ticker']}")
        except Exception as e:
            self.logger.error(f"Error updating cache: {e}")
    
    def clear_expired(self):
        for fn in os.listdir(self.cache_dir):
            if fn.endswith('.pkl'):
                cp = os.path.join(self.cache_dir, fn)
                try:
                    with open(cp, 'rb') as f:
                        c = pickle.load(f)
                    age = datetime.now() - c['timestamp']
                    if age.days >= self.cache_expiry_days:
                        os.remove(cp)
                except:
                    os.remove(cp)

# ====================== EnhancedEarningsScanner ======================
class EnhancedEarningsScanner:
    def __init__(self, analyzer: OptionsAnalyzer):
        self.analyzer = analyzer
        self.calendar_fetcher = EarningsCalendarFetcher(self.analyzer.proxy_manager)
        self.data_cache = DataCache()
        self.batch_size = 10
        self.logger = None
        self._init_log()
    
    def _init_log(self):
        self.logger = logging.getLogger('EnhancedEarningsScanner')
        self.logger.setLevel(logging.DEBUG)
        if not self.logger.handlers:
            fh = logging.FileHandler('earnings_scanner_debug.log')
            fh.setLevel(logging.DEBUG)
            formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            fh.setFormatter(formatter)
            self.logger.addHandler(fh)
        add_console_logging(self.logger, level=logging.INFO)
    
    def batch_download_history(self, tickers: List[str])->Dict[str,pd.DataFrame]:
      ticker_str= " ".join(tickers)
      try:
          for _ in range(3):
              data = yf.download(
                  tickers=ticker_str,
                  period="3mo",
                  group_by='ticker',
                  auto_adjust=True,
                  prepost=True,
                  threads=True,
                  proxy=self.analyzer.session_manager.get_session().proxies
              )

              if self.analyzer.session_manager.proxy_manager.proxy_enabled and len(shared._ERRORS) > 0:
                  self.analyzer.session_manager.rotate_session()
              else:
                  break

          res={}
          if len(tickers)==1:
              res[tickers[0]]= data
          else:
              for tk in tickers:
                  try:
                      df= data.xs(tk, axis=1, level=0)
                      if not df.empty:
                          res[tk]=df
                  except:
                      continue
          return res
      except Exception as e:
          self.logger.error(f"batch download error: {e}")
          return {}

    
    def scan_earnings_stocks(self, date: datetime, progress_callback=None) -> List[Dict]:
        ds = date.strftime('%Y-%m-%d')
        self.logger.info(f"Scan earnings for {ds}")
        e_stocks = self.calendar_fetcher.fetch_earnings_data(ds)
        try:
            with open("otc-tickers.txt", "r") as f:
                otc_tickers = {line.strip().upper() for line in f if line.strip()}
        except FileNotFoundError:
            otc_tickers = set()
        original_count = len(e_stocks)
        e_stocks = [ticker for ticker in e_stocks if ticker.upper() not in otc_tickers]
        self.logger.info(f"Filtered out {original_count - len(e_stocks)} OTC tickers.")
        if not e_stocks:
            return []
        cached_data, missing_data = self.data_cache.get_data(ds, e_stocks)
        if cached_data:
            self.logger.info(f"Using cached data for {ds}")
            raw_results = cached_data
            if missing_data:
                self.logger.info(f"{len(missing_data)} missing, attempting fill.")
                missing_tickers = [m['ticker'] for m in missing_data]
                done = 0
                total = len(missing_tickers)
                batches = [missing_tickers[i:i+self.batch_size] for i in range(0, total, self.batch_size)]
                for b in batches:
                    hist = self.batch_download_history(b)
                    with concurrent.futures.ThreadPoolExecutor(max_workers=min(5, len(b))) as ex:
                        fut2stk = {ex.submit(self.analyze_stock, st, hist.get(st)): st for st in b}
                        for fut in concurrent.futures.as_completed(fut2stk):
                            stsym = fut2stk[fut]
                            done += 1
                            if progress_callback:
                                val = 80 + (done/total * 20)
                                progress_callback(val)
                            try:
                                r = fut.result()
                                if r:
                                    self.data_cache.update_missing_data(ds, e_stocks, r)
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
        batches = [e_stocks[i:i+self.batch_size] for i in range(0, total_stocks, self.batch_size)]
        for b in batches:
            hist_map = self.batch_download_history(b)
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(5, len(b))) as ex:
                fut2stk = {ex.submit(self.analyze_stock, st, hist_map.get(st)): st for st in b}
                for ft in concurrent.futures.as_completed(fut2stk):
                    st = fut2stk[ft]
                    done += 1
                    if progress_callback:
                        pc = (done/total_stocks * 80)
                        progress_callback(pc)
                    try:
                        r = ft.result()
                        if r:
                            recommended.append(r)
                    except Exception as e_:
                        self.logger.error(f"Error processing future result: {e_}")
        recommended.sort(key=lambda x: (
            x['recommendation'] != 'Recommended',
            x['earnings_time'] == 'Unknown',
            x['earnings_time'],
            x['ticker']
        ))
        self.data_cache.save_data(ds, e_stocks, recommended)
        if progress_callback:
            progress_callback(100)
        return recommended
    
    def analyze_stock(self, ticker: str, history_data: Optional[pd.DataFrame] = None, skip_otc_check: bool = False) -> Optional[Dict]:
        try:
            st2 = self.analyzer.get_ticker(ticker)
            if not skip_otc_check:
                exchange = st2.info.get('exchange', '')
                otc_exchanges = {"PNK", "Other OTC", "OTC", "GREY"}
                if exchange in otc_exchanges:
                    self.logger.info(f"[SKIP] Ticker '{ticker}' is OTC (exchange='{exchange}').")
                    return None
            if history_data is None or history_data.empty:
                hd = st2.history(period='3mo')
                if hd.empty:
                    # Fallback to 1mo if 3mo returns empty.
                    hd = st2.history(period='1mo')
                if hd.empty:
                    self.logger.warning(f"No data for {ticker}; skipping.")
                    return None
                history_data = hd

            if isinstance(history_data.columns, pd.MultiIndex):
                history_data.columns = history_data.columns.get_level_values(1)
            if 'Close' in history_data.columns:
                cp = history_data['Close'].iloc[-1]
            elif 'Adj Close' in history_data.columns:
                cp = history_data['Adj Close'].iloc[-1]
            else:
                raise ValueError("No close price data available.")
            voldata = history_data['Volume']
            hv = self.analyzer.yang_zhang_volatility(history_data)
            tv = voldata.iloc[-1] if not voldata.empty else 0
            od = self.analyzer.compute_recommendation(ticker)
            if isinstance(od, dict) and "error" not in od:
                avb = od['avg_volume']
                ivcheck = (od['iv30_rv30'] >= 1.25)
                slopecheck = (od['term_slope'] <= -0.00406)
                if avb and ivcheck and slopecheck:
                    rec = "Recommended"
                elif slopecheck and ((avb and not ivcheck) or (ivcheck and not avb)):
                    rec = "Consider"
                else:
                    rec = "Avoid"
                return {
                    'ticker': ticker,
                    'current_price': cp,
                    'market_cap': st2.info.get('marketCap', 0),
                    'volume': tv,
                    'avg_volume': avb,
                    'avg_volume_value': od.get('avg_volume_value', 0),
                    'earnings_time': self.calendar_fetcher.get_earnings_time(ticker),
                    'recommendation': rec,
                    'expected_move': od.get('expected_move', 'N/A'),
                    'atr14': od.get('atr14', 0),
                    'atr14_pct': od.get('atr14_pct', 0),
                    'iv30_rv30': od.get('iv30_rv30', 0),
                    'term_slope': od.get('term_slope', 0),
                    'term_structure': od.get('term_structure', 0),
                    'historical_volatility': hv,
                    'current_iv': od.get('current_iv', None)
                }
            return {
                'ticker': ticker,
                'current_price': cp,
                'market_cap': 0,
                'volume': tv,
                'avg_volume': False,
                'avg_volume_value': 0,
                'earnings_time': self.calendar_fetcher.get_earnings_time(ticker),
                'recommendation': "Avoid",
                'expected_move': "N/A",
                'atr14': 0,
                'atr14_pct': 0,
                'iv30_rv30': 0,
                'term_slope': 0,
                'term_structure': 0,
                'historical_volatility': hv,
                'current_iv': None
            }
        except Exception as e:
            self.logger.error(f"Analyze error for {ticker}: {e}")
            return None

# ====================== Candlestick Chart Function ======================
def show_interactive_chart(ticker: str, session_manager: Optional[SessionManager] = None):
    try:
        st = yf.Ticker(ticker)
        if session_manager:
            st.session = session_manager.get_session()
        hist = st.history(period='1y')
        if hist.empty:
            messagebox.showerror("Error", f"No historical data for {ticker}.")
            return
        mpf.plot(hist, type='candle', style='charles', volume=True, title=f"{ticker} Chart")
        plt.show()
    except Exception as e:
        messagebox.showerror("Chart Error", f"Error generating chart for {ticker}: {e}")

# ====================== The Tkinter App ======================
class EarningsTkApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Earnings Volatility Calculator (Tkinter)")
        self.proxy_manager = ProxyManager()
        # Enable proxy support; proxies will be updated only when button is pressed.
        self.proxy_manager.proxy_enabled = True
        self.analyzer = OptionsAnalyzer(self.proxy_manager)
        self.scanner = EnhancedEarningsScanner(self.analyzer)
        self.raw_results: List[Dict] = []
        self.sort_orders: Dict[str, bool] = {}
        self.build_layout()
        # Automatically update OTC tickers at startup
        threading.Thread(target=update_otc_tickers, daemon=True).start()
    
    def build_layout(self):
        # ---------- Proxy Settings -----------
        proxy_frame = ttk.LabelFrame(self.root, text="Proxy Settings", padding=2)
        proxy_frame.pack(side="top", fill="x", padx=5, pady=(2, 0))
        self.proxy_var = tk.BooleanVar(value=self.proxy_manager.proxy_enabled)
        cb = ttk.Checkbutton(proxy_frame, text="Enable Proxy",
                             variable=self.proxy_var,
                             command=self.on_toggle_proxy)
        cb.pack(side="left", padx=5, pady=0)
        btn_proxy_update = ttk.Button(proxy_frame, text="Update Proxies",
                                      command=self.on_update_proxies)
        btn_proxy_update.pack(side="left", padx=5, pady=0)
        self.lbl_proxy_status = ttk.Label(proxy_frame, text=f"Enabled ({len(self.proxy_manager.proxies)} proxies)")
        self.lbl_proxy_status.pack(side="left", padx=5, pady=0)
        
        # ---------- Single Stock Analysis -----------
        single_frame = ttk.Frame(self.root, padding=2)
        single_frame.pack(side="top", fill="x", padx=5, pady=(0,0))
        ttk.Label(single_frame, text="Enter Stock Symbol:").pack(side="left", padx=5, pady=0)
        self.entry_symbol = ttk.Entry(single_frame, width=12)
        self.entry_symbol.pack(side="left", padx=5, pady=0)
        btn_analyze = ttk.Button(single_frame, text="Analyze", command=self.on_analyze_stock)
        btn_analyze.pack(side="left", padx=5, pady=0)
        
        # ---------- Earnings Scan with tkcalendar -----------
        scan_frame = ttk.Frame(self.root, padding=2)
        scan_frame.pack(side="top", fill="x", padx=5, pady=(0,0))
        ttk.Label(scan_frame, text="Earnings Date:").pack(side="left", padx=5, pady=0)
        self.cal_date = DateEntry(scan_frame, width=12, date_pattern='yyyy-MM-dd')
        self.cal_date.pack(side="left", padx=5, pady=0)
        btn_scan = ttk.Button(scan_frame, text="Scan Earnings", command=self.on_scan_earnings)
        btn_scan.pack(side="left", padx=5, pady=0)
        
        # ============ Filters + Threshold Label =============
        filter_and_threshold_frame = ttk.Frame(self.root, padding=2)
        filter_and_threshold_frame.pack(side="top", fill="x", padx=5, pady=(0,0))
        filter_frame = ttk.LabelFrame(filter_and_threshold_frame, text="", padding=2)
        filter_frame.pack(side="left", fill="x", expand=True)
        ttk.Label(filter_frame, text="Earnings Time Filter:").pack(side="left", padx=(0,5), pady=0)
        self.filter_time_var = tk.StringVar(value="All")
        cbox_time = ttk.Combobox(filter_frame, textvariable=self.filter_time_var,
                                 values=["All","Pre Market","Post Market","During Market"],
                                 width=12)
        cbox_time.pack(side="left", padx=5, pady=0)
        cbox_time.bind("<<ComboboxSelected>>", self.on_filter_changed)
        ttk.Label(filter_frame, text="Recommendation Filter:").pack(side="left", padx=(10,5), pady=0)
        self.filter_rec_var = tk.StringVar(value="All")
        cbox_rec = ttk.Combobox(filter_frame, textvariable=self.filter_rec_var,
                                values=["All","Recommended","Consider","Avoid"],
                                width=12)
        cbox_rec.pack(side="left", padx=5, pady=0)
        cbox_rec.bind("<<ComboboxSelected>>", self.on_filter_changed)
        ttk.Label(filter_frame, text="Min Stock Price Filter:").pack(side="left", padx=(10,5), pady=0)
        self.filter_price_var = tk.StringVar(value="All")
        cbox_price = ttk.Combobox(filter_frame, textvariable=self.filter_price_var,
                                values=["All","1.00","2.50","5.00","10.00"],
                                width=12)
        cbox_price.pack(side="left", padx=5, pady=0)
        cbox_price.bind("<<ComboboxSelected>>", self.on_filter_changed)
        thresholds_text = ("Recommended If:\n- Avg. Daily Volume ≥ 1,500,000\n- IV30/RV30 ≥ 1.25\n- Term Slope ≤ -0.00406")
        thresholds_label = ttk.Label(filter_and_threshold_frame, text=thresholds_text, justify="left")
        thresholds_label.pack(side="right", padx=(10,5), pady=(0,0), anchor="n")
        
        # ---------- The Table -----------
        table_frame = ttk.Frame(self.root, padding=0)
        table_frame.pack(side="top", fill="both", expand=True)
        self.headings = ["Ticker", "Price", "Market Cap", "Volume 1d", "Avg Vol Check",
                         "30D Volume", "Earnings Time", "Recommendation", "Expected Move",
                         "ATR 14d", "ATR 14d %", "IV30/RV30", "Term Slope",
                         "Term Structure", "Historical Vol", "Current IV"]
        self.tree = ttk.Treeview(table_frame, columns=self.headings, show="headings")
        self.tree.pack(side="left", fill="both", expand=True)
        for col in self.headings:
            self.sort_orders[col] = True
            self.tree.heading(col, text=col, command=lambda c=col: self.on_column_heading_click(c))
            self.tree.column(col, width=100)
        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        vsb.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.tag_configure("Recommended", background="green", foreground="white")
        self.tree.tag_configure("Consider", background="orange", foreground="black")
        self.tree.tag_configure("Avoid", background="red", foreground="white")
        self.tree.bind("<Double-1>", self.on_table_double_click)
        
        # ---------- Bottom Row (Status/Progress/Export/Exit) -----------
        bottom_frame = ttk.Frame(self.root, padding=2)
        bottom_frame.pack(side="bottom", fill="x", padx=5, pady=(0,2))
        self.lbl_status = ttk.Label(bottom_frame, text="Status: Ready")
        self.lbl_status.pack(side="left", padx=5, pady=0)
        btn_export = ttk.Button(bottom_frame, text="Export CSV", command=self.on_export_csv)
        btn_export.pack(side="right", padx=5, pady=0)
        btn_exit = ttk.Button(bottom_frame, text="Exit", command=self.root.destroy)
        btn_exit.pack(side="right", padx=5, pady=0)
        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(bottom_frame, orient="horizontal",
                                            variable=self.progress_var, maximum=100, length=150)
        self.progress_bar.pack(side="right", padx=10, pady=0)
    
    # -------- Proxy Handlers --------
    def on_toggle_proxy(self):
        self.proxy_manager.proxy_enabled = self.proxy_var.get()
        self.update_proxy_status()
    
    def on_update_proxies(self):
        # Create a Toplevel window with a progress bar for proxy update feedback.
        loading_win = tk.Toplevel(self.root)
        loading_win.title("Updating Proxies")
        loading_win.geometry("300x120")
        ttk.Label(loading_win, text="Fetching and validating proxies...").pack(pady=10)
        pb = ttk.Progressbar(loading_win, mode='indeterminate')
        pb.pack(pady=10, padx=20, fill='x')
        pb.start(10)
        
        # Define a progress callback that prints to console and updates the status label.
        def progress_callback(msg):
            print(msg)
            self.root.after(0, lambda: self.set_status(msg))
        
        def update_task():
            try:
                self.proxy_manager.build_valid_proxy_pool(max_proxies=50, concurrency=20, progress_callback=progress_callback)
                self.root.after(0, lambda: self.update_proxy_status())
                self.root.after(0, lambda: self.set_status("Proxies updated."))
            except Exception as e:
                self.root.after(0, lambda: self.set_status(f"Failed to update proxies: {e}"))
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
    
    # -------- Single Stock Analysis (OG) --------
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
            r = self.scanner.analyze_stock(ticker, hist_map.get(ticker), skip_otc_check=True)
            if r:
                self.raw_results = [r]
            self.root.after(0, self.fill_table)
            self.set_status("Single stock analysis complete.")
        threading.Thread(target=worker, daemon=True).start()
    
    # -------- Earnings Scan --------
    def on_scan_earnings(self):
        dt = self.cal_date.get_date()
        self.clear_table()
        self.raw_results.clear()
        self.progress_var.set(0)
        self.set_status("Scanning earnings...")
        def progress_cb(val):
            self.progress_var.set(val)
        def worker():
            results = self.scanner.scan_earnings_stocks(dt, progress_cb)
            self.raw_results = results
            self.set_status(f"Scan complete. Found {len(results)} stocks.")
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
            et = row.get('earnings_time', "Unknown")
            if time_val != "All" and et != time_val:
                continue
            rv = row.get('recommendation', "Avoid")
            if rec_val != "All" and rv != rec_val:
                continue
            pv = row.get('current_price', "All")
            if price_val != "All" and pv < float(price_val):
                continue
            filtered.append(row)
        return filtered
    
    # -------- Table Helpers --------
    def fill_table(self):
        self.clear_table()
        filtered = self.apply_filters(self.raw_results)
        for row in filtered:
            rec = row.get('recommendation', "Avoid")
            row_vals = self.build_row_values(row)
            self.tree.insert("", "end", values=row_vals, tags=(rec,))
    
    def clear_table(self):
        for iid in self.tree.get_children():
            self.tree.delete(iid)
    
    def build_row_values(self, row: Dict) -> List[str]:
        return [
            row.get('ticker', "N/A"),
            f"${row.get('current_price',0):.2f}",
            (f"${row.get('market_cap',0):,}" if row.get('market_cap',0) else "N/A"),
            (f"{row.get('volume',0):,}" if row.get('volume',0) else "N/A"),
            ("PASS" if row.get('avg_volume') else "FAIL"),
            (f"{int(row.get('avg_volume_value',0)):,}" if row.get('avg_volume_value',0) else "N/A"),
            row.get('earnings_time', "Unknown"),
            row.get('recommendation', "Avoid"),
            row.get('expected_move', "N/A"),
            f"{row.get('atr14',0):.2f}",
            f"{row.get('atr14_pct',0):.2f}%",
            f"{row.get('iv30_rv30',0):.2f}",
            f"{row.get('term_slope',0):.4f}",
            (f"{row.get('term_structure',0):.2%}" if row.get('term_structure',0) else "N/A"),
            f"{row.get('historical_volatility',0):.2%}",
            (f"{row.get('current_iv',0):.2%}" if row.get('current_iv',0) else "N/A")
        ]
    
    # -------- Sorting --------
    def on_column_heading_click(self, colname: str):
        ascending = self.sort_orders[colname]
        self.sort_orders[colname] = not ascending
        key_map = {
            "Ticker": "ticker",
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
            "Current IV": "current_iv"
        }
        data_key = key_map.get(colname, colname)
        def transform_value(row: Dict):
            val = row.get(data_key, 0)
            if isinstance(val, str):
                if val.endswith('%'):
                    try:
                        return float(val[:-1])
                    except:
                        return val
                if val.startswith('$'):
                    try:
                        return float(val.replace('$','').replace(',',''))
                    except:
                        return val
                if val.replace(',','').isdigit():
                    return float(val.replace(',',''))
            return val
        self.raw_results.sort(key=lambda r: transform_value(r), reverse=not ascending)
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
        f = filedialog.asksaveasfilename(defaultextension=".csv",
                                         filetypes=[("CSV","*.csv")])
        if not f:
            return
        try:
            import csv
            with open(f, 'w', newline='') as out:
                writer = csv.writer(out)
                writer.writerow(self.headings)
                for row in filtered:
                    rv = self.build_row_values(row)
                    writer.writerow(rv)
            self.set_status(f"Exported to {f}")
        except Exception as e:
            self.set_status(f"Export error: {e}")
    
    # -------- Helper --------
    def set_status(self, msg: str):
        self.lbl_status.config(text=f"Status: {msg}")

# ====================== Main Function ======================
def main():
    root = tk.Tk()
    app = EarningsTkApp(root)
    root.mainloop()

if __name__=="__main__":
    main()

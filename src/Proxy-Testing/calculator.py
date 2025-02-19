"""
DISCLAIMER: 

This software is provided solely for educational and research purposes. 
It is not intended to provide investment advice, and no investment recommendations are made herein. 
The developers are not financial advisors and accept no responsibility for any financial decisions or losses resulting from the use of this software. 
Always consult a professional financial advisor before making any investment decisions.
"""

# Standard library imports
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

# Third-party imports
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from bs4 import BeautifulSoup
from typing import Dict, List, Optional

import matplotlib.pyplot as plt
from io import BytesIO
import mplfinance as mpf  # For candlestick charts
import FreeSimpleGUI as sg

# Check NumPy version for compatibility
NUMPY_VERSION = tuple(map(int, np.__version__.split('.')[:2]))
IS_NUMPY_2 = NUMPY_VERSION[0] >= 2

# ------------------- Proxy Manager -------------------
class ProxyManager:
    """Manages proxy connections and rotation from multiple free sources."""
    
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
            formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            fh.setFormatter(formatter)
            self.logger.addHandler(fh)
    
    def fetch_proxyscrape(self) -> List[Dict[str, str]]:
        """Fetch proxies from Proxyscrape."""
        try:
            url = "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=10000&country=all&ssl=all&anonymity=all"
            response = requests.get(url)
            if response.status_code == 200:
                proxy_list = [x.strip() for x in response.text.split('\n') if x.strip()]
                return [
                    {
                        'http': f"http://{proxy}",
                        'https': f"http://{proxy}"
                    }
                    for proxy in proxy_list
                ]
            return []
        except Exception as e:
            self.logger.error(f"Error fetching from Proxyscrape: {e}")
            return []

    def fetch_geonode(self) -> List[Dict[str, str]]:
        """Fetch proxies from Geonode's free API."""
        try:
            url = "https://proxylist.geonode.com/api/proxy-list?limit=100&page=1&sort_by=lastChecked&sort_type=desc&protocols=http&anonymityLevel=elite&anonymityLevel=anonymous"
            response = requests.get(url)
            if response.status_code == 200:
                data = response.json()
                return [
                    {
                        'http': f"http://{proxy['ip']}:{proxy['port']}",
                        'https': f"http://{proxy['ip']}:{proxy['port']}"
                    }
                    for proxy in data.get('data', [])
                ]
            return []
        except Exception as e:
            self.logger.error(f"Error fetching from Geonode: {e}")
            return []

    def fetch_pubproxy(self) -> List[Dict[str, str]]:
        """Fetch proxies from PubProxy."""
        try:
            url = "http://pubproxy.com/api/proxy?limit=20&format=json&type=http"
            response = requests.get(url)
            if response.status_code == 200:
                data = response.json()
                return [
                    {
                        'http': f"http://{proxy['ip']}:{proxy['port']}",
                        'https': f"http://{proxy['ip']}:{proxy['port']}"
                    }
                    for proxy in data.get('data', [])
                ]
            return []
        except Exception as e:
            self.logger.error(f"Error fetching from PubProxy: {e}")
            return []

    def fetch_proxylist_download(self) -> List[Dict[str, str]]:
        """Fetch proxies from ProxyList.download."""
        try:
            url = "https://www.proxy-list.download/api/v1/get?type=http"
            response = requests.get(url)
            if response.status_code == 200:
                proxy_list = [x.strip() for x in response.text.split('\n') if x.strip()]
                return [
                    {
                        'http': f"http://{proxy}",
                        'https': f"http://{proxy}"
                    }
                    for proxy in proxy_list
                ]
            return []
        except Exception as e:
            self.logger.error(f"Error fetching from ProxyList.download: {e}")
            return []

    def fetch_spys_one(self) -> List[Dict[str, str]]:
        """Fetch proxies from Spys.one."""
        try:
            url = "https://spys.one/free-proxy-list/ALL/"
            headers = {'User-Agent': 'Mozilla/5.0'}
            response = requests.get(url, headers=headers)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                proxy_rows = soup.find_all('tr', class_=['spy1x', 'spy1xx'])
                proxies = []
                for row in proxy_rows:
                    cols = row.find_all('td')
                    if len(cols) >= 2:
                        ip = cols[0].text.strip()
                        port = cols[1].text.strip()
                        proxies.append({
                            'http': f"http://{ip}:{port}",
                            'https': f"http://{ip}:{port}"
                        })
                return proxies
            return []
        except Exception as e:
            self.logger.error(f"Error fetching from Spys.one: {e}")
            return []

    def verify_proxy(self, proxy: Dict[str, str]) -> bool:
        """Test if a proxy is working."""
        try:
            test_url = "https://www.google.com"
            response = requests.get(test_url, proxies=proxy, timeout=5)
            return response.status_code == 200
        except:
            return False

    def fetch_proxies(self) -> None:
        """Fetch proxies from all sources and verify them."""
        all_proxies = []
        sources = [
            self.fetch_proxyscrape,
            self.fetch_geonode,
            self.fetch_pubproxy,
            self.fetch_proxylist_download,
            self.fetch_spys_one
        ]
        
        for source in sources:
            proxies = source()
            all_proxies.extend(proxies)
            self.logger.info(f"Fetched {len(proxies)} proxies from {source.__name__}")
        
        # Remove duplicates
        seen = set()
        unique_proxies = []
        for proxy in all_proxies:
            proxy_str = f"{proxy['http']}"
            if proxy_str not in seen:
                seen.add(proxy_str)
                unique_proxies.append(proxy)
        
        # Verify proxies (optional - can be slow)
        # working_proxies = [p for p in unique_proxies if self.verify_proxy(p)]
        # self.proxies = working_proxies
        
        self.proxies = unique_proxies
        self.logger.info(f"Total unique proxies: {len(self.proxies)}")
        
    def get_proxy(self) -> Optional[Dict[str, str]]:
        """Get a random proxy from the pool."""
        if not self.proxy_enabled or not self.proxies:
            return None
        self.current_proxy = random.choice(self.proxies)
        return self.current_proxy
    
    def rotate_proxy(self) -> Optional[Dict[str, str]]:
        """Rotate to a new proxy, avoiding the current one."""
        if not self.proxy_enabled or len(self.proxies) <= 1:
            return None
        available_proxies = [p for p in self.proxies if p != self.current_proxy]
        if available_proxies:
            self.current_proxy = random.choice(available_proxies)
            return self.current_proxy
        return None
    """Manages proxy connections and rotation for YFinance requests."""
    
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
            formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            fh.setFormatter(formatter)
            self.logger.addHandler(fh)
    
    def fetch_proxies(self) -> None:
        """Fetch fresh proxies from Proxyscrape's free proxy service."""
        try:
            url = "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=10000&country=all&ssl=all&anonymity=all"
            response = requests.get(url)
            if response.status_code == 200:
                proxy_list = [x.strip() for x in response.text.split('\n') if x.strip()]
                self.proxies = [
                    {
                        'http': f"http://{proxy}",
                        'https': f"http://{proxy}"
                    }
                    for proxy in proxy_list
                ]
                self.logger.info(f"Successfully fetched {len(self.proxies)} proxies")
            else:
                raise Exception(f"Failed to fetch proxies: {response.status_code}")
        except Exception as e:
            self.logger.error(f"Error fetching proxies: {e}")
            raise
    
    def get_proxy(self) -> Optional[Dict[str, str]]:
        """Get a random proxy from the pool."""
        if not self.proxy_enabled or not self.proxies:
            return None
        self.current_proxy = random.choice(self.proxies)
        return self.current_proxy
    
    def rotate_proxy(self) -> Optional[Dict[str, str]]:
        """Rotate to a new proxy, avoiding the current one."""
        if not self.proxy_enabled or len(self.proxies) <= 1:
            return None
        available_proxies = [p for p in self.proxies if p != self.current_proxy]
        if available_proxies:
            self.current_proxy = random.choice(available_proxies)
            return self.current_proxy
        return None

# ------------------- Session Manager -------------------
class SessionManager:
    """Manages YFinance sessions with proxy support."""
    
    def __init__(self, proxy_manager: ProxyManager):
        self.proxy_manager = proxy_manager
        self.session = self._create_session()
    
    def _create_session(self) -> requests.Session:
        """Create a new session with current proxy settings."""
        session = requests.Session()
        if self.proxy_manager.proxy_enabled:
            proxy = self.proxy_manager.get_proxy()
            if proxy:
                session.proxies.update(proxy)
        return session
    
    def rotate_session(self) -> None:
        """Rotate to a new session with a different proxy."""
        if self.proxy_manager.proxy_enabled:
            proxy = self.proxy_manager.rotate_proxy()
            if proxy:
                self.session = self._create_session()
    
    def get_session(self) -> requests.Session:
        """Get the current session."""
        return self.session

# ------------------- Options Analyzer -------------------
class OptionsAnalyzer:
    """Options analysis tool with version compatibility and proxy support."""
    
    def __init__(self, proxy_manager: Optional[ProxyManager] = None):
        self.warnings_shown = False
        self.proxy_manager = proxy_manager or ProxyManager()
        self.session_manager = SessionManager(self.proxy_manager)
        self._initialize_logging()
    
    def _initialize_logging(self):
        self.logger = logging.getLogger('OptionsAnalyzer')
        self.logger.setLevel(logging.DEBUG)
        if not self.logger.handlers:
            fh = logging.FileHandler('options_analyzer_debug.log')
            fh.setLevel(logging.DEBUG)
            formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            fh.setFormatter(formatter)
            self.logger.addHandler(fh)
    
    def get_ticker(self, symbol: str) -> yf.Ticker:
        """Get a ticker instance with the current session."""
        ticker = yf.Ticker(symbol)
        ticker.session = self.session_manager.get_session()
        return ticker
    
    def safe_log(self, values: np.ndarray) -> np.ndarray:
        """Safe logarithm calculation compatible with both NumPy versions."""
        if IS_NUMPY_2:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                return np.log(values)
        return np.log(values)
    
    def safe_sqrt(self, values: np.ndarray) -> np.ndarray:
        """Safe square root calculation compatible with both NumPy versions."""
        if IS_NUMPY_2:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                return np.sqrt(values)
        return np.sqrt(values)
    
    def filter_dates(self, dates: List[str]) -> List[str]:
        """Filter option expiration dates – keep only those 45+ days in the future."""
        today = datetime.today().date()
        cutoff_date = today + timedelta(days=45)
        sorted_dates = sorted(datetime.strptime(date, "%Y-%m-%d").date() for date in dates)
        arr = []
        for i, date in enumerate(sorted_dates):
            if date >= cutoff_date:
                arr = [d.strftime("%Y-%m-%d") for d in sorted_dates[:i+1]]
                break
        if arr:
            if arr[0] == today.strftime("%Y-%m-%d"):
                return arr[1:]
            return arr
        raise ValueError("No date 45 days or more in the future found.")
    
    def yang_zhang_volatility(self, price_data: pd.DataFrame, window: int = 30, trading_periods: int = 252, return_last_only: bool = True) -> float:
        """Calculate Yang-Zhang volatility; falls back to simple volatility on error."""
        try:
            log_ho = self.safe_log(price_data['High'] / price_data['Open'])
            log_lo = self.safe_log(price_data['Low'] / price_data['Open'])
            log_co = self.safe_log(price_data['Close'] / price_data['Open'])
            log_oc = self.safe_log(price_data['Open'] / price_data['Close'].shift(1))
            log_oc_sq = log_oc ** 2
            log_cc = self.safe_log(price_data['Close'] / price_data['Close'].shift(1))
            log_cc_sq = log_cc ** 2
            rs = log_ho * (log_ho - log_co) + log_lo * (log_lo - log_co)
            close_vol = log_cc_sq.rolling(window=window).sum() * (1.0 / (window - 1.0))
            open_vol = log_oc_sq.rolling(window=window).sum() * (1.0 / (window - 1.0))
            window_rs = rs.rolling(window=window).sum() * (1.0 / (window - 1.0))
            k = 0.34 / (1.34 + (window + 1) / (window - 1))
            result = self.safe_sqrt(open_vol + k * close_vol + (1 - k) * window_rs) * self.safe_sqrt(trading_periods)
            if return_last_only:
                return result.iloc[-1]
            return result.dropna()
        except Exception as e:
            if not self.warnings_shown:
                warnings.warn(f"Error in volatility calculation: {str(e)}. Using alternative method.")
                self.warnings_shown = True
            return self.calculate_simple_volatility(price_data, window, trading_periods, return_last_only)
    
    def calculate_simple_volatility(self, price_data: pd.DataFrame, window: int = 30, trading_periods: int = 252, return_last_only: bool = True) -> float:
        """Calculate simple volatility as fallback."""
        try:
            returns = price_data['Close'].pct_change().dropna()
            vol = returns.rolling(window=window).std() * np.sqrt(trading_periods)
            if return_last_only:
                return vol.iloc[-1]
            return vol
        except Exception as e:
            warnings.warn(f"Error in simple volatility calculation: {str(e)}")
            return np.nan
    
    def build_term_structure(self, days: List[int], ivs: List[float]) -> callable:
        """Build IV term structure using linear interpolation."""
        try:
            days_arr = np.array(days)
            ivs_arr = np.array(ivs)
            sort_idx = days_arr.argsort()
            days_arr = days_arr[sort_idx]
            ivs_arr = ivs_arr[sort_idx]
            from scipy.interpolate import interp1d
            spline = interp1d(days_arr, ivs_arr, kind='linear', fill_value="extrapolate")
            def term_spline(dte: float) -> float:
                if dte < days_arr[0]:
                    return float(ivs_arr[0])
                elif dte > days_arr[-1]:
                    return float(ivs_arr[-1])
                else:
                    return float(spline(dte))
            return term_spline
        except Exception as e:
            warnings.warn(f"Error in term structure calculation: {str(e)}")
            return lambda x: np.nan
    
    def get_current_price(self, ticker: yf.Ticker) -> float:
        """Return the current stock price."""
        max_retries = 3
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                todays_data = ticker.history(period='1d')
                if todays_data.empty:
                    raise ValueError("No price data available")
                return todays_data['Close'].iloc[-1]
            except Exception as e:
                retry_count += 1
                if retry_count < max_retries:
                    self.logger.warning(f"Failed to get price, attempt {retry_count}. Rotating proxy...")
                    self.session_manager.rotate_session()
                    ticker.session = self.session_manager.get_session()
                else:
                    raise ValueError(f"Failed to get price after {max_retries} attempts: {str(e)}")
    
    def compute_recommendation(self, ticker: str) -> Dict:
        """
        Compute the trading recommendation with proxy support and automatic retry.
        
        Criteria:
          - Average volume must be at least 1,500,000 shares.
          - IV30/RV30 ratio must be at least 1.25.
          - Term structure slope (0 to 45 days) must be less than or equal to -0.00406.
        """
        max_retries = 3
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                ticker = ticker.strip().upper()
                if not ticker:
                    return {"error": "No stock symbol provided."}
                
                stock = self.get_ticker(ticker)
                if len(stock.options) == 0:
                    return {"error": f"No options found for stock symbol '{ticker}'."}
                
                exp_dates = list(stock.options)
                exp_dates = self.filter_dates(exp_dates)
                options_chains = {}
                for exp_date in exp_dates:
                    try:
                        options_chains[exp_date] = stock.option_chain(exp_date)
                    except Exception as e:
                        self.logger.warning(f"Failed to fetch option chain for {exp_date}: {str(e)}")
                        self.session_manager.rotate_session()
                        stock.session = self.session_manager.get_session()
                        options_chains[exp_date] = stock.option_chain(exp_date)
                
                underlying_price = self.get_current_price(stock)
                
                # Get the latest volume from a 1-day history
                today_volume = stock.history(period='1d')['Volume'].iloc[-1]
                atm_iv = {}
                straddle = None
                first_atm_iv = None  # store current IV from the first valid chain
                i = 0
                data_inaccurate = False  # Flag for missing/zero bid/ask values
                
                for exp_date, chain in options_chains.items():
                    calls = chain.calls
                    puts = chain.puts
                    if calls.empty or puts.empty:
                        continue
                    
                    call_idx = (calls['strike'] - underlying_price).abs().idxmin()
                    put_idx = (puts['strike'] - underlying_price).abs().idxmin()
                    call_iv = calls.loc[call_idx, 'impliedVolatility']
                    put_iv = puts.loc[put_idx, 'impliedVolatility']
                    atm_iv_value = (call_iv + put_iv) / 2.0
                    atm_iv[exp_date] = atm_iv_value
                    
                    if i == 0:
                        first_atm_iv = atm_iv_value
                        call_bid = calls.loc[call_idx, 'bid']
                        call_ask = calls.loc[call_idx, 'ask']
                        put_bid = puts.loc[put_idx, 'bid']
                        put_ask = puts.loc[put_idx, 'ask']
                        
                        # Guard rails: if any bid/ask is missing or <= 0, flag data as inaccurate.
                        if (call_bid is None or call_ask is None or call_bid <= 0 or call_ask <= 0 or
                            put_bid is None or put_ask is None or put_bid <= 0 or put_ask <= 0):
                            self.logger.warning(f"Zero or missing bid/ask data for ticker {ticker} expiration {exp_date}. Data may be inaccurate.")
                            data_inaccurate = True
                        else:
                            call_mid = (call_bid + call_ask) / 2.0
                            put_mid = (put_bid + put_ask) / 2.0
                            straddle = call_mid + put_mid
                    i += 1
                
                if not atm_iv:
                    return {"error": "Could not determine ATM IV for any expiration dates."}
                
                today = datetime.today().date()
                dtes = []
                ivs = []
                for exp_date, iv in atm_iv.items():
                    exp_date_obj = datetime.strptime(exp_date, "%Y-%m-%d").date()
                    days_to_expiry = (exp_date_obj - today).days
                    dtes.append(days_to_expiry)
                    ivs.append(iv)
                
                term_spline = self.build_term_structure(dtes, ivs)
                iv30 = term_spline(30)
                ts_slope_0_45 = (term_spline(45) - term_spline(dtes[0])) / (45 - dtes[0])
                
                try:
                    hist_vol = self.yang_zhang_volatility(stock.history(period='3mo'))
                except Exception as e:
                    self.logger.warning(f"Failed to get historical data, retrying with new proxy...")
                    self.session_manager.rotate_session()
                    stock.session = self.session_manager.get_session()
                    hist_vol = self.yang_zhang_volatility(stock.history(period='3mo'))
                
                iv30_rv30 = iv30 / hist_vol
                price_history = stock.history(period='3mo')
                avg_volume = price_history['Volume'].rolling(30).mean().dropna().iloc[-1]
                
                # Compute ATR 14d
                high = price_history['High']
                low = price_history['Low']
                prev_close = price_history['Close'].shift(1)
                tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
                atr14 = tr.rolling(window=14).mean().iloc[-1]
                
                # Get market cap from stock info
                market_cap = stock.info.get('marketCap', 0)
                expected_move = f"{round(straddle / underlying_price * 100, 2)}%" if straddle else "N/A"
                
                return {
                    'avg_volume': avg_volume >= 1500000,
                    'iv30_rv30': iv30_rv30,
                    'term_slope': ts_slope_0_45,
                    'term_structure': iv30,
                    'expected_move': expected_move,
                    'underlying_price': underlying_price,
                    'historical_volatility': hist_vol,
                    'data_inaccurate': data_inaccurate,
                    'current_iv': first_atm_iv,
                    'atr14': atr14,
                    'market_cap': market_cap,
                    'volume': today_volume
                }
                
            except Exception as e:
                retry_count += 1
                if retry_count < max_retries:
                    self.logger.warning(f"Attempt {retry_count} failed for {ticker}: {str(e)}. Rotating proxy and retrying...")
                    self.session_manager.rotate_session()
                else:
                    self.logger.error(f"All attempts failed for {ticker}: {str(e)}")
                    return {"error": f"Error occurred processing: {str(e)}"}


# ------------------- Earnings Calendar Fetcher -------------------
class EarningsCalendarFetcher:
    """Fetch earnings calendar data with proxy support."""
    
    def __init__(self, proxy_manager: Optional[ProxyManager] = None):
        self.data_queue = Queue()
        self.earnings_times = {}
        self.proxy_manager = proxy_manager or ProxyManager()
        self.session_manager = SessionManager(self.proxy_manager)
        self._initialize_logging()
    
    def _initialize_logging(self):
        self.logger = logging.getLogger('EarningsCalendarFetcher')
        self.logger.setLevel(logging.DEBUG)
        if not self.logger.handlers:
            fh = logging.FileHandler('earnings_calendar_debug.log')
            fh.setLevel(logging.DEBUG)
            formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            fh.setFormatter(formatter)
            self.logger.addHandler(fh)
    
    def fetch_earnings_data(self, date: str) -> List[str]:
        """
        Fetch earnings data for a given date (YYYY-MM-DD) from investing.com.
        Includes proxy support and automatic retry logic.
        """
        max_retries = 3
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                self.logger.info(f"Fetching earnings data for date: {date}")
                url = "https://www.investing.com/earnings-calendar/Service/getCalendarFilteredData"
                headers = {
                    'User-Agent': 'Mozilla/5.0',
                    'X-Requested-With': 'XMLHttpRequest',
                    'Content-Type': 'application/x-www-form-urlencoded',
                    'Referer': 'https://www.investing.com/earnings-calendar/'
                }
                payload = {
                    'country[]': '5',  # US
                    'dateFrom': date,
                    'dateTo': date,
                    'currentTab': 'custom',
                    'limit_from': 0
                }
                
                session = self.session_manager.get_session()
                response = session.post(url, headers=headers, data=payload)
                data = json.loads(response.text)
                soup = BeautifulSoup(data['data'], 'html.parser')
                rows = soup.find_all('tr')
                earnings_data = []
                self.earnings_times.clear()
                
                for row in rows:
                    if not row.find('span', class_='earnCalCompanyName'):
                        continue
                    try:
                        ticker = row.find('a', class_='bold').text.strip()
                        timing_span = row.find('span', class_='genToolTip')
                        timing = "During Market"
                        if timing_span and 'data-tooltip' in timing_span.attrs:
                            tooltip = timing_span['data-tooltip']
                            if tooltip == 'Before market open':
                                timing = 'Pre Market'
                            elif tooltip == 'After market close':
                                timing = 'Post Market'
                        self.earnings_times[ticker] = timing
                        earnings_data.append(ticker)
                    except Exception as e:
                        self.logger.error(f"Error processing row for ticker: {e}")
                        continue
                
                self.logger.info(f"Successfully retrieved {len(earnings_data)} companies")
                return earnings_data
                
            except Exception as e:
                retry_count += 1
                if retry_count < max_retries:
                    self.logger.warning(f"Attempt {retry_count} failed: {str(e)}. Rotating proxy and retrying...")
                    self.session_manager.rotate_session()
                else:
                    self.logger.error(f"All attempts failed: {str(e)}")
                    return []
    
    def get_earnings_time(self, ticker: str) -> str:
        """Return the market timing for the given ticker."""
        return self.earnings_times.get(ticker, 'Unknown')

# ------------------- Data Cache -------------------
class DataCache:
    """Persistent cache for stock data with gap filling capabilities."""
    
    from typing import List, Dict, Optional, Tuple
    
    def __init__(self, cache_dir: str = "stock_cache"):
        self.cache_dir = cache_dir
        self.cache_expiry_days = 7  # Cache data expires after 7 days
        self._ensure_cache_dir()
        self._initialize_logging()
    
    def _initialize_logging(self):
        """Initialize logging for the cache system."""
        self.logger = logging.getLogger('DataCache')
        self.logger.setLevel(logging.DEBUG)
        if not self.logger.handlers:
            fh = logging.FileHandler('cache_debug.log')
            fh.setLevel(logging.DEBUG)
            formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            fh.setFormatter(formatter)
            self.logger.addHandler(fh)
    
    def _ensure_cache_dir(self):
        """Create cache directory if it doesn't exist."""
        if not os.path.exists(self.cache_dir):
            os.makedirs(self.cache_dir)
    
    def _get_cache_key(self, date: str, tickers: List[str]) -> str:
        """Generate a unique cache key for a date and list of tickers."""
        tickers_str = "_".join(sorted(tickers))
        data_str = f"{date}_{tickers_str}"
        return hashlib.md5(data_str.encode()).hexdigest()
    
    def _get_cache_path(self, cache_key: str) -> str:
        """Get the full path for a cache file."""
        return os.path.join(self.cache_dir, f"{cache_key}.pkl")
    
    def _identify_missing_data(self, data: List[Dict]) -> List[Dict]:
        """
        Identify entries with missing or incomplete data.
        Returns a list of dictionaries containing tickers with missing data.
        """
        missing_data = []
        for entry in data:
            is_missing = False
            missing_fields = []
            
            # Check for missing or invalid values
            if entry.get('expected_move') == 'N/A':
                missing_fields.append('expected_move')
                is_missing = True
            
            if entry.get('current_iv') is None:
                missing_fields.append('current_iv')
                is_missing = True
            
            if entry.get('term_structure') == 0 or entry.get('term_structure') == "N/A":
                missing_fields.append('term_structure')
                is_missing = True
            
            if is_missing:
                missing_data.append({
                    'ticker': entry['ticker'],
                    'missing_fields': missing_fields,
                    'earnings_time': entry.get('earnings_time', 'Unknown')
                })
        
        return missing_data
    
    def save_data(self, date: str, tickers: List[str], data: List[Dict]) -> None:
        """Save data to cache, identifying any missing fields."""
        cache_key = self._get_cache_key(date, tickers)
        cache_path = self._get_cache_path(cache_key)
        
        # Identify missing data before saving
        missing_data = self._identify_missing_data(data)
        
        cache_data = {
            'timestamp': datetime.now(),
            'date': date,
            'tickers': tickers,
            'data': data,
            'missing_data': missing_data  # Store information about missing data
        }
        
        with open(cache_path, 'wb') as f:
            pickle.dump(cache_data, f)
        
        if missing_data:
            self.logger.info(f"Saved cache with {len(missing_data)} entries having missing data")
    
    def get_data(self, date: str, tickers: List[str]) -> Tuple[Optional[List[Dict]], List[Dict]]:
        """
        Retrieve data from cache if it exists and is not expired.
        Returns a tuple of (cached_data, missing_data_entries).
        """
        cache_key = self._get_cache_key(date, tickers)
        cache_path = self._get_cache_path(cache_key)
        
        if not os.path.exists(cache_path):
            return None, []
        
        try:
            with open(cache_path, 'rb') as f:
                cache_data = pickle.load(f)
            
            # Check if cache is expired
            cache_age = datetime.now() - cache_data['timestamp']
            if cache_age.days >= self.cache_expiry_days:
                os.remove(cache_path)  # Remove expired cache
                return None, []
            
            return cache_data['data'], cache_data.get('missing_data', [])
        except Exception as e:
            self.logger.error(f"Error reading cache: {str(e)}")
            return None, []
    
    def update_missing_data(self, date: str, tickers: List[str], new_data: Dict) -> None:
        """
        Update cache with new data for previously missing fields.
        """
        cache_key = self._get_cache_key(date, tickers)
        cache_path = self._get_cache_path(cache_key)
        
        try:
            with open(cache_path, 'rb') as f:
                cache_data = pickle.load(f)
            
            # Update the existing data with new information
            for idx, entry in enumerate(cache_data['data']):
                if entry['ticker'] == new_data['ticker']:
                    # Update missing fields
                    for key, value in new_data.items():
                        if key in entry and (entry[key] == 'N/A' or entry[key] is None or entry[key] == 0):
                            entry[key] = value
            
            # Recalculate missing data
            cache_data['missing_data'] = self._identify_missing_data(cache_data['data'])
            
            # Save updated cache
            with open(cache_path, 'wb') as f:
                pickle.dump(cache_data, f)
            
            self.logger.info(f"Updated cache for ticker {new_data['ticker']}")
        except Exception as e:
            self.logger.error(f"Error updating cache: {str(e)}")
    
    def clear_expired(self) -> None:
        """Clear all expired cache files."""
        for filename in os.listdir(self.cache_dir):
            if not filename.endswith('.pkl'):
                continue
            
            cache_path = os.path.join(self.cache_dir, filename)
            try:
                with open(cache_path, 'rb') as f:
                    cache_data = pickle.load(f)
                
                cache_age = datetime.now() - cache_data['timestamp']
                if cache_age.days >= self.cache_expiry_days:
                    os.remove(cache_path)
            except Exception as e:
                self.logger.error(f"Error clearing cache file {filename}: {str(e)}")
                # Remove corrupted cache files
                os.remove(cache_path)
# ------------------- EnhancedEarningScanner -------------------
class EnhancedEarningsScanner:
    """Earnings scanner with persistent caching and optimized data fetching."""
    
    def __init__(self, options_analyzer: OptionsAnalyzer):
        self.analyzer = options_analyzer
        self.calendar_fetcher = EarningsCalendarFetcher(self.analyzer.proxy_manager)
        self.data_cache = DataCache()
        self.batch_size = 10
        self.logger = None
        self._initialize_logging()
    
    def _initialize_logging(self):
        """Initialize logging configuration."""
        self.logger = logging.getLogger('EnhancedEarningsScanner')
        self.logger.setLevel(logging.DEBUG)
        if not self.logger.handlers:
            fh = logging.FileHandler('earnings_scanner_debug.log')
            fh.setLevel(logging.DEBUG)
            formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            fh.setFormatter(formatter)
            self.logger.addHandler(fh)

    def batch_download_history(self, tickers: List[str]) -> Dict[str, pd.DataFrame]:
        """Download historical data for multiple tickers in a single call."""
        ticker_str = " ".join(tickers)
        try:
            data = yf.download(
                tickers=ticker_str,
                period="3mo",
                group_by='ticker',
                auto_adjust=True,
                prepost=True,
                threads=True,
                proxy=self.analyzer.session_manager.get_session().proxies
            )
            
            results = {}
            if len(tickers) == 1:
                # Handle single ticker case
                results[tickers[0]] = data
            else:
                # Handle multiple tickers
                for ticker in tickers:
                    try:
                        ticker_data = data.xs(ticker, axis=1, level=0)
                        if not ticker_data.empty:
                            results[ticker] = ticker_data
                    except:
                        continue
            
            return results
        except Exception as e:
            self.logger.error(f"Error in batch download: {e}")
            return {}

    def scan_earnings_stocks(self, date: datetime, progress_callback: Optional[callable] = None) -> List[Dict]:
        """Scan stocks with earnings, using cached data if available and filling in missing data."""
        date_str = date.strftime('%Y-%m-%d')
        self.logger.info(f"Starting earnings scan for date: {date_str}")
        
        # Get earnings stocks for the date
        earnings_stocks = self.calendar_fetcher.fetch_earnings_data(date_str)
        if not earnings_stocks:
            return []
        
        # Check cache first
        cached_data, missing_data = self.data_cache.get_data(date_str, earnings_stocks)
        
        if cached_data:
            self.logger.info(f"Using cached data for {date_str}")
            
            if missing_data:
                self.logger.info(f"Found {len(missing_data)} entries with missing data, attempting to fill gaps")
                
                # Process only stocks with missing data
                missing_tickers = [entry['ticker'] for entry in missing_data]
                completed = 0
                total_missing = len(missing_tickers)
                
                # Process missing data in batches
                batches = [missing_tickers[i:i + self.batch_size] 
                        for i in range(0, len(missing_tickers), self.batch_size)]
                
                for batch in batches:
                    # Batch download historical data for missing entries
                    histories = self.batch_download_history(batch)
                    
                    # Process each stock in the batch
                    with concurrent.futures.ThreadPoolExecutor(max_workers=min(5, len(batch))) as executor:
                        future_to_stock = {executor.submit(self.analyze_stock, stock, histories.get(stock)): stock 
                                        for stock in batch}
                        
                        for future in concurrent.futures.as_completed(future_to_stock):
                            stock = future_to_stock[future]
                            completed += 1
                            if progress_callback:
                                # Scale progress to 20% of total (reserving 80% for initial scan)
                                progress_value = 80 + (completed / total_missing * 20)
                                progress_callback(progress_value)
                            
                            try:
                                result = future.result()
                                if result:
                                    # Update cache with new data
                                    self.data_cache.update_missing_data(date_str, earnings_stocks, result)
                            except Exception as e:
                                self.logger.error(f"Error updating {stock}: {str(e)}")
                
                # Get updated cache data
                cached_data, missing_data = self.data_cache.get_data(date_str, earnings_stocks)
            
            if progress_callback:
                progress_callback(100)
            
            return cached_data
        
        # If no cache available, process all stocks
        recommended_stocks = []
        total_stocks = len(earnings_stocks)
        completed = 0
        
        # Process in batches
        batches = [earnings_stocks[i:i + self.batch_size] 
                for i in range(0, len(earnings_stocks), self.batch_size)]
        
        for batch in batches:
            # Batch download historical data
            histories = self.batch_download_history(batch)
            
            # Process each stock in the batch
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(5, len(batch))) as executor:
                future_to_stock = {executor.submit(self.analyze_stock, stock, histories.get(stock)): stock 
                                for stock in batch}
                
                for future in concurrent.futures.as_completed(future_to_stock):
                    stock = future_to_stock[future]
                    completed += 1
                    if progress_callback:
                        # Scale progress to 80% (reserving 20% for potential gap filling)
                        progress_value = (completed / total_stocks * 80)
                        progress_callback(progress_value)
                    
                    try:
                        result = future.result()
                        if result:
                            recommended_stocks.append(result)
                    except Exception as e:
                        self.logger.error(f"Error analyzing {stock}: {str(e)}")
        
        # Sort recommendations
        recommended_stocks.sort(key=lambda x: (
            x['recommendation'] != 'Recommended',
            x['earnings_time'] == 'Unknown',
            x['earnings_time'],
            x['ticker']
        ))
        
        # Cache the results
        self.data_cache.save_data(date_str, earnings_stocks, recommended_stocks)
        
        if progress_callback:
            progress_callback(100)
        
        return recommended_stocks

    def analyze_stock(self, ticker: str, history_data: Optional[pd.DataFrame] = None) -> Optional[Dict]:
        """Analyze a single stock using cached data where possible."""
        try:
            self.logger.debug(f"Analyzing stock: {ticker}")
            
            # Use provided historical data or fetch it
            if history_data is not None and not history_data.empty:
                current_price = history_data['Close'].iloc[-1]
                volume_data = history_data['Volume']
                hist_vol = self.analyzer.yang_zhang_volatility(history_data)
                avg_volume = volume_data.rolling(30).mean().dropna().iloc[-1]
                today_volume = volume_data.iloc[-1]
            else:
                # Fallback to individual requests if no history provided
                stock = self.analyzer.get_ticker(ticker)
                history_data = stock.history(period='3mo')
                current_price = history_data['Close'].iloc[-1]
                volume_data = history_data['Volume']
                hist_vol = self.analyzer.yang_zhang_volatility(history_data)
                avg_volume = volume_data.rolling(30).mean().dropna().iloc[-1]
                today_volume = volume_data.iloc[-1]
            
            # Get options data
            stock = self.analyzer.get_ticker(ticker)
            options_data = self.analyzer.compute_recommendation(ticker)
            
            if isinstance(options_data, dict) and "error" not in options_data:
                avg_volume_bool = options_data['avg_volume']
                iv30_rv30_bool = options_data['iv30_rv30'] >= 1.25
                ts_slope_bool = options_data['term_slope'] <= -0.00406
                
                if avg_volume_bool and iv30_rv30_bool and ts_slope_bool:
                    rec = "Recommended"
                elif ts_slope_bool and ((avg_volume_bool and not iv30_rv30_bool) or 
                                      (iv30_rv30_bool and not avg_volume_bool)):
                    rec = "Consider"
                else:
                    rec = "Avoid"
                
                return {
                    'ticker': ticker,
                    'current_price': current_price,
                    'market_cap': stock.info.get('marketCap', 0),
                    'volume': today_volume,
                    'avg_volume': avg_volume_bool,
                    'earnings_time': self.calendar_fetcher.get_earnings_time(ticker),
                    'recommendation': rec,
                    'expected_move': options_data['expected_move'],
                    'atr14': options_data['atr14'],
                    'iv30_rv30': options_data['iv30_rv30'],
                    'term_slope': options_data['term_slope'],
                    'term_structure': options_data['term_structure'],
                    'historical_volatility': hist_vol,
                    'current_iv': options_data['current_iv']
                }
                
            return {
                "ticker": ticker,
                "current_price": current_price,
                "market_cap": 0,
                "volume": today_volume,
                "avg_volume": False,
                "earnings_time": "Unknown",
                "recommendation": "Avoid",
                "expected_move": "N/A",
                "atr14": 0,
                "iv30_rv30": 0,
                "term_slope": 0,
                "term_structure": 0,
                "historical_volatility": hist_vol,
                "current_iv": None
            }
            
        except Exception as e:
            self.logger.error(f"Error in analyze_stock for {ticker}: {str(e)}")
            return None
# ------------------- Interactive Chart Function -------------------
def show_interactive_chart(ticker: str, session_manager: Optional[SessionManager] = None):
    """
    Open an interactive Matplotlib window with a 1-year candlestick chart for the given ticker.
    Users can zoom, pan, etc. with the standard Matplotlib toolbar. Includes proxy support.
    """
    try:
        stock = yf.Ticker(ticker)
        if session_manager:
            stock.session = session_manager.get_session()
        
        max_retries = 3
        retry_count = 0
        hist = None
        
        while retry_count < max_retries:
            try:
                hist = stock.history(period='1y')
                if not hist.empty:
                    break
            except Exception as e:
                retry_count += 1
                if retry_count < max_retries and session_manager:
                    session_manager.rotate_session()
                    stock.session = session_manager.get_session()
                else:
                    raise
        
        if hist is None or hist.empty:
            sg.popup_error(f"No historical data available for {ticker}.")
            return
            
        # Create a candlestick chart using mplfinance with volume
        mpf.plot(hist, type='candle', style='charles', 
                title=f"{ticker} Candlestick Chart",
                volume=True,
                figsize=(12, 8),
                panel_ratios=(2, 1))  # 2:1 ratio between price and volume panels
        
        # Show an interactive window (blocking until closed)
        plt.show()
        
    except Exception as e:
        sg.popup_error(f"Error generating chart for {ticker}: {str(e)}")

# ------------------- Enhanced GUI -------------------
def create_enhanced_gui():
    """
    Create the enhanced GUI with proxy support and advanced visualization capabilities.
    """
    # Initialize proxy manager and analyzer
    proxy_manager = ProxyManager()
    analyzer = OptionsAnalyzer(proxy_manager)
    scanner = EnhancedEarningsScanner(analyzer)
    
    # Use a simpler system theme
    sg.theme('SystemDefault')
    
    # Define table headings in the desired order
    headings = [
        "Ticker", "Price", "Market Cap", "Volume", "Avg Volume", "Earnings Time", 
        "Recommendation", "Expected Move", "ATR 14d", "IV30/RV30", 
        "Term Slope", "Term Structure", "Historical Vol", "Current IV"
    ]
    
    # Add proxy settings to the layout
    proxy_settings = [
        [sg.Text("Proxy Settings:")],
        [sg.Checkbox("Enable Proxy", key="-PROXY-", enable_events=True),
         sg.Button("Update Proxies"),
         sg.Text("Status:", size=(8, 1)),
         sg.Text("Disabled", key="-PROXY-STATUS-", size=(20, 1))]
    ]
    
    # Main layout with proxy settings
    main_layout = [
        [sg.Text("Enter Stock Symbol:"), 
         sg.Input(key="stock", size=(20, 1)),
         sg.Button("Analyze", bind_return_key=True)],
        [sg.Column(proxy_settings)],
        [sg.Text("Or scan earnings stocks:")],
        [sg.CalendarButton('Choose Date', target='earnings_date', format='%Y-%m-%d'),
         sg.Input(key='earnings_date', size=(20, 1), disabled=True),
         sg.Button("Scan Earnings"),
         sg.Combo(['All', 'Pre Market', 'Post Market', 'During Market'], 
                  default_value='All', key='-FILTER-', enable_events=True)],
        [sg.Table(values=[],
                  headings=headings,
                  auto_size_columns=True,
                  display_row_numbers=False,
                  justification='center',
                  key='-TABLE-',
                  num_rows=20,
                  expand_x=True,
                  expand_y=True,
                  enable_events=True)],
        [sg.Text("Status: Ready", key='-STATUS-', size=(80, 1))],
        [sg.Button("Export to CSV"), sg.Button("Exit")]
    ]
    
    window = sg.Window("Enhanced Options Analysis Tool", 
                      main_layout,
                      resizable=True,
                      size=(1200, 800),
                      finalize=True)
    
    # Variables to store table data and row colors for highlighting
    all_data = []
    row_colors = []
    
    def assign_row_color(idx: int, expected_move: str, recommendation: str) -> str:
        """
        Determine row color based on:
          1) If expected_move == "N/A": GRAY
          2) elif recommended => GREEN
          3) elif consider => ORANGE
          4) else => RED (avoid)
        """
        if expected_move == "N/A":
            return 'gray'
        elif recommendation == "Recommended":
            return 'green'
        elif recommendation == "Consider":
            return 'orange'
        else:  # "Avoid"
            return 'red'
    
    def update_proxy_status():
        """Update the proxy status display in the GUI."""
        status = "Enabled" if proxy_manager.proxy_enabled else "Disabled"
        if proxy_manager.proxy_enabled:
            status += f" ({len(proxy_manager.proxies)} proxies)"
        window["-PROXY-STATUS-"].update(status)
    
    while True:
        event, values = window.read()
        
        if event in (sg.WINDOW_CLOSED, "Exit"):
            break
        
        if event == "-PROXY-":
            proxy_manager.proxy_enabled = values["-PROXY-"]
            if proxy_manager.proxy_enabled and not proxy_manager.proxies:
                try:
                    proxy_manager.fetch_proxies()
                    window['-STATUS-'].update("Proxies updated successfully")
                except Exception as e:
                    window['-STATUS-'].update(f"Failed to fetch proxies: {str(e)}")
                    proxy_manager.proxy_enabled = False
                    window["-PROXY-"].update(False)
            update_proxy_status()
        
        elif event == "Update Proxies":
            try:
                proxy_manager.fetch_proxies()
                window['-STATUS-'].update("Proxies updated successfully")
                update_proxy_status()
            except Exception as e:
                window['-STATUS-'].update(f"Failed to fetch proxies: {str(e)}")
        
        elif event == "Analyze":
            window['-STATUS-'].update("Analyzing stock...")
            ticker = values.get("stock", "").strip().upper()
            if not ticker:
                window['-STATUS-'].update("Please enter a stock symbol")
                continue
            
            try:
                result = scanner.analyze_stock(ticker)
                if result:
                    # Build a single-row table using the new order
                    row = [
                        result['ticker'],
                        f"${result['current_price']:.2f}",
                        f"${result['market_cap']:,}" if result['market_cap'] else "N/A",
                        f"{result['volume']:,}" if result['volume'] else "N/A",
                        'PASS' if result['avg_volume'] else 'FAIL',
                        result['earnings_time'],
                        result['recommendation'],
                        result['expected_move'],
                        f"{result['atr14']:.2f}",
                        f"{result['iv30_rv30']:.2f}",
                        f"{result['term_slope']:.4f}",
                        f"{result['term_structure']:.2%}" if result['term_structure'] else "N/A",
                        f"{result['historical_volatility']:.2%}",
                        f"{result['current_iv']:.2%}" if result['current_iv'] else "N/A"
                    ]
                    all_data = [row]
                    
                    # Assign color for this single row
                    row_colors = []
                    row_color = assign_row_color(
                        idx=0, 
                        expected_move=result['expected_move'], 
                        recommendation=result['recommendation']
                    )
                    row_colors.append((0, row_color))
                    
                    window['-TABLE-'].update(values=all_data, row_colors=row_colors)
                    window['-STATUS-'].update("Analysis complete")
                else:
                    window['-STATUS-'].update("No recommendation returned")
            except Exception as e:
                window['-STATUS-'].update(f"Error: {str(e)}")
        
        elif event == "Scan Earnings":
            try:
                date_str = values.get('earnings_date')
                if not date_str:
                    sg.popup_error("Please select a date first!")
                    continue
                
                date = datetime.strptime(date_str, '%Y-%m-%d')
                progress_layout = [
                    [sg.Text('Scanning earnings stocks...')],
                    [sg.ProgressBar(100, orientation='h', size=(30, 20), key='progress')]
                ]
                progress_window = sg.Window('Progress', progress_layout, modal=True, finalize=True)
                progress_bar = progress_window['progress']
                
                window['-STATUS-'].update("Scanning earnings stocks...")
                result_holder = {'stocks': [], 'error': None}
                
                def update_progress(value):
                    progress_bar.update(value)
                    progress_window.refresh()
                
                def worker():
                    try:
                        stocks = scanner.scan_earnings_stocks(date, update_progress)
                        result_holder['stocks'] = stocks
                    except Exception as e:
                        result_holder['error'] = str(e)
                
                thread = threading.Thread(target=worker, daemon=True)
                thread.start()
                
                while thread.is_alive():
                    event_prog, _ = progress_window.read(timeout=100)
                    if event_prog == sg.WINDOW_CLOSED:
                        break
                
                progress_window.close()
                
                if result_holder['error']:
                    window['-STATUS-'].update(f"Error: {result_holder['error']}")
                else:
                    stocks = result_holder['stocks']
                    if not stocks:
                        window['-STATUS-'].update("No recommended stocks found")
                        continue
                    
                    table_data = []
                    row_colors = []
                    for idx, stock in enumerate(stocks):
                        row = [
                            stock['ticker'],
                            f"${stock['current_price']:.2f}",
                            f"${stock['market_cap']:,}" if stock['market_cap'] else "N/A",
                            f"{stock['volume']:,}" if stock['volume'] else "N/A",
                            'PASS' if stock['avg_volume'] else 'FAIL',
                            stock['earnings_time'],
                            stock['recommendation'],
                            stock['expected_move'],
                            f"{stock['atr14']:.2f}",
                            f"{stock['iv30_rv30']:.2f}",
                            f"{stock['term_slope']:.4f}",
                            f"{stock['term_structure']:.2%}" if stock['term_structure'] else "N/A",
                            f"{stock['historical_volatility']:.2%}",
                            f"{stock['current_iv']:.2%}" if stock['current_iv'] else "N/A"
                        ]
                        table_data.append(row)
                        
                        # Assign color for each row
                        color = assign_row_color(
                            idx=idx, 
                            expected_move=stock['expected_move'], 
                            recommendation=stock['recommendation']
                        )
                        row_colors.append((idx, color))
                    
                    all_data = table_data
                    window['-TABLE-'].update(values=table_data, row_colors=row_colors)
                    window['-STATUS-'].update(f"Found {len(stocks)} recommended stocks")
                    
                    # Popup for incomplete straddle data
                    incomplete_tickers = [s['ticker'] for s in stocks if s['expected_move'] == "N/A"]
                    if incomplete_tickers:
                        sg.popup("Incomplete Data",
                                "The following tickers have incomplete data (expected move is N/A):",
                                "\n".join(incomplete_tickers))
                        
            except Exception as e:
                window['-STATUS-'].update(f"Error: {str(e)}")
        
        elif event == "-FILTER-":
            # Filter based on the "Earnings Time" column
            if all_data:
                filter_value = values['-FILTER-']
                if filter_value == 'All':
                    filtered_data = all_data
                else:
                    filtered_data = [row for row in all_data if row[5] == filter_value]
                window['-TABLE-'].update(values=filtered_data)
                window['-STATUS-'].update(f"Showing {len(filtered_data)} stocks")
        
        elif event == "Export to CSV":
            if not all_data:
                window['-STATUS-'].update("No data to export")
                continue
            try:
                date_str = values.get('earnings_date', datetime.now().strftime('%Y-%m-%d'))
                filename = f"earnings_scan_{date_str}.csv"
                import csv
                with open(filename, 'w', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow(headings)
                    writer.writerows(all_data)
                window['-STATUS-'].update(f"Successfully exported to {filename}")
            except Exception as e:
                window['-STATUS-'].update(f"Export failed: {str(e)}")
        
        elif event == "-TABLE-":
            # When a row in the table is clicked, show an interactive candlestick chart
            if values["-TABLE-"]:
                selected_index = values["-TABLE-"][0]
                selected_row = all_data[selected_index]
                ticker = selected_row[0]
                show_interactive_chart(ticker, analyzer.session_manager)
    
    window.close()

if __name__ == "__main__":
    create_enhanced_gui()
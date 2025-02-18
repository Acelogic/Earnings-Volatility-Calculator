"""
DISCLAIMER: 

This software is provided solely for educational and research purposes. 
It is not intended to provide investment advice, and no investment recommendations are made herein. 
The developers are not financial advisors and accept no responsibility for any financial decisions or losses resulting from the use of this software. 
Always consult a professional financial advisor before making any investment decisions.
"""

import FreeSimpleGUI as sg
import yfinance as yf
from datetime import datetime, timedelta
import pandas as pd
import threading
import warnings
import concurrent.futures
import numpy as np
import requests
import logging
import json
from bs4 import BeautifulSoup
from queue import Queue
from typing import Dict, List, Optional

import matplotlib.pyplot as plt
from io import BytesIO
import mplfinance as mpf  # For candlestick charts

# Check NumPy version for compatibility
NUMPY_VERSION = tuple(map(int, np.__version__.split('.')[:2]))
IS_NUMPY_2 = NUMPY_VERSION[0] >= 2

# ------------------- Options Analyzer -------------------
class OptionsAnalyzer:
    """Options analysis tool with version compatibility."""
    
    def __init__(self):
        self.warnings_shown = False
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
        todays_data = ticker.history(period='1d')
        if todays_data.empty:
            raise ValueError("No price data available")
        return todays_data['Close'].iloc[-1]
    
    def compute_recommendation(self, ticker: str) -> Dict:
        """
        Compute the trading recommendation using the following criteria:
          - Average volume must be at least 1,500,000 shares.
          - IV30/RV30 ratio must be at least 1.25.
          - Term structure slope (0 to 45 days) must be less than or equal to -0.00406.
        Also computes additional metrics:
          - Current IV (from the first option chain)
          - ATR 14d (Average True Range over 14 days)
          - Market Cap from stock info.
          - Volume (latest day's volume)
          - Term Structure: IV value at 30 days from the term structure spline.
          - Term Slope: computed over the 0-to-45 day range.
        Returns a dictionary with these values and boolean qualifiers.
        Also sets a flag 'data_inaccurate' if bid/ask values are missing or zero.
        """
        try:
            ticker = ticker.strip().upper()
            if not ticker:
                return {"error": "No stock symbol provided."}
            stock = yf.Ticker(ticker)
            if len(stock.options) == 0:
                return {"error": f"No options found for stock symbol '{ticker}'."}
            exp_dates = list(stock.options)
            exp_dates = self.filter_dates(exp_dates)
            options_chains = {}
            for exp_date in exp_dates:
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
            return {"error": f"Error occurred processing: {str(e)}"}

# ------------------- Earnings Calendar Fetcher -------------------
class EarningsCalendarFetcher:
    """Fetch earnings calendar data from investing.com."""
    
    def __init__(self):
        self.data_queue = Queue()
        self.earnings_times = {}
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
        Parses the HTML response and extracts tickers along with market timing.
        """
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
            response = requests.post(url, headers=headers, data=payload)
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
            self.logger.error(f"Error fetching earnings data: {e}")
            return []
    
    def get_earnings_time(self, ticker: str) -> str:
        """Return the market timing for the given ticker."""
        return self.earnings_times.get(ticker, 'Unknown')

# ------------------- Enhanced Earnings Scanner -------------------
class EnhancedEarningsScanner:
    """Earnings scanner that integrates the options analyzer with enhanced earnings calendar data."""
    
    def __init__(self, options_analyzer: OptionsAnalyzer):
        self.analyzer = options_analyzer
        self.calendar_fetcher = EarningsCalendarFetcher()
        self._initialize_logging()
    
    def _initialize_logging(self):
        self.logger = logging.getLogger('EnhancedEarningsScanner')
        self.logger.setLevel(logging.DEBUG)
        if not self.logger.handlers:
            fh = logging.FileHandler('earnings_scanner_debug.log')
            fh.setLevel(logging.DEBUG)
            formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            fh.setFormatter(formatter)
            self.logger.addHandler(fh)
    
    def scan_earnings_stocks(self, date: datetime, progress_callback: Optional[callable] = None) -> List[Dict]:
        """
        Scan stocks with earnings on the specified date and return a list of recommendations.
        Uses multithreading for concurrent analysis.
        """
        self.logger.info(f"Starting earnings scan for date: {date.strftime('%Y-%m-%d')}")
        earnings_stocks = self.calendar_fetcher.fetch_earnings_data(date.strftime('%Y-%m-%d'))
        recommended_stocks = []
        total_stocks = len(earnings_stocks)
        self.logger.info(f"Found {total_stocks} stocks with earnings")
        if total_stocks == 0:
            return []
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            future_to_stock = {executor.submit(self.analyze_stock, stock): stock for stock in earnings_stocks}
            completed = 0
            for future in concurrent.futures.as_completed(future_to_stock):
                stock = future_to_stock[future]
                completed += 1
                if progress_callback:
                    progress_callback(completed / total_stocks * 100)
                try:
                    result = future.result()
                    if result:
                        recommended_stocks.append(result)
                        self.logger.info(f"Added {stock} to recommendations: {result['recommendation']}")
                except Exception as e:
                    self.logger.error(f"Error analyzing {stock}: {str(e)}")
        # Sort recommendations (custom sort as needed)
        recommended_stocks.sort(key=lambda x: (
            x['recommendation'] != 'Recommended',
            x['earnings_time'] == 'Unknown',
            x['earnings_time'],
            x['ticker']
        ))
        return recommended_stocks
    
    def analyze_stock(self, ticker: str) -> Optional[Dict]:
        """
        Analyze a single stock using the options analyzer.
        Returns a dictionary with recommendation and additional details.
        Always returns a result—even if incomplete—defaulting to "Avoid" when data is missing.
        """
        try:
            self.logger.debug(f"Analyzing stock: {ticker}")
            result = self.analyzer.compute_recommendation(ticker)
            if isinstance(result, dict) and "error" not in result:
                avg_volume_bool = result['avg_volume']
                # For recommendation logic, we only care if iv30_rv30 >= 1.25
                # but we still store the actual float in the table.
                iv30_rv30_bool = result['iv30_rv30'] >= 1.25
                ts_slope_bool = result['term_slope'] <= -0.00406
                if avg_volume_bool and iv30_rv30_bool and ts_slope_bool:
                    rec = "Recommended"
                elif ts_slope_bool and ((avg_volume_bool and not iv30_rv30_bool) or (iv30_rv30_bool and not avg_volume_bool)):
                    rec = "Consider"
                else:
                    rec = "Avoid"
                return {
                    'ticker': ticker,
                    'current_price': result['underlying_price'],
                    'market_cap': result['market_cap'],
                    'volume': result['volume'],
                    'avg_volume': avg_volume_bool,
                    'earnings_time': self.calendar_fetcher.get_earnings_time(ticker),
                    'recommendation': rec,
                    'expected_move': result['expected_move'],
                    'atr14': result['atr14'],
                    'iv30_rv30': result['iv30_rv30'],
                    'term_slope': result['term_slope'],
                    'term_structure': result['term_structure'],
                    'historical_volatility': result['historical_volatility'],
                    'current_iv': result['current_iv']
                }
            else:
                return {
                    "ticker": ticker,
                    "current_price": 0,
                    "market_cap": 0,
                    "volume": 0,
                    "avg_volume": False,
                    "earnings_time": "Unknown",
                    "recommendation": "Avoid",
                    "expected_move": "N/A",
                    "atr14": 0,
                    "iv30_rv30": 0,
                    "term_slope": 0,
                    "term_structure": 0,
                    "historical_volatility": 0,
                    "current_iv": None
                }
        except Exception as e:
            self.logger.error(f"Error in analyze_stock for {ticker}: {str(e)}")
            return {
                "ticker": ticker,
                "current_price": 0,
                "market_cap": 0,
                "volume": 0,
                "avg_volume": False,
                "earnings_time": "Unknown",
                "recommendation": "Avoid",
                "expected_move": "N/A",
                "atr14": 0,
                "iv30_rv30": 0,
                "term_slope": 0,
                "term_structure": 0,
                "historical_volatility": 0,
                "current_iv": None
            }

# ------------------- Interactive Chart Function -------------------
def show_interactive_chart(ticker: str):
    """
    Open an interactive Matplotlib window with a 1-year candlestick chart for the given ticker.
    Users can zoom, pan, etc. with the standard Matplotlib toolbar.
    """
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period='1y')
        if hist.empty:
            sg.popup_error(f"No historical data available for {ticker}.")
            return
        # Create a candlestick chart using mplfinance with volume
        mpf.plot(hist, type='candle', style='charles', title=f"{ticker} Candlestick Chart", volume=True)
        # Show an interactive window (blocking until closed)
        plt.show()
    except Exception as e:
        sg.popup_error(f"Error generating chart for {ticker}: {str(e)}")

# ------------------- Enhanced GUI -------------------
def create_enhanced_gui():
    """
    Create the enhanced GUI with the table columns in the desired order.
    Row color logic:
      - If Expected Move is "N/A": row is GRAY (takes precedence).
      - Else if Recommendation is "Recommended": row is GREEN.
      - Else if Recommendation is "Consider": row is ORANGE.
      - Else (Avoid): row is RED.
    """
    analyzer = OptionsAnalyzer()
    scanner = EnhancedEarningsScanner(analyzer)
    
    # Use a simpler system theme
    sg.theme('SystemDefault')
    
    # Define table headings in the desired order.
    headings = [
        "Ticker", "Price", "Market Cap", "Volume", "Avg Volume", "Earnings Time", 
        "Recommendation", "Expected Move", "ATR 14d", "IV30/RV30", 
        "Term Slope", "Term Structure", "Historical Vol", "Current IV"
    ]
    
    main_layout = [
        [sg.Text("Enter Stock Symbol:"), 
         sg.Input(key="stock", size=(20, 1)),
         sg.Button("Analyze", bind_return_key=True)],
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
    
    while True:
        event, values = window.read()
        if event in (sg.WINDOW_CLOSED, "Exit"):
            break
        
        if event == "Analyze":
            window['-STATUS-'].update("Analyzing stock...")
            ticker = values.get("stock", "").strip().upper()
            if not ticker:
                window['-STATUS-'].update("Please enter a stock symbol")
                continue
            try:
                result = scanner.analyze_stock(ticker)
                if result:
                    # Build a single-row table using the new order.
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
                    
                    # (Optional) If you want to popup for incomplete straddle data:
                    incomplete_tickers = [s['ticker'] for s in stocks if s['expected_move'] == "N/A"]
                    if incomplete_tickers:
                        sg.popup("Incomplete Data",
                                 "The following tickers have incomplete data (expected move is N/A):",
                                 "\n".join(incomplete_tickers))
            except Exception as e:
                window['-STATUS-'].update(f"Error: {str(e)}")
        
        elif event == "-FILTER-":
            # Filter based on the "Earnings Time" column, which is at index 5 in the table
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
            # When a row in the table is clicked, show an interactive candlestick chart for that ticker.
            if values["-TABLE-"]:
                selected_index = values["-TABLE-"][0]
                selected_row = all_data[selected_index]
                ticker = selected_row[0]
                show_interactive_chart(ticker)
                # The GUI will pause until the user closes the Matplotlib window.
    
    window.close()

if __name__ == "__main__":
    create_enhanced_gui()
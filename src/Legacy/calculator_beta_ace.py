import FreeSimpleGUI as sg
import yfinance as yf
from yahooquery import Ticker
from datetime import datetime, timedelta
import pandas as pd
import threading
from typing import Dict, List, Tuple, Optional
import warnings
import concurrent.futures
import numpy as np
import requests
import logging
import json


# Version checking
NUMPY_VERSION = tuple(map(int, np.__version__.split('.')[:2]))
IS_NUMPY_2 = NUMPY_VERSION[0] >= 2

class OptionsAnalyzer:
    """Options analysis tool with version compatibility."""
    
    def __init__(self):
        self.warnings_shown = False
    
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
        """Filter option expiration dates."""
        today = datetime.today().date()
        cutoff_date = today + timedelta(days=45)
        
        sorted_dates = sorted(datetime.strptime(date, "%Y-%m-%d").date() for date in dates)
        
        arr = []
        for i, date in enumerate(sorted_dates):
            if date >= cutoff_date:
                arr = [d.strftime("%Y-%m-%d") for d in sorted_dates[:i+1]]
                break
        
        if len(arr) > 0:
            if arr[0] == today.strftime("%Y-%m-%d"):
                return arr[1:]
            return arr
        
        raise ValueError("No date 45 days or more in the future found.")

    def yang_zhang_volatility(self, price_data: pd.DataFrame, 
                            window: int = 30, 
                            trading_periods: int = 252, 
                            return_last_only: bool = True) -> float:
        """Calculate Yang-Zhang volatility with version compatibility."""
        try:
            log_ho = self.safe_log(price_data['High'] / price_data['Open'])
            log_lo = self.safe_log(price_data['Low'] / price_data['Open'])
            log_co = self.safe_log(price_data['Close'] / price_data['Open'])
            
            log_oc = self.safe_log(price_data['Open'] / price_data['Close'].shift(1))
            log_oc_sq = log_oc**2
            
            log_cc = self.safe_log(price_data['Close'] / price_data['Close'].shift(1))
            log_cc_sq = log_cc**2
            
            rs = log_ho * (log_ho - log_co) + log_lo * (log_lo - log_co)
            
            close_vol = log_cc_sq.rolling(window=window, center=False).sum() * (1.0 / (window - 1.0))
            open_vol = log_oc_sq.rolling(window=window, center=False).sum() * (1.0 / (window - 1.0))
            window_rs = rs.rolling(window=window, center=False).sum() * (1.0 / (window - 1.0))
            
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

    def calculate_simple_volatility(self, price_data: pd.DataFrame,
                                  window: int = 30,
                                  trading_periods: int = 252,
                                  return_last_only: bool = True) -> float:
        """Calculate simple volatility as fallback method."""
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
        """Build IV term structure with error handling."""
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
        """Get current stock price."""
        todays_data = ticker.history(period='1d')
        if todays_data.empty:
            raise ValueError("No price data available")
        return todays_data['Close'].iloc[0]

    def compute_recommendation(self, ticker: str) -> Dict:
        """Compute trading recommendation with all original features."""
        try:
            ticker = ticker.strip().upper()
            if not ticker:
                return "No stock symbol provided."
            
            try:
                stock = yf.Ticker(ticker)
                if len(stock.options) == 0:
                    raise KeyError()
            except KeyError:
                return f"Error: No options found for stock symbol '{ticker}'."
            
            exp_dates = list(stock.options)
            try:
                exp_dates = self.filter_dates(exp_dates)
            except:
                return "Error: Not enough option data."
            
            options_chains = {}
            for exp_date in exp_dates:
                options_chains[exp_date] = stock.option_chain(exp_date)
            
            try:
                underlying_price = self.get_current_price(stock)
                if underlying_price is None:
                    raise ValueError("No market price found.")
            except Exception:
                return "Error: Unable to retrieve underlying stock price."
            
            atm_iv = {}
            straddle = None
            i = 0
            for exp_date, chain in options_chains.items():
                calls = chain.calls
                puts = chain.puts
                
                if calls.empty or puts.empty:
                    continue
                
                call_diffs = (calls['strike'] - underlying_price).abs()
                call_idx = call_diffs.idxmin()
                call_iv = calls.loc[call_idx, 'impliedVolatility']
                
                put_diffs = (puts['strike'] - underlying_price).abs()
                put_idx = put_diffs.idxmin()
                put_iv = puts.loc[put_idx, 'impliedVolatility']
                
                atm_iv_value = (call_iv + put_iv) / 2.0
                atm_iv[exp_date] = atm_iv_value
                
                if i == 0:
                    call_bid = calls.loc[call_idx, 'bid']
                    call_ask = calls.loc[call_idx, 'ask']
                    put_bid = puts.loc[put_idx, 'bid']
                    put_ask = puts.loc[put_idx, 'ask']
                    
                    if call_bid is not None and call_ask is not None:
                        call_mid = (call_bid + call_ask) / 2.0
                    else:
                        call_mid = None
                    
                    if put_bid is not None and put_ask is not None:
                        put_mid = (put_bid + put_ask) / 2.0
                    else:
                        put_mid = None
                    
                    if call_mid is not None and put_mid is not None:
                        straddle = (call_mid + put_mid)
                
                i += 1
            
            if not atm_iv:
                return "Error: Could not determine ATM IV for any expiration dates."
            
            today = datetime.today().date()
            dtes = []
            ivs = []
            for exp_date, iv in atm_iv.items():
                exp_date_obj = datetime.strptime(exp_date, "%Y-%m-%d").date()
                days_to_expiry = (exp_date_obj - today).days
                dtes.append(days_to_expiry)
                ivs.append(iv)
            
            term_spline = self.build_term_structure(dtes, ivs)
            
            ts_slope_0_45 = (term_spline(45) - term_spline(dtes[0])) / (45-dtes[0])
            
            price_history = stock.history(period='3mo')
            iv30_rv30 = term_spline(30) / self.yang_zhang_volatility(price_history)
            
            avg_volume = price_history['Volume'].rolling(30).mean().dropna().iloc[-1]
            
            expected_move = str(round(straddle / underlying_price * 100, 2)) + "%" if straddle else None
            
            return {
                'avg_volume': avg_volume >= 1500000,
                'iv30_rv30': iv30_rv30 >= 1.25,
                'ts_slope_0_45': ts_slope_0_45 <= -0.00406,
                'expected_move': expected_move,
                'underlying_price': underlying_price,
                'historical_volatility': self.yang_zhang_volatility(price_history),
                'term_structure_slope': ts_slope_0_45
            }
            
        except Exception as e:
            return f"Error occurred processing: {str(e)}"

class EarningsScanner:
    """Scanner for finding recommended stocks with upcoming earnings."""
    
    def __init__(self, options_analyzer: OptionsAnalyzer):
        self.analyzer = options_analyzer
        self.debug_info = {}
        self.earnings_times = {}
        self._initialize_logging()
    
    def _initialize_logging(self):
        """Initialize logging for the scanner."""
        self.logger = logging.getLogger('EarningsScanner')
        self.logger.setLevel(logging.DEBUG)
        
        if not self.logger.handlers:
            fh = logging.FileHandler('earnings_scanner_debug.log')
            fh.setLevel(logging.DEBUG)
            formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            fh.setFormatter(formatter)
            self.logger.addHandler(fh)
    
    def get_earnings_time(self, ticker: str, target_date: datetime) -> str:
        """Get earnings timing from Yahoo Finance using get_earnings_dates."""
        try:
            stock = yf.Ticker(ticker)
            earnings_dates = stock.get_earnings_dates()
            
            if earnings_dates is not None and not earnings_dates.empty:
                # Convert target_date to date only for comparison
                target_date = target_date.date()
                
                # Find the earnings entry for our target date
                for idx, row in earnings_dates.iterrows():
                    if idx.date() == target_date:
                        hour = idx.hour
                        
                        if hour < 12:  # Morning
                            return 'Pre Market'
                        elif hour >= 16:  # After 4 PM
                            return 'Post Market'
                        else:
                            return 'During Market'
                
                self.logger.debug(f"No matching earnings date found for {ticker} on {target_date}")
            else:
                self.logger.debug(f"No earnings dates data available for {ticker}")
            
            return 'Unknown'
            
        except Exception as e:
            self.logger.error(f"Error getting earnings time for {ticker}: {str(e)}")
            return 'Unknown'
    
    def get_earnings_calendar(self, date: datetime) -> List[str]:
        """Get earnings calendar for a specific date using Yahoo Finance."""
        try:
            date_str = date.strftime('%Y-%m-%d')
            self.logger.info(f"Fetching earnings calendar for date: {date_str}")
            
            # Initialize earnings dictionary
            self.earnings_times = {}
            symbols = []
            
            # Get earnings calendar from Yahoo Finance
            calendar_url = f'https://finance.yahoo.com/calendar/earnings?day={date_str}'
            try:
                tables = pd.read_html(calendar_url)
                if tables and len(tables) > 0:
                    calendar = tables[0]
                    if 'Symbol' in calendar.columns:
                        for _, row in calendar.iterrows():
                            symbol = row['Symbol']
                            if isinstance(symbol, str):
                                symbols.append(symbol)
                                # Get timing using get_earnings_dates
                                timing = self.get_earnings_time(symbol, date)
                                self.earnings_times[symbol] = timing
                                self.logger.debug(f"Found timing for {symbol}: {timing}")
            except Exception as e:
                self.logger.error(f"Error reading calendar: {str(e)}")
            
            self.logger.info(f"Successfully retrieved {len(symbols)} symbols")
            self.debug_info = {
                "date": date_str,
                "symbols_found": len(symbols),
                "last_update": datetime.now().isoformat(),
                "timings": {
                    "pre_market": sum(1 for t in self.earnings_times.values() if t == 'Pre Market'),
                    "post_market": sum(1 for t in self.earnings_times.values() if t == 'Post Market'),
                    "during_market": sum(1 for t in self.earnings_times.values() if t == 'During Market'),
                    "unknown": sum(1 for t in self.earnings_times.values() if t == 'Unknown')
                }
            }
            
            return symbols
            
        except Exception as e:
            self.logger.error(f"Error in get_earnings_calendar: {str(e)}")
            self.debug_info = {
                "date": date_str,
                "error": str(e),
                "last_update": datetime.now().isoformat()
            }
            return []
    
    def get_debug_status(self) -> Dict:
        """Get the current debug status and latest interaction details."""
        return {
            "last_debug_info": self.debug_info,
            "earnings_times_count": len(self.earnings_times),
            "last_update": self.debug_info.get("last_update"),
            "timings_breakdown": self.debug_info.get("timings", {})
        }
    
    def scan_earnings_stocks(self, date: datetime, 
                           progress_callback: callable = None) -> List[Dict]:
        """Scan all stocks with earnings and return recommended ones."""
        self.logger.info(f"Starting earnings scan for date: {date.strftime('%Y-%m-%d')}")
        earnings_stocks = self.get_earnings_calendar(date)
        recommended_stocks = []
        
        total_stocks = len(earnings_stocks)
        self.logger.info(f"Found {total_stocks} stocks with earnings")
        
        if total_stocks == 0:
            return []
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            future_to_stock = {
                executor.submit(self.analyze_stock, stock): stock 
                for stock in earnings_stocks
            }
            
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
        
        # Sort recommendations by type and timing
        recommended_stocks.sort(key=lambda x: (
            x['recommendation'] != 'Recommended',  # Recommended first
            x['earnings_time'] == 'Unknown',      # Known times first
            x['earnings_time'],                   # Then by timing
            x['ticker']                          # Then by ticker
        ))
        
        self.logger.info(f"Scan completed. Found {len(recommended_stocks)} recommended stocks")
        return recommended_stocks
    
    def analyze_stock(self, ticker: str) -> Optional[Dict]:
        """Analyze a single stock and return if recommended."""
        try:
            self.logger.debug(f"Analyzing stock: {ticker}")
            result = self.analyzer.compute_recommendation(ticker)
            
            if isinstance(result, dict):
                avg_volume_bool = result['avg_volume']
                iv30_rv30_bool = result['iv30_rv30']
                ts_slope_bool = result['ts_slope_0_45']
                
                # Only include if it's recommended or worth considering
                if (ts_slope_bool and 
                    (avg_volume_bool or iv30_rv30_bool)):
                    
                    analysis_result = {
                        'ticker': ticker,
                        'recommendation': 'Recommended' if (avg_volume_bool and iv30_rv30_bool and ts_slope_bool) else 'Consider',
                        'expected_move': result['expected_move'],
                        'current_price': result['underlying_price'],
                        'earnings_time': self.earnings_times.get(ticker, 'Unknown'),
                        'historical_volatility': result['historical_volatility'],
                        'term_structure_slope': result['term_structure_slope'],
                        'avg_volume': avg_volume_bool,
                        'iv30_rv30': iv30_rv30_bool,
                        'ts_slope_0_45': ts_slope_bool
                    }
                    
                    self.logger.debug(f"Analysis completed for {ticker}: {analysis_result['recommendation']}")
                    return analysis_result
            
            self.logger.debug(f"Stock {ticker} did not meet criteria")
            return None
        except Exception as e:
            self.logger.error(f"Error in analyze_stock for {ticker}: {str(e)}")
            return None

    def reset_debug_info(self):
        """Reset debug information and clear any cached data."""
        self.debug_info = {}
        self.earnings_times = {}
        self.logger.info("Debug info and earnings times cache reset")
    
    def __init__(self, options_analyzer: OptionsAnalyzer):
        self.analyzer = options_analyzer
        self.debug_info = {}
        self.earnings_times = {}
        self._initialize_logging()
    
    def _initialize_logging(self):
        """Initialize logging for the scanner."""
        self.logger = logging.getLogger('EarningsScanner')
        self.logger.setLevel(logging.DEBUG)
        
        if not self.logger.handlers:
            fh = logging.FileHandler('earnings_scanner_debug.log')
            fh.setLevel(logging.DEBUG)
            formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            fh.setFormatter(formatter)
            self.logger.addHandler(fh)
    
    def get_earnings_time(self, ticker: str) -> str:
        """Get earnings timing from Yahoo Finance."""
        try:
            stock = yf.Ticker(ticker)
            
            # First try earnings calendar
            try:
                calendar = stock.earnings_dates
                if calendar is not None and not calendar.empty:
                    # Get the most recent or upcoming earnings date
                    earnings_row = calendar.iloc[0]
                    
                    # Check if we have a specific time in the index
                    if isinstance(earnings_row.name, pd.Timestamp):
                        hour = earnings_row.name.hour
                        
                        if hour < 12:  # Morning
                            return 'Pre Market'
                        elif hour >= 16:  # After 4 PM
                            return 'Post Market'
                        else:
                            return 'During Market'
            except Exception as e:
                self.logger.debug(f"earnings_dates approach failed for {ticker}: {str(e)}")
            
            # If calendar approach didn't work, try calendar property
            try:
                cal = stock.calendar
                if cal is not None and not cal.empty:
                    earnings_date = cal.iloc[0].get('Earnings Date')
                    if isinstance(earnings_date, pd.Timestamp):
                        hour = earnings_date.hour
                        
                        if hour < 12:
                            return 'Pre Market'
                        elif hour >= 16:
                            return 'Post Market'
                        else:
                            return 'During Market'
            except Exception as e:
                self.logger.debug(f"calendar approach failed for {ticker}: {str(e)}")
            
            # If still no timing found, try getting it from next earnings date
            try:
                next_earnings = stock.info.get('earningsTimestamp')
                if next_earnings:
                    # Convert timestamp to datetime
                    earnings_time = datetime.fromtimestamp(next_earnings)
                    hour = earnings_time.hour
                    
                    if hour < 12:
                        return 'Pre Market'
                    elif hour >= 16:
                        return 'Post Market'
                    else:
                        return 'During Market'
            except Exception as e:
                self.logger.debug(f"info approach failed for {ticker}: {str(e)}")
                
            self.logger.debug(f"No timing information found for {ticker}")
            return 'Unknown'
            
        except Exception as e:
            self.logger.error(f"Error getting YF earnings time for {ticker}: {str(e)}")
            return 'Unknown'
    
    def get_earnings_calendar(self, date: datetime) -> List[str]:
        """Get earnings calendar for a specific date using Yahoo Finance."""
        try:
            date_str = date.strftime('%Y-%m-%d')
            self.logger.info(f"Fetching earnings calendar for date: {date_str}")
            
            # Initialize earnings dictionary
            self.earnings_times = {}
            symbols = []
            
            # Try multiple methods to get earnings data
            
            # Method 1: Use yfinance calendar
            calendar_url = f'https://finance.yahoo.com/calendar/earnings?day={date_str}'
            try:
                tables = pd.read_html(calendar_url)
                if tables and len(tables) > 0:
                    calendar = tables[0]
                    if 'Symbol' in calendar.columns:
                        for _, row in calendar.iterrows():
                            symbol = row['Symbol']
                            if isinstance(symbol, str):
                                symbols.append(symbol)
            except Exception as e:
                self.logger.error(f"Error reading calendar: {str(e)}")
            
            # If we found symbols, get their timing information
            for symbol in symbols:
                timing = self.get_earnings_time(symbol)
                self.earnings_times[symbol] = timing
                self.logger.debug(f"Found timing for {symbol}: {timing}")
            
            self.logger.info(f"Successfully retrieved {len(symbols)} symbols")
            self.debug_info = {
                "date": date_str,
                "symbols_found": len(symbols),
                "last_update": datetime.now().isoformat()
            }
            
            return symbols
            
        except Exception as e:
            self.logger.error(f"Error in get_earnings_calendar: {str(e)}")
            self.debug_info = {
                "date": date_str,
                "error": str(e),
                "last_update": datetime.now().isoformat()
            }
            return []
    
    def get_debug_status(self) -> Dict:
        """Get the current debug status and latest interaction details."""
        return {
            "last_debug_info": self.debug_info,
            "earnings_times_count": len(self.earnings_times),
            "last_update": self.debug_info.get("last_update"),
            "timings_breakdown": {
                "pre_market": sum(1 for t in self.earnings_times.values() if t == 'Pre Market'),
                "post_market": sum(1 for t in self.earnings_times.values() if t == 'Post Market'),
                "during_market": sum(1 for t in self.earnings_times.values() if t == 'During Market'),
                "unknown": sum(1 for t in self.earnings_times.values() if t == 'Unknown')
            }
        }
    
    def scan_earnings_stocks(self, date: datetime, 
                           progress_callback: callable = None) -> List[Dict]:
        """Scan all stocks with earnings and return recommended ones."""
        self.logger.info(f"Starting earnings scan for date: {date.strftime('%Y-%m-%d')}")
        earnings_stocks = self.get_earnings_calendar(date)
        recommended_stocks = []
        
        total_stocks = len(earnings_stocks)
        self.logger.info(f"Found {total_stocks} stocks with earnings")
        
        if total_stocks == 0:
            return []
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            future_to_stock = {
                executor.submit(self.analyze_stock, stock): stock 
                for stock in earnings_stocks
            }
            
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
        
        # Sort recommendations by type and timing
        recommended_stocks.sort(key=lambda x: (
            x['recommendation'] != 'Recommended',  # Recommended first
            x['earnings_time'] == 'Unknown',      # Known times first
            x['earnings_time'],                   # Then by timing
            x['ticker']                          # Then by ticker
        ))
        
        self.logger.info(f"Scan completed. Found {len(recommended_stocks)} recommended stocks")
        return recommended_stocks
    
    def analyze_stock(self, ticker: str) -> Optional[Dict]:
        """Analyze a single stock and return if recommended."""
        try:
            self.logger.debug(f"Analyzing stock: {ticker}")
            result = self.analyzer.compute_recommendation(ticker)
            
            if isinstance(result, dict):
                avg_volume_bool = result['avg_volume']
                iv30_rv30_bool = result['iv30_rv30']
                ts_slope_bool = result['ts_slope_0_45']
                
                # Only include if it's recommended or worth considering
                if (ts_slope_bool and 
                    (avg_volume_bool or iv30_rv30_bool)):
                    
                    earnings_time = self.get_earnings_time(ticker)
                    
                    analysis_result = {
                        'ticker': ticker,
                        'recommendation': 'Recommended' if (avg_volume_bool and iv30_rv30_bool and ts_slope_bool) else 'Consider',
                        'expected_move': result['expected_move'],
                        'current_price': result['underlying_price'],
                        'earnings_time': earnings_time,
                        'historical_volatility': result['historical_volatility'],
                        'term_structure_slope': result['term_structure_slope'],
                        'avg_volume': avg_volume_bool,
                        'iv30_rv30': iv30_rv30_bool,
                        'ts_slope_0_45': ts_slope_bool
                    }
                    
                    self.logger.debug(f"Analysis completed for {ticker}: {analysis_result['recommendation']}")
                    return analysis_result
            
            self.logger.debug(f"Stock {ticker} did not meet criteria")
            return None
        except Exception as e:
            self.logger.error(f"Error in analyze_stock for {ticker}: {str(e)}")
            return None

    def reset_debug_info(self):
        """Reset debug information and clear any cached data."""
        self.debug_info = {}
        self.earnings_times = {}
        self.logger.info("Debug info and earnings times cache reset")
    
    def __init__(self, options_analyzer: OptionsAnalyzer):
        self.analyzer = options_analyzer
        self.debug_info = {}
        self.earnings_times = {}
        self._initialize_logging()
    
    def _initialize_logging(self):
        """Initialize logging for the scanner."""
        self.logger = logging.getLogger('EarningsScanner')
        self.logger.setLevel(logging.DEBUG)
        
        if not self.logger.handlers:
            fh = logging.FileHandler('earnings_scanner_debug.log')
            fh.setLevel(logging.DEBUG)
            formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            fh.setFormatter(formatter)
            self.logger.addHandler(fh)
    
    def get_earnings_time(self, ticker: str) -> str:
        """Get earnings timing from Yahoo Finance."""
        try:
            stock = yf.Ticker(ticker)
            calendar = stock.calendar
            
            if calendar is not None and not calendar.empty:
                # Get the earnings timestamp
                earnings_timestamp = calendar.iloc[0].get('Earnings Date')
                
                if isinstance(earnings_timestamp, pd.Timestamp):
                    hour = earnings_timestamp.hour
                    
                    # Yahoo Finance typically uses these time slots:
                    # BMO (Before Market Open): Usually around 7:00-8:00 AM
                    # AMC (After Market Close): Usually around 16:00-17:00 (4:00-5:00 PM)
                    if hour < 12:  # Morning
                        return 'Pre Market'
                    elif hour >= 16:  # After 4 PM
                        return 'Post Market'
                    else:
                        return 'During Market'
                
                self.logger.debug(f"No timestamp found in calendar for {ticker}")
            else:
                self.logger.debug(f"No calendar data found for {ticker}")
            
            return 'Unknown'
            
        except Exception as e:
            self.logger.error(f"Error getting YF earnings time for {ticker}: {str(e)}")
            return 'Unknown'
    
    def get_earnings_calendar(self, date: datetime) -> List[str]:
        """Get earnings calendar for a specific date using Yahoo Finance."""
        try:
            date_str = date.strftime('%Y-%m-%d')
            self.logger.info(f"Fetching earnings calendar for date: {date_str}")
            
            # Initialize earnings dictionary
            self.earnings_times = {}
            
            # Get list of stocks with earnings
            calendar = pd.read_html('https://finance.yahoo.com/calendar/earnings?day=' + date_str)[0]
            
            # Process the calendar data
            symbols = []
            for _, row in calendar.iterrows():
                symbol = row['Symbol']
                if isinstance(symbol, str):  # Ensure symbol is a string
                    symbols.append(symbol)
                    # Get detailed timing information
                    timing = self.get_earnings_time(symbol)
                    self.earnings_times[symbol] = timing
            
            self.logger.info(f"Successfully retrieved {len(symbols)} symbols")
            self.debug_info = {
                "date": date_str,
                "symbols_found": len(symbols),
                "last_update": datetime.now().isoformat()
            }
            
            return symbols
            
        except Exception as e:
            self.logger.error(f"Error in get_earnings_calendar: {str(e)}")
            self.debug_info = {
                "date": date_str,
                "error": str(e),
                "last_update": datetime.now().isoformat()
            }
            return []
    
    def get_debug_status(self) -> Dict:
        """Get the current debug status and latest API interaction details."""
        return {
            "last_debug_info": self.debug_info,
            "earnings_times_count": len(self.earnings_times),
            "last_update": self.debug_info.get("last_update")
        }
    
    def scan_earnings_stocks(self, date: datetime, 
                           progress_callback: callable = None) -> List[Dict]:
        """Scan all stocks with earnings and return recommended ones."""
        self.logger.info(f"Starting earnings scan for date: {date.strftime('%Y-%m-%d')}")
        earnings_stocks = self.get_earnings_calendar(date)
        recommended_stocks = []
        
        total_stocks = len(earnings_stocks)
        self.logger.info(f"Found {total_stocks} stocks with earnings")
        
        if total_stocks == 0:
            return []
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            future_to_stock = {
                executor.submit(self.analyze_stock, stock): stock 
                for stock in earnings_stocks
            }
            
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
        
        self.logger.info(f"Scan completed. Found {len(recommended_stocks)} recommended stocks")
        return recommended_stocks
    
    def analyze_stock(self, ticker: str) -> Optional[Dict]:
        """Analyze a single stock and return if recommended."""
        try:
            self.logger.debug(f"Analyzing stock: {ticker}")
            result = self.analyzer.compute_recommendation(ticker)
            
            if isinstance(result, dict):
                avg_volume_bool = result['avg_volume']
                iv30_rv30_bool = result['iv30_rv30']
                ts_slope_bool = result['ts_slope_0_45']
                
                # Only include if it's recommended or worth considering
                if (ts_slope_bool and 
                    (avg_volume_bool or iv30_rv30_bool)):
                    
                    earnings_time = self.get_earnings_time(ticker)
                    
                    analysis_result = {
                        'ticker': ticker,
                        'recommendation': 'Recommended' if (avg_volume_bool and iv30_rv30_bool and ts_slope_bool) else 'Consider',
                        'expected_move': result['expected_move'],
                        'current_price': result['underlying_price'],
                        'earnings_time': earnings_time,
                        'historical_volatility': result['historical_volatility'],
                        'term_structure_slope': result['term_structure_slope'],
                        'avg_volume': avg_volume_bool,
                        'iv30_rv30': iv30_rv30_bool,
                        'ts_slope_0_45': ts_slope_bool
                    }
                    
                    self.logger.debug(f"Analysis completed for {ticker}: {analysis_result['recommendation']}")
                    return analysis_result
            
            self.logger.debug(f"Stock {ticker} did not meet criteria")
            return None
        except Exception as e:
            self.logger.error(f"Error in analyze_stock for {ticker}: {str(e)}")
            return None

    def reset_debug_info(self):
        """Reset debug information and clear any cached data."""
        self.debug_info = {}
        self.earnings_times = {}
        self.logger.info("Debug info and earnings times cache reset")
    """Scanner for finding recommended stocks with upcoming earnings."""
    
    def __init__(self, options_analyzer: OptionsAnalyzer):
        self.analyzer = options_analyzer
        self.debug_info = {}
        self.earnings_times = {}
        self._initialize_logging()
    
    def _initialize_logging(self):
        """Initialize logging for the scanner."""
        self.logger = logging.getLogger('EarningsScanner')
        self.logger.setLevel(logging.DEBUG)
        
        # Create file handler
        fh = logging.FileHandler('earnings_scanner_debug.log')
        fh.setLevel(logging.DEBUG)
        
        # Create formatter
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        fh.setFormatter(formatter)
        
        # Add handler to logger if it doesn't already have one
        if not self.logger.handlers:
            self.logger.addHandler(fh)
    
    def get_earnings_time(self, ticker: str) -> str:
        """Get whether earnings is pre or post market."""
        return self.earnings_times.get(ticker, 'Unknown')
    
    def get_earnings_calendar(self, date: datetime) -> List[str]:
        """Get all stocks with earnings on the specified date from NASDAQ."""
        try:
            date_str = date.strftime('%Y-%m-%d')
            self.logger.info(f"Fetching earnings calendar for date: {date_str}")
            
            headers = {
                "Accept": "application/json, text/plain, */*",
                "Accept-Encoding": "gzip, deflate, br",
                "Accept-Language": "en-US,en;q=0.9",
                "Origin": "https://www.nasdaq.com",
                "Referer": "https://www.nasdaq.com",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            }

            url = 'https://api.nasdaq.com/api/calendar/earnings'
            payload = {"date": date_str}
            
            try:
                response = requests.get(url=url, headers=headers, params=payload, verify=True, timeout=10)
                
                self.debug_info = {
                    "last_request_time": datetime.now().isoformat(),
                    "status_code": response.status_code,
                    "response_headers": dict(response.headers),
                    "url": url,
                    "request_headers": headers,
                    "payload": payload
                }
                
                if response.status_code == 403:
                    self.logger.error("NASDAQ API access forbidden (403). Possible rate limiting or IP blocking.")
                    self.debug_info["error"] = "API access forbidden"
                    return []
                
                data = response.json()
                
                # Extract symbols and timing from the response
                earnings_data = data.get('data', {}).get('rows', [])
                symbols = []
                self.earnings_times = {}
                
                for row in earnings_data:
                    symbol = row.get('symbol')
                    if symbol:
                        symbols.append(symbol)
                        # Handle various time formats that might appear in the API
                        time = str(row.get('time', '')).lower()
                        if any(pre in time for pre in ['pre', 'before', 'morning', 'am', 'bmo']):
                            self.earnings_times[symbol] = 'Pre Market'
                        elif any(post in time for post in ['post', 'after', 'afternoon', 'pm', 'amc']):
                            self.earnings_times[symbol] = 'Post Market'
                        elif 'during' in time or 'market' in time:
                            self.earnings_times[symbol] = 'During Market'
                        else:
                            # Log the unrecognized time format for debugging
                            self.logger.debug(f"Unrecognized time format for {symbol}: {time}")
                            self.earnings_times[symbol] = 'Unknown'
                
                self.logger.info(f"Successfully retrieved {len(symbols)} symbols")
                self.debug_info["symbols_count"] = len(symbols)
                return symbols
                
            except requests.exceptions.Timeout:
                self.logger.error("Request timed out")
                self.debug_info["error"] = "Request timeout"
                return []
            except requests.exceptions.RequestException as e:
                self.logger.error(f"Request failed: {str(e)}")
                self.debug_info["error"] = f"Request failed: {str(e)}"
                return []
            except ValueError as e:  # JSON decode error
                self.logger.error(f"Failed to parse JSON response: {str(e)}")
                self.debug_info["error"] = f"JSON parse error: {str(e)}"
                return []
                
        except Exception as e:
            self.logger.error(f"Unexpected error in get_earnings_calendar: {str(e)}")
            self.debug_info["error"] = f"Unexpected error: {str(e)}"
            return []
    
    def get_debug_status(self) -> Dict:
        """Get the current debug status and latest API interaction details."""
        return {
            "last_debug_info": self.debug_info,
            "is_blocked": self.debug_info.get("status_code") == 403,
            "last_error": self.debug_info.get("error"),
            "symbols_found": self.debug_info.get("symbols_count", 0),
            "earnings_times_count": len(self.earnings_times)
        }
    
    def scan_earnings_stocks(self, date: datetime, 
                           progress_callback: callable = None) -> List[Dict]:
        """Scan all stocks with earnings and return recommended ones."""
        self.logger.info(f"Starting earnings scan for date: {date.strftime('%Y-%m-%d')}")
        earnings_stocks = self.get_earnings_calendar(date)
        recommended_stocks = []
        
        total_stocks = len(earnings_stocks)
        self.logger.info(f"Found {total_stocks} stocks with earnings")
        
        if total_stocks == 0:
            return []
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            future_to_stock = {
                executor.submit(self.analyze_stock, stock): stock 
                for stock in earnings_stocks
            }
            
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
        
        self.logger.info(f"Scan completed. Found {len(recommended_stocks)} recommended stocks")
        return recommended_stocks
    
    def analyze_stock(self, ticker: str) -> Optional[Dict]:
        """Analyze a single stock and return if recommended."""
        try:
            self.logger.debug(f"Analyzing stock: {ticker}")
            result = self.analyzer.compute_recommendation(ticker)
            
            if isinstance(result, dict):
                avg_volume_bool = result['avg_volume']
                iv30_rv30_bool = result['iv30_rv30']
                ts_slope_bool = result['ts_slope_0_45']
                
                # Only include if it's recommended or worth considering
                if (ts_slope_bool and 
                    (avg_volume_bool or iv30_rv30_bool)):
                    
                    earnings_time = self.get_earnings_time(ticker)
                    
                    analysis_result = {
                        'ticker': ticker,
                        'recommendation': 'Recommended' if (avg_volume_bool and iv30_rv30_bool and ts_slope_bool) else 'Consider',
                        'expected_move': result['expected_move'],
                        'current_price': result['underlying_price'],
                        'earnings_time': earnings_time,
                        'historical_volatility': result['historical_volatility'],
                        'term_structure_slope': result['term_structure_slope'],
                        'avg_volume': avg_volume_bool,
                        'iv30_rv30': iv30_rv30_bool,
                        'ts_slope_0_45': ts_slope_bool
                    }
                    
                    self.logger.debug(f"Analysis completed for {ticker}: {analysis_result['recommendation']}")
                    return analysis_result
            
            self.logger.debug(f"Stock {ticker} did not meet criteria")
            return None
        except Exception as e:
            self.logger.error(f"Error in analyze_stock for {ticker}: {str(e)}")
            return None

    def reset_debug_info(self):
        """Reset debug information and clear any cached data."""
        self.debug_info = {}
        self.earnings_times = {}
        self.logger.info("Debug info and earnings times cache reset")
    """Scanner for finding recommended stocks with upcoming earnings."""
    
    def __init__(self, options_analyzer: OptionsAnalyzer):
        self.analyzer = options_analyzer
        self.debug_info = {}
        self._initialize_logging()
    
    def _initialize_logging(self):
        """Initialize logging for the scanner."""
        # Create logger
        self.logger = logging.getLogger('EarningsScanner')
        self.logger.setLevel(logging.DEBUG)
        
        # Create file handler
        fh = logging.FileHandler('earnings_scanner_debug.log')
        fh.setLevel(logging.DEBUG)
        
        # Create formatter
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        fh.setFormatter(formatter)
        
        # Add handler to logger
        self.logger.addHandler(fh)
    
    def get_earnings_time(self, ticker: str) -> str:
        """Get whether earnings is pre or post market."""
        return self.earnings_times.get(ticker, 'Unknown')
    
    def get_earnings_calendar(self, date: datetime) -> List[str]:
        """Get all stocks with earnings on the specified date from NASDAQ."""
        try:
            date_str = date.strftime('%Y-%m-%d')
            self.logger.info(f"Fetching earnings calendar for date: {date_str}")
            
            headers = {
                "Accept": "application/json, text/plain, */*",
                "Accept-Encoding": "gzip, deflate, br",
                "Accept-Language": "en-US,en;q=0.9",
                "Origin": "https://www.nasdaq.com",
                "Referer": "https://www.nasdaq.com",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            }

            url = 'https://api.nasdaq.com/api/calendar/earnings'
            payload = {"date": date_str}
            
            # Log request details
            self.logger.debug(f"Request URL: {url}")
            self.logger.debug(f"Request headers: {headers}")
            self.logger.debug(f"Request payload: {payload}")
            
            try:
                response = requests.get(url=url, headers=headers, params=payload, verify=True, timeout=10)
                
                # Store debug information
                self.debug_info = {
                    "last_request_time": datetime.now().isoformat(),
                    "status_code": response.status_code,
                    "response_headers": dict(response.headers),
                    "url": url,
                    "request_headers": headers,
                    "payload": payload
                }
                
                self.logger.info(f"Response status code: {response.status_code}")
                self.logger.debug(f"Response headers: {dict(response.headers)}")
                
                if response.status_code == 403:
                    self.logger.error("NASDAQ API access forbidden (403). Possible rate limiting or IP blocking.")
                    self.debug_info["error"] = "API access forbidden"
                    return []
                
                data = response.json()
                
                # Extract symbols from the response
                earnings_data = data.get('data', {}).get('rows', [])
                symbols = [row.get('symbol') for row in earnings_data if row.get('symbol')]
                
                # Store market session information
                self.earnings_times = {
                    row.get('symbol'): 'Pre Market' if row.get('time') == 'Pre-market' 
                                      else 'Post Market' if row.get('time') == 'After-market' 
                                      else 'Unknown'
                    for row in earnings_data if row.get('symbol')
                }
                
                self.logger.info(f"Successfully retrieved {len(symbols)} symbols")
                self.debug_info["symbols_count"] = len(symbols)
                return symbols
                
            except requests.exceptions.Timeout:
                self.logger.error("Request timed out")
                self.debug_info["error"] = "Request timeout"
                return []
            except requests.exceptions.RequestException as e:
                self.logger.error(f"Request failed: {str(e)}")
                self.debug_info["error"] = f"Request failed: {str(e)}"
                return []
            except ValueError as e:  # JSON decode error
                self.logger.error(f"Failed to parse JSON response: {str(e)}")
                self.debug_info["error"] = f"JSON parse error: {str(e)}"
                return []
                
        except Exception as e:
            self.logger.error(f"Unexpected error in get_earnings_calendar: {str(e)}")
            self.debug_info["error"] = f"Unexpected error: {str(e)}"
            return []
    
    def get_debug_status(self) -> Dict:
        """Get the current debug status and latest API interaction details."""
        return {
            "last_debug_info": self.debug_info,
            "is_blocked": self.debug_info.get("status_code") == 403,
            "last_error": self.debug_info.get("error"),
            "symbols_found": self.debug_info.get("symbols_count", 0)
        }
    
    def scan_earnings_stocks(self, date: datetime, 
                           progress_callback: callable = None) -> List[Dict]:
        """Scan all stocks with earnings and return recommended ones."""
        earnings_stocks = self.get_earnings_calendar(date)
        recommended_stocks = []
        
        total_stocks = len(earnings_stocks)
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            future_to_stock = {
                executor.submit(self.analyze_stock, stock): stock 
                for stock in earnings_stocks
            }
            
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
                except Exception as e:
                    self.logger.error(f"Error analyzing {stock}: {str(e)}")
        
        return recommended_stocks
    
    def analyze_stock(self, ticker: str) -> Optional[Dict]:
        """Analyze a single stock and return if recommended."""
        try:
            result = self.analyzer.compute_recommendation(ticker)
            
            if isinstance(result, dict):
                avg_volume_bool = result['avg_volume']
                iv30_rv30_bool = result['iv30_rv30']
                ts_slope_bool = result['ts_slope_0_45']
                
                # Only include if it's recommended or worth considering
                if (ts_slope_bool and 
                    (avg_volume_bool or iv30_rv30_bool)):
                    
                    earnings_time = self.get_earnings_time(ticker)
                    
                    return {
                        'ticker': ticker,
                        'recommendation': 'Recommended' if (avg_volume_bool and iv30_rv30_bool and ts_slope_bool) else 'Consider',
                        'expected_move': result['expected_move'],
                        'current_price': result['underlying_price'],
                        'earnings_time': earnings_time,
                        **result
                    }
            
            return None
        except Exception as e:
            self.logger.error(f"Error in analyze_stock for {ticker}: {str(e)}")
            return None

def create_gui():
    """Create enhanced GUI with earnings scanner and debug capabilities."""
    analyzer = OptionsAnalyzer()
    scanner = EarningsScanner(analyzer)
    
    main_layout = [
        [sg.Text("Enter Stock Symbol:"), sg.Input(key="stock", size=(20, 1))],
        [sg.Button("Submit", bind_return_key=True), sg.Button("Exit")],
        [sg.Text("Or scan earnings stocks:")],
        [sg.CalendarButton('Choose Date', target='earnings_date', format='%Y-%m-%d'),
         sg.Input(key='earnings_date', size=(20, 1), disabled=True),
         sg.Button("Scan Earnings"),
         sg.Button("Check API Status")],  # New debug button
        [sg.Text("", key="recommendation", size=(50, 1))],
        [sg.Text("API Status:", key="api_status", text_color="blue", visible=False)]  # Status display
    ]
    
    window = sg.Window("Options Analysis Tool", main_layout)
    
    while True:
        event, values = window.read()
        if event in (sg.WINDOW_CLOSED, "Exit"):
            break
            
        if event == "Check API Status":
            # Get the debug status
            debug_status = scanner.get_debug_status()
            
            if not debug_status.get("last_debug_info"):
                status_text = "No API calls made yet. Try scanning earnings first."
                color = "blue"
            elif debug_status.get("is_blocked"):
                status_text = "❌ API is currently blocking requests (403 Forbidden)"
                color = "red"
            elif debug_status.get("last_error"):
                status_text = f"⚠️ Last API call had error: {debug_status['last_error']}"
                color = "orange"
            else:
                status_text = f"✓ API working (Found {debug_status['symbols_found']} symbols in last call)"
                color = "green"
            
            window["api_status"].update(status_text, text_color=color, visible=True)
        
        elif event == "Submit":
            window["recommendation"].update("")
            stock = values.get("stock", "")
            
            loading_layout = [[sg.Text("Loading...", key="loading", justification="center")]]
            loading_window = sg.Window("Loading", loading_layout, modal=True, finalize=True, size=(275, 200))
            
            result_holder = {}
            
            def worker():
                try:
                    result = analyzer.compute_recommendation(stock)
                    result_holder['result'] = result
                except Exception as e:
                    result_holder['error'] = str(e)
            
            thread = threading.Thread(target=worker, daemon=True)
            thread.start()
            
            while thread.is_alive():
                event_load, _ = loading_window.read(timeout=100)
                if event_load == sg.WINDOW_CLOSED:
                    break
            thread.join(timeout=1)
            
            loading_window.close()
            
            if 'error' in result_holder:
                window["recommendation"].update(f"Error: {result_holder['error']}")
            elif 'result' in result_holder:
                result = result_holder['result']
                
                if isinstance(result, str):  # Error message
                    window["recommendation"].update(result)
                    continue
                
                avg_volume_bool = result['avg_volume']
                iv30_rv30_bool = result['iv30_rv30']
                ts_slope_bool = result['ts_slope_0_45']
                expected_move = result['expected_move']
                
                if avg_volume_bool and iv30_rv30_bool and ts_slope_bool:
                    title = "Recommended"
                    title_color = "#006600"
                elif ts_slope_bool and ((avg_volume_bool and not iv30_rv30_bool) or (iv30_rv30_bool and not avg_volume_bool)):
                    title = "Consider"
                    title_color = "#ff9900"
                else:
                    title = "Avoid"
                    title_color = "#800000"
                
                result_layout = [
                    [sg.Text(title, text_color=title_color, font=("Helvetica", 16))],
                    [sg.Text(f"avg_volume: {'PASS' if avg_volume_bool else 'FAIL'}", 
                            text_color="#006600" if avg_volume_bool else "#800000")],
                    [sg.Text(f"iv30_rv30: {'PASS' if iv30_rv30_bool else 'FAIL'}", 
                            text_color="#006600" if iv30_rv30_bool else "#800000")],
                    [sg.Text(f"ts_slope_0_45: {'PASS' if ts_slope_bool else 'FAIL'}", 
                            text_color="#006600" if ts_slope_bool else "#800000")],
                    [sg.Text(f"Expected Move: {expected_move}", text_color="blue")],
                    [sg.Text(f"Current Price: ${result['underlying_price']:.2f}")],
                    [sg.Text(f"Historical Volatility: {result['historical_volatility']:.2%}")],
                    [sg.Text(f"Term Structure Slope: {result['term_structure_slope']:.4f}")],
                    [sg.Button("OK")]
                ]
                
                result_window = sg.Window("Recommendation", result_layout, modal=True, finalize=True, size=(275, 300))
                while True:
                    event_result, _ = result_window.read()
                    if event_result in (sg.WINDOW_CLOSED, "OK"):
                        break
                result_window.close()
        
        elif event == "Scan Earnings":
            window["api_status"].update(visible=False)  # Hide previous status
            try:
                date_str = values.get('earnings_date')
                if not date_str:
                    sg.popup_error("Please select a date first!")
                    continue
                
                date = datetime.strptime(date_str, '%Y-%m-%d')
                
                # Create progress window
                progress_layout = [
                    [sg.Text('Scanning earnings stocks...')],
                    [sg.ProgressBar(100, orientation='h', size=(20, 20), key='progress')]
                ]
                progress_window = sg.Window('Progress', progress_layout, modal=True, finalize=True)
                progress_bar = progress_window['progress']
                
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
                
                # After scan, check and display API status
                debug_status = scanner.get_debug_status()
                if debug_status.get("is_blocked"):
                    window["api_status"].update("❌ NASDAQ API is blocking requests", text_color="red", visible=True)
                elif debug_status.get("last_error"):
                    window["api_status"].update(f"⚠️ API Error: {debug_status['last_error']}", text_color="orange", visible=True)
                
                if result_holder['error']:
                    sg.popup_error(f"Error: {result_holder['error']}")
                else:
                    stocks = result_holder['stocks']
                    if not stocks:
                        sg.popup_info("No recommended stocks found for this date.")
                        continue
                    
                    # Create results window with expanded information
                    headers = ['Ticker', 'Recommendation', 'Expected Move', 'Price', 'Earnings Time', 
                             'Avg Volume', 'IV30/RV30', 'Term Slope', 'Historical Vol', 'Term Structure Slope']
                    # Sort stocks by recommendation ("Recommended" first, then "Consider")
                    sorted_stocks = sorted(stocks, 
                                        key=lambda x: (x['recommendation'] != "Recommended", x['recommendation'] != "Consider"))
                    
                    data = [[
                        stock['ticker'],
                        stock['recommendation'],
                        stock['expected_move'],
                        f"${stock['current_price']:.2f}",
                        stock['earnings_time'],
                        'PASS' if stock['avg_volume'] else 'FAIL',
                        'PASS' if stock['iv30_rv30'] else 'FAIL',
                        'PASS' if stock['ts_slope_0_45'] else 'FAIL',
                        f"{stock['historical_volatility']:.2%}",
                        f"{stock['term_structure_slope']:.4f}"
                    ] for stock in sorted_stocks]
                    
                    results_layout = [
                        [sg.Text(f"Earnings Stocks for {date_str}", font=("Helvetica", 16))],
                        [sg.Table(
                            values=data,
                            headings=headers,
                            auto_size_columns=True,
                            justification='center',
                            key='-TABLE-',
                            enable_events=True
                        )],
                        [sg.Button("Export to CSV"), sg.Button("OK")],
                        [sg.Text("", key="export_status", visible=False)]
                    ]
                    
                    results_window = sg.Window(
                        "Earnings Scan Results", 
                        results_layout,
                        modal=True,
                        finalize=True,
                        resizable=True,
                        size=(800, 600)
                    )
                    
                    while True:
                        event_result, values_result = results_window.read()
                        if event_result in (sg.WINDOW_CLOSED, "OK"):
                            break
                        elif event_result == "Export to CSV":
                            try:
                                # Create CSV filename with date
                                csv_filename = f"earnings_scan_{date_str}.csv"
                                
                                # Prepare data for CSV - include all columns
                                csv_data = [headers]  # Add headers first
                                csv_data.extend(data)
                                
                                # Write to CSV
                                import csv
                                with open(csv_filename, 'w', newline='') as f:
                                    writer = csv.writer(f)
                                    writer.writerows(csv_data)
                                
                                results_window["export_status"].update(
                                    f"✓ Successfully exported to {csv_filename}", 
                                    text_color="green",
                                    visible=True
                                )
                            except Exception as e:
                                results_window["export_status"].update(
                                    f"❌ Export failed: {str(e)}", 
                                    text_color="red",
                                    visible=True
                                )
                    
                    results_window.close()
                
            except Exception as e:
                sg.popup_error(f"Error: {str(e)}")
    
    window.close()

if __name__ == "__main__":
    create_gui()
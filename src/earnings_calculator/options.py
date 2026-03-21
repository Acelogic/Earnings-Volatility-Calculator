"""Options analysis: volatility calculations and recommendation engine."""

import warnings
from datetime import datetime, timedelta
from typing import Dict, List

import numpy as np
import pandas as pd
import yfinance as yf

from earnings_calculator.logging_config import create_logger
from earnings_calculator.proxy import ProxyManager
from earnings_calculator.sessions import SessionManager

NUMPY_VERSION = tuple(map(int, np.__version__.split(".")[:2]))
IS_NUMPY_2 = NUMPY_VERSION[0] >= 2

FILTER_MAX_DTE = 45
IV_INTERPOLATION_DTE = 30
MIN_AVG_VOLUME = 1_500_000


class OptionsAnalyzer:
    def __init__(self, proxy_manager=None):
        self.warnings_shown = False
        self.proxy_manager = proxy_manager or ProxyManager()
        self.session_manager = SessionManager(self.proxy_manager)
        self.logger = create_logger("OptionsAnalyzer", "options_analyzer_debug.log")

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
        t = yf.Ticker(symbol, session=self.session_manager.get_yf_session())
        return t

    def filter_dates(self, dates: List[str]) -> List[str]:
        today = datetime.today().date()
        cutoff = today + timedelta(days=FILTER_MAX_DTE)
        sdates = sorted(datetime.strptime(d, "%Y-%m-%d").date() for d in dates)
        # Filter out today's date (0-DTE) before processing
        filtered = [d for d in sdates if d > today]
        if not filtered:
            # Fall back to original unfiltered list if filtering removes all dates
            filtered = sdates
        arr = []
        for i, d in enumerate(filtered):
            if d >= cutoff:
                arr = [x.strftime("%Y-%m-%d") for x in filtered[: i + 1]]
                break
        if arr:
            return arr
        else:
            return [x.strftime("%Y-%m-%d") for x in filtered]

    def yang_zhang_volatility(
        self,
        pdf: pd.DataFrame,
        window=30,
        trading_periods=252,
        return_last_only=True,
    ):
        try:
            log_ho = self.safe_log(pdf["High"] / pdf["Open"])
            log_lo = self.safe_log(pdf["Low"] / pdf["Open"])
            log_co = self.safe_log(pdf["Close"] / pdf["Open"])
            log_oc = self.safe_log(pdf["Open"] / pdf["Close"].shift(1))
            log_oc_sq = log_oc**2
            log_cc = self.safe_log(pdf["Close"] / pdf["Close"].shift(1))
            log_cc_sq = log_cc**2
            rs = log_ho * (log_ho - log_co) + log_lo * (log_lo - log_co)
            close_vol = log_cc_sq.rolling(window=window).sum() / (window - 1.0)
            open_vol = log_oc_sq.rolling(window=window).sum() / (window - 1.0)
            rs_ = rs.rolling(window=window).sum() / (window - 1.0)
            k = 0.34 / (1.34 + (window + 1) / (window - 1))
            out = self.safe_sqrt(
                open_vol + k * close_vol + (1 - k) * rs_
            ) * self.safe_sqrt(trading_periods)
            if return_last_only:
                return out.iloc[-1]
            else:
                return out.dropna()
        except Exception as e:
            if not self.warnings_shown:
                warnings.warn(f"Error in Yang-Zhang: {e}")
                self.warnings_shown = True
            return self.calculate_simple_volatility(
                pdf, window, trading_periods, return_last_only
            )

    def calculate_simple_volatility(
        self,
        pdf: pd.DataFrame,
        window=30,
        trading_periods=252,
        return_last_only=True,
    ):
        try:
            rets = pdf["Close"].pct_change().dropna()
            vol = rets.rolling(window=window).std() * np.sqrt(trading_periods)
            if return_last_only:
                return vol.iloc[-1]
            return vol
        except Exception as e:
            warnings.warn(f"Error in fallback volatility: {e}")
            return np.nan

    def compute_atr(self, pdf: pd.DataFrame, window=14):
        """Compute Average True Range over the given window."""
        high = pdf["High"]
        low = pdf["Low"]
        close = pdf["Close"]
        prev_close = close.shift(1)
        tr = pd.concat(
            [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
        ).max(axis=1)
        atr = tr.rolling(window=window, min_periods=window).mean()
        return atr.iloc[-1] if not atr.empty else np.nan

    def build_term_structure(self, days: List[int], ivs: List[float]) -> callable:
        try:
            from scipy.interpolate import interp1d

            da = np.array(days)
            va = np.array(ivs)
            idx = da.argsort()
            da, va = da[idx], va[idx]
            f = interp1d(da, va, kind="linear", fill_value="extrapolate")

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
                td = ticker.history(period="1d")
                if td.empty:
                    raise ValueError("No price data for 1d.")
                if "Close" in td.columns:
                    return td["Close"].iloc[-1]
                elif "Adj Close" in td.columns:
                    return td["Adj Close"].iloc[-1]
                else:
                    raise ValueError("No Close or Adj Close data found.")
            except Exception as e:
                if attempt < 2:
                    self.logger.warning(
                        f"Failed to get price: {e}. Rotating proxy."
                    )
                    self.session_manager.rotate_session()
                    ticker.session = self.session_manager.get_yf_session()
                else:
                    raise ValueError(f"Cannot get price: {e}")

    def compute_recommendation(self, symbol: str, history_data: pd.DataFrame = None) -> Dict:
        for attempt in range(3):
            try:
                s = symbol.strip().upper()
                if not s:
                    return {"error": "No symbol provided."}
                t = self.get_ticker(s)
                if not t.options:
                    return {"error": f"No options for {s}."}
                exps = list(t.options)
                exps = self.filter_dates(exps)
                oc = {}
                for e in exps:
                    try:
                        oc[e] = t.option_chain(e)
                    except Exception as ex_:
                        self.logger.warning(
                            f"Couldn't get chain {e} for {s}: {ex_}"
                        )
                        self.session_manager.rotate_session()
                        t.session = self.session_manager.get_yf_session()
                        oc[e] = t.option_chain(e)
                # Use passed-in history or fetch once for all derived metrics
                if history_data is not None and not history_data.empty:
                    h3 = history_data
                else:
                    h3 = t.history(period="3mo")
                # Extract current price from history to avoid a redundant API call
                up = h3["Close"].iloc[-1]
                tv = h3["Volume"].iloc[-1] if not h3.empty else 0
                atm_ivs = {}
                stprice = None
                fi_iv = None
                i = 0
                for e, chain in oc.items():
                    calls, puts = chain.calls, chain.puts
                    if calls.empty or puts.empty:
                        continue
                    call_idx = (calls["strike"] - up).abs().idxmin()
                    put_idx = (puts["strike"] - up).abs().idxmin()
                    civ = calls.loc[call_idx, "impliedVolatility"]
                    piv = puts.loc[put_idx, "impliedVolatility"]
                    av = (civ + piv) / 2
                    atm_ivs[e] = av
                    if i == 0:
                        cbid = calls.loc[call_idx, "bid"]
                        cask = calls.loc[call_idx, "ask"]
                        pbid = puts.loc[put_idx, "bid"]
                        pask = puts.loc[put_idx, "ask"]
                        if (
                            cbid
                            and cask
                            and cbid > 0
                            and cask > 0
                            and pbid
                            and pask
                            and pbid > 0
                            and pask > 0
                        ):
                            midc = (cbid + cask) / 2
                            midp = (pbid + pask) / 2
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
                iv30 = spline(IV_INTERPOLATION_DTE)
                d0 = min(ds)
                if d0 == FILTER_MAX_DTE:
                    slope = 0
                else:
                    dden = (FILTER_MAX_DTE - d0) if (FILTER_MAX_DTE - d0) != 0 else 1
                    slope = (spline(FILTER_MAX_DTE) - spline(d0)) / dden
                hv = self.yang_zhang_volatility(h3)
                # IV Rank: compare current IV to rolling 30-day HV range over history
                iv_rank = None
                if fi_iv is not None and len(h3) >= 60:
                    hv_series = self.yang_zhang_volatility(
                        h3, window=30, return_last_only=False
                    )
                    if len(hv_series) >= 2:
                        hv_min = float(hv_series.min())
                        hv_max = float(hv_series.max())
                        if hv_max > hv_min:
                            iv_rank = (fi_iv - hv_min) / (hv_max - hv_min) * 100
                            iv_rank = max(0.0, min(100.0, iv_rank))
                if hv == 0:
                    iv30_rv30 = 9999
                else:
                    iv30_rv30 = iv30 / hv
                avgv = (
                    h3["Volume"].rolling(IV_INTERPOLATION_DTE).mean().dropna().iloc[-1]
                    if not h3.empty
                    else 0
                )
                if stprice and up != 0:
                    exmo = f"{round(stprice / up * 100, 2)}%"
                else:
                    exmo = "N/A"
                atr14 = self.compute_atr(h3, window=14) if not h3.empty else 0
                atr14_pct = (atr14 / up) * 100 if up else 0
                return {
                    "avg_volume": avgv >= MIN_AVG_VOLUME,
                    "avg_volume_value": avgv,
                    "iv30_rv30": iv30_rv30,
                    "term_slope": slope,
                    "term_structure": iv30,
                    "expected_move": exmo,
                    "underlying_price": up,
                    "historical_volatility": hv,
                    "current_iv": fi_iv,
                    "atr14": atr14,
                    "atr14_pct": atr14_pct,
                    "iv_rank": iv_rank,
                }
            except Exception as e:
                if attempt < 2:
                    self.logger.warning(
                        f"Attempt {attempt} for {symbol} failed: {e}. Rotating proxy."
                    )
                    self.session_manager.rotate_session()
                else:
                    self.logger.error(
                        f"All attempts for {symbol} failed: {str(e)}"
                    )
                    return {"error": f"Err: {e}"}

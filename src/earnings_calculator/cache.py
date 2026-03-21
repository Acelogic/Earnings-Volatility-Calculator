"""Pickle-based analysis cache with expiry and missing-data tracking."""

import os
import pickle
import hashlib
import threading
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from earnings_calculator.logging_config import create_logger


class DataCache:
    def __init__(self, cache_dir="stock_cache"):
        self.cache_dir = cache_dir
        self.cache_expiry_days = 7
        self._lock = threading.Lock()
        self._ensure_cache_dir()
        self.logger = create_logger("DataCache", "cache_debug.log")

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
            if d.get("expected_move") == "N/A":
                mf.append("expected_move")
                is_missing = True
            if d.get("current_iv") is None:
                mf.append("current_iv")
                is_missing = True
            if d.get("term_structure") in [0, "N/A"]:
                mf.append("term_structure")
                is_missing = True
            if is_missing:
                missing.append(
                    {
                        "ticker": d["ticker"],
                        "missing_fields": mf,
                        "earnings_time": d.get("earnings_time", "Unknown"),
                    }
                )
        return missing

    def save_data(self, date: str, tickers: List[str], data: List[Dict]):
        ck = self._get_cache_key(date, tickers)
        cp = self._get_cache_path(ck)
        missing_data = self._identify_missing_data(data)
        cdata = {
            "timestamp": datetime.now(),
            "date": date,
            "tickers": tickers,
            "data": data,
            "missing_data": missing_data,
        }
        with open(cp, "wb") as f:
            pickle.dump(cdata, f)
        if missing_data:
            self.logger.info(f"Saved with {len(missing_data)} missing.")

    def get_data(
        self, date: str, tickers: List[str]
    ) -> Tuple[Optional[List[Dict]], List[Dict]]:
        ck = self._get_cache_key(date, tickers)
        cp = self._get_cache_path(ck)
        if not os.path.exists(cp):
            return None, []
        try:
            with open(cp, "rb") as f:
                c = pickle.load(f)
            age = datetime.now() - c["timestamp"]
            if age.days >= self.cache_expiry_days:
                os.remove(cp)
                return None, []
            return c["data"], c["missing_data"]
        except Exception as e:
            self.logger.error(f"Error reading cache: {e}")
            return None, []

    def update_missing_data(self, date: str, tickers: List[str], new_data: Dict):
        ck = self._get_cache_key(date, tickers)
        cp = self._get_cache_path(ck)
        with self._lock:
            try:
                with open(cp, "rb") as f:
                    c = pickle.load(f)
                for entry in c["data"]:
                    if entry["ticker"] == new_data["ticker"]:
                        for k, v in new_data.items():
                            if (k in entry) and (entry[k] in [None, "N/A", 0]):
                                entry[k] = v
                c["missing_data"] = self._identify_missing_data(c["data"])
                with open(cp, "wb") as f:
                    pickle.dump(c, f)
                self.logger.info(f"Updated cache for {new_data['ticker']}")
            except Exception as e:
                self.logger.error(f"Error updating cache: {e}")

    def clear_expired(self):
        for fn in os.listdir(self.cache_dir):
            if fn.endswith(".pkl"):
                cp = os.path.join(self.cache_dir, fn)
                try:
                    with open(cp, "rb") as f:
                        c = pickle.load(f)
                    age = datetime.now() - c["timestamp"]
                    if age.days >= self.cache_expiry_days:
                        os.remove(cp)
                except Exception:
                    os.remove(cp)

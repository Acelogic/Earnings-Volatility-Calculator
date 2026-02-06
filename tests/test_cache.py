"""Tests for DataCache."""

import os
import pickle
from datetime import datetime, timedelta

import pytest
from freezegun import freeze_time

from earnings_calculator.cache import DataCache


class TestCacheKey:
    def test_deterministic(self, tmp_path):
        cache = DataCache(cache_dir=str(tmp_path / "cache"))
        key1 = cache._get_cache_key("2025-01-15", ["AAPL", "MSFT"])
        key2 = cache._get_cache_key("2025-01-15", ["AAPL", "MSFT"])
        assert key1 == key2

    def test_order_independent(self, tmp_path):
        cache = DataCache(cache_dir=str(tmp_path / "cache"))
        key1 = cache._get_cache_key("2025-01-15", ["AAPL", "MSFT"])
        key2 = cache._get_cache_key("2025-01-15", ["MSFT", "AAPL"])
        assert key1 == key2

    def test_different_dates_differ(self, tmp_path):
        cache = DataCache(cache_dir=str(tmp_path / "cache"))
        key1 = cache._get_cache_key("2025-01-15", ["AAPL"])
        key2 = cache._get_cache_key("2025-01-16", ["AAPL"])
        assert key1 != key2


class TestIdentifyMissingData:
    def test_no_missing(self, tmp_path):
        cache = DataCache(cache_dir=str(tmp_path / "cache"))
        data = [
            {
                "ticker": "AAPL",
                "expected_move": "3.5%",
                "current_iv": 0.35,
                "term_structure": 0.42,
            }
        ]
        assert cache._identify_missing_data(data) == []

    def test_missing_expected_move(self, tmp_path):
        cache = DataCache(cache_dir=str(tmp_path / "cache"))
        data = [
            {
                "ticker": "AAPL",
                "expected_move": "N/A",
                "current_iv": 0.35,
                "term_structure": 0.42,
            }
        ]
        result = cache._identify_missing_data(data)
        assert len(result) == 1
        assert "expected_move" in result[0]["missing_fields"]

    def test_missing_current_iv(self, tmp_path):
        cache = DataCache(cache_dir=str(tmp_path / "cache"))
        data = [
            {
                "ticker": "XYZ",
                "expected_move": "2%",
                "current_iv": None,
                "term_structure": 0.3,
            }
        ]
        result = cache._identify_missing_data(data)
        assert len(result) == 1
        assert "current_iv" in result[0]["missing_fields"]

    def test_missing_term_structure_zero(self, tmp_path):
        cache = DataCache(cache_dir=str(tmp_path / "cache"))
        data = [
            {
                "ticker": "ABC",
                "expected_move": "1%",
                "current_iv": 0.2,
                "term_structure": 0,
            }
        ]
        result = cache._identify_missing_data(data)
        assert len(result) == 1
        assert "term_structure" in result[0]["missing_fields"]

    def test_multiple_missing_fields(self, tmp_path):
        cache = DataCache(cache_dir=str(tmp_path / "cache"))
        data = [
            {
                "ticker": "ALL",
                "expected_move": "N/A",
                "current_iv": None,
                "term_structure": "N/A",
            }
        ]
        result = cache._identify_missing_data(data)
        assert len(result) == 1
        assert len(result[0]["missing_fields"]) == 3


class TestSaveAndGet:
    def test_roundtrip(self, tmp_path):
        cache = DataCache(cache_dir=str(tmp_path / "cache"))
        tickers = ["AAPL", "MSFT"]
        data = [
            {
                "ticker": "AAPL",
                "expected_move": "3%",
                "current_iv": 0.35,
                "term_structure": 0.4,
            },
            {
                "ticker": "MSFT",
                "expected_move": "2%",
                "current_iv": 0.30,
                "term_structure": 0.38,
            },
        ]
        cache.save_data("2025-01-15", tickers, data)
        result, missing = cache.get_data("2025-01-15", tickers)
        assert result is not None
        assert len(result) == 2
        assert result[0]["ticker"] == "AAPL"
        assert missing == []

    def test_cache_miss(self, tmp_path):
        cache = DataCache(cache_dir=str(tmp_path / "cache"))
        result, missing = cache.get_data("2099-01-01", ["NONEXIST"])
        assert result is None
        assert missing == []

    @freeze_time("2025-01-22")
    def test_cache_expiry(self, tmp_path):
        cache = DataCache(cache_dir=str(tmp_path / "cache"))
        tickers = ["AAPL"]
        data = [
            {
                "ticker": "AAPL",
                "expected_move": "3%",
                "current_iv": 0.35,
                "term_structure": 0.4,
            }
        ]
        # Manually write cache with old timestamp
        ck = cache._get_cache_key("2025-01-15", tickers)
        cp = cache._get_cache_path(ck)
        cdata = {
            "timestamp": datetime(2025, 1, 10),  # 12 days old
            "date": "2025-01-15",
            "tickers": tickers,
            "data": data,
            "missing_data": [],
        }
        with open(cp, "wb") as f:
            pickle.dump(cdata, f)

        result, missing = cache.get_data("2025-01-15", tickers)
        assert result is None  # Expired, removed

    def test_corrupt_file_handling(self, tmp_path):
        cache = DataCache(cache_dir=str(tmp_path / "cache"))
        ck = cache._get_cache_key("2025-01-15", ["AAPL"])
        cp = cache._get_cache_path(ck)
        with open(cp, "wb") as f:
            f.write(b"not a pickle")
        result, missing = cache.get_data("2025-01-15", ["AAPL"])
        assert result is None


class TestUpdateMissingData:
    def test_updates_na_fields(self, tmp_path):
        cache = DataCache(cache_dir=str(tmp_path / "cache"))
        tickers = ["AAPL"]
        data = [
            {
                "ticker": "AAPL",
                "expected_move": "N/A",
                "current_iv": None,
                "term_structure": 0.4,
            }
        ]
        cache.save_data("2025-01-15", tickers, data)
        cache.update_missing_data(
            "2025-01-15",
            tickers,
            {"ticker": "AAPL", "expected_move": "3.5%", "current_iv": 0.42},
        )
        result, missing = cache.get_data("2025-01-15", tickers)
        assert result[0]["expected_move"] == "3.5%"
        assert result[0]["current_iv"] == 0.42


class TestClearExpired:
    @freeze_time("2025-01-22")
    def test_removes_expired(self, tmp_path):
        cache = DataCache(cache_dir=str(tmp_path / "cache"))
        # Write an expired entry
        ck = cache._get_cache_key("2025-01-10", ["AAPL"])
        cp = cache._get_cache_path(ck)
        cdata = {
            "timestamp": datetime(2025, 1, 10),
            "date": "2025-01-10",
            "tickers": ["AAPL"],
            "data": [],
            "missing_data": [],
        }
        with open(cp, "wb") as f:
            pickle.dump(cdata, f)

        assert os.path.exists(cp)
        cache.clear_expired()
        assert not os.path.exists(cp)

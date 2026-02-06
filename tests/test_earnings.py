"""Tests for EarningsCalendarFetcher."""

import json
from unittest.mock import patch, MagicMock

from earnings_calculator.calendar import EarningsCalendarFetcher


SAMPLE_HTML = """
<tr>
    <span class="earnCalCompanyName">Apple Inc</span>
    <a class="bold">AAPL</a>
    <span class="genToolTip" data-tooltip="Before market open"></span>
</tr>
<tr>
    <span class="earnCalCompanyName">Microsoft Corp</span>
    <a class="bold">MSFT</a>
    <span class="genToolTip" data-tooltip="After market close"></span>
</tr>
<tr>
    <span class="earnCalCompanyName">Tesla Inc</span>
    <a class="bold">TSLA</a>
    <span class="genToolTip"></span>
</tr>
"""


class TestFetchEarningsData:
    def test_parse_success(self):
        fetcher = EarningsCalendarFetcher()
        mock_resp = MagicMock()
        mock_resp.text = json.dumps({"data": SAMPLE_HTML})
        mock_session = MagicMock()
        mock_session.post.return_value = mock_resp

        with patch.object(
            fetcher.session_manager, "get_session", return_value=mock_session
        ):
            result = fetcher.fetch_earnings_data("2025-01-15")

        assert "AAPL" in result
        assert "MSFT" in result
        assert "TSLA" in result
        assert len(result) == 3

    def test_timing_extraction(self):
        fetcher = EarningsCalendarFetcher()
        mock_resp = MagicMock()
        mock_resp.text = json.dumps({"data": SAMPLE_HTML})
        mock_session = MagicMock()
        mock_session.post.return_value = mock_resp

        with patch.object(
            fetcher.session_manager, "get_session", return_value=mock_session
        ):
            fetcher.fetch_earnings_data("2025-01-15")

        assert fetcher.get_earnings_time("AAPL") == "Pre Market"
        assert fetcher.get_earnings_time("MSFT") == "Post Market"
        assert fetcher.get_earnings_time("TSLA") == "During Market"

    def test_empty_response(self):
        fetcher = EarningsCalendarFetcher()
        mock_resp = MagicMock()
        mock_resp.text = json.dumps({"data": "<table></table>"})
        mock_session = MagicMock()
        mock_session.post.return_value = mock_resp

        with patch.object(
            fetcher.session_manager, "get_session", return_value=mock_session
        ):
            result = fetcher.fetch_earnings_data("2025-01-15")

        assert result == []

    def test_retry_on_error(self):
        fetcher = EarningsCalendarFetcher()
        mock_session = MagicMock()
        mock_session.post.side_effect = [
            Exception("Connection error"),
            Exception("Connection error"),
            Exception("Connection error"),
        ]

        with patch.object(
            fetcher.session_manager, "get_session", return_value=mock_session
        ):
            result = fetcher.fetch_earnings_data("2025-01-15")

        assert result == []

    def test_get_earnings_time_unknown(self):
        fetcher = EarningsCalendarFetcher()
        assert fetcher.get_earnings_time("UNKNOWN") == "Unknown"

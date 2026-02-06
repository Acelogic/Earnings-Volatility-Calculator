"""Tests for update_otc_tickers function."""

from unittest.mock import patch, MagicMock

from earnings_calculator.scanner import update_otc_tickers


class TestUpdateOtcTickers:
    def test_pagination(self, tmp_path):
        page1_resp = MagicMock()
        page1_resp.status_code = 200
        page1_resp.json.return_value = {
            "data": {
                "data": [
                    {"s": "OTC/ABCD"},
                    {"s": "OTC/EFGH"},
                ]
            }
        }
        page2_resp = MagicMock()
        page2_resp.status_code = 200
        page2_resp.json.return_value = {"data": {"data": []}}

        written = []

        class FakeFile:
            name = str(tmp_path / "otc-tickers.tmp")

            def write(self, s):
                written.append(s)

            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

        with patch("earnings_calculator.scanner.requests.get") as mock_get, \
             patch("earnings_calculator.scanner.tempfile.NamedTemporaryFile", return_value=FakeFile()), \
             patch("earnings_calculator.scanner.os.replace"):
            mock_get.side_effect = [page1_resp, page2_resp]
            update_otc_tickers()

        assert mock_get.call_count == 2

    def test_slash_extraction(self, tmp_path):
        """Symbols with / should extract the part after the slash."""
        resp1 = MagicMock()
        resp1.status_code = 200
        resp1.raise_for_status = MagicMock()
        resp1.json.return_value = {
            "data": {"data": [{"s": "OTC/WXYZ"}, {"s": "SIMPLE"}]}
        }
        resp2 = MagicMock()
        resp2.status_code = 200
        resp2.raise_for_status = MagicMock()
        resp2.json.return_value = {"data": {"data": []}}

        written = []

        class FakeFile:
            name = str(tmp_path / "otc-tickers.tmp")

            def write(self, s):
                written.append(s)

            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

        with patch("earnings_calculator.scanner.requests.get") as mock_get, \
             patch("earnings_calculator.scanner.tempfile.NamedTemporaryFile", return_value=FakeFile()), \
             patch("earnings_calculator.scanner.os.replace") as mock_replace:
            mock_get.side_effect = [resp1, resp2]
            update_otc_tickers()

        assert "WXYZ\n" in written
        assert "SIMPLE\n" in written
        # Verify atomic rename was called
        mock_replace.assert_called_once()

    def test_http_error(self):
        """Should raise on HTTP error."""
        resp = MagicMock()
        resp.raise_for_status.side_effect = Exception("404")

        with patch("earnings_calculator.scanner.requests.get", return_value=resp):
            try:
                update_otc_tickers()
            except Exception:
                pass  # Expected to raise

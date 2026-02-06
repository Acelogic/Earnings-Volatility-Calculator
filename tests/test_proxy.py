"""Tests for ProxyManager."""

from unittest.mock import patch, MagicMock

from earnings_calculator.proxy import ProxyManager


class TestFetchSources:
    def test_fetch_proxyscrape_success(self):
        pm = ProxyManager()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "1.2.3.4:8080\n5.6.7.8:3128\n"
        with patch("earnings_calculator.proxy.requests.get", return_value=mock_resp):
            result = pm.fetch_proxyscrape()
        assert len(result) == 2
        assert result[0]["http"] == "http://1.2.3.4:8080"

    def test_fetch_proxyscrape_error(self):
        pm = ProxyManager()
        with patch(
            "earnings_calculator.proxy.requests.get",
            side_effect=Exception("timeout"),
        ):
            result = pm.fetch_proxyscrape()
        assert result == []

    def test_fetch_geonode_success(self):
        pm = ProxyManager()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [{"ip": "10.0.0.1", "port": "8080"}]
        }
        with patch("earnings_calculator.proxy.requests.get", return_value=mock_resp):
            result = pm.fetch_geonode()
        assert len(result) == 1
        assert "10.0.0.1:8080" in result[0]["http"]

    def test_fetch_geonode_empty(self):
        pm = ProxyManager()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": []}
        with patch("earnings_calculator.proxy.requests.get", return_value=mock_resp):
            result = pm.fetch_geonode()
        assert result == []

    def test_fetch_pubproxy_success(self):
        pm = ProxyManager()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [{"ip": "11.0.0.1", "port": "3128"}]
        }
        with patch("earnings_calculator.proxy.requests.get", return_value=mock_resp):
            result = pm.fetch_pubproxy()
        assert len(result) == 1

    def test_fetch_proxylist_download_success(self):
        pm = ProxyManager()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "9.8.7.6:1080\n"
        with patch("earnings_calculator.proxy.requests.get", return_value=mock_resp):
            result = pm.fetch_proxylist_download()
        assert len(result) == 1

    def test_fetch_spys_one_success(self):
        pm = ProxyManager()
        html = (
            '<table><tr class="spy1x"><td>12.0.0.1</td><td>8888</td></tr></table>'
        )
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = html
        with patch("earnings_calculator.proxy.requests.get", return_value=mock_resp):
            result = pm.fetch_spys_one()
        assert len(result) == 1

    def test_fetch_github_speedx_success(self):
        pm = ProxyManager()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "40.50.60.70:8080\n80.90.10.20:3128\n"
        with patch("earnings_calculator.proxy.requests.get", return_value=mock_resp):
            result = pm.fetch_github_speedx()
        assert len(result) == 2
        assert result[0]["http"] == "http://40.50.60.70:8080"

    def test_fetch_github_speedx_error(self):
        pm = ProxyManager()
        with patch(
            "earnings_calculator.proxy.requests.get",
            side_effect=Exception("connection error"),
        ):
            result = pm.fetch_github_speedx()
        assert result == []

    def test_fetch_github_monosans_success(self):
        pm = ProxyManager()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "55.66.77.88:1080\n"
        with patch("earnings_calculator.proxy.requests.get", return_value=mock_resp):
            result = pm.fetch_github_monosans()
        assert len(result) == 1
        assert result[0]["http"] == "http://55.66.77.88:1080"

    def test_fetch_github_monosans_error(self):
        pm = ProxyManager()
        with patch(
            "earnings_calculator.proxy.requests.get",
            side_effect=Exception("timeout"),
        ):
            result = pm.fetch_github_monosans()
        assert result == []

    def test_fetch_github_clarketm_success(self):
        pm = ProxyManager()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "100.200.30.40:9090\n"
        with patch("earnings_calculator.proxy.requests.get", return_value=mock_resp):
            result = pm.fetch_github_clarketm()
        assert len(result) == 1
        assert result[0]["http"] == "http://100.200.30.40:9090"

    def test_fetch_github_clarketm_error(self):
        pm = ProxyManager()
        with patch(
            "earnings_calculator.proxy.requests.get",
            side_effect=Exception("timeout"),
        ):
            result = pm.fetch_github_clarketm()
        assert result == []


class TestValidateProxy:
    def test_validate_success(self):
        pm = ProxyManager()
        proxy = {"http": "http://1.2.3.4:8080", "https": "http://1.2.3.4:8080"}
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '{"origin": "1.2.3.4"}'
        with patch("earnings_calculator.proxy.requests.get", return_value=mock_resp):
            assert pm.validate_proxy(proxy) is True

    def test_validate_timeout(self):
        pm = ProxyManager()
        proxy = {"http": "http://1.2.3.4:8080", "https": "http://1.2.3.4:8080"}
        with patch(
            "earnings_calculator.proxy.requests.get",
            side_effect=Exception("timeout"),
        ):
            assert pm.validate_proxy(proxy) is False

    def test_validate_fallback_to_second_endpoint(self):
        """First endpoint fails, second succeeds."""
        pm = ProxyManager()
        proxy = {"http": "http://1.2.3.4:8080", "https": "http://1.2.3.4:8080"}
        ok_resp = MagicMock()
        ok_resp.status_code = 200
        ok_resp.text = "1.2.3.4"

        def side_effect(url, **kwargs):
            if "httpbin" in url:
                raise Exception("httpbin down")
            return ok_resp

        with patch("earnings_calculator.proxy.requests.get", side_effect=side_effect):
            assert pm.validate_proxy(proxy) is True

    def test_validate_all_endpoints_fail(self):
        """All endpoints fail — proxy is rejected."""
        pm = ProxyManager()
        proxy = {"http": "http://1.2.3.4:8080", "https": "http://1.2.3.4:8080"}
        with patch(
            "earnings_calculator.proxy.requests.get",
            side_effect=Exception("all down"),
        ):
            assert pm.validate_proxy(proxy) is False

    def test_validate_empty_body_rejected(self):
        """HTTP 200 but empty body should not count as valid."""
        pm = ProxyManager()
        proxy = {"http": "http://1.2.3.4:8080", "https": "http://1.2.3.4:8080"}
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "   "
        with patch("earnings_calculator.proxy.requests.get", return_value=mock_resp):
            assert pm.validate_proxy(proxy) is False


class TestProxyPool:
    def test_get_proxy_disabled(self):
        pm = ProxyManager()
        pm.proxy_enabled = False
        assert pm.get_proxy() is None

    def test_get_proxy_empty_pool(self):
        pm = ProxyManager()
        pm.proxy_enabled = True
        pm.proxies = []
        assert pm.get_proxy() is None

    def test_get_proxy_returns_from_pool(self):
        pm = ProxyManager()
        pm.proxy_enabled = True
        pm.proxies = [
            {"http": "http://1.1.1.1:80", "https": "http://1.1.1.1:80"},
        ]
        result = pm.get_proxy()
        assert result is not None
        assert result == pm.current_proxy

    def test_rotate_proxy_disabled(self):
        pm = ProxyManager()
        pm.proxy_enabled = False
        assert pm.rotate_proxy() is None

    def test_rotate_proxy_single(self):
        pm = ProxyManager()
        pm.proxy_enabled = True
        pm.proxies = [{"http": "http://1.1.1.1:80", "https": "http://1.1.1.1:80"}]
        assert pm.rotate_proxy() is None

    def test_rotate_proxy_picks_different(self):
        pm = ProxyManager()
        pm.proxy_enabled = True
        p1 = {"http": "http://1.1.1.1:80", "https": "http://1.1.1.1:80"}
        p2 = {"http": "http://2.2.2.2:80", "https": "http://2.2.2.2:80"}
        pm.proxies = [p1, p2]
        pm.current_proxy = p1
        new = pm.rotate_proxy()
        assert new == p2

    def _mock_all_sources(self, pm, fetch_return=None):
        """Helper to mock all 8 source methods on a ProxyManager."""
        if fetch_return is None:
            fetch_return = []
        source_names = [
            "fetch_proxyscrape",
            "fetch_geonode",
            "fetch_pubproxy",
            "fetch_proxylist_download",
            "fetch_spys_one",
            "fetch_github_speedx",
            "fetch_github_monosans",
            "fetch_github_clarketm",
        ]
        patches = {}
        for name in source_names:
            mock = MagicMock(return_value=fetch_return, __name__=name)
            patches[name] = patch.object(pm, name, mock)
        return patches

    def test_build_valid_proxy_pool(self):
        pm = ProxyManager()
        proxy_data = [
            {"http": "http://1.1.1.1:80", "https": "http://1.1.1.1:80"},
        ]
        patches = self._mock_all_sources(pm)
        # Override proxyscrape to return one proxy
        patches["fetch_proxyscrape"] = patch.object(
            pm,
            "fetch_proxyscrape",
            MagicMock(return_value=proxy_data, __name__="fetch_proxyscrape"),
        )
        ctx_managers = [p for p in patches.values()]
        with ctx_managers[0], ctx_managers[1], ctx_managers[2], ctx_managers[3], \
             ctx_managers[4], ctx_managers[5], ctx_managers[6], ctx_managers[7], \
             patch.object(pm, "validate_proxy", return_value=True):
            pm.build_valid_proxy_pool(max_proxies=5)
        assert len(pm.proxies) == 1

    def test_build_valid_proxy_pool_with_callback(self):
        pm = ProxyManager()
        messages = []
        patches = self._mock_all_sources(pm)
        ctx_managers = [p for p in patches.values()]
        with ctx_managers[0], ctx_managers[1], ctx_managers[2], ctx_managers[3], \
             ctx_managers[4], ctx_managers[5], ctx_managers[6], ctx_managers[7]:
            pm.build_valid_proxy_pool(progress_callback=messages.append)
        assert len(messages) > 0

    def test_cancel_keeps_proxies_found_so_far(self):
        pm = ProxyManager()
        proxies = [
            {"http": f"http://{i}.{i}.{i}.{i}:80", "https": f"http://{i}.{i}.{i}.{i}:80"}
            for i in range(1, 11)
        ]
        call_count = 0

        def slow_validate(proxy):
            nonlocal call_count
            call_count += 1
            if call_count >= 3:
                pm.cancel_validation()
            return True

        patches = self._mock_all_sources(pm)
        patches["fetch_proxyscrape"] = patch.object(
            pm,
            "fetch_proxyscrape",
            MagicMock(return_value=proxies, __name__="fetch_proxyscrape"),
        )
        ctx_managers = [p for p in patches.values()]
        with ctx_managers[0], ctx_managers[1], ctx_managers[2], ctx_managers[3], \
             ctx_managers[4], ctx_managers[5], ctx_managers[6], ctx_managers[7], \
             patch.object(pm, "validate_proxy", side_effect=slow_validate):
            pm.build_valid_proxy_pool(max_proxies=50, concurrency=1)
        # Should have stopped early but kept the valid ones found before cancel
        assert 0 < len(pm.proxies) < 10

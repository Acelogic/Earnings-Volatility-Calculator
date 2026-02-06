"""Proxy fetching, validation, and rotation."""

import random
import threading
import concurrent.futures
from typing import Callable, Dict, List, Optional

import requests
from bs4 import BeautifulSoup

from earnings_calculator.logging_config import create_logger

VALIDATION_TIMEOUT = 4
VALIDATION_ENDPOINTS = [
    "https://httpbin.org/ip",
    "https://api.ipify.org?format=json",
    "https://ifconfig.me/ip",
]
SOURCE_FETCH_CONCURRENCY = 8


class ProxyManager:
    def __init__(self):
        self.proxies: List[Dict[str, str]] = []
        self.current_proxy: Optional[Dict[str, str]] = None
        self.proxy_enabled: bool = False
        self._cancel_event = threading.Event()
        self.logger = create_logger("ProxyManager", "proxy_manager_debug.log")

    def cancel_validation(self) -> None:
        """Signal the validation loop to stop early and keep proxies found so far."""
        self._cancel_event.set()

    # ----- Fetching Proxies from Multiple Sources -----
    def fetch_proxyscrape(self) -> List[Dict[str, str]]:
        try:
            url = (
                "https://api.proxyscrape.com/v2/?request=displayproxies"
                "&protocol=http&timeout=10000&country=all&ssl=all&anonymity=all"
            )
            resp = requests.get(url, timeout=15)
            if resp.status_code == 200:
                lines = [x.strip() for x in resp.text.split("\n") if x.strip()]
                return [
                    {"http": f"http://{line}", "https": f"http://{line}"}
                    for line in lines
                ]
            return []
        except Exception as e:
            self.logger.error(f"Error from Proxyscrape: {e}")
            return []

    def fetch_geonode(self) -> List[Dict[str, str]]:
        try:
            url = (
                "https://proxylist.geonode.com/api/proxy-list?limit=100&page=1"
                "&sort_by=lastChecked&sort_type=desc&protocols=http"
                "&anonymityLevel=elite&anonymityLevel=anonymous"
            )
            resp = requests.get(url, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                proxies = []
                for p in data.get("data", []):
                    ip = p["ip"]
                    port = p["port"]
                    proxies.append(
                        {"http": f"http://{ip}:{port}", "https": f"http://{ip}:{port}"}
                    )
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
                for p in data.get("data", []):
                    ip = p["ip"]
                    port = p["port"]
                    proxies.append(
                        {"http": f"http://{ip}:{port}", "https": f"http://{ip}:{port}"}
                    )
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
                lines = [x.strip() for x in resp.text.split("\n") if x.strip()]
                return [
                    {"http": f"http://{line}", "https": f"http://{line}"}
                    for line in lines
                ]
            return []
        except Exception as e:
            self.logger.error(f"Error from ProxyList.download: {e}")
            return []

    def fetch_spys_one(self) -> List[Dict[str, str]]:
        try:
            url = "https://spys.one/free-proxy-list/ALL/"
            headers = {"User-Agent": "Mozilla/5.0"}
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                rows = soup.find_all("tr", class_=["spy1x", "spy1xx"])
                proxies = []
                for r in rows:
                    cols = r.find_all("td")
                    if len(cols) >= 2:
                        ip = cols[0].text.strip()
                        port = cols[1].text.strip()
                        proxies.append(
                            {
                                "http": f"http://{ip}:{port}",
                                "https": f"http://{ip}:{port}",
                            }
                        )
                return proxies
            return []
        except Exception as e:
            self.logger.error(f"Error from Spys.one: {e}")
            return []

    def fetch_github_speedx(self) -> List[Dict[str, str]]:
        try:
            url = (
                "https://raw.githubusercontent.com/TheSpeedX/PROXY-List"
                "/master/http.txt"
            )
            resp = requests.get(url, timeout=15)
            if resp.status_code == 200:
                lines = [x.strip() for x in resp.text.split("\n") if x.strip()]
                return [
                    {"http": f"http://{line}", "https": f"http://{line}"}
                    for line in lines
                ]
            return []
        except Exception as e:
            self.logger.error(f"Error from GitHub/SpeedX: {e}")
            return []

    def fetch_github_monosans(self) -> List[Dict[str, str]]:
        try:
            url = (
                "https://raw.githubusercontent.com/monosans/proxy-list"
                "/main/proxies/http.txt"
            )
            resp = requests.get(url, timeout=15)
            if resp.status_code == 200:
                lines = [x.strip() for x in resp.text.split("\n") if x.strip()]
                return [
                    {"http": f"http://{line}", "https": f"http://{line}"}
                    for line in lines
                ]
            return []
        except Exception as e:
            self.logger.error(f"Error from GitHub/monosans: {e}")
            return []

    def fetch_github_clarketm(self) -> List[Dict[str, str]]:
        try:
            url = (
                "https://raw.githubusercontent.com/clarketm/proxy-list"
                "/master/proxy-list-raw.txt"
            )
            resp = requests.get(url, timeout=15)
            if resp.status_code == 200:
                lines = [x.strip() for x in resp.text.split("\n") if x.strip()]
                return [
                    {"http": f"http://{line}", "https": f"http://{line}"}
                    for line in lines
                ]
            return []
        except Exception as e:
            self.logger.error(f"Error from GitHub/clarketm: {e}")
            return []

    # ----- Parallel Proxy Validation with Feedback -----
    def validate_proxy(self, proxy: Dict[str, str], timeout=VALIDATION_TIMEOUT) -> bool:
        """Test a proxy against multiple endpoints; succeed on first HTTP 200 with a body."""
        for endpoint in VALIDATION_ENDPOINTS:
            try:
                resp = requests.get(endpoint, proxies=proxy, timeout=timeout)
                if resp.status_code == 200 and resp.text.strip():
                    return True
            except Exception:
                continue
        return False

    def build_valid_proxy_pool(
        self,
        max_proxies=50,
        concurrency=20,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> None:
        """Fetch candidate proxies and validate them in parallel."""
        self._cancel_event.clear()
        candidates = []
        sources = [
            self.fetch_proxyscrape,
            self.fetch_geonode,
            self.fetch_pubproxy,
            self.fetch_proxylist_download,
            self.fetch_spys_one,
            self.fetch_github_speedx,
            self.fetch_github_monosans,
            self.fetch_github_clarketm,
        ]
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=SOURCE_FETCH_CONCURRENCY
        ) as executor:
            future_to_src = {executor.submit(src): src for src in sources}
            for future in concurrent.futures.as_completed(future_to_src):
                src = future_to_src[future]
                try:
                    src_candidates = future.result()
                except Exception:
                    src_candidates = []
                candidates.extend(src_candidates)
                msg = f"Fetched {len(src_candidates)} from {src.__name__}"
                self.logger.info(msg)
                if progress_callback:
                    progress_callback(msg)
        # Remove duplicates, then shuffle for source diversity
        candidates = list({p["http"]: p for p in candidates}.values())
        random.shuffle(candidates)
        msg = f"{len(candidates)} unique candidate proxies after deduplication."
        self.logger.info(msg)
        if progress_callback:
            progress_callback(msg)
        self.logger.info("Starting parallel validation...")
        if progress_callback:
            progress_callback("Starting parallel validation of proxies...")
        valid = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
            future_to_proxy = {
                executor.submit(self.validate_proxy, p): p for p in candidates
            }
            for future in concurrent.futures.as_completed(future_to_proxy):
                if self._cancel_event.is_set() or len(valid) >= max_proxies:
                    break
                p = future_to_proxy[future]
                try:
                    if future.result():
                        valid.append(p)
                        msg = f"Validated: {p['http']}"
                        self.logger.info(msg)
                        if progress_callback:
                            progress_callback(msg)
                except Exception:
                    continue
            # Cancel remaining pending futures
            for f in future_to_proxy:
                f.cancel()
        self.proxies = valid
        cancelled = self._cancel_event.is_set()
        label = "Cancelled" if cancelled else "Validation complete"
        msg = f"{label}. {len(valid)} proxies are usable."
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

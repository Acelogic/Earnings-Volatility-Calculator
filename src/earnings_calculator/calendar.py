"""Earnings calendar fetching from Investing.com."""

import json
from queue import Queue
from typing import List

from bs4 import BeautifulSoup

from earnings_calculator.logging_config import create_logger
from earnings_calculator.proxy import ProxyManager
from earnings_calculator.sessions import SessionManager


class EarningsCalendarFetcher:
    def __init__(self, proxy_manager=None):
        self.data_queue = Queue()
        self.earnings_times = {}
        self.proxy_manager = proxy_manager or ProxyManager()
        self.session_manager = SessionManager(self.proxy_manager)
        self.logger = create_logger(
            "EarningsCalendarFetcher", "earnings_calendar_debug.log"
        )

    def fetch_earnings_data(self, date: str) -> List[str]:
        max_retries = 3
        attempt = 0
        ret = []
        while attempt < max_retries:
            try:
                self.logger.info(f"Fetching earnings for {date}")
                url = "https://www.investing.com/earnings-calendar/Service/getCalendarFilteredData"
                hd = {
                    "User-Agent": "Mozilla/5.0",
                    "X-Requested-With": "XMLHttpRequest",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Referer": "https://www.investing.com/earnings-calendar/",
                }
                pl = {
                    "country[]": "5",
                    "dateFrom": date,
                    "dateTo": date,
                    "currentTab": "custom",
                    "limit_from": 0,
                }
                s = self.session_manager.get_session()
                r = s.post(url, headers=hd, data=pl)
                data = json.loads(r.text)
                soup = BeautifulSoup(data["data"], "html.parser")
                rows = soup.find_all("tr")
                self.earnings_times.clear()
                for row in rows:
                    if not row.find("span", class_="earnCalCompanyName"):
                        continue
                    try:
                        ticker = row.find("a", class_="bold").text.strip()
                        timing_span = row.find("span", class_="genToolTip")
                        timing = "During Market"
                        if timing_span and "data-tooltip" in timing_span.attrs:
                            tip = timing_span["data-tooltip"]
                            if tip == "Before market open":
                                timing = "Pre Market"
                            elif tip == "After market close":
                                timing = "Post Market"
                        self.earnings_times[ticker] = timing
                        ret.append(ticker)
                    except Exception as e:
                        self.logger.warning(f"Error parsing row: {e}")
                        continue
                self.logger.info(f"Found {len(ret)} tickers for date {date}")
                return ret
            except Exception as e:
                attempt += 1
                if attempt < max_retries:
                    self.logger.warning(f"Retry {attempt}: {e}. Rotating proxy.")
                    self.session_manager.rotate_session()
                else:
                    self.logger.error(f"All attempts failed: {e}")
                    return []
        return ret

    def get_earnings_time(self, ticker: str) -> str:
        return self.earnings_times.get(ticker, "Unknown")

import requests
import yfinance as yf
import time
import random
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Optional
import logging

class ProxyTester:
    def __init__(self):
        self.proxies: List[Dict[str, str]] = []
        self._setup_logging()
    
    def _setup_logging(self):
        """Setup logging configuration"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('proxy_test.log'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)

    def fetch_proxies(self) -> None:
        """Fetch fresh proxies from Proxyscrape"""
        try:
            url = "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=10000&country=all&ssl=all&anonymity=all"
            response = requests.get(url)
            if response.status_code == 200:
                proxy_list = [x.strip() for x in response.text.split('\n') if x.strip()]
                self.proxies = [
                    {
                        'http': f"http://{proxy}",
                        'https': f"http://{proxy}"
                    }
                    for proxy in proxy_list
                ]
                self.logger.info(f"Successfully fetched {len(self.proxies)} proxies")
            else:
                raise Exception(f"Failed to fetch proxies: {response.status_code}")
        except Exception as e:
            self.logger.error(f"Error fetching proxies: {e}")
            raise

    def get_random_proxy(self) -> Optional[Dict[str, str]]:
        """Get a random proxy from the pool"""
        return random.choice(self.proxies) if self.proxies else None

    def test_single_stock(self, symbol: str, proxy: Dict[str, str]) -> bool:
        """Test fetching data for a single stock using a proxy"""
        try:
            # Create a session with the proxy
            session = requests.Session()
            session.proxies.update(proxy)
            
            # Create ticker with the session
            ticker = yf.Ticker(symbol)
            ticker.session = session  # Use our proxy session
            
            # Try to fetch various types of data
            info = ticker.info
            history = ticker.history(period="1mo")
            options = ticker.options
            
            self.logger.info(f"Successfully fetched data for {symbol} using proxy {proxy['http']}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to fetch data for {symbol} using proxy {proxy['http']}: {str(e)}")
            return False

    def stress_test(self, symbols: List[str], max_workers: int = 5, requests_per_proxy: int = 3) -> Dict:
        """
        Stress test YFinance using multiple proxies and stock symbols
        
        Args:
            symbols: List of stock symbols to test
            max_workers: Maximum number of concurrent threads
            requests_per_proxy: Number of requests to make with each proxy before rotating
        """
        results = {
            'total_requests': 0,
            'successful_requests': 0,
            'failed_requests': 0,
            'successful_proxies': set(),
            'failed_proxies': set()
        }

        def worker(symbol: str) -> None:
            proxy = self.get_random_proxy()
            if not proxy:
                self.logger.error("No proxies available")
                return
            
            results['total_requests'] += 1
            success = self.test_single_stock(symbol, proxy)
            
            if success:
                results['successful_requests'] += 1
                results['successful_proxies'].add(proxy['http'])
            else:
                results['failed_requests'] += 1
                results['failed_proxies'].add(proxy['http'])

        # Create multiple requests using ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Generate test cases: each symbol multiple times with different proxies
            test_cases = symbols * requests_per_proxy
            random.shuffle(test_cases)  # Randomize the order
            
            # Submit all test cases
            futures = [executor.submit(worker, symbol) for symbol in test_cases]
            
            # Wait for all futures to complete
            for future in futures:
                future.result()

        return results

def main():
    # List of test symbols (you can modify this)
    test_symbols = ['AAPL', 'GOOGL', 'MSFT', 'AMZN', 'META', 'NVDA', 'TSLA', 'AMD', 'INTC', 'NFLX']
    
    tester = ProxyTester()
    
    # Fetch initial proxies
    print("Fetching proxies...")
    tester.fetch_proxies()
    print(f"Retrieved {len(tester.proxies)} proxies")
    
    # Run stress test
    print("\nStarting stress test...")
    start_time = time.time()
    
    results = tester.stress_test(
        symbols=test_symbols,
        max_workers=5,  # Adjust based on your needs
        requests_per_proxy=2  # Adjust based on your needs
    )
    
    # Print results
    duration = time.time() - start_time
    print("\nStress Test Results:")
    print(f"Duration: {duration:.2f} seconds")
    print(f"Total Requests: {results['total_requests']}")
    print(f"Successful Requests: {results['successful_requests']}")
    print(f"Failed Requests: {results['failed_requests']}")
    print(f"Success Rate: {(results['successful_requests'] / results['total_requests'] * 100):.2f}%")
    print(f"Working Proxies: {len(results['successful_proxies'])}")
    print(f"Failed Proxies: {len(results['failed_proxies'])}")

if __name__ == "__main__":
    main()
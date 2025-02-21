import requests
import requests_cache
import threading
import time
import random
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor, as_completed

# =======================================
#  Global Variables & Config
# =======================================
cached_session = requests_cache.CachedSession('yfinance.cache')

PROXYSCRAPE_API = ("https://api.proxyscrape.com/v4/free-proxy-list/get?"
                   "request=display_proxies&proxytype=http&timeout=1000&country=all&ssl=all&anonymity=all")
FREE_PROXY_LIST_URL = "https://free-proxy-list.net/"

proxy_pool = []           # List of working proxies in "ip:port" string format.
proxy_index = 0           # Round-robin index
proxy_lock = threading.Lock()
stats_lock = threading.Lock()

# Stats tracking for final summary
total_requests = 0
success_count = 0
failure_count = 0
proxy_stats = {}


# =======================================
#  Proxy Fetching
# =======================================
def fetch_proxies():
    """
    Fetch a list of proxies from multiple free sources.
    Returns a combined, deduplicated list of candidate proxies (in 'ip:port' format).
    """
    proxies = []

    # ----- 1) Fetch from ProxyScrape -----
    try:
        resp = requests.get(PROXYSCRAPE_API, timeout=5)
        if resp.status_code == 200:
            for line in resp.text.splitlines():
                line = line.strip()
                if line:
                    proxies.append(line)
        else:
            print(f"[WARN] ProxyScrape responded with {resp.status_code}")
    except Exception as e:
        print(f"[WARN] ProxyScrape fetch failed: {e}")

    # ----- 2) Fetch from free-proxy-list.net -----
    try:
        resp = requests.get(FREE_PROXY_LIST_URL, timeout=5)
        if resp.status_code == 200:
            import re
            html = resp.text
            matches = re.findall(r'<td>(\d+\.\d+\.\d+\.\d+)</td><td>(\d+)</td>', html)
            for ip, port in matches:
                proxies.append(f"{ip}:{port}")
        else:
            print(f"[WARN] free-proxy-list.net responded with {resp.status_code}")
    except Exception as e:
        print(f"[WARN] Free Proxy List fetch failed: {e}")

    # Remove duplicates and return
    proxies = list(dict.fromkeys(proxies))  # preserves order, removes dups
    return proxies


def validate_proxy(proxy, timeout=3):
    """
    Checks if a proxy is working by making a quick request. 
    If it succeeds within 'timeout' seconds, returns True; otherwise False.
    """
    test_url = "https://httpbin.org/ip"
    proxies = {
        "http": f"http://{proxy}",
        "https": f"http://{proxy}"
    }
    try:
        resp = requests.get(test_url, proxies=proxies, timeout=timeout)
        if resp.status_code == 200:
            reported_ip = resp.json().get("origin", "")
            # Check if the proxy's IP matches the returned IP
            proxy_ip = proxy.split(":")[0]
            if proxy_ip in reported_ip:
                return True
    except Exception:
        pass
    return False


def build_proxy_pool(max_proxies=50, concurrency=20):
    """
    Fetch proxy candidates, validate them in parallel, and build a pool of working proxies.
    - max_proxies: maximum number of valid proxies to keep
    - concurrency: number of parallel threads to use for validation
    """
    candidates = fetch_proxies()
    if not candidates:
        print("[ERROR] No proxy candidates fetched.")
        return []

    print(f"[INFO] Fetched {len(candidates)} proxy addresses. Validating in parallel with {concurrency} threads...")

    valid_proxies = []
    # Validate in parallel using ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        future_to_proxy = {executor.submit(validate_proxy, p): p for p in candidates}
        for future in as_completed(future_to_proxy):
            proxy_str = future_to_proxy[future]
            try:
                ok = future.result()
                if ok:
                    valid_proxies.append(proxy_str)
                    if len(valid_proxies) >= max_proxies:
                        break
            except Exception as e:
                # This shouldn't usually happen unless there's some internal error in validate_proxy
                pass

    print(f"[INFO] Validation done: {len(valid_proxies)} proxies are usable.")
    return valid_proxies


# =======================================
#  Round-Robin Proxy Access
# =======================================
def get_next_proxy():
    """Round-robin selection: get the next proxy from the pool in a thread-safe way."""
    global proxy_index, proxy_pool
    with proxy_lock:
        if not proxy_pool:
            return None
        if proxy_index >= len(proxy_pool):
            proxy_index = 0
        proxy = proxy_pool[proxy_index]
        proxy_index += 1
        if proxy_index >= len(proxy_pool):
            proxy_index = 0
        return proxy


def remove_proxy(proxy):
    """Remove a proxy from the pool (thread-safe)."""
    global proxy_pool
    with proxy_lock:
        if proxy in proxy_pool:
            proxy_pool.remove(proxy)
            print(f"[INFO] Removed proxy {proxy}")


# =======================================
#  Stats
# =======================================
def record_result(proxy, success):
    global total_requests, success_count, failure_count, proxy_stats
    with stats_lock:
        total_requests += 1
        if success:
            success_count += 1
        else:
            failure_count += 1
        if proxy not in proxy_stats:
            proxy_stats[proxy] = {"success": 0, "fail": 0}
        if success:
            proxy_stats[proxy]["success"] += 1
        else:
            proxy_stats[proxy]["fail"] += 1


# =======================================
#  Worker Thread
# =======================================
def worker_thread(thread_id, tickers, end_time):
    """
    Each thread repeatedly picks a proxy and uses yfinance to request data 
    until time is up or no proxies remain.
    """
    while time.time() < end_time:
        proxy = get_next_proxy()
        if not proxy:
            print(f"[WARN] Thread-{thread_id} found no proxy in pool, exiting.")
            return

        symbol = random.choice(tickers)
        # To pass a proxy to yfinance, we must set that proxy in the requests session for each call.
        # We can do so by temporarily adjusting environment or patching the session, but simpler 
        # is to manually request data with a custom session. We'll do a short example below:
        session = requests_cache.CachedSession('yfinance.cache')
        session.proxies = {
            "http": f"http://{proxy}",
            "https": f"http://{proxy}"
        }
        session.timeout = 5  # each request times out quickly if proxy is slow

        try:
            ticker = yf.Ticker(symbol, session=session)
            # fetch some data
            data = ticker.history(period="1d")  # a small fetch
            if not data.empty:
                record_result(proxy, True)
            else:
                # Could happen if Yahoo returns empty data or something else fails
                record_result(proxy, False)
        except Exception as e:
            record_result(proxy, False)
            # Probably the proxy failed. Remove from pool
            print(f"[WARN] Thread-{thread_id} removing failing proxy {proxy}: {e}")
            remove_proxy(proxy)
            # Attempt to fetch & add a new proxy
            new_candidates = fetch_proxies()
            for c in new_candidates:
                if validate_proxy(c):
                    with proxy_lock:
                        if c not in proxy_pool:
                            proxy_pool.append(c)
                            print(f"[INFO] Thread-{thread_id} replaced a bad proxy with {c}")
                            break
            # continue loop so we pick another proxy next iteration
            continue


# =======================================
#  Main Stress Test
# =======================================
if __name__ == "__main__":
    # Step 1: Build initial proxy pool with parallel validation
    proxy_pool = build_proxy_pool(max_proxies=50, concurrency=20)
    if not proxy_pool:
        print("[ERROR] No valid proxies. Exiting.")
        exit(1)

    # A few example symbols to stress test
    tickers = ["AAPL", "MSFT", "GOOG", "AMZN", "TSLA", "JPM", "XOM", "GE", "NVDA", "NFLX"]

    # Step 2: Start multiple threads for 60 seconds
    num_threads = min(10, len(proxy_pool))  # up to 10 threads, or fewer if pool <10
    test_duration = 60
    end_time = time.time() + test_duration

    print(f"[INFO] Starting stress test with {num_threads} threads for {test_duration}s")
    threads = []
    for i in range(num_threads):
        t = threading.Thread(target=worker_thread, args=(i, tickers, end_time))
        t.start()
        threads.append(t)

    for t in threads:
        t.join()

    # Step 3: Print final summary
    print("\n=== Stress Test Summary ===")
    print(f"Total requests: {total_requests}")
    print(f"Successes: {success_count}")
    print(f"Failures: {failure_count}")
    if total_requests > 0:
        sr = (success_count / total_requests) * 100
        print(f"Success Rate: {sr:.2f}%")

    print("\n=== Per-Proxy Stats ===")
    for pxy, st in proxy_stats.items():
        print(f"{pxy} -> success={st['success']}, fail={st['fail']}")
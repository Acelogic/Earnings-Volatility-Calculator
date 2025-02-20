import requests

base_url = "https://api.stockanalysis.com/api/screener/a/f"

headers = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:135.0) Gecko/20100101 Firefox/135.0",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer": "https://stockanalysis.com/",
    "Origin": "https://stockanalysis.com",
}

params = {
    "m": "marketCap",
    "s": "desc",
    "c": "no,s,n,marketCap,price,change,revenue",
    "cn": "1000",
    "f": "exchangeCode-is-OTC,subtype-is-stock",
    "i": "symbols"
}

all_tickers = []
page = 1

while True:
    params["p"] = page
    response = requests.get(base_url, headers=headers, params=params)
    response.raise_for_status()
    data = response.json()

    page_data = data.get("data", {}).get("data", [])
    if not page_data:
        break

    for item in page_data:
        full_symbol = item.get("s", "")
        ticker = full_symbol.split("/")[-1] if "/" in full_symbol else full_symbol
        all_tickers.append(ticker)
    
    print(f"Processed page {page}")
    page += 1

# Write the tickers to a file line by line without quotes
with open("tickers.txt", "w") as f:
    for ticker in all_tickers:
        f.write(f"{ticker}\n")

print("Total tickers count:", len(all_tickers))
print("Tickers have been written to tickers.txt")
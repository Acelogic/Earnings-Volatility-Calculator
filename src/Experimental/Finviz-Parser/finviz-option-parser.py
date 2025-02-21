import requests
from datetime import datetime

# Browser-like headers to avoid 403 errors on Finviz
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:135.0) Gecko/20100101 Firefox/135.0",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer": "https://finviz.com",
}

def fetch_expirations(ticker):
    """Fetch the list of available expiration dates for the given ticker."""
    url = f"https://finviz.com/api/options/{ticker}/expiries"
    try:
        response = requests.get(url, headers=HEADERS)
        response.raise_for_status()
        return response.json()  # e.g. ["2025-02-21","2025-03-14",...]
    except Exception as e:
        print(f"Error fetching expirations for {ticker}: {e}")
        return []

def fetch_option_chain(ticker, expiry):
    """Fetch the option chain JSON data for a given ticker and expiry date."""
    url = f"https://finviz.com/api/options/{ticker}?expiry={expiry}"
    try:
        response = requests.get(url, headers=HEADERS)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error fetching option chain: {e}")
        return None

def group_options_by_strike(options):
    """
    Group options by strike price into:
      { strike_price: {"call": {...}, "put": {...}} }
    """
    chain = {}
    for opt in options:
        strike = opt.get("strike")
        if strike not in chain:
            chain[strike] = {"call": None, "put": None}
        if opt.get("type") == "call":
            chain[strike]["call"] = opt
        else:
            chain[strike]["put"] = opt
    return chain

def format_float(value, decimals=2):
    """Safely format a float to a given number of decimals."""
    try:
        return f"{float(value):.{decimals}f}"
    except (TypeError, ValueError):
        return "N/A"

def compute_change_pct(last_close, last_change):
    """
    Compute % change given lastClose and lastChange:
      old_close = lastClose - lastChange
      % = (lastChange / old_close) * 100
    """
    try:
        last_close = float(last_close)
        last_change = float(last_change)
        old_close = last_close - last_change
        if abs(old_close) < 1e-9:
            return 0.0
        return (last_change / old_close) * 100
    except:
        return 0.0

# -------------------- (1) PRICE VIEW -------------------- #
def get_price_fields(opt):
    """Return tuple of price fields: (Last, Chg, %Chg, Bid, Ask, Vol, OI)."""
    if not opt:
        return ("-", "-", "-", "-", "-", "-", "-")

    last_close = opt.get("lastClose", 0.0)
    last_change = opt.get("lastChange", 0.0)
    pct = compute_change_pct(last_close, last_change)

    return (
        format_float(last_close),
        format_float(last_change),
        f"{pct:>5.2f}%",
        format_float(opt.get("bidPrice", 0.0)),
        format_float(opt.get("askPrice", 0.0)),
        str(opt.get("lastVolume", 0)),       # or opt.get("averageVolume")
        str(opt.get("openInterest", 0))
    )

def print_price_table(chain, ticker, expiry):
    """
    Print ASCII table of price data: calls on left, strike in center, puts on right.
    Columns: Last, Chg, %Chg, Bid, Ask, Vol, OI
    """
    print(f"\nOption Chain (Prices) for {ticker.upper()} (Expiry: {expiry})\n")

    # Column widths
    field_width = 8
    call_width  = field_width * 7  # 7 columns for calls
    put_width   = field_width * 7
    strike_width = 8

    divider = "+" + "-"*call_width + "+" + "-"*strike_width + "+" + "-"*put_width + "+"
    header = f"|{'CALLS':^{call_width}}|{'STRIKE':^{strike_width}}|{'PUTS':^{put_width}}|"
    subheader_cols = ["Last","Chg","%Chg","Bid","Ask","Vol","OI"]
    subheader_str = " ".join(f"{col:^{field_width}}" for col in subheader_cols)
    subheader = f"|{subheader_str:^{call_width}}|{'':^{strike_width}}|{subheader_str:^{put_width}}|"

    print(divider)
    print(header)
    print(divider)
    print(subheader)
    print(divider)

    for strike in sorted(chain.keys()):
        call_opt = chain[strike]["call"]
        put_opt  = chain[strike]["put"]
        call_data = get_price_fields(call_opt)
        put_data  = get_price_fields(put_opt)

        call_str = " ".join(f"{val:>{field_width}}" for val in call_data)
        put_str  = " ".join(f"{val:>{field_width}}" for val in put_data)
        row = f"|{call_str:^{call_width}}|{str(strike):^{strike_width}}|{put_str:^{put_width}}|"
        print(row)
        print(divider)
    print()

# -------------------- (2) GREEK VIEW -------------------- #
def get_greek_fields(opt):
    """
    Return tuple of Greek-based columns:
    (LastClose, IV, Delta, Gamma, Theta, Vega).
    """
    if not opt:
        return ("-", "-", "-", "-", "-", "-")

    last_close = format_float(opt.get("lastClose"), 2)
    iv         = format_float(opt.get("iv"), 2)
    delta      = format_float(opt.get("delta"), 4)
    gamma      = format_float(opt.get("gamma"), 4)
    theta      = format_float(opt.get("theta"), 4)
    vega       = format_float(opt.get("vega"), 4)
    return (last_close, iv, delta, gamma, theta, vega)

def print_greek_table(chain, ticker, expiry):
    """
    Print ASCII table of Greek data: calls on left, strike in center, puts on right.
    Columns: LastClose, IV, Delta, Gamma, Theta, Vega
    """
    print(f"\nOption Chain (Greeks) for {ticker.upper()} (Expiry: {expiry})\n")

    col_names = ["LastClose", "IV", "Delta", "Gamma", "Theta", "Vega"]
    col_width = 10
    call_width = col_width * 6
    put_width  = col_width * 6
    strike_width = 8

    divider = "+" + "-"*call_width + "+" + "-"*strike_width + "+" + "-"*put_width + "+"
    header = f"|{'CALLS':^{call_width}}|{'STRIKE':^{strike_width}}|{'PUTS':^{put_width}}|"
    subheader_str = " ".join(f"{col:^{col_width}}" for col in col_names)
    subheader = f"|{subheader_str:^{call_width}}|{'':^{strike_width}}|{subheader_str:^{put_width}}|"

    print(divider)
    print(header)
    print(divider)
    print(subheader)
    print(divider)

    for strike in sorted(chain.keys()):
        call_opt = chain[strike]["call"]
        put_opt  = chain[strike]["put"]
        call_data = get_greek_fields(call_opt)
        put_data  = get_greek_fields(put_opt)

        call_str = " ".join(f"{val:>{col_width}}" for val in call_data)
        put_str  = " ".join(f"{val:>{col_width}}" for val in put_data)
        row = f"|{call_str:^{call_width}}|{str(strike):^{strike_width}}|{put_str:^{put_width}}|"
        print(row)
        print(divider)
    print()

# -------------------- (3) SINGLE STRIKE DETAILED VIEW -------------------- #

# Which fields to show in the "detailed" pretty print:
DETAILED_FIELDS = [
    ("lastClose",   "LastClose"),
    ("lastChange",  "Change"),
    ("bidPrice",    "Bid"),
    ("askPrice",    "Ask"),
    ("lastVolume",  "Volume"),
    ("openInterest","OI"),
    ("iv",          "IV"),
    ("delta",       "Delta"),
    ("gamma",       "Gamma"),
    ("theta",       "Theta"),
    ("vega",        "Vega"),
    ("rho",         "Rho"),
    ("lambda",      "Lambda"),
]

def print_single_option_detail(title, opt):
    """
    Print all fields from DETAILED_FIELDS for one option side (call or put).
    If opt is None, print "No data".
    """
    print(f"{title} Option:")
    if not opt:
        print("  No data for this option.\n")
        return

    for field_key, field_label in DETAILED_FIELDS:
        val = opt.get(field_key)
        # Let's do 2 decimal places for most fields, except a few might need 4 decimals
        # But for simplicity, let's just do 4 decimals for 'delta', 'gamma', 'theta', 'vega', 'rho', 'lambda', else 2 decimals
        if field_key in ("delta","gamma","theta","vega","rho","lambda"):
            val_str = format_float(val, 4)
        else:
            val_str = format_float(val, 2)
        print(f"  {field_label:10}: {val_str}")
    print()

def print_single_strike_detail(chain, ticker, expiry):
    """
    Ask user for a strike, then pretty-print a detailed breakdown
    of the call & put for that strike.
    """
    # Show available strikes
    strikes = sorted(chain.keys())
    print(f"\nAvailable Strikes: {', '.join(str(strk) for strk in strikes)}")
    pick_str = input("Enter the strike you want to view: ").strip()

    try:
        strike_val = float(pick_str)
    except ValueError:
        print("Invalid numeric strike. Exiting.\n")
        return

    if strike_val not in chain:
        print("That strike doesn't exist in the chain. Exiting.\n")
        return

    call_opt = chain[strike_val]["call"]
    put_opt  = chain[strike_val]["put"]

    print(f"\nDetailed Option Data for {ticker.upper()}, Expiry: {expiry}, Strike: {strike_val}\n")
    print_single_option_detail("CALL", call_opt)
    print_single_option_detail("PUT",  put_opt)

# -------------------- MAIN SCRIPT -------------------- #
def main():
    ticker = input("Enter a ticker symbol (e.g. AAPL): ").strip().upper()
    if not ticker:
        print("No ticker provided. Exiting.")
        return

    # Fetch expiration dates
    expirations = fetch_expirations(ticker)
    if not expirations:
        print("No expirations found. Exiting.")
        return

    print(f"\nAvailable Expiration Dates for {ticker}:")
    for i, date_str in enumerate(expirations, start=1):
        print(f"{i}. {date_str}")
    choice_str = input("\nPick an expiration date by number (1, 2, ...): ").strip()
    try:
        choice_idx = int(choice_str)
        if choice_idx < 1 or choice_idx > len(expirations):
            raise ValueError
        chosen_expiry = expirations[choice_idx - 1]
    except ValueError:
        print("Invalid choice. Exiting.")
        return

    # Fetch the chain
    data = fetch_option_chain(ticker, chosen_expiry)
    if not data or "options" not in data:
        print("No option data found for that expiry. Exiting.")
        return

    # Group by strike
    chain = group_options_by_strike(data["options"])

    # Prompt user: price data, greek data, or single-strike detail
    print("\nWhat do you want to view?")
    print("  1) Price data (Last, Chg, %Chg, Bid, Ask, Vol, OI)")
    print("  2) Greek data (LastClose, IV, Delta, Gamma, Theta, Vega)")
    print("  3) Detailed data for a single strike (call & put)")
    choice = input("Enter 1, 2, or 3: ").strip()

    if choice == "1":
        print_price_table(chain, ticker, chosen_expiry)
    elif choice == "2":
        print_greek_table(chain, ticker, chosen_expiry)
    elif choice == "3":
        print_single_strike_detail(chain, ticker, chosen_expiry)
    else:
        print("Invalid choice. Exiting.")

if __name__ == "__main__":
    main()
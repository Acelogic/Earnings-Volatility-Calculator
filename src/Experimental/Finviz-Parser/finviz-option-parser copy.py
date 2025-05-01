import requests
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime
import numpy as np
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# ----------------------- Data Fetching & Helpers ----------------------- #

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
        return response.json()  # e.g. ["2025-02-21", "2025-03-14", ...]
    except Exception as e:
        messagebox.showerror("Error", f"Error fetching expirations for {ticker}: {e}")
        return []

def fetch_option_chain(ticker, expiry):
    """Fetch the option chain JSON data for a given ticker and expiry date."""
    url = f"https://finviz.com/api/options/{ticker}?expiry={expiry}"
    try:
        response = requests.get(url, headers=HEADERS)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        messagebox.showerror("Error", f"Error fetching option chain: {e}")
        return None

def group_options_by_strike(options):
    """
    Group options by strike price into a dict:
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
      old_close = lastClose - lastChange,
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

# Fields for the detailed view
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
        str(opt.get("lastVolume", 0)),
        str(opt.get("openInterest", 0))
    )

def get_greek_fields(opt):
    """Return tuple of Greek fields: (LastClose, IV, Delta, Gamma, Theta, Vega)."""
    if not opt:
        return ("-", "-", "-", "-", "-", "-")
    return (
        format_float(opt.get("lastClose"), 2),
        format_float(opt.get("iv"), 2),
        format_float(opt.get("delta"), 4),
        format_float(opt.get("gamma"), 4),
        format_float(opt.get("theta"), 4),
        format_float(opt.get("vega"), 4)
    )

# ----------------------- Rich GUI using Tkinter ----------------------- #

class OptionChainGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Option Chain Viewer")
        self.chain = None  # will hold grouped options
        
        # Top frame for ticker and expiration input
        top_frame = ttk.Frame(root, padding="10")
        top_frame.pack(side=tk.TOP, fill=tk.X)
        
        ttk.Label(top_frame, text="Ticker:").pack(side=tk.LEFT)
        self.ticker_entry = ttk.Entry(top_frame, width=10)
        self.ticker_entry.pack(side=tk.LEFT, padx=5)
        
        self.fetch_exp_btn = ttk.Button(top_frame, text="Fetch Expirations", command=self.fetch_expirations)
        self.fetch_exp_btn.pack(side=tk.LEFT, padx=5)
        
        ttk.Label(top_frame, text="Expiration:").pack(side=tk.LEFT, padx=5)
        self.expiry_var = tk.StringVar()
        self.expiry_combo = ttk.Combobox(top_frame, textvariable=self.expiry_var, state="readonly", width=15)
        self.expiry_combo.pack(side=tk.LEFT, padx=5)
        
        self.fetch_chain_btn = ttk.Button(top_frame, text="Fetch Option Chain", command=self.fetch_option_chain)
        self.fetch_chain_btn.pack(side=tk.LEFT, padx=5)
        
        # Notebook with four tabs for different views
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(expand=True, fill=tk.BOTH)
        
        # Price Data Tab
        self.price_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.price_tab, text="Price Data")
        self.init_price_tab()
        
        # Greek Data Tab
        self.greek_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.greek_tab, text="Greek Data")
        self.init_greek_tab()
        
        # Detailed View Tab
        self.detail_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.detail_tab, text="Detailed View")
        self.init_detail_tab()
        
        # P/L Chart Tab
        self.pl_chart_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.pl_chart_tab, text="P/L Chart")
        self.init_pl_chart_tab()
    
    def init_price_tab(self):
        columns = [
            "call_last", "call_chg", "call_pct_chg", "call_bid", "call_ask", "call_vol", "call_oi",
            "strike",
            "put_last", "put_chg", "put_pct_chg", "put_bid", "put_ask", "put_vol", "put_oi"
        ]
        self.price_tree = ttk.Treeview(self.price_tab, columns=columns, show="headings")
        for col in columns:
            self.price_tree.heading(col, text=col.replace("_", " ").title())
            self.price_tree.column(col, width=80, anchor="center")
        vsb = ttk.Scrollbar(self.price_tab, orient="vertical", command=self.price_tree.yview)
        self.price_tree.configure(yscrollcommand=vsb.set)
        self.price_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
    
    def init_greek_tab(self):
        columns = [
            "call_lastclose", "call_iv", "call_delta", "call_gamma", "call_theta", "call_vega",
            "strike",
            "put_lastclose", "put_iv", "put_delta", "put_gamma", "put_theta", "put_vega"
        ]
        self.greek_tree = ttk.Treeview(self.greek_tab, columns=columns, show="headings")
        for col in columns:
            self.greek_tree.heading(col, text=col.replace("_", " ").title())
            self.greek_tree.column(col, width=80, anchor="center")
        vsb = ttk.Scrollbar(self.greek_tab, orient="vertical", command=self.greek_tree.yview)
        self.greek_tree.configure(yscrollcommand=vsb.set)
        self.greek_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
    
    def init_detail_tab(self):
        top = ttk.Frame(self.detail_tab, padding="10")
        top.pack(side=tk.TOP, fill=tk.X)
        ttk.Label(top, text="Select Strike:").pack(side=tk.LEFT)
        self.detail_strike_var = tk.StringVar()
        self.detail_strike_combo = ttk.Combobox(top, textvariable=self.detail_strike_var, state="readonly", width=10)
        self.detail_strike_combo.pack(side=tk.LEFT, padx=5)
        self.detail_strike_combo.bind("<<ComboboxSelected>>", self.update_detail_view)
        
        # Frame to display detailed option data
        self.detail_display = ttk.Frame(self.detail_tab, padding="10")
        self.detail_display.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        
        # Two sub-frames for Call and Put details
        self.call_detail_frame = ttk.LabelFrame(self.detail_display, text="Call Option Details", padding="10")
        self.call_detail_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.put_detail_frame = ttk.LabelFrame(self.detail_display, text="Put Option Details", padding="10")
        self.put_detail_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Create labels for each detailed field (for both call and put)
        self.call_detail_labels = {}
        self.put_detail_labels = {}
        for field_key, field_label in DETAILED_FIELDS:
            # Call details
            frm = ttk.Frame(self.call_detail_frame)
            frm.pack(fill=tk.X, pady=2)
            ttk.Label(frm, text=f"{field_label}:", width=12).pack(side=tk.LEFT)
            lbl = ttk.Label(frm, text="N/A")
            lbl.pack(side=tk.LEFT)
            self.call_detail_labels[field_key] = lbl
            
            # Put details
            frm2 = ttk.Frame(self.put_detail_frame)
            frm2.pack(fill=tk.X, pady=2)
            ttk.Label(frm2, text=f"{field_label}:", width=12).pack(side=tk.LEFT)
            lbl2 = ttk.Label(frm2, text="N/A")
            lbl2.pack(side=tk.LEFT)
            self.put_detail_labels[field_key] = lbl2
    
    def init_pl_chart_tab(self):
        # Top controls frame for the P/L chart
        top = ttk.Frame(self.pl_chart_tab, padding="10")
        top.pack(side=tk.TOP, fill=tk.X)
        ttk.Label(top, text="Strike:").pack(side=tk.LEFT)
        self.pl_strike_var = tk.StringVar()
        self.pl_strike_combo = ttk.Combobox(top, textvariable=self.pl_strike_var, state="readonly", width=10)
        self.pl_strike_combo.pack(side=tk.LEFT, padx=5)
        
        self.pl_option_type = tk.StringVar(value="call")
        ttk.Label(top, text="Option Type:").pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(top, text="Call", variable=self.pl_option_type, value="call").pack(side=tk.LEFT)
        ttk.Radiobutton(top, text="Put", variable=self.pl_option_type, value="put").pack(side=tk.LEFT)
        
        ttk.Label(top, text="Premium:").pack(side=tk.LEFT, padx=5)
        self.pl_premium_entry = ttk.Entry(top, width=10)
        self.pl_premium_entry.pack(side=tk.LEFT, padx=5)
        
        self.plot_button = ttk.Button(top, text="Plot P/L Chart", command=self.plot_pl_chart)
        self.plot_button.pack(side=tk.LEFT, padx=5)
        
        # Frame for matplotlib figure
        self.pl_fig_frame = ttk.Frame(self.pl_chart_tab)
        self.pl_fig_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        
        # Create matplotlib figure and embed it
        self.pl_fig = Figure(figsize=(5, 4), dpi=100)
        self.pl_ax = self.pl_fig.add_subplot(111)
        self.pl_canvas = FigureCanvasTkAgg(self.pl_fig, master=self.pl_fig_frame)
        self.pl_canvas.draw()
        self.pl_canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)
    
    def fetch_expirations(self):
        ticker = self.ticker_entry.get().strip().upper()
        if not ticker:
            messagebox.showwarning("Input Error", "Please enter a ticker symbol.")
            return
        expirations = fetch_expirations(ticker)
        if expirations:
            self.expiry_combo["values"] = expirations
            self.expiry_combo.current(0)
        else:
            self.expiry_combo["values"] = []
    
    def fetch_option_chain(self):
        ticker = self.ticker_entry.get().strip().upper()
        expiry = self.expiry_var.get().strip()
        if not ticker or not expiry:
            messagebox.showwarning("Input Error", "Please enter ticker and select an expiration date.")
            return
        data = fetch_option_chain(ticker, expiry)
        if not data or "options" not in data:
            messagebox.showerror("Data Error", "No option data found for that expiry.")
            return
        self.chain = group_options_by_strike(data["options"])
        self.update_price_tab()
        self.update_greek_tab()
        self.update_detail_tab()
        self.update_pl_chart_tab()
    
    def update_price_tab(self):
        for row in self.price_tree.get_children():
            self.price_tree.delete(row)
        if not self.chain:
            return
        for strike in sorted(self.chain.keys()):
            call_opt = self.chain[strike]["call"]
            put_opt = self.chain[strike]["put"]
            call_data = get_price_fields(call_opt)
            put_data = get_price_fields(put_opt)
            # Combine: call data (7 items) + strike + put data (7 items)
            row = list(call_data) + [strike] + list(put_data)
            self.price_tree.insert("", tk.END, values=row)
    
    def update_greek_tab(self):
        for row in self.greek_tree.get_children():
            self.greek_tree.delete(row)
        if not self.chain:
            return
        for strike in sorted(self.chain.keys()):
            call_opt = self.chain[strike]["call"]
            put_opt = self.chain[strike]["put"]
            call_data = get_greek_fields(call_opt)
            put_data = get_greek_fields(put_opt)
            # Combine: call greek data (6 items) + strike + put greek data (6 items)
            row = list(call_data) + [strike] + list(put_data)
            self.greek_tree.insert("", tk.END, values=row)
    
    def update_detail_tab(self):
        if not self.chain:
            return
        strikes = sorted(self.chain.keys())
        self.detail_strike_combo["values"] = strikes
        if strikes:
            self.detail_strike_combo.current(0)
            self.update_detail_view()
    
    def update_detail_view(self, event=None):
        try:
            strike_val = float(self.detail_strike_var.get())
        except ValueError:
            return
        if strike_val not in self.chain:
            return
        call_opt = self.chain[strike_val]["call"]
        put_opt = self.chain[strike_val]["put"]
        # Update call option details
        for field_key, field_label in DETAILED_FIELDS:
            if call_opt:
                if field_key in ("delta", "gamma", "theta", "vega", "rho", "lambda"):
                    val_str = format_float(call_opt.get(field_key), 4)
                else:
                    val_str = format_float(call_opt.get(field_key), 2)
            else:
                val_str = "N/A"
            self.call_detail_labels[field_key].configure(text=val_str)
        # Update put option details
        for field_key, field_label in DETAILED_FIELDS:
            if put_opt:
                if field_key in ("delta", "gamma", "theta", "vega", "rho", "lambda"):
                    val_str = format_float(put_opt.get(field_key), 4)
                else:
                    val_str = format_float(put_opt.get(field_key), 2)
            else:
                val_str = "N/A"
            self.put_detail_labels[field_key].configure(text=val_str)
    
    def update_pl_chart_tab(self):
        if not self.chain:
            return
        strikes = sorted(self.chain.keys())
        self.pl_strike_combo["values"] = strikes
        if strikes:
            self.pl_strike_combo.current(0)
            # Set default premium from call option if available
            opt = self.chain[strikes[0]].get("call")
            if opt:
                premium = opt.get("lastClose", 0)
                self.pl_premium_entry.delete(0, tk.END)
                self.pl_premium_entry.insert(0, format_float(premium))
    
    def plot_pl_chart(self):
        # Get the strike, option type, and premium for the P/L chart
        try:
            strike = float(self.pl_strike_var.get())
        except ValueError:
            messagebox.showerror("Error", "Invalid strike selected.")
            return
        option_type = self.pl_option_type.get()
        try:
            premium = float(self.pl_premium_entry.get())
        except ValueError:
            messagebox.showerror("Error", "Invalid premium value.")
            return
        
        # Define a range of underlying prices around the strike
        S = np.linspace(strike * 0.5, strike * 1.5, 100)
        if option_type == "call":
            payoff = np.maximum(S - strike, 0) - premium
        else:
            payoff = np.maximum(strike - S, 0) - premium
        
        # Clear the axis and plot the P/L chart
        self.pl_ax.clear()
        self.pl_ax.plot(S, payoff, label=f"{option_type.capitalize()} Option")
        self.pl_ax.axhline(0, color="black", lw=1, ls="--")
        self.pl_ax.set_xlabel("Underlying Price")
        self.pl_ax.set_ylabel("Profit / Loss")
        self.pl_ax.set_title(f"Option P/L Chart (Strike: {strike}, Premium: {premium})")
        self.pl_ax.legend()
        self.pl_canvas.draw()

# ----------------------- Main ----------------------- #

if __name__ == "__main__":
    root = tk.Tk()
    app = OptionChainGUI(root)
    root.mainloop()
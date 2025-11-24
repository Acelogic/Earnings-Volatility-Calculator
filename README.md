# Earnings Volatility Calculator

A Python-based tool that analyzes options data around earnings events, calculates volatility metrics (like IV30/RV30, ATR, and Yang-Zhang volatility), and provides **Recommended**, **Consider**, or **Avoid** labels based on user-defined criteria. The calculator includes a Tkinter GUI for Windows (or other OS), interactive candlestick charts, and multi-threaded earnings scanning.

> **Disclaimer**: All information contained in this repository, including the source code and associated resources, is provided **for educational and research purposes only**. It does **not** constitute financial advice or recommendation of any investment strategy. Trading options carries significant risk. Always consult a licensed financial advisor before making any investment decisions.

---

## Table of Contents

- [Earnings Volatility Calculator](#earnings-volatility-calculator)
  - [Table of Contents](#table-of-contents)
  - [Overview](#overview)
  - [Core Features](#core-features)
  - [Motivation \& Strategy Background](#motivation--strategy-background)
  - [Installation Instructions](#installation-instructions)
    - [Prerequisites](#prerequisites)
    - [Steps](#steps)
  - [Usage](#usage)
    - [Single Stock Analysis](#single-stock-analysis)
    - [Earnings Scan](#earnings-scan)
    - [Interactive Charts](#interactive-charts)
    - [Exporting Data](#exporting-data)
  - [Configuration \& Customization](#configuration--customization)
  - [Troubleshooting \& Common Issues](#troubleshooting--common-issues)
  - [Contributing](#contributing)
  - [License](#license)
  - [Additional Resources](#additional-resources)

---

## Overview

**Earnings Volatility Calculator** leverages market data from [Yahoo Finance](https://finance.yahoo.com/) and [Investing.com](https://www.investing.com/) to identify earnings events, retrieve option chains, and analyze a stock’s implied volatility (IV) relative to its historical or realized volatility (RV). It assigns a recommendation based on volume, IV/RV ratios, and implied volatility term structure slopes.

This project was inspired by research indicating that **shorting volatility during earnings** can provide an edge if specific conditions (e.g., high implied volatility, steep term structure) are met. The included GUI offers a user-friendly way to:

- **Scan** for upcoming earnings.
- **Filter** by timing (Pre/Post/During Market) and recommendation.
- **View** recommended setups.
- **Generate** a candlestick chart with a double-click.

---

## Core Features

- **Tkinter-Based GUI**  
  - Table with sortable columns, color-coded rows, filtering options, and direct CSV export.

- **Proxy & Multi-Threaded Support**  
  - Optional proxy rotation for fetching data.  
  - Concurrent requests for earnings scanning to speed up data collection.

- **Options Analysis**  
  - Computes 30-day realized volatility (Yang-Zhang or fallback method).  
  - Fetches Implied Volatilities from ATM calls/puts.  
  - Builds a simple term structure to approximate IV at different expirations.

- **Recommendation Logic**  
  - **Recommended**: Average daily volume ≥ 1,500,000 shares, IV30/RV30 ≥ 1.25, and term slope ≤ –0.00406.  
  - **Consider**: Partial overlap of conditions.  
  - **Avoid**: Fails key criteria or missing data.

- **Candlestick Charts**  
  - Double-click a row to pop up a Matplotlib “candle” chart showing up to 1 year of price data.

---

## Motivation & Strategy Background

This code is loosely based on the insights shared in the [Volatility Vibes YouTube channel](https://www.youtube.com/@VolatilityVibes) video, **“This Option Strategy Turned $10k Into $1 Million In One Year”**. The primary strategy revolves around **selling implied volatility (IV) around earnings** based on the observation that markets often **overprice** near-term earnings volatility.

Key points from the research:

1. **Term Structure & IV Overpricing**  
   Earnings events concentrate uncertainty into near-term options, often causing **implied volatility** to spike and the term structure to invert (negative slope).  
2. **Volume Matters**  
   Stocks with healthy trading volume (both shares and options) often see heightened demand for protection and speculative bets, leading to higher IV.  
3. **IV30 vs. RV30**  
   When short-dated implied volatility is significantly higher than recent realized volatility, it may suggest **overpricing**.  
4. **Risk Management**  
   Selling naked straddles can be highly profitable but also suffers large drawdowns; the referenced video suggests **calendar spreads** might offer a safer risk profile.

For a deep-dive into the underlying concepts, see the [video transcript](#) in the repository or the original YouTube link above.


## Installation Instructions

### Prerequisites

- **Operating System**:  
  - Windows 10 or higher (also works on macOS / Linux with minor adjustments)  
- **Python**:  
  - Version 3.7+; 3.10+ recommended  
- **Internet Connection**:  
  - Required for fetching stock market data from Yahoo Finance and Investing.com  

### Steps

1. **Install Python**  
   - [Download here](https://www.python.org/downloads/) and make sure to check **“Add Python to PATH”** during installation.
   - macOS: ```brew install python@3.10 python-tk@3.10```

2. **Open a Terminal / Command Prompt**  
   - On Windows, press `Win + R`, type `cmd`, and press Enter.
   - On macOS, press `Command + space`, type `Terminal`, and press Enter.

3. **Clone or Download the Repository**  
   ```bash
   git clone https://github.com/Acelogic/Earnings-Volatility-Calculator.git
   cd Earnings-Volatility-Calculator
   ```
   - Using python virtual environment:
   - Windows
   ```bash
   python -m venv venv
   source venv/bin/activate
   ```
   - macOS
   ```bash
   python3.10 -m venv venv
   source venv/bin/activate
   ```

4. **Install Dependencies**  
   ```bash
   pip install -r requirements.txt
   ```

5. **Run the Application**  
   ```bash
   python src/calculator.py
   ```
   The Tkinter UI should open.

---

## Usage

### Single Stock Analysis

1. Launch the GUI (`python src/calculator.py`).  
2. In the **“Enter Stock Symbol”** field (top panel), type the stock ticker (e.g. `AAPL`).  
3. Click **“Analyze”**.  

### Earnings Scan

1. Select a date using the **tkcalendar** date picker.  
2. Click **“Scan Earnings”** to fetch a list of all US stocks with earnings on that date.  

### Interactive Charts

- **Double‐click** on any row in the table.  
- A Matplotlib “candle” chart appears, showing approximately 1 year of price/volume history.

### Exporting Data

- Click **“Export CSV”** at the bottom-right of the GUI.  
- Choose a file name and location.

---

## Configuration & Customization

- **Proxy Usage**  
  - Enable or disable proxies via the **“Enable Proxy”** checkbox.  
  - Use **“Update Proxies”** to fetch a new list of free proxies.  

- **Logging & Debug**  
  - Debug logs are written to files (e.g., `options_analyzer_debug.log`).  

---

## Troubleshooting & Common Issues

1. **“No module named tkcalendar”**  
   - Install with `pip install tkcalendar`.
2. **No Internet Access or Proxy Failures**  
   - Disable proxy in the GUI or verify you have a valid network connection.  
3. **Missing Data or “N/A”**  
   - Some stocks may lack options or have incomplete data.  

---

## Contributing

Contributions, bug reports, and feature requests are welcome!  
- Open an issue or create a pull request on [GitHub](https://github.com/Acelogic/Earnings-Volatility-Calculator).

---

## License

This project is licensed under the [MIT License](./LICENSE).

---

## Additional Resources

- **Volatility Vibes Channel**  
  [This Option Strategy Turned \$10k Into \$1 Million In One Year](https://www.youtube.com/@VolatilityVibes)  

- **Trade Tracker Template**  
  Google Sheets link: [Trade Tracker Template](https://docs.google.com/spreadsheets/)  

- **Further Reading**  
  - *Option Volatility & Pricing* by Sheldon Natenberg  
  - *Options as a Strategic Investment* by Lawrence G. McMillan

**Happy researching!**

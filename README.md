# Earnings Volatility Calculator

The Earnings Volatility Calculator is a Python-based tool designed for educational and research purposes. It analyzes options data around earnings events, calculates various volatility metrics, and provides recommendations based on technical criteria. The tool includes a Windows-friendly GUI, interactive charts, and multi-threaded earnings scanning to help you assess stocks based on their earnings performance.

> **Disclaimer:** This tool and its associated resources are provided for educational and research purposes only. They do not constitute financial advice. Always consult a professional financial advisor before making any investment decisions.

---

## Table of Contents

- [Features](#features)
- [Installation Instructions (Windows)](#installation-instructions-windows)
- [Usage](#usage)
- [Related Tools and Resources](#related-tools-and-resources)
- [Support](#support)
- [License](#license)

---

## Features

- **Options Analysis:**  
  Analyzes options data to compute key metrics such as implied volatility, historical volatility, ATR (Average True Range), and more.

- **Earnings Scanning:**  
  Scans for stocks with upcoming earnings using earnings calendar data with multi-threaded processing for efficiency.

- **Interactive GUI:**  
  A user-friendly interface (built with FreeSimpleGUI or PySimpleGUI) that lets you click on table rows to view interactive candlestick charts.

- **Dynamic Recommendations:**  
  Provides trading recommendations ("Recommended", "Consider", or "Avoid") based on criteria like average volume, IV30/RV30 ratio, and term structure slope.

- **Data Export:**  
  Export analyzed data to CSV for further analysis.

- **Comprehensive Metrics:**  
  Displays metrics including current stock price, market cap, volume, expected move, and more.

For a detailed look at the implementation, check out the main source file:  
[calculator.py](https://github.com/Acelogic/Earnings-Volatility-Calculator/blob/main/calculator.py)

---

## Installation Instructions (Windows)

### Prerequisites

- **Operating System:** Windows 10 or higher
- **Python:** Version 3.7 or later (Python 3.10.11 is recommended for some modules)
- **Internet Connection:** Required to fetch live financial and earnings data

### Step-by-Step Installation

1. **Install Python**

   - Download the latest version of Python from the [official Python website](https://www.python.org/downloads/).
   - Run the installer and **ensure you check "Add Python to PATH"** before clicking “Install Now”.

2. **Open Command Prompt**

   - Press `Win + R`, type `cmd`, and hit Enter to open the Command Prompt.

3. **Clone the Repository (Optional)**

   If you wish to clone the repository locally, run:
   ```bash
   git clone https://github.com/Acelogic/Earnings-Volatility-Calculator.git
   cd Earnings-Volatility-Calculator
   ```

4. **Install Required Python Packages**

   Run the following command in the Command Prompt:  
   ```bash
   pip install yfinance pandas numpy requests beautifulsoup4 matplotlib mplfinance scipy FreeSimpleGUI
   ```

   **Note:**
   - If you encounter issues with installing `FreeSimpleGUI` (as it might be a custom module), replace it with `PySimpleGUI` by modifying the import in the code:

   **Replace this:**
   ```python
   import FreeSimpleGUI as sg
   ```
   **With this:**
   ```python
   import PySimpleGUI as sg
   ```
   - All other packages should install without issues.

5. **Run the Application**

   - Navigate to the directory where the repository is saved (or where you cloned it):  
   ```bash
   cd C:\path\to\your\directory
   ```
   - Run the Python script:  
   ```bash
   python calculator.py
   ```

---

## Usage

- **Single Stock Analysis:**  
  Enter a stock symbol in the GUI input field and click “Analyze” (or press Enter) to view detailed metrics and recommendations.

- **Earnings Scan:**  
  Use the “Choose Date” button to select an earnings date, then click “Scan Earnings”. The tool will fetch and analyze stocks with earnings on the selected date. You can filter the results by earnings time (e.g., Pre Market, Post Market, During Market).

- **Interactive Charting:**  
  Click on any row in the displayed table to open an interactive candlestick chart for that stock.

- **Data Export:**  
  Export the analysis results to a CSV file by clicking the “Export to CSV” button.

---

## Related Tools and Resources

- **Trade Calculator:**  
  - All Python files and library requirements are located in the `trade_calculator` directory.  
  - Built and tested on Python version 3.10.11.  
  - Detailed installation and running instructions are available in this document.  
  - If further assistance is needed, there are many YouTube tutorials available or you can join our Discord for help.

- **Monte Carlo / Backtest Results:**  
  Detailed simulation and backtest results are available here.

- **Trade Tracker Template:**  
  Access the Trade Tracker Template in Google Sheets [here](https://docs.google.com/spreadsheets/).  
  **Instructions:** Make a copy or download it for Excel (currently tested in Google Sheets).

- **YouTube Video:**  
  Watch our demonstration video [here](https://youtube.com/) and don’t forget to subscribe!

---

## Support

For support or questions, feel free to open an issue on our GitHub repository or join our community on Discord.

---

## License

This project is licensed under the MIT License. See the [LICENSE](https://github.com/Acelogic/Earnings-Volatility-Calculator/blob/main/LICENSE) file for details.

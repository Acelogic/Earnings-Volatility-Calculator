"""Interactive candlestick chart rendering."""

from typing import Optional

import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
import mplfinance as mpf
import yfinance as yf

from earnings_calculator.sessions import SessionManager


def show_interactive_chart(
    ticker: str, session_manager: Optional[SessionManager] = None
):
    try:
        from tkinter import messagebox

        st = yf.Ticker(
            ticker,
            session=session_manager.get_yf_session() if session_manager else None,
        )
        hist = st.history(period="1y")
        if hist.empty:
            messagebox.showerror("Error", f"No historical data for {ticker}.")
            return
        mpf.plot(
            hist,
            type="candle",
            style="charles",
            volume=True,
            title=f"{ticker} Chart",
        )
        plt.show()
    except Exception as e:
        from tkinter import messagebox

        messagebox.showerror(
            "Chart Error", f"Error generating chart for {ticker}: {e}"
        )

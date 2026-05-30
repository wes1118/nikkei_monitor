# Nikkei Monitor

A beginner-friendly monitoring tool for Nikkei 225 Mini futures that calculates technical indicators and generates BUY / SELL / WAIT signals.

> **Important:** This project does **NOT** perform automatic trading or order execution. It is a display-only tool for learning and observation purposes.

---

## Project Overview

Nikkei Monitor reads candlestick (OHLCV) data, computes three technical indicators — VWAP, CVD, and Volume Average — and uses them together to produce simple signals. Results are printed to the terminal in a color-coded table, saved as a chart image (`chart.png`), and sent as a Windows desktop notification.

Currently the tool runs on dummy data so you can experiment safely without connecting to a live market feed.

---

## Current Features

| Feature | Description |
|---|---|
| **Real market data** | Fetches live Nikkei 225 data from Yahoo Finance via `yfinance` (ticker: `^N225`) |
| **VWAP** | Volume Weighted Average Price — average price weighted by trading volume, resets each session |
| **CVD** | Cumulative Volume Delta — tracks whether buying or selling pressure is dominant |
| **Volume Average** | 5-bar moving average of volume, used to confirm signal strength |
| **BUY / SELL / WAIT signals** | Signals fire only when all three conditions align (price vs VWAP, CVD direction, and above-average volume) |
| **chart.png generation** | Saves a candlestick chart with VWAP overlay and signal markers to `chart.png` |
| **Windows notifications** | Pops a desktop toast notification when a BUY or SELL signal is detected |

> **Data source note:** Live Nikkei 225 Mini futures (OSE) are not freely available via public APIs. This project uses the **Nikkei 225 Index** (`^N225`) from Yahoo Finance as a price-accurate proxy. To switch to a futures contract, change `TICKER` in `data_source.py` (e.g. `NIY=F` for CME Nikkei Yen futures).

### Signal Logic

| Signal | Conditions |
|---|---|
| **BUY** | Close > VWAP AND CVD > 0 AND Volume > Volume Average |
| **SELL** | Close < VWAP AND CVD < 0 AND Volume > Volume Average |
| **WAIT** | Any other condition |

---

## Installation

### Requirements

- Python 3.10 or later
- Windows OS (for desktop notifications)

### Steps

1. **Clone the repository**

   ```bash
   git clone https://github.com/wesbass1118/nikkei_monitor.git
   cd nikkei_monitor
   ```

2. **Create a virtual environment (recommended)**

   ```bash
   python -m venv .venv
   .venv\Scripts\activate
   ```

3. **Install dependencies**

   ```bash
   pip install -r requirements.txt
   ```

---

## How to Run

```bash
python main.py
```

The program will:

1. Generate dummy candlestick data (20 bars of 5-minute Nikkei 225 Mini data)
2. Calculate VWAP, Volume Average, and CVD
3. Determine BUY / SELL / WAIT signals for each bar
4. Print a color-coded results table to the terminal
5. Save `chart.png` in the project folder
6. Send a Windows desktop notification for the latest signal

---

## Project Structure

```
nikkei_monitor/
├── main.py               # Entry point — orchestrates data flow and display
├── data_source.py        # Fetches real market data from Yahoo Finance
├── indicators.py         # VWAP, Volume Average, and CVD calculations
├── strategy.py           # Signal logic (BUY / SELL / WAIT)
├── chart.py              # Candlestick chart generation (saves chart.png)
├── notifier.py           # Windows desktop notification
├── backtest.py           # Backtest simulator (60-day history, saves backtest_report.txt)
├── requirements.txt      # Python dependencies
├── chart.png             # Generated chart (created on first run)
└── backtest_report.txt   # Backtest results (created on first backtest run)
```

---

## Version History

| Version | Description |
|---|---|
| **v1.0** | Monitoring MVP — terminal output with VWAP, CVD, Volume Average, and signal logic |
| **v1.1** | Chart output — candlestick chart with VWAP overlay saved as `chart.png` |
| **v1.2** | Windows notifications — desktop toast alert when BUY or SELL signal fires |
| **v1.3** | Real market data — replaced dummy data with Yahoo Finance feed via `yfinance` (`data_source.py`) |
| **v1.4** | Backtesting — `backtest.py` simulates BUY/SELL signals on 60 days of history and saves `backtest_report.txt` |

---

## Future Roadmap

- **LINE Messaging API notifications** — Send signals to your phone via LINE
- **AI decision engine** — Use a language model to add context-aware commentary on signals

---

## Dependencies

```
pandas
tabulate
colorama
matplotlib
```

Install all at once with `pip install -r requirements.txt`.

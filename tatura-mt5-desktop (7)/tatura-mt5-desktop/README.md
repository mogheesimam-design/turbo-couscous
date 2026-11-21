# Tatura MT5 Desktop Bridge

A native Windows computer application that connects to your running **MetaTrader 5** terminal, scans **3 live markets**, triggers **EMA + RSI + ATR** signals, fetches the exact stake amount from your **Cloudflare Pages Tatura Model website** (`GET /api/bot/next`), executes the trade on MT5, and pushes the win/loss outcome back to the website (`POST /api/bot/result`).

## Requirements
- Windows 10 / 11 with **MetaTrader 5** terminal installed and logged into your trading account
- **Algo Trading** enabled inside MetaTrader 5 (toolbar button turned green)
- **Python 3.10 – 3.12 (64-bit)** (required by MetaTrader's official `MetaTrader5` Python package)
- Your Cloudflare Pages deployment URL and `BOT_TOKEN` secret (minimum 20 characters, configured in Cloudflare Pages environment variables)

## Quick Start
1. Double-click `Launch_Tatura_MT5.bat` (or run `pip install -r requirements.txt` and `python tatura_desktop.py`).
2. Enter your Cloudflare Pages URL (e.g., `https://your-app.pages.dev`), your `BOT_TOKEN`, and optional website username.
3. Configure your 3 MT5 market symbols (for example `EURUSD`, `GBPUSD`, `XAUUSD`), timeframe (`M5`), Stop Loss points, and TP mode (`match_payout` automatically sets Take Profit distance using your website's `payout_pct`).
4. Click **Save Settings**, **Connect MT5**, and **Start Scanner**.
5. On your Cloudflare Pages website, open the **Admin** tab to turn the Trading Bot **ON**, and press **Start session** on the **Session** tab.

## Local Bridge Mode
While `tatura_desktop.py` is running, it also serves a local bridge at `http://127.0.0.1:8765`, allowing the web dashboard to monitor live MT5 ticks, account equity, and positions directly from your browser.

## Headless 24/7 VPS Mode
```bash
python tatura_cli.py
```

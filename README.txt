# Tatura Bot — MT5 Demo Build

## Included
- `gui.py`: Windows desktop GUI for manual settings and start/stop.
- `engine.py`: closed-candle EMA signal engine, ATR stop/TP sizing, MT5 demo order execution.
- `config.json`: editable defaults.
- `run.bat`: launches the GUI.
- `requirements.txt`: Python dependencies.

## Important safety scope
This build is intentionally DEMO ONLY. It refuses MT5 accounts whose `trade_mode` is not DEMO (0). It does not contain Cloudflare sync, Masaniello/session money management, account fleet management, Quotex integration, or installer packaging. It uses a simple configurable percentage-of-equity risk model for demo testing, capped at 1% per trade. Do not use on a live account.

## Install
1. Install 64-bit Python on Windows and MT5 desktop terminal.
2. Open MT5 and log into a DEMO account. Enable Algo Trading in MT5.
3. Open Command Prompt in this folder and run:
   `python -m pip install -r requirements.txt`
4. Double-click `run.bat`.
5. Set the symbol exactly as it appears in Market Watch. Optionally fill MT5 login/server/password; password is never saved. If fields are blank, log in through the MT5 terminal first.
6. Click **Test MT5 connection**. Confirm the log explicitly says DEMO.
7. Review all strategy and risk settings, then click **Start Bot**.

## Strategy behavior
- Signals are generated only once per newly closed candle.
- CALL means BUY; PUT means SELL.
- EMA crossover: fast EMA crosses slow EMA.
- Optional trend filter uses the trend EMA.
- ATR stop distance = ATR(period) × ATR multiplier.
- Take-profit distance = stop distance × reward/risk.
- Lot size is calculated from the configured equity-risk percentage using MT5's `order_calc_profit`, then rounded down to broker volume steps.
- At most one open Tatura position (matching the configured magic number) is allowed at a time.

## Operational notes
- Keep Windows awake, MT5 open, logged in and connected. For 24/5 operation, deploy to a Windows VPS after demo validation.
- If market data is unavailable or internet/MT5 disconnects, no valid new signal/order can be generated.
- Stop button stops future bot actions; it does not forcibly close an already-open position.
- This is an engineering prototype, not evidence of strategy profitability. Validate on demo and check vProp rules before any live use.

# Tatura market analyser and demo execution engine.
# Closed-candle signals only. Live/real accounts are deliberately blocked.

import time
import threading
import MetaTrader5 as mt5
import pandas as pd

TF = {
    "M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15, "M30": mt5.TIMEFRAME_M30,
    "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4,
}

DEFAULTS = {
    "mt5_path": "",
    "mt5_login": "",
    "mt5_server": "",
    "symbol": "EURUSD",
    "timeframe": "M1",
    "ema_fast": 9,
    "ema_slow": 21,
    "ema_trend": 200,
    "use_trend_filter": True,
    "max_spread_points": 20,
    "poll_seconds": 2,
    "risk_percent": 0.25,
    "atr_period": 14,
    "atr_multiplier": 1.5,
    "reward_risk": 1.0,
    "magic": 28001,
    "deviation_points": 20,
}

def analyse(cfg):
    rates = mt5.copy_rates_from_pos(cfg["symbol"], TF[cfg["timeframe"]], 0, 650)
    if rates is None or len(rates) < max(cfg["ema_trend"] + 5, cfg["atr_period"] + 5):
        return None
    df = pd.DataFrame(rates).iloc[:-1].copy()  # exclude forming candle
    if len(df) < max(cfg["ema_trend"] + 2, cfg["atr_period"] + 2):
        return None
    df["fast"] = df["close"].ewm(span=cfg["ema_fast"], adjust=False).mean()
    df["slow"] = df["close"].ewm(span=cfg["ema_slow"], adjust=False).mean()
    df["trend"] = df["close"].ewm(span=cfg["ema_trend"], adjust=False).mean()
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs()
    ], axis=1).max(axis=1)
    df["atr"] = tr.rolling(cfg["atr_period"]).mean()
    prev, last = df.iloc[-2], df.iloc[-1]
    info = mt5.symbol_info(cfg["symbol"])
    if info is None or pd.isna(last["atr"]) or float(last["atr"]) <= 0:
        return None
    return {
        "time": int(last["time"]), "close": float(last["close"]),
        "fast": float(last["fast"]), "slow": float(last["slow"]),
        "trend": float(last["trend"]), "prev_fast": float(prev["fast"]),
        "prev_slow": float(prev["slow"]), "atr": float(last["atr"]),
        "spread_points": int(info.spread),
    }

def generate_signal(m, cfg):
    up = m["prev_fast"] <= m["prev_slow"] and m["fast"] > m["slow"]
    down = m["prev_fast"] >= m["prev_slow"] and m["fast"] < m["slow"]
    if not up and not down:
        return None, "no crossover"
    if m["spread_points"] > cfg["max_spread_points"]:
        return None, "spread too wide"
    if up:
        if cfg["use_trend_filter"] and m["close"] < m["trend"]:
            return None, "CALL filtered by trend EMA"
        return "CALL", "fast EMA crossed above slow EMA"
    if cfg["use_trend_filter"] and m["close"] > m["trend"]:
        return None, "PUT filtered by trend EMA"
    return "PUT", "fast EMA crossed below slow EMA"

def connect(cfg, password):
    kwargs = {}
    if cfg.get("mt5_path", "").strip():
        kwargs["path"] = cfg["mt5_path"].strip()
    login = str(cfg.get("mt5_login", "")).strip()
    server = str(cfg.get("mt5_server", "")).strip()
    if login and server and password:
        kwargs.update(login=int(login), password=password, server=server)
    if not mt5.initialize(**kwargs):
        raise RuntimeError("MT5 initialize failed: %s" % (mt5.last_error(),))
    account = mt5.account_info()
    if account is None:
        mt5.shutdown()
        raise RuntimeError("MT5 terminal is open but no account is logged in.")
    # Safety gate: MT5 account trade_mode 0 is DEMO. Never trade contest/real.
    if int(getattr(account, "trade_mode", -1)) != 0:
        mt5.shutdown()
        raise RuntimeError("SAFETY BLOCK: Tatura only runs on a DEMO account. Current account is not demo.")
    if not mt5.symbol_select(cfg["symbol"], True):
        mt5.shutdown()
        raise RuntimeError("Cannot select symbol: %s" % cfg["symbol"])
    return account

def _floor_volume(value, step):
    import math
    return math.floor((value + 1e-12) / step) * step

def calculate_volume(symbol, order_type, entry, stop, risk_cash):
    info = mt5.symbol_info(symbol)
    if info is None:
        raise RuntimeError("No symbol information.")
    loss = mt5.order_calc_profit(order_type, symbol, 1.0, entry, stop)
    if loss is None or abs(float(loss)) <= 0:
        raise RuntimeError("Could not calculate 1-lot stop-loss risk: %s" % (mt5.last_error(),))
    raw = risk_cash / abs(float(loss))
    volume = _floor_volume(raw, float(info.volume_step))
    volume = min(volume, float(info.volume_max))
    if volume < float(info.volume_min):
        raise RuntimeError("Calculated volume %.4f is below broker minimum %.4f; trade skipped." %
                           (volume, info.volume_min))
    return round(volume, 8)

def bot_positions(magic):
    positions = mt5.positions_get()
    if positions is None:
        return []
    return [p for p in positions if int(getattr(p, "magic", 0)) == int(magic)]

def place_trade(signal, m, cfg, log):
    symbol = cfg["symbol"]
    info = mt5.symbol_info(symbol)
    tick = mt5.symbol_info_tick(symbol)
    account = mt5.account_info()
    terminal = mt5.terminal_info()
    if info is None or tick is None or account is None:
        raise RuntimeError("Missing MT5 symbol/tick/account data.")
    if terminal is None or not terminal.trade_allowed or not account.trade_allowed:
        raise RuntimeError("MT5 algorithmic trading is disabled.")
    if bot_positions(cfg["magic"]):
        log("Trade skipped: Tatura already has an open position.")
        return None

    is_buy = signal == "CALL"
    order_type = mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL
    entry = float(tick.ask if is_buy else tick.bid)
    distance = float(m["atr"]) * float(cfg["atr_multiplier"])
    if distance <= 0:
        raise RuntimeError("Invalid ATR stop distance.")
    digits = int(info.digits)
    sl = round(entry - distance if is_buy else entry + distance, digits)
    tp_distance = distance * float(cfg["reward_risk"])
    tp = round(entry + tp_distance if is_buy else entry - tp_distance, digits)

    risk_cash = float(account.equity) * float(cfg["risk_percent"]) / 100.0
    volume = calculate_volume(symbol, order_type, entry, sl, risk_cash)
    margin = mt5.order_calc_margin(order_type, symbol, volume, entry)
    if margin is None or float(margin) > float(account.margin_free):
        raise RuntimeError("Insufficient free margin; trade skipped.")

    request_base = {
        "action": mt5.TRADE_ACTION_DEAL, "symbol": symbol, "volume": volume,
        "type": order_type, "price": entry, "sl": sl, "tp": tp,
        "deviation": int(cfg["deviation_points"]), "magic": int(cfg["magic"]),
        "comment": "Tatura demo",
        "type_time": mt5.ORDER_TIME_GTC,
    }
    # Try common filling policies; broker may only accept one.
    last_result = None
    for filling in (mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_RETURN):
        request = dict(request_base, type_filling=filling)
        last_result = mt5.order_send(request)
        if last_result is not None and last_result.retcode == mt5.TRADE_RETCODE_DONE:
            log("%s placed: %s lots | entry %.*f | SL %.*f | TP %.*f | risk about %.2f" %
                (signal, volume, digits, entry, digits, sl, digits, tp, risk_cash))
            return last_result
        if last_result is not None and last_result.retcode not in (
            getattr(mt5, "TRADE_RETCODE_INVALID_FILL", 10030),
            getattr(mt5, "TRADE_RETCODE_INVALID", 10013),
        ):
            break
    if last_result is None:
        raise RuntimeError("order_send returned None: %s" % (mt5.last_error(),))
    raise RuntimeError("Order rejected: retcode=%s comment=%s" %
                       (last_result.retcode, getattr(last_result, "comment", "")))

def run(cfg, password, stop_event, log, on_status=None, on_signal=None):
    account = connect(cfg, password)
    mode = "DEMO"
    log("Connected to DEMO account %s | %s | balance %.2f | equity %.2f" %
        (account.login, account.server, account.balance, account.equity))
    if on_status:
        on_status("Connected — DEMO")
    log("Watching %s %s; EMA %s/%s; ATR(%s) × %s" %
        (cfg["symbol"], cfg["timeframe"], cfg["ema_fast"], cfg["ema_slow"],
         cfg["atr_period"], cfg["atr_multiplier"]))
    last_candle = None
    try:
        while not stop_event.is_set():
            try:
                # Re-check account mode on every cycle, not only at startup.
                acc = mt5.account_info()
                if acc is None or int(getattr(acc, "trade_mode", -1)) != 0:
                    raise RuntimeError("DEMO account connection lost or account mode changed; stopping.")
                m = analyse(cfg)
                if m and m["time"] != last_candle:
                    last_candle = m["time"]
                    signal, reason = generate_signal(m, cfg)
                    stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(m["time"]))
                    log("%s | close %.5f | EMA %.5f/%.5f | ATR %.5f | spread %s | %s" %
                        (stamp, m["close"], m["fast"], m["slow"], m["atr"],
                         m["spread_points"], signal or reason))
                    if on_signal:
                        on_signal(signal or "WAIT", reason)
                    if signal:
                        place_trade(signal, m, cfg, log)
            except Exception as exc:
                log("ERROR: %s" % exc)
                if "DEMO account" in str(exc) or "account mode" in str(exc):
                    break
            stop_event.wait(max(1, int(cfg["poll_seconds"])))
    finally:
        mt5.shutdown()
        log("MT5 connection closed.")
        if on_status:
            on_status("Stopped")

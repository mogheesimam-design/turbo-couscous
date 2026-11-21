from typing import Any, Dict, List


def calc_ema(values: List[float], period: int) -> List[float]:
    if not values or period <= 1:
        return list(values)
    k = 2.0 / (period + 1)
    out = [values[0]]
    for price in values[1:]:
        out.append(price * k + out[-1] * (1.0 - k))
    return out


def calc_rsi(closes: List[float], period: int = 14) -> float:
    if len(closes) <= period:
        return 50.0
    gains = 0.0
    losses = 0.0
    for i in range(1, period + 1):
        diff = closes[i] - closes[i - 1]
        if diff >= 0:
            gains += diff
        else:
            losses -= diff
    avg_gain = gains / period
    avg_loss = losses / period
    for i in range(period + 1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gain = diff if diff > 0 else 0.0
        loss = -diff if diff < 0 else 0.0
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def calc_atr(candles: List[Dict[str, float]], period: int = 14) -> float:
    if len(candles) < 2:
        return 0.0
    trs: List[float] = []
    for i in range(1, len(candles)):
        h = candles[i]["high"]
        l = candles[i]["low"]
        pc = candles[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if not trs:
        return 0.0
    window = trs[-period:] if len(trs) >= period else trs
    return sum(window) / len(window)


def evaluate_market(
    symbol: str,
    candles: List[Dict[str, float]],
    bid: float,
    ask: float,
    spread_points: int,
    cfg: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Evaluates a market using EMA fast/slow crossover & trend momentum + RSI + ATR filter.
    Uses closed candles (-2 vs -3) to avoid intrabar repainting.
    strategy_mode:
      - 'strict': requires fresh EMA fast/slow crossover + RSI filter
      - 'balanced': triggers on EMA crossover OR clean trend continuation candle + RSI + ATR filter
    """
    if len(candles) < 30:
        return {
            "symbol": symbol,
            "bid": bid,
            "ask": ask,
            "spread_points": spread_points,
            "ema_fast": 0.0,
            "ema_slow": 0.0,
            "rsi": 50.0,
            "atr": 0.0,
            "signal": "NONE",
            "reason": "Waiting for sufficient candle history",
            "candle_time": 0,
            "closes": [],
        }

    ema_fast_p = max(2, int(cfg.get("ema_fast", 9)))
    ema_slow_p = max(ema_fast_p + 1, int(cfg.get("ema_slow", 21)))
    rsi_p = max(2, int(cfg.get("rsi_period", 14)))
    rsi_buy_min = float(cfg.get("rsi_buy_min", 52))
    rsi_buy_max = float(cfg.get("rsi_buy_max", 72))
    rsi_sell_max = float(cfg.get("rsi_sell_max", 48))
    rsi_sell_min = float(cfg.get("rsi_sell_min", 28))
    mode = str(cfg.get("strategy_mode", "balanced")).lower()

    closes = [float(c["close"]) for c in candles]
    fast_series = calc_ema(closes, ema_fast_p)
    slow_series = calc_ema(closes, ema_slow_p)

    f_prev, f_curr = fast_series[-3], fast_series[-2]
    s_prev, s_curr = slow_series[-3], slow_series[-2]
    c_curr = candles[-2]
    rsi_val = calc_rsi(closes[:-1], rsi_p)
    atr_val = calc_atr(candles[:-1], 14)

    bullish_cross = f_prev <= s_prev and f_curr > s_curr
    bearish_cross = f_prev >= s_prev and f_curr < s_curr
    bullish_trend = f_curr > s_curr and (f_curr - f_prev) > 0 and c_curr["close"] > c_curr["open"]
    bearish_trend = f_curr < s_curr and (f_curr - f_prev) < 0 and c_curr["close"] < c_curr["open"]
    body = abs(c_curr["close"] - c_curr["open"])
    volatility_ok = atr_val > 0 and body >= atr_val * 0.2

    bull_setup = bullish_cross if mode == "strict" else (bullish_cross or bullish_trend)
    bear_setup = bearish_cross if mode == "strict" else (bearish_cross or bearish_trend)

    signal = "NONE"
    if bull_setup and rsi_buy_min <= rsi_val <= rsi_buy_max and volatility_ok:
        signal = "BUY"
        reason = (
            f"EMA({ema_fast_p}) bullish cross & RSI {rsi_val:.1f}"
            if bullish_cross
            else f"EMA({ema_fast_p}>{ema_slow_p}) bullish momentum & RSI {rsi_val:.1f}"
        )
    elif bear_setup and rsi_sell_min <= rsi_val <= rsi_sell_max and volatility_ok:
        signal = "SELL"
        reason = (
            f"EMA({ema_fast_p}) bearish cross & RSI {rsi_val:.1f}"
            if bearish_cross
            else f"EMA({ema_fast_p}<{ema_slow_p}) bearish momentum & RSI {rsi_val:.1f}"
        )
    else:
        if f_curr > s_curr:
            reason = f"Uptrend EMA({ema_fast_p}>{ema_slow_p}) | RSI {rsi_val:.1f}"
        else:
            reason = f"Downtrend EMA({ema_fast_p}<{ema_slow_p}) | RSI {rsi_val:.1f}"

    return {
        "symbol": symbol,
        "bid": bid,
        "ask": ask,
        "spread_points": spread_points,
        "ema_fast": round(f_curr, 6),
        "ema_slow": round(s_curr, 6),
        "rsi": round(rsi_val, 2),
        "atr": round(atr_val, 6),
        "signal": signal,
        "reason": reason,
        "candle_time": int(c_curr.get("time", 0)),
        "closes": [round(x, 6) for x in closes[-30:]],
    }

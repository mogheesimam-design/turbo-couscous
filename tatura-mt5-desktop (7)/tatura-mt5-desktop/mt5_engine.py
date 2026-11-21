import math
import time
from typing import Any, Dict, List, Optional, Tuple

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None


TIMEFRAME_MAP = {
    "M1": 1,
    "M5": 5,
    "M15": 15,
    "M30": 30,
    "H1": 16385,
    "H4": 16388,
    "D1": 16408,
}


class MT5Error(Exception):
    pass


class MT5Engine:
    def __init__(self, mt5_path: str = ""):
        self.mt5_path = mt5_path.strip()
        self.connected = False
        self.resolved_symbols: Dict[str, str] = {}

    def connect(self) -> Dict[str, Any]:
        if mt5 is None:
            raise MT5Error("MetaTrader5 Python package is not installed. Run: pip install -r requirements.txt")
        ok = mt5.initialize(path=self.mt5_path) if self.mt5_path else mt5.initialize()
        if not ok:
            err = mt5.last_error()
            raise MT5Error(f"mt5.initialize() failed: {err}. Make sure MetaTrader 5 terminal is open and logged in.")
        self.connected = True
        return self.get_account_info()

    def shutdown(self) -> None:
        if mt5 is not None and self.connected:
            mt5.shutdown()
        self.connected = False

    def get_account_info(self) -> Dict[str, Any]:
        if not self.connected or mt5 is None:
            raise MT5Error("MT5 is not connected.")
        acc = mt5.account_info()
        term = mt5.terminal_info()
        if acc is None:
            raise MT5Error(f"Could not read MT5 account_info: {mt5.last_error()}")
        return {
            "login": int(acc.login),
            "server": str(acc.server),
            "name": str(acc.name),
            "currency": str(acc.currency),
            "balance": float(acc.balance),
            "equity": float(acc.equity),
            "margin_free": float(acc.margin_free),
            "leverage": int(acc.leverage),
            "trade_allowed": bool(term.trade_allowed if term else acc.trade_allowed),
        }

    def resolve_symbol(self, requested: str) -> str:
        req = requested.strip()
        if req in self.resolved_symbols:
            return self.resolved_symbols[req]
        info = mt5.symbol_info(req)
        if info is not None:
            mt5.symbol_select(req, True)
            self.resolved_symbols[req] = req
            return req
        # Try case-insensitive prefix match for broker suffixes (e.g. EURUSDm, EURUSD.raw)
        all_syms = mt5.symbols_get() or []
        req_up = req.upper()
        for s in all_syms:
            if s.name.upper().startswith(req_up):
                mt5.symbol_select(s.name, True)
                self.resolved_symbols[req] = s.name
                return s.name
        raise MT5Error(f"Symbol '{req}' not found in MT5 Market Watch.")

    def _tf_const(self, tf_str: str) -> int:
        if mt5 is not None:
            mapping = {
                "M1": mt5.TIMEFRAME_M1,
                "M5": mt5.TIMEFRAME_M5,
                "M15": mt5.TIMEFRAME_M15,
                "M30": mt5.TIMEFRAME_M30,
                "H1": mt5.TIMEFRAME_H1,
                "H4": mt5.TIMEFRAME_H4,
                "D1": mt5.TIMEFRAME_D1,
            }
            return mapping.get(tf_str.upper(), mt5.TIMEFRAME_M5)
        return TIMEFRAME_MAP.get(tf_str.upper(), 5)

    def fetch_market_data(self, requested_symbol: str, timeframe: str = "M5", count: int = 100) -> Tuple[str, List[Dict[str, float]], float, float, int]:
        sym = self.resolve_symbol(requested_symbol)
        tf = self._tf_const(timeframe)
        rates = mt5.copy_rates_from_pos(sym, tf, 0, count)
        if rates is None or len(rates) == 0:
            raise MT5Error(f"No candle rates returned for {sym} ({timeframe}): {mt5.last_error()}")
        tick = mt5.symbol_info_tick(sym)
        info = mt5.symbol_info(sym)
        if tick is None or info is None:
            raise MT5Error(f"No tick/symbol info for {sym}")
        point = float(info.point or 0.00001)
        spread_pts = int(round((tick.ask - tick.bid) / point)) if point > 0 else 0
        candles = [
            {
                "time": int(r["time"]),
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
            }
            for r in rates
        ]
        return sym, candles, float(tick.bid), float(tick.ask), spread_pts

    def calculate_lot_size(
        self,
        sym: str,
        stake_amount: float,
        sl_points: int,
        sizing_mode: str = "risk_from_stake",
        lot_per_100: float = 0.05,
    ) -> float:
        info = mt5.symbol_info(sym)
        if info is None:
            raise MT5Error(f"Symbol info missing for {sym}")

        if sizing_mode == "lot_per_100":
            raw_lots = (max(0.0, stake_amount) / 100.0) * float(lot_per_100)
        else:
            tick_val = float(info.trade_tick_value_loss or info.trade_tick_value or 1.0)
            tick_size = float(info.trade_tick_size or info.point or 0.00001)
            point = float(info.point or 0.00001)
            value_per_point_per_lot = tick_val * (point / tick_size) if tick_size > 0 else tick_val
            risk_per_lot = max(1e-6, float(sl_points) * value_per_point_per_lot)
            raw_lots = max(0.0, stake_amount) / risk_per_lot

        v_min = float(info.volume_min or 0.01)
        v_max = float(info.volume_max or 100.0)
        v_step = float(info.volume_step or 0.01)
        steps = math.floor(raw_lots / v_step)
        lots = max(v_min, min(v_max, round(steps * v_step, 4)))
        return lots

    def _filling_mode(self, info: Any) -> int:
        fm = int(getattr(info, "filling_mode", 0))
        if fm & 1:
            return mt5.ORDER_FILLING_FOK
        if fm & 2:
            return mt5.ORDER_FILLING_IOC
        return mt5.ORDER_FILLING_RETURN

    def open_trade(
        self,
        requested_symbol: str,
        direction: str,
        stake_amount: float,
        payout_pct: float,
        sl_points: int,
        tp_mode: str,
        tp_points: int,
        sizing_mode: str,
        lot_per_100: float,
        magic: int,
        deviation: int,
        comment: str,
    ) -> Dict[str, Any]:
        sym = self.resolve_symbol(requested_symbol)
        info = mt5.symbol_info(sym)
        tick = mt5.symbol_info_tick(sym)
        if info is None or tick is None:
            raise MT5Error(f"Cannot fetch tick/info for {sym}")

        point = float(info.point)
        digits = int(info.digits)
        lots = self.calculate_lot_size(sym, stake_amount, sl_points, sizing_mode, lot_per_100)

        effective_tp_pts = (
            max(10, int(round(sl_points * (float(payout_pct) / 100.0))))
            if tp_mode == "match_payout"
            else max(10, int(tp_points))
        )

        # Ensure SL/TP respect broker stops_level
        stops_lvl = int(getattr(info, "trade_stops_level", 0) or 0)
        min_dist = max(sl_points, stops_lvl + 5) * point
        tp_dist = max(effective_tp_pts, stops_lvl + 5) * point

        if direction == "BUY":
            order_type = mt5.ORDER_TYPE_BUY
            price = float(tick.ask)
            sl = round(price - min_dist, digits)
            tp = round(price + tp_dist, digits)
        else:
            order_type = mt5.ORDER_TYPE_SELL
            price = float(tick.bid)
            sl = round(price + min_dist, digits)
            tp = round(price - tp_dist, digits)

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": sym,
            "volume": lots,
            "type": order_type,
            "price": price,
            "sl": sl,
            "tp": tp,
            "deviation": int(deviation),
            "magic": int(magic),
            "comment": comment[:31],
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": self._filling_mode(info),
        }

        res = mt5.order_send(request)
        if res is None:
            raise MT5Error(f"order_send returned None: {mt5.last_error()}")
        if res.retcode != mt5.TRADE_RETCODE_DONE:
            raise MT5Error(f"MT5 order rejected ({res.retcode}): {res.comment}")

        pos_id = int(res.order)
        # Find exact position ticket by order/magic if needed
        time.sleep(0.2)
        positions = mt5.positions_get(symbol=sym) or []
        for p in positions:
            if int(p.magic) == int(magic):
                pos_id = int(p.ticket)
                break

        return {
            "symbol": sym,
            "direction": direction,
            "volume": lots,
            "order_ticket": int(res.order),
            "position_id": pos_id,
            "entry_price": float(res.price or price),
            "sl": sl,
            "tp": tp,
            "opened_at": time.time(),
        }

    def close_position(self, position_id: int, magic: int, deviation: int) -> None:
        positions = mt5.positions_get(ticket=position_id)
        if not positions:
            return
        pos = positions[0]
        sym = pos.symbol
        tick = mt5.symbol_info_tick(sym)
        info = mt5.symbol_info(sym)
        if tick is None or info is None:
            return
        is_buy = pos.type == mt5.POSITION_TYPE_BUY
        close_type = mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY
        price = float(tick.bid if is_buy else tick.ask)
        req = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": sym,
            "volume": float(pos.volume),
            "type": close_type,
            "position": int(pos.ticket),
            "price": price,
            "deviation": int(deviation),
            "magic": int(magic),
            "comment": "Tatura expiry close",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": self._filling_mode(info),
        }
        mt5.order_send(req)

    def inspect_trade(self, trade: Dict[str, Any], max_hold_minutes: int, magic: int, deviation: int) -> Dict[str, Any]:
        pos_id = int(trade["position_id"])
        positions = mt5.positions_get(ticket=pos_id)
        if positions and len(positions) > 0:
            p = positions[0]
            elapsed_min = (time.time() - float(trade["opened_at"])) / 60.0
            if max_hold_minutes > 0 and elapsed_min >= max_hold_minutes:
                self.close_position(pos_id, magic, deviation)
                time.sleep(0.3)
            else:
                return {
                    "closed": False,
                    "floating_profit": float(p.profit + p.swap),
                    "current_price": float(p.price_current),
                }

        deals = mt5.history_deals_get(position=pos_id)
        if not deals:
            return {"closed": False, "floating_profit": 0.0, "current_price": trade["entry_price"]}

        net_profit = 0.0
        has_exit = False
        for d in deals:
            net_profit += float(d.profit) + float(d.swap) + float(d.commission)
            if d.entry in (mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_OUT_BY):
                has_exit = True

        if not has_exit:
            return {"closed": False, "floating_profit": net_profit, "current_price": trade["entry_price"]}

        return {
            "closed": True,
            "profit": round(net_profit, 2),
            "result": "win" if net_profit >= 0 else "loss",
        }

import json
import os
import threading
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from cloudflare_client import TaturaWebClient, TaturaWebError
from mt5_engine import MT5Engine, MT5Error
from signal_engine import evaluate_market


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
EXAMPLE_FILE = os.path.join(BASE_DIR, "config.example.json")


def _default_config() -> Dict[str, Any]:
    return {
        "cloudflare_url": "https://your-tatura-site.pages.dev",
        "bot_token": "PASTE_YOUR_BOT_TOKEN_HERE",
        "website_user": "",
        "markets": ["EURUSD", "GBPUSD", "XAUUSD"],
        "timeframe": "M5",
        "strategy_mode": "balanced",
        "scan_interval_sec": 2,
        "sl_points": 150,
        "tp_mode": "match_payout",
        "tp_points": 150,
        "max_hold_minutes": 0,
        "sizing_mode": "risk_from_stake",
        "lot_per_100": 0.05,
        "ema_fast": 9,
        "ema_slow": 21,
        "rsi_period": 14,
        "rsi_buy_min": 52,
        "rsi_buy_max": 72,
        "rsi_sell_max": 48,
        "rsi_sell_min": 28,
        "magic_number": 774201,
        "deviation_points": 20,
        "auto_trade": True,
        "bridge_port": 8765,
        "mt5_path": "",
    }


def load_config() -> Dict[str, Any]:
    cfg = _default_config()
    for path in (CONFIG_FILE, EXAMPLE_FILE):
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8-sig") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    cfg.update(loaded)
                break
            except Exception:
                continue
    if not isinstance(cfg.get("markets"), list) or len(cfg["markets"]) < 3:
        cfg["markets"] = ["EURUSD", "GBPUSD", "XAUUSD"]
    return cfg


def save_config(cfg: Dict[str, Any]) -> None:
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


class TaturaBotCoordinator:
    def __init__(self, on_update: Optional[Callable[[], None]] = None):
        self.cfg: Dict[str, Any] = load_config()
        self.mt5 = MT5Engine(str(self.cfg.get("mt5_path", "")))
        self.web = self._make_web_client()
        self.on_update = on_update

        self.lock = threading.Lock()
        self.running = False
        self.thread: Optional[threading.Thread] = None

        self.account: Optional[Dict[str, Any]] = None
        self.website_state: Dict[str, Any] = {
            "connected": False,
            "go": False,
            "reason": "Not synced yet",
            "session_id": None,
            "seq": None,
            "stake_amount": 0.0,
            "stake_pct": 0.0,
            "capital": 0.0,
            "payout_pct": 80.0,
            "wins": 0,
            "losses": 0,
            "last_sync": None,
        }
        self.market_snapshots: List[Dict[str, Any]] = []
        self.active_trade: Optional[Dict[str, Any]] = None
        self.trade_history: List[Dict[str, Any]] = []
        self.logs: List[Dict[str, str]] = []
        self.last_triggered_candle: Dict[str, int] = {}

    def _make_web_client(self) -> TaturaWebClient:
        return TaturaWebClient(
            base_url=str(self.cfg.get("cloudflare_url", "")),
            bot_token=str(self.cfg.get("bot_token", "")),
            user=str(self.cfg.get("website_user", "")),
        )

    def reload_config(self, new_cfg: Dict[str, Any]) -> None:
        with self.lock:
            self.cfg = dict(new_cfg)
            save_config(self.cfg)
            self.web = self._make_web_client()
            self.mt5.mt5_path = str(self.cfg.get("mt5_path", ""))
            self.mt5.resolved_symbols.clear()
        self.log("INFO", "Configuration saved and reloaded.")

    def log(self, level: str, message: str) -> None:
        entry = {
            "time": datetime.now().strftime("%H:%M:%S"),
            "level": level,
            "message": message,
        }
        with self.lock:
            self.logs.insert(0, entry)
            self.logs = self.logs[:150]
        if self.on_update:
            try:
                self.on_update()
            except Exception:
                pass

    def _apply_website_payload(self, data: Dict[str, Any]) -> Dict[str, Any]:
        with self.lock:
            self.website_state = {
                "connected": True,
                "go": bool(data.get("go")),
                "reason": str(data.get("reason") or ("Ready to trade" if data.get("go") else "Stopped")),
                "session_id": data.get("session_id"),
                "seq": data.get("seq"),
                "stake_amount": float(data.get("stake_amount") or 0.0),
                "stake_pct": float(data.get("stake_pct") or 0.0),
                "capital": float(data.get("capital") or 0.0),
                "payout_pct": float(data.get("payout_pct") or 80.0),
                "wins": int(data.get("wins") or 0),
                "losses": int(data.get("losses") or 0),
                "last_sync": datetime.now().strftime("%H:%M:%S"),
            }
            return dict(self.website_state)

    def sync_website_once(self) -> Dict[str, Any]:
        try:
            data = self.web.get_next_stake()
            return self._apply_website_payload(data)
        except TaturaWebError as exc:
            with self.lock:
                self.website_state["connected"] = False
                self.website_state["go"] = False
                self.website_state["reason"] = str(exc)
                self.website_state["last_sync"] = datetime.now().strftime("%H:%M:%S")
            raise

    def connect_mt5(self) -> Dict[str, Any]:
        info = self.mt5.connect()
        with self.lock:
            self.account = info
        self.log("INFO", f"Connected to MT5 #{info['login']} ({info['server']}) | Balance {info['balance']:.2f} {info['currency']}")
        return info

    def start(self) -> None:
        if self.running:
            return
        if not self.mt5.connected:
            self.connect_mt5()
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        self.log("INFO", "3-Market live scanner started.")

    def stop(self) -> None:
        self.running = False
        self.log("INFO", "Scanner paused.")

    def _execute_from_website(self, symbol: str, direction: str, reason: str, snap: Optional[Dict[str, Any]] = None) -> None:
        # 1. Push signal to website if upgraded endpoint exists; otherwise read /api/bot/next
        signal_payload = {
            "symbol": symbol,
            "direction": direction,
            "timeframe": str(self.cfg.get("timeframe", "M5")),
            "price": (snap.get("ask") if direction == "BUY" else snap.get("bid")) if snap else 0.0,
            "rsi": snap.get("rsi", 50.0) if snap else 50.0,
            "reason": reason,
        }
        nxt = None
        try:
            with self.lock:
                mkts_copy = list(self.market_snapshots)
            sig_resp = self.web.push_signal(mkts_copy, signal_payload)
            if sig_resp and "go" in sig_resp:
                nxt = sig_resp
        except TaturaWebError:
            nxt = None

        if nxt is None:
            nxt = self.web.get_next_stake()

        self._apply_website_payload(nxt)

        if not nxt.get("go"):
            self.log("WARN", f"{symbol} {direction} signal skipped — Website: {nxt.get('reason')}")
            return

        stake = float(nxt["stake_amount"])
        payout = float(nxt.get("payout_pct") or 80.0)
        session_id = int(nxt["session_id"])
        seq = int(nxt["seq"])

        order = self.mt5.open_trade(
            requested_symbol=symbol,
            direction=direction,
            stake_amount=stake,
            payout_pct=payout,
            sl_points=int(self.cfg.get("sl_points", 150)),
            tp_mode=str(self.cfg.get("tp_mode", "match_payout")),
            tp_points=int(self.cfg.get("tp_points", 150)),
            sizing_mode=str(self.cfg.get("sizing_mode", "risk_from_stake")),
            lot_per_100=float(self.cfg.get("lot_per_100", 0.05)),
            magic=int(self.cfg.get("magic_number", 774201)),
            deviation=int(self.cfg.get("deviation_points", 20)),
            comment=f"Tatura #{session_id}.{seq}",
        )

        trade_obj = {
            **order,
            "session_id": session_id,
            "seq": seq,
            "stake_amount": stake,
            "stake_pct": float(nxt.get("stake_pct") or 0.0),
            "payout_pct": payout,
            "signal_reason": reason,
            "floating_profit": 0.0,
            "current_price": order["entry_price"],
        }

        with self.lock:
            self.active_trade = trade_obj

        try:
            self.web.push_trade_open(trade_obj)
        except Exception:
            pass

        self.log(
            "TRADE",
            f"OPEN {order['direction']} {order['symbol']} {order['volume']} lots @ {order['entry_price']} | "
            f"Website Stake ${stake:.2f} (Session #{session_id}, Trade #{seq})",
        )

    def manual_trade(self, symbol: str, direction: str) -> Dict[str, Any]:
        if not self.mt5.connected:
            self.connect_mt5()
        with self.lock:
            if self.active_trade is not None:
                raise MT5Error("An active MT5 trade is already open. Wait for it to close before opening the next sequential trade.")
        self._execute_from_website(symbol, direction.upper(), "Manual execution")
        with self.lock:
            return dict(self.active_trade or {})

    def _loop(self) -> None:
        last_web_sync = 0.0
        while self.running:
            interval = max(1.0, float(self.cfg.get("scan_interval_sec", 2)))
            try:
                if self.mt5.connected:
                    acc = self.mt5.get_account_info()
                    with self.lock:
                        self.account = acc

                markets = [str(m).strip() for m in self.cfg.get("markets", [])[:3] if str(m).strip()]
                tf = str(self.cfg.get("timeframe", "M5"))
                snapshots: List[Dict[str, Any]] = []
                for req_sym in markets:
                    try:
                        sym, candles, bid, ask, spread = self.mt5.fetch_market_data(req_sym, tf, 100)
                        snap = evaluate_market(sym, candles, bid, ask, spread, self.cfg)
                        snap["requested_symbol"] = req_sym
                        snapshots.append(snap)
                    except MT5Error as exc:
                        snapshots.append({
                            "symbol": req_sym,
                            "requested_symbol": req_sym,
                            "bid": 0.0,
                            "ask": 0.0,
                            "spread_points": 0,
                            "ema_fast": 0.0,
                            "ema_slow": 0.0,
                            "rsi": 0.0,
                            "atr": 0.0,
                            "signal": "NONE",
                            "reason": str(exc),
                            "candle_time": 0,
                            "closes": [],
                        })

                with self.lock:
                    self.market_snapshots = snapshots

                if time.time() - last_web_sync >= 3.0:
                    last_web_sync = time.time()
                    try:
                        self.sync_website_once()
                        self.web.push_signal(snapshots, None)
                    except TaturaWebError as exc:
                        self.log("WARN", f"Website sync: {exc}")

                with self.lock:
                    current_trade = dict(self.active_trade) if self.active_trade else None

                if current_trade is not None:
                    status = self.mt5.inspect_trade(
                        current_trade,
                        max_hold_minutes=int(self.cfg.get("max_hold_minutes", 0)),
                        magic=int(self.cfg.get("magic_number", 774201)),
                        deviation=int(self.cfg.get("deviation_points", 20)),
                    )
                    if status.get("closed"):
                        res_str = str(status["result"])
                        profit = float(status["profit"])
                        push_resp = self.web.push_result(
                            session_id=int(current_trade["session_id"]),
                            seq=int(current_trade["seq"]),
                            result=res_str,
                            profit=profit,
                        )
                        closed_record = {
                            **current_trade,
                            "closed_at": datetime.now().strftime("%H:%M:%S"),
                            "profit": profit,
                            "result": res_str,
                            "website_capital_after": push_resp.get("capital"),
                            "stopped": push_resp.get("stopped"),
                        }
                        with self.lock:
                            self.trade_history.insert(0, closed_record)
                            self.trade_history = self.trade_history[:100]
                            self.active_trade = None
                        self.log(
                            "WIN" if res_str == "win" else "LOSS",
                            f"CLOSED {current_trade['symbol']} ({res_str.upper()} {profit:+.2f}) -> "
                            f"Pushed to Website (New Capital: {push_resp.get('capital')})",
                        )
                        if push_resp.get("stopped"):
                            self.log("WARN", f"Website session stopped: {push_resp['stopped']}")
                        try:
                            self.sync_website_once()
                        except Exception:
                            pass
                    else:
                        with self.lock:
                            if self.active_trade:
                                self.active_trade["floating_profit"] = status.get("floating_profit", 0.0)
                                self.active_trade["current_price"] = status.get("current_price", current_trade["entry_price"])
                else:
                    for snap in snapshots:
                        sig = snap.get("signal", "NONE")
                        c_time = int(snap.get("candle_time") or 0)
                        sym = snap["symbol"]
                        if sig in ("BUY", "SELL") and c_time > 0:
                            if self.last_triggered_candle.get(sym) == c_time:
                                continue
                            self.last_triggered_candle[sym] = c_time
                            self.log("SIGNAL", f"{sym} {sig} triggered: {snap['reason']}")
                            if self.cfg.get("auto_trade", True):
                                self._execute_from_website(sym, sig, snap["reason"], snap)
                                break
            except Exception as exc:
                self.log("ERROR", str(exc))

            if self.on_update:
                try:
                    self.on_update()
                except Exception:
                    pass
            time.sleep(interval)

    def state_snapshot(self) -> Dict[str, Any]:
        with self.lock:
            return {
                "running": self.running,
                "mt5_connected": self.mt5.connected,
                "account": self.account,
                "website": dict(self.website_state),
                "markets": list(self.market_snapshots),
                "active_trade": dict(self.active_trade) if self.active_trade else None,
                "history": list(self.trade_history[:30]),
                "logs": list(self.logs[:50]),
                "config": {k: v for k, v in self.cfg.items() if k != "bot_token"},
            }

import json
import os
import threading
import tkinter as tk
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from tkinter import messagebox, ttk
from typing import Any, Dict, Optional

from runner import TaturaBotCoordinator


def start_local_bridge(coordinator: TaturaBotCoordinator, port: int) -> Optional[ThreadingHTTPServer]:
    class BridgeHandler(BaseHTTPRequestHandler):
        def _cors(self) -> None:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")

        def _json(self, data: Dict[str, Any], code: int = 200) -> None:
            body = json.dumps(data).encode("utf-8")
            self.send_response(code)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            return

        def do_OPTIONS(self) -> None:
            self.send_response(204)
            self._cors()
            self.end_headers()

        def do_GET(self) -> None:
            if self.path == "/status":
                self._json(coordinator.state_snapshot())
            else:
                self._json({"error": "Not found"}, 404)

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(length) if length > 0 else b"{}"
            try:
                body = json.loads(raw.decode("utf-8"))
            except Exception:
                body = {}
            try:
                if self.path == "/start":
                    coordinator.start()
                    self._json({"ok": True})
                elif self.path == "/stop":
                    coordinator.stop()
                    self._json({"ok": True})
                elif self.path == "/trade":
                    res = coordinator.manual_trade(str(body.get("symbol", "")), str(body.get("direction", "BUY")))
                    self._json({"ok": True, "trade": res})
                else:
                    self._json({"error": "Not found"}, 404)
            except Exception as exc:
                self._json({"error": str(exc)}, 400)

    for candidate in range(port, port + 10):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", candidate), BridgeHandler)
            t = threading.Thread(target=server.serve_forever, daemon=True)
            t.start()
            coordinator.log("INFO", f"Local browser bridge listening on http://127.0.0.1:{candidate}")
            return server
        except OSError:
            continue

    coordinator.log("WARN", f"Local bridge port {port} busy; continuing without local HTTP bridge.")
    return None


class TaturaDesktopApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Tatura MT5 Bridge — Desktop Trading Terminal")
        self.root.geometry("1180x780")
        self.root.configure(bg="#090D10")

        self.coordinator = TaturaBotCoordinator()
        try:
            bridge_port = int(self.coordinator.cfg.get("bridge_port", 8765))
        except Exception:
            bridge_port = 8765
        start_local_bridge(self.coordinator, bridge_port)

        self._build_ui()
        self._load_form_from_cfg()
        self._schedule_refresh()

    def _build_ui(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("TCombobox", fieldbackground="#141C22", background="#141C22", foreground="#E9F2EE")

        # Top header
        hdr = tk.Frame(self.root, bg="#10161B", highlightbackground="#1F2933", highlightthickness=1, padx=16, pady=12)
        hdr.pack(fill="x", padx=12, pady=(12, 8))

        tk.Label(hdr, text="TATURA MT5 BRIDGE", bg="#10161B", fg="#E9F2EE", font=("Segoe UI", 13, "bold")).pack(side="left")
        self.lbl_status = tk.Label(hdr, text="MT5: Disconnected  |  Website: Not Synced", bg="#10161B", fg="#94A3B8", font=("Consolas", 10))
        self.lbl_status.pack(side="left", padx=20)

        self.btn_toggle = tk.Button(hdr, text="Start Scanner", command=self._toggle_scanner, bg="#16A34A", fg="#FFFFFF", relief="flat", font=("Segoe UI", 10, "bold"), padx=16, pady=6)
        self.btn_toggle.pack(side="right")

        tk.Button(hdr, text="Connect MT5", command=self._connect_mt5, bg="#1E293B", fg="#E9F2EE", relief="flat", font=("Segoe UI", 9, "bold"), padx=12, pady=6).pack(side="right", padx=8)
        tk.Button(hdr, text="Sync Website", command=self._sync_website, bg="#1E293B", fg="#E9F2EE", relief="flat", font=("Segoe UI", 9, "bold"), padx=12, pady=6).pack(side="right")

        # Main 2-column body
        body = tk.Frame(self.root, bg="#090D10")
        body.pack(fill="both", expand=True, padx=12, pady=4)

        left = tk.Frame(body, bg="#10161B", highlightbackground="#1F2933", highlightthickness=1, width=370, padx=14, pady=12)
        left.pack(side="left", fill="y", padx=(0, 10))
        left.pack_propagate(False)

        self._section_label(left, "Cloudflare Pages Connection")
        self.ent_url = self._field(left, "Website URL")
        self.ent_token = self._field(left, "BOT_TOKEN", show="*")
        self.ent_user = self._field(left, "Website Username (exact login name)")

        self._section_label(left, "3-Market Scanner")
        row_m = tk.Frame(left, bg="#10161B")
        row_m.pack(fill="x", pady=(0, 8))
        self.ent_m1 = self._mini_entry(row_m, "Market 1")
        self.ent_m2 = self._mini_entry(row_m, "Market 2")
        self.ent_m3 = self._mini_entry(row_m, "Market 3")

        row_tf = tk.Frame(left, bg="#10161B")
        row_tf.pack(fill="x", pady=4)
        tk.Label(row_tf, text="Timeframe / Strategy", bg="#10161B", fg="#94A3B8", font=("Segoe UI", 9)).pack(side="left")
        self.cmb_strat = ttk.Combobox(row_tf, values=["balanced", "strict"], width=9, state="readonly")
        self.cmb_strat.pack(side="right", padx=(6, 0))
        self.cmb_tf = ttk.Combobox(row_tf, values=["M1", "M5", "M15", "M30", "H1"], width=6, state="readonly")
        self.cmb_tf.pack(side="right")

        self._section_label(left, "Execution & Website Sizing")
        self.ent_sl = self._field(left, "Stop Loss (points)")
        row_tp = tk.Frame(left, bg="#10161B")
        row_tp.pack(fill="x", pady=4)
        tk.Label(row_tp, text="TP Mode", bg="#10161B", fg="#94A3B8", font=("Segoe UI", 9)).pack(side="left")
        self.cmb_tp = ttk.Combobox(row_tp, values=["match_payout", "fixed_points"], width=14, state="readonly")
        self.cmb_tp.pack(side="right")

        row_sz = tk.Frame(left, bg="#10161B")
        row_sz.pack(fill="x", pady=4)
        tk.Label(row_sz, text="Lot Sizing", bg="#10161B", fg="#94A3B8", font=("Segoe UI", 9)).pack(side="left")
        self.cmb_sizing = ttk.Combobox(row_sz, values=["risk_from_stake", "lot_per_100"], width=14, state="readonly")
        self.cmb_sizing.pack(side="right")

        self.ent_tp = self._field(left, "Fixed TP (points) / Lot per $100")
        self.ent_hold = self._field(left, "Max Hold Minutes (0 = SL/TP only)")

        self.var_auto = tk.BooleanVar(value=True)
        tk.Checkbutton(left, text="Auto-execute signals on MT5", variable=self.var_auto, bg="#10161B", fg="#E9F2EE", selectcolor="#141C22", activebackground="#10161B", activeforeground="#E9F2EE", font=("Segoe UI", 9)).pack(anchor="w", pady=(6, 8))

        tk.Button(left, text="Save Settings", command=self._save_cfg_safe, bg="#2563EB", fg="#FFFFFF", relief="flat", font=("Segoe UI", 10, "bold"), pady=8).pack(fill="x")

        # Right column
        right = tk.Frame(body, bg="#090D10")
        right.pack(side="left", fill="both", expand=True)

        top_cards = tk.Frame(right, bg="#090D10")
        top_cards.pack(fill="x", pady=(0, 8))

        self.card_web = tk.Frame(top_cards, bg="#10161B", highlightbackground="#1F2933", highlightthickness=1, padx=14, pady=12)
        self.card_web.pack(side="left", fill="both", expand=True, padx=(0, 8))
        tk.Label(self.card_web, text="Website Stake Amount (Cloudflare /api/bot/next)", bg="#10161B", fg="#94A3B8", font=("Segoe UI", 9, "bold")).pack(anchor="w")
        self.lbl_stake = tk.Label(self.card_web, text="$0.00 (0%)", bg="#10161B", fg="#22C55E", font=("Consolas", 22, "bold"))
        self.lbl_stake.pack(anchor="w", pady=(4, 2))
        self.lbl_web_meta = tk.Label(self.card_web, text="Session: --  |  Trade: --  |  Capital: --", bg="#10161B", fg="#CBD5E1", font=("Consolas", 9), justify="left")
        self.lbl_web_meta.pack(anchor="w")

        self.card_pos = tk.Frame(top_cards, bg="#10161B", highlightbackground="#1F2933", highlightthickness=1, padx=14, pady=12)
        self.card_pos.pack(side="left", fill="both", expand=True)
        tk.Label(self.card_pos, text="MT5 Account & Open Position", bg="#10161B", fg="#94A3B8", font=("Segoe UI", 9, "bold")).pack(anchor="w")
        self.lbl_acc = tk.Label(self.card_pos, text="Balance: --", bg="#10161B", fg="#E9F2EE", font=("Consolas", 14, "bold"))
        self.lbl_acc.pack(anchor="w", pady=(4, 2))
        self.lbl_pos = tk.Label(self.card_pos, text="No active MT5 trade (waiting for signal)", bg="#10161B", fg="#94A3B8", font=("Consolas", 9))
        self.lbl_pos.pack(anchor="w")

        # 3 Market Cards
        mkt_row = tk.Frame(right, bg="#090D10")
        mkt_row.pack(fill="x", pady=(0, 8))
        self.mkt_labels = []
        for i in range(3):
            f = tk.Frame(mkt_row, bg="#10161B", highlightbackground="#1F2933", highlightthickness=1, padx=12, pady=10)
            f.pack(side="left", fill="both", expand=True, padx=(0 if i == 0 else 6, 0))
            t = tk.Label(f, text=f"Market {i+1}", bg="#10161B", fg="#E9F2EE", font=("Consolas", 11, "bold"))
            t.pack(anchor="w")
            p = tk.Label(f, text="Bid -- / Ask --", bg="#10161B", fg="#94A3B8", font=("Consolas", 9))
            p.pack(anchor="w", pady=(2, 2))
            ind = tk.Label(f, text="EMA -- / RSI --", bg="#10161B", fg="#64748B", font=("Consolas", 9))
            ind.pack(anchor="w")
            sig = tk.Label(f, text="SIGNAL: NONE", bg="#10161B", fg="#94A3B8", font=("Consolas", 10, "bold"))
            sig.pack(anchor="w", pady=(4, 0))
            btn_row = tk.Frame(f, bg="#10161B")
            btn_row.pack(fill="x", pady=(6, 0))
            tk.Button(btn_row, text="Buy", command=lambda idx=i: self._manual(idx, "BUY"), bg="#15803D", fg="#FFF", relief="flat", font=("Segoe UI", 8, "bold"), padx=10, pady=2).pack(side="left", padx=(0, 4))
            tk.Button(btn_row, text="Sell", command=lambda idx=i: self._manual(idx, "SELL"), bg="#B91C1C", fg="#FFF", relief="flat", font=("Segoe UI", 8, "bold"), padx=10, pady=2).pack(side="left")
            self.mkt_labels.append((t, p, ind, sig))

        # Live Execution Log
        log_frame = tk.Frame(right, bg="#10161B", highlightbackground="#1F2933", highlightthickness=1, padx=12, pady=10)
        log_frame.pack(fill="both", expand=True)
        tk.Label(log_frame, text="Signal & Execution Log", bg="#10161B", fg="#94A3B8", font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(0, 6))
        self.txt_log = tk.Text(log_frame, bg="#090D10", fg="#CBD5E1", relief="flat", font=("Consolas", 9), state="disabled")
        self.txt_log.pack(fill="both", expand=True)

    def _section_label(self, parent: tk.Frame, text: str) -> None:
        tk.Label(parent, text=text, bg="#10161B", fg="#E9F2EE", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(8, 4))

    def _field(self, parent: tk.Frame, label: str, show: str = "") -> tk.Entry:
        tk.Label(parent, text=label, bg="#10161B", fg="#94A3B8", font=("Segoe UI", 8)).pack(anchor="w")
        ent = tk.Entry(parent, bg="#141C22", fg="#E9F2EE", insertbackground="#E9F2EE", relief="flat", font=("Consolas", 9), show=show)
        ent.pack(fill="x", ipady=4, pady=(1, 5))
        return ent

    def _mini_entry(self, parent: tk.Frame, label: str) -> tk.Entry:
        wrap = tk.Frame(parent, bg="#10161B")
        wrap.pack(side="left", fill="x", expand=True, padx=2)
        tk.Label(wrap, text=label, bg="#10161B", fg="#94A3B8", font=("Segoe UI", 8)).pack(anchor="w")
        ent = tk.Entry(wrap, bg="#141C22", fg="#E9F2EE", insertbackground="#E9F2EE", relief="flat", font=("Consolas", 9), width=10)
        ent.pack(fill="x", ipady=4)
        return ent

    def _load_form_from_cfg(self) -> None:
        c = self.coordinator.cfg
        self.ent_url.insert(0, str(c.get("cloudflare_url", "")))
        self.ent_token.insert(0, str(c.get("bot_token", "")))
        self.ent_user.insert(0, str(c.get("website_user", "")))
        mkts = c.get("markets", ["EURUSD", "GBPUSD", "XAUUSD"])
        self.ent_m1.insert(0, mkts[0] if len(mkts) > 0 else "EURUSD")
        self.ent_m2.insert(0, mkts[1] if len(mkts) > 1 else "GBPUSD")
        self.ent_m3.insert(0, mkts[2] if len(mkts) > 2 else "XAUUSD")
        self.cmb_tf.set(str(c.get("timeframe", "M5")))
        self.cmb_strat.set(str(c.get("strategy_mode", "balanced")))
        self.ent_sl.insert(0, str(c.get("sl_points", 150)))
        self.cmb_tp.set(str(c.get("tp_mode", "match_payout")))
        self.cmb_sizing.set(str(c.get("sizing_mode", "risk_from_stake")))
        self.ent_tp.insert(0, str(c.get("tp_points", 150)) if c.get("sizing_mode") != "lot_per_100" else str(c.get("lot_per_100", 0.05)))
        self.ent_hold.insert(0, str(c.get("max_hold_minutes", 0)))
        self.var_auto.set(bool(c.get("auto_trade", True)))

    def _save_cfg(self) -> None:
        c = dict(self.coordinator.cfg)
        c["cloudflare_url"] = self.ent_url.get().strip()
        c["bot_token"] = self.ent_token.get().strip()
        c["website_user"] = self.ent_user.get().strip()
        c["markets"] = [
            self.ent_m1.get().strip() or "EURUSD",
            self.ent_m2.get().strip() or "GBPUSD",
            self.ent_m3.get().strip() or "XAUUSD",
        ]
        c["timeframe"] = self.cmb_tf.get() or "M5"
        c["strategy_mode"] = self.cmb_strat.get() or "balanced"
        c["sl_points"] = max(10, int(float(self.ent_sl.get() or 150)))
        c["tp_mode"] = self.cmb_tp.get() or "match_payout"
        c["sizing_mode"] = self.cmb_sizing.get() or "risk_from_stake"
        val_tp_lot = float(self.ent_tp.get() or 150)
        if c["sizing_mode"] == "lot_per_100":
            c["lot_per_100"] = max(0.01, val_tp_lot if val_tp_lot <= 10 else 0.05)
        else:
            c["tp_points"] = max(10, int(val_tp_lot))
        c["max_hold_minutes"] = max(0, int(float(self.ent_hold.get() or 0)))
        c["auto_trade"] = bool(self.var_auto.get())
        self.coordinator.reload_config(c)

    def _save_cfg_safe(self) -> bool:
        try:
            self._save_cfg()
            return True
        except Exception as exc:
            messagebox.showerror("Invalid Settings", str(exc))
            return False

    def _connect_mt5(self) -> None:
        try:
            self.coordinator.connect_mt5()
        except Exception as exc:
            messagebox.showerror("MT5 Connection", str(exc))

    def _sync_website(self) -> None:
        if not self._save_cfg_safe():
            return
        try:
            self.coordinator.sync_website_once()
        except Exception as exc:
            messagebox.showerror("Website Sync", str(exc))

    def _toggle_scanner(self) -> None:
        if not self._save_cfg_safe():
            return
        try:
            if self.coordinator.running:
                self.coordinator.stop()
            else:
                self.coordinator.start()
        except Exception as exc:
            messagebox.showerror("Scanner Error", str(exc))

    def _manual(self, idx: int, direction: str) -> None:
        if not self._save_cfg_safe():
            return
        mkts = self.coordinator.cfg.get("markets", [])
        if idx >= len(mkts):
            return
        try:
            self.coordinator.manual_trade(mkts[idx], direction)
        except Exception as exc:
            messagebox.showerror("Trade Error", str(exc))

    def _schedule_refresh(self) -> None:
        try:
            self._refresh_ui()
        except Exception:
            pass
        self.root.after(700, self._schedule_refresh)

    def _refresh_ui(self) -> None:
        snap = self.coordinator.state_snapshot()
        mt5_txt = "MT5: Connected" if snap["mt5_connected"] else "MT5: Disconnected"
        web = snap["website"]
        web_txt = f"Website: {'GO' if web['go'] else 'STOPPED'} ({web['last_sync'] or 'not synced'})"
        self.lbl_status.config(text=f"{mt5_txt}  |  {web_txt}")

        if snap["running"]:
            self.btn_toggle.config(text="Pause Scanner", bg="#DC2626")
        else:
            self.btn_toggle.config(text="Start Scanner", bg="#16A34A")

        self.lbl_stake.config(
            text=f"${web['stake_amount']:.2f} ({web['stake_pct']:.1f}%)",
            fg="#22C55E" if web["go"] else "#F59E0B",
        )
        self.lbl_web_meta.config(
            text=f"Session: {web['session_id'] or '--'}  |  Trade #{web['seq'] or '--'}  |  Cap: ${web['capital']:.2f}  |  {web['wins']}W/{web['losses']}L\n{web['reason']}"
        )

        acc = snap["account"]
        if acc:
            self.lbl_acc.config(text=f"{acc['balance']:.2f} {acc['currency']} (Eq {acc['equity']:.2f})")
        tr = snap["active_trade"]
        if tr:
            self.lbl_pos.config(
                text=f"OPEN {tr['direction']} {tr['symbol']} {tr['volume']} lots @ {tr['entry_price']} | P/L: {tr.get('floating_profit', 0.0):+.2f}",
                fg="#22C55E" if tr.get("floating_profit", 0.0) >= 0 else "#EF4444",
            )
        else:
            self.lbl_pos.config(text="No active MT5 trade (waiting for signal)", fg="#94A3B8")

        mkts = snap["markets"]
        for i in range(3):
            t, p, ind, sig = self.mkt_labels[i]
            if i < len(mkts):
                m = mkts[i]
                t.config(text=m["symbol"])
                p.config(text=f"Bid {m['bid']} / Ask {m['ask']} ({m['spread_points']}pt)")
                ind.config(text=f"EMA9 {m['ema_fast']} | EMA21 {m['ema_slow']} | RSI {m['rsi']}")
                s_val = m["signal"]
                sig.config(
                    text=f"SIGNAL: {s_val}",
                    fg="#22C55E" if s_val == "BUY" else ("#EF4444" if s_val == "SELL" else "#94A3B8"),
                )

        self.txt_log.config(state="normal")
        self.txt_log.delete("1.0", "end")
        for row in snap["logs"][:40]:
            self.txt_log.insert("end", f"[{row['time']}] {row['level']:6s} {row['message']}\n")
        self.txt_log.config(state="disabled")


def main() -> None:
    try:
        root = tk.Tk()
        TaturaDesktopApp(root)
        root.mainloop()
    except Exception:
        err_text = traceback.format_exc()
        log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tatura_crash.log")
        try:
            with open(log_path, "w", encoding="utf-8") as f:
                f.write(err_text)
        except Exception:
            pass
        try:
            r = tk.Tk()
            r.withdraw()
            messagebox.showerror("Tatura MT5 Bridge Crash", f"{err_text}\n\nSaved to {log_path}")
        except Exception:
            print(err_text)


if __name__ == "__main__":
    main()

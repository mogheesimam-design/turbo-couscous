import json
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from pathlib import Path

import MetaTrader5 as mt5
import engine

APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "config.json"

class TaturaApp:
    def __init__(self, root):
        self.root = root
        self.root.title("TATURA BOT | MT5 Demo")
        self.root.geometry("1040x760")
        self.root.minsize(900, 650)
        self.root.configure(bg="#0b1118")
        self.events = queue.Queue()
        self.stop_event = threading.Event()
        self.worker = None
        self.running = False
        self.vars = {}
        self._style()
        self._build()
        self._load()
        self.root.after(150, self._drain)
        self.root.protocol("WM_DELETE_WINDOW", self._close)

    def _style(self):
        s = ttk.Style()
        s.theme_use("clam")
        s.configure("TFrame", background="#0b1118")
        s.configure("Panel.TFrame", background="#121c27")
        s.configure("TLabel", background="#0b1118", foreground="#dce6f0", font=("Segoe UI", 10))
        s.configure("Muted.TLabel", background="#121c27", foreground="#91a2b5")
        s.configure("Header.TLabel", background="#0b1118", foreground="#f4f7fb", font=("Segoe UI", 21, "bold"))
        s.configure("PanelTitle.TLabel", background="#121c27", foreground="#f4f7fb", font=("Segoe UI", 11, "bold"))
        s.configure("TEntry", fieldbackground="#1b2937", foreground="#ffffff", insertcolor="white")
        s.configure("TCombobox", fieldbackground="#1b2937", foreground="#ffffff")
        s.configure("TCheckbutton", background="#121c27", foreground="#dce6f0")
        s.configure("TButton", font=("Segoe UI", 10, "bold"), padding=8)
        s.configure("Start.TButton", background="#147d59", foreground="white")
        s.map("Start.TButton", background=[("disabled", "#34434e"), ("active", "#18966a")])
        s.configure("Stop.TButton", background="#9c3541", foreground="white")

    def _panel(self, parent, title, row, col, colspan=1):
        frame = ttk.Frame(parent, style="Panel.TFrame", padding=14)
        frame.grid(row=row, column=col, columnspan=colspan, sticky="nsew", padx=7, pady=7)
        ttk.Label(frame, text=title, style="PanelTitle.TLabel").pack(anchor="w", pady=(0, 10))
        return frame

    def _field(self, parent, label, key, default="", width=18):
        row = ttk.Frame(parent, style="Panel.TFrame")
        row.pack(fill="x", pady=4)
        ttk.Label(row, text=label, style="Muted.TLabel", width=22).pack(side="left")
        var = tk.StringVar(value=str(default))
        self.vars[key] = var
        ent = ttk.Entry(row, textvariable=var, width=width)
        ent.pack(side="right", fill="x", expand=True)
        return ent

    def _build(self):
        top = ttk.Frame(self.root, padding=(18, 16, 18, 8))
        top.pack(fill="x")
        ttk.Label(top, text="TATURA", style="Header.TLabel").pack(side="left")
        ttk.Label(top, text="MT5 AUTOMATION • DEMO MODE ONLY",
                  foreground="#69d6ad", background="#0b1118",
                  font=("Segoe UI", 10, "bold")).pack(side="right")
        status = ttk.Frame(self.root, padding=(18, 0, 18, 8))
        status.pack(fill="x")
        self.status_var = tk.StringVar(value="Not connected")
        self.signal_var = tk.StringVar(value="WAITING")
        ttk.Label(status, text="STATUS", foreground="#91a2b5").pack(side="left")
        ttk.Label(status, textvariable=self.status_var, foreground="#69d6ad",
                  font=("Segoe UI", 10, "bold")).pack(side="left", padx=8)
        ttk.Label(status, text="LAST SIGNAL", foreground="#91a2b5").pack(side="left", padx=(35, 5))
        ttk.Label(status, textvariable=self.signal_var, foreground="#f0c674",
                  font=("Segoe UI", 10, "bold")).pack(side="left")

        body = ttk.Frame(self.root, padding=(10, 0, 10, 8))
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(1, weight=1)

        mt = self._panel(body, "01  METATRADER CONNECTION", 0, 0)
        self._field(mt, "Terminal executable (optional)", "mt5_path", "")
        self._field(mt, "Account login (optional)", "mt5_login", "")
        self._field(mt, "Server (optional)", "mt5_server", "")
        self._field(mt, "Password (not saved)", "password", "")
        self.vars["password"].set("")
        # mask password field
        # Password is supplied only for this run and is never written to config.json.
        password_row = mt.winfo_children()[3]
        for sub in password_row.winfo_children():
            if isinstance(sub, ttk.Entry):
                sub.configure(show="•")
        note = ttk.Label(mt, text="Or leave login/server/password blank and log into the MT5 terminal first.",
                         style="Muted.TLabel", wraplength=430)
        note.pack(anchor="w", pady=(6, 0))

        strat = self._panel(body, "02  STRATEGY CONFIGURATION", 0, 1)
        self._field(strat, "Trading symbol", "symbol", "EURUSD")
        self._combo(strat, "Timeframe", "timeframe", ["M1","M5","M15","M30","H1","H4"])
        self._field(strat, "Fast EMA", "ema_fast", "9")
        self._field(strat, "Slow EMA", "ema_slow", "21")
        self._field(strat, "Trend EMA", "ema_trend", "200")
        self._check(strat, "Use trend EMA filter", "use_trend_filter", True)
        self._field(strat, "Maximum spread (points)", "max_spread_points", "20")

        risk = self._panel(body, "03  ATR RISK MANAGEMENT", 1, 0)
        self._field(risk, "Risk per trade (% equity)", "risk_percent", "0.25")
        self._field(risk, "ATR period", "atr_period", "14")
        self._field(risk, "ATR stop multiplier", "atr_multiplier", "1.5")
        self._field(risk, "Reward / risk ratio", "reward_risk", "1.0")
        self._field(risk, "Polling interval (seconds)", "poll_seconds", "2")
        self._field(risk, "Bot magic number", "magic", "28001")
        self._field(risk, "Price deviation (points)", "deviation_points", "20")
        ttk.Label(risk, text="One Tatura position at a time. SL = ATR × multiplier. TP = SL distance × reward/risk.",
                  style="Muted.TLabel", wraplength=440).pack(anchor="w", pady=(8, 0))

        controls = self._panel(body, "04  CONTROL", 1, 1)
        ttk.Label(controls, text="DEMO ACCOUNT LOCK IS ACTIVE",
                  foreground="#69d6ad", background="#121c27",
                  font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(2, 10))
        btns = ttk.Frame(controls, style="Panel.TFrame")
        btns.pack(fill="x")
        self.start_btn = ttk.Button(btns, text="▶  START BOT", style="Start.TButton", command=self.start)
        self.start_btn.pack(side="left", fill="x", expand=True, padx=(0, 5))
        self.stop_btn = ttk.Button(btns, text="■  STOP", style="Stop.TButton", command=self.stop, state="disabled")
        self.stop_btn.pack(side="left", fill="x", expand=True, padx=(5, 0))
        ttk.Button(controls, text="Save configuration", command=self.save).pack(fill="x", pady=(12, 5))
        ttk.Button(controls, text="Test MT5 connection (no trades)", command=self.test_connection).pack(fill="x")
        ttk.Label(controls, text="The bot refuses to start on REAL or CONTEST accounts. Test on demo first.",
                  style="Muted.TLabel", wraplength=440).pack(anchor="w", pady=(12, 0))

        log_panel = ttk.Frame(self.root, style="Panel.TFrame", padding=14)
        log_panel.pack(fill="both", expand=False, padx=17, pady=(0, 14))
        ttk.Label(log_panel, text="LIVE ACTIVITY LOG", style="PanelTitle.TLabel").pack(anchor="w", pady=(0, 10))
        self.log_text = tk.Text(log_panel, height=11, bg="#081018", fg="#c7d4e0",
                                insertbackground="white", relief="flat",
                                font=("Consolas", 9), wrap="word")
        self.log_text.pack(fill="both", expand=True)
        self._log("Tatura ready. Configure MT5 and strategy, then test connection.")

    def _combo(self, parent, label, key, values):
        row = ttk.Frame(parent, style="Panel.TFrame")
        row.pack(fill="x", pady=4)
        ttk.Label(row, text=label, style="Muted.TLabel", width=22).pack(side="left")
        var = tk.StringVar(value=values[0])
        self.vars[key] = var
        ttk.Combobox(row, textvariable=var, values=values, state="readonly", width=15).pack(side="right")

    def _check(self, parent, label, key, default):
        var = tk.BooleanVar(value=default)
        self.vars[key] = var
        ttk.Checkbutton(parent, text=label, variable=var).pack(anchor="w", pady=5)

    def _config(self):
        cfg = {}
        for k, v in self.vars.items():
            if k == "password":
                continue
            cfg[k] = v.get()
        numeric_int = ["ema_fast","ema_slow","ema_trend","max_spread_points","poll_seconds",
                       "atr_period","magic","deviation_points"]
        numeric_float = ["risk_percent","atr_multiplier","reward_risk"]
        for k in numeric_int:
            cfg[k] = int(cfg[k])
        for k in numeric_float:
            cfg[k] = float(cfg[k])
        cfg["use_trend_filter"] = bool(cfg["use_trend_filter"])
        if cfg["ema_fast"] <= 0 or cfg["ema_slow"] <= cfg["ema_fast"]:
            raise ValueError("EMA values must be positive and slow EMA must be greater than fast EMA.")
        if cfg["ema_trend"] < cfg["ema_slow"]:
            raise ValueError("Trend EMA should be greater than slow EMA.")
        if cfg["risk_percent"] <= 0 or cfg["risk_percent"] > 1:
            raise ValueError("Demo build caps risk per trade at 1% of equity.")
        if cfg["atr_period"] < 2 or cfg["atr_multiplier"] <= 0 or cfg["reward_risk"] <= 0:
            raise ValueError("ATR period, ATR multiplier and reward/risk must be positive.")
        if cfg["poll_seconds"] < 1:
            raise ValueError("Polling interval must be at least 1 second.")
        return cfg

    def _load(self):
        if CONFIG_PATH.exists():
            try:
                data = json.loads(CONFIG_PATH.read_text())
                for k, v in data.items():
                    if k in self.vars:
                        self.vars[k].set(v)
            except Exception as e:
                self._log("Could not load config: %s" % e)

    def save(self):
        try:
            cfg = self._config()
            CONFIG_PATH.write_text(json.dumps(cfg, indent=2))
            self._log("Configuration saved to config.json (password is not saved).")
            messagebox.showinfo("Tatura", "Configuration saved.")
        except Exception as e:
            messagebox.showerror("Configuration error", str(e))

    def _log(self, text):
        self.log_text.insert("end", text + "\n")
        self.log_text.see("end")

    def _worker_log(self, text):
        self.events.put(("log", text))

    def _worker_status(self, text):
        self.events.put(("status", text))

    def _worker_signal(self, signal, reason):
        self.events.put(("signal", "%s — %s" % (signal, reason)))

    def _drain(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "log":
                    self._log(value)
                elif kind == "status":
                    self.status_var.set(value)
                elif kind == "signal":
                    self.signal_var.set(value)
                elif kind == "finished":
                    self.running = False
                    self.start_btn.configure(state="normal")
                    self.stop_btn.configure(state="disabled")
        except queue.Empty:
            pass
        self.root.after(150, self._drain)

    def test_connection(self):
        try:
            cfg = self._config()
            password = self.vars["password"].get()
            def work():
                try:
                    acc = engine.connect(cfg, password)
                    self.events.put(("log", "TEST OK: DEMO account %s | server %s | balance %.2f" %
                                     (acc.login, acc.server, acc.balance)))
                    self.events.put(("status", "Demo connection verified"))
                except Exception as e:
                    self.events.put(("log", "CONNECTION TEST FAILED: %s" % e))
                    self.events.put(("status", "Connection failed"))
                finally:
                    mt5.shutdown()
            threading.Thread(target=work, daemon=True).start()
        except Exception as e:
            messagebox.showerror("Configuration error", str(e))

    def start(self):
        if self.running:
            return
        try:
            cfg = self._config()
            password = self.vars["password"].get()
            CONFIG_PATH.write_text(json.dumps(cfg, indent=2))
        except Exception as e:
            messagebox.showerror("Configuration error", str(e))
            return
        self.stop_event.clear()
        self.running = True
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.status_var.set("Connecting...")
        self._log("Starting Tatura. Demo-only execution safety is enabled.")
        def work():
            try:
                engine.run(cfg, password, self.stop_event, self._worker_log,
                           self._worker_status, self._worker_signal)
            except Exception as e:
                self.events.put(("log", "BOT STOPPED: %s" % e))
                self.events.put(("status", "Stopped — see log"))
            finally:
                self.events.put(("finished", ""))
        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def stop(self):
        self.stop_event.set()
        self.status_var.set("Stopping...")
        self._log("Stop requested. No new trades will be initiated.")

    def _close(self):
        if self.running:
            self.stop_event.set()
        self.root.after(250, self.root.destroy)

if __name__ == "__main__":
    root = tk.Tk()
    app = TaturaApp(root)
    root.mainloop()

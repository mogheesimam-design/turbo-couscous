import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional


class TaturaWebError(Exception):
    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class TaturaWebClient:
    """
    Client for the Tatura Model Cloudflare Pages Bot API.
    Uses Python standard-library urllib so it has zero third-party HTTP dependencies.
    Supports both the current (/api/bot/next, /api/bot/result) and upgraded
    (/api/bot/signal, /api/bot/trade-open) Cloudflare Pages endpoints.
    """

    def __init__(self, base_url: str, bot_token: str, user: str = "", timeout: float = 10.0):
        self.base_url = base_url.strip().rstrip("/")
        self.bot_token = bot_token.strip()
        self.user = user.strip()
        self.timeout = timeout
        self.supports_signal_endpoint: Optional[bool] = None
        self.supports_trade_open_endpoint: Optional[bool] = None

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.bot_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Tatura-MT5-Bridge/1.0",
        }

    def _build_url(self, path: str) -> str:
        if self.user:
            q = urllib.parse.urlencode({"user": self.user})
            return f"{self.base_url}{path}?{q}"
        return f"{self.base_url}{path}"

    def _request(self, method: str, path: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not self.base_url:
            raise TaturaWebError("Cloudflare Pages URL is not configured.")
        if not (self.base_url.startswith("https://") or self.base_url.startswith("http://")):
            raise TaturaWebError("Cloudflare Pages URL must start with https:// or http://")
        if len(self.bot_token) < 20:
            raise TaturaWebError("BOT_TOKEN must be at least 20 characters.")

        url = self._build_url(path)
        body_bytes = json.dumps(payload).encode("utf-8") if payload is not None else None
        last_err: Optional[Exception] = None

        for attempt in range(3):
            req = urllib.request.Request(url=url, data=body_bytes, headers=self._headers(), method=method)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    raw = resp.read().decode("utf-8")
                    return json.loads(raw)
            except urllib.error.HTTPError as exc:
                raw = exc.read().decode("utf-8", errors="replace")
                try:
                    data = json.loads(raw)
                    msg = data.get("error") if isinstance(data, dict) else f"HTTP {exc.code}"
                except Exception:
                    msg = f"HTTP {exc.code}"
                if msg == "Bot user not found":
                    msg = (
                        f"Bot user '{self.user}' not found or inactive on website. Use exact login username."
                        if self.user
                        else "Bot user not found: no active admin user in D1. Enter your login username in Website Username."
                    )
                raise TaturaWebError(msg or f"HTTP {exc.code}", status_code=exc.code)
            except urllib.error.URLError as exc:
                last_err = exc
                if attempt < 2:
                    time.sleep(0.5 * (attempt + 1))
            except Exception as exc:
                last_err = exc
                if attempt < 2:
                    time.sleep(0.5 * (attempt + 1))

        raise TaturaWebError(f"Network error contacting Cloudflare Pages: {last_err}")

    def get_next_stake(self) -> Dict[str, Any]:
        """Calls GET /api/bot/next to check go status and fetch exact stake_amount."""
        return self._request("GET", "/api/bot/next")

    def push_signal(
        self,
        markets: List[Dict[str, Any]],
        triggered_signal: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Pushes scanned 3-market telemetry and any triggered signal to POST /api/bot/signal.
        Gracefully disables itself if the Cloudflare Worker returns 404 (older website version).
        """
        if self.supports_signal_endpoint is False:
            return None
        try:
            res = self._request(
                "POST",
                "/api/bot/signal",
                payload={
                    "markets": [
                        {
                            "symbol": m.get("symbol"),
                            "bid": m.get("bid"),
                            "ask": m.get("ask"),
                            "spread_points": m.get("spread_points"),
                            "ema_fast": m.get("ema_fast"),
                            "ema_slow": m.get("ema_slow"),
                            "rsi": m.get("rsi"),
                            "signal": m.get("signal"),
                            "reason": m.get("reason"),
                        }
                        for m in markets
                    ],
                    "signal": triggered_signal,
                },
            )
            self.supports_signal_endpoint = True
            return res
        except TaturaWebError as exc:
            if exc.status_code == 404:
                self.supports_signal_endpoint = False
                return None
            raise

    def push_trade_open(self, trade: Dict[str, Any]) -> None:
        """Reports a newly opened MT5 trade to POST /api/bot/trade-open if supported."""
        if self.supports_trade_open_endpoint is False:
            return
        try:
            self._request(
                "POST",
                "/api/bot/trade-open",
                payload={
                    "session_id": trade.get("session_id"),
                    "seq": trade.get("seq"),
                    "symbol": trade.get("symbol"),
                    "direction": trade.get("direction"),
                    "volume": trade.get("volume"),
                    "entry_price": trade.get("entry_price"),
                    "sl": trade.get("sl"),
                    "tp": trade.get("tp"),
                    "ticket": trade.get("position_id"),
                    "stake_amount": trade.get("stake_amount"),
                },
            )
            self.supports_trade_open_endpoint = True
        except TaturaWebError as exc:
            if exc.status_code == 404:
                self.supports_trade_open_endpoint = False

    def push_result(self, session_id: int, seq: int, result: str, profit: float = 0.0) -> Dict[str, Any]:
        """Calls POST /api/bot/result with win or loss."""
        if result not in ("win", "loss"):
            raise ValueError("result must be 'win' or 'loss'")
        return self._request(
            "POST",
            "/api/bot/result",
            payload={
                "session_id": int(session_id),
                "seq": int(seq),
                "result": result,
                "profit": round(float(profit), 2),
            },
        )

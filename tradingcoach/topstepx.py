"""Minimal client for the TopstepX API (ProjectX Gateway).

Standard library only, so it runs anywhere Python 3.10+ is installed.

Auth flow: POST /api/Auth/loginKey with {userName, apiKey} returns a session
token valid for 24h, then sent as "Authorization: Bearer <token>".
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

DEFAULT_BASE_URL = "https://api.topstepx.com"

LOGIN_ERRORS = {
    1: "UserNotFound",
    2: "PasswordVerificationFailed",
    3: "InvalidCredentials",
    4: "AppNotFound",
    5: "AppVerificationFailed",
    6: "InvalidDevice",
    7: "AgreementsNotSigned",
}
TRADE_SEARCH_ERRORS = {1: "AccountNotFound"}

# Rate limit documented by the gateway: 200 requests / 60 s (non-history endpoints).
_MIN_INTERVAL = 60.0 / 200
_TOKEN_LIFETIME = 23 * 3600  # refresh before the 24h expiry


class TopstepXError(Exception):
    """Raised when the API answers with success=false or an HTTP error."""

    def __init__(self, message: str, *, error_code: int | None = None, status: int | None = None):
        super().__init__(message)
        self.error_code = error_code
        self.status = status


@dataclass
class Account:
    id: int
    name: str
    balance: float
    can_trade: bool
    is_visible: bool
    simulated: bool

    @classmethod
    def from_api(cls, d: dict) -> "Account":
        return cls(
            id=d["id"],
            name=d.get("name", ""),
            balance=d.get("balance", 0.0),
            can_trade=bool(d.get("canTrade")),
            is_visible=bool(d.get("isVisible")),
            simulated=bool(d.get("simulated")),
        )


def to_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class TopstepXClient:
    def __init__(self, username: str, api_key: str, base_url: str = DEFAULT_BASE_URL, timeout: float = 30.0):
        if not username or not api_key:
            raise TopstepXError("Identifiants manquants : TOPSTEPX_USERNAME et TOPSTEPX_API_KEY sont requis.")
        self.username = username
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._token: str | None = None
        self._token_time = 0.0
        self._last_call = 0.0

    # --- low level ---------------------------------------------------------

    def _http(self, method: str, path: str, body: dict | None, auth: bool, retries: int = 3):
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if auth:
            headers["Authorization"] = f"Bearer {self._ensure_token()}"
        data = json.dumps(body).encode() if body is not None else None
        for attempt in range(retries + 1):
            wait = _MIN_INTERVAL - (time.monotonic() - self._last_call)
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.monotonic()
            req = urllib.request.Request(self.base_url + path, data=data, headers=headers, method=method)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    raw = resp.read().decode()
                    return json.loads(raw) if raw else None
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503, 504) and attempt < retries:
                    time.sleep(2 ** (attempt + 1))
                    continue
                if e.code == 401:
                    raise TopstepXError("Non autorisé (401) : token invalide ou expiré.", status=401) from e
                raise TopstepXError(f"Erreur HTTP {e.code} sur {path}", status=e.code) from e
            except urllib.error.URLError as e:
                if attempt < retries:
                    time.sleep(2 ** (attempt + 1))
                    continue
                raise TopstepXError(f"Impossible de joindre {self.base_url} : {e.reason}") from e

    def _call(self, path: str, body: dict | None, errors: dict[int, str] | None = None) -> dict:
        resp = self._http("POST", path, body, auth=True)
        if not resp or not resp.get("success"):
            code = (resp or {}).get("errorCode")
            name = (errors or {}).get(code, f"code {code}")
            msg = (resp or {}).get("errorMessage") or ""
            raise TopstepXError(f"{path} a échoué : {name} {msg}".strip(), error_code=code)
        return resp

    # --- auth --------------------------------------------------------------

    def login(self) -> str:
        resp = self._http("POST", "/api/Auth/loginKey", {"userName": self.username, "apiKey": self.api_key}, auth=False)
        if not resp or not resp.get("success") or not resp.get("token"):
            code = (resp or {}).get("errorCode")
            name = LOGIN_ERRORS.get(code, f"code {code}")
            raise TopstepXError(f"Connexion refusée : {name}", error_code=code)
        self._token = resp["token"]
        self._token_time = time.monotonic()
        return self._token

    def _ensure_token(self) -> str:
        if self._token is None or time.monotonic() - self._token_time > _TOKEN_LIFETIME:
            self.login()
        return self._token  # type: ignore[return-value]

    def ping(self) -> str:
        resp = self._http("GET", "/api/Status/ping", None, auth=False)
        return str(resp)

    # --- data --------------------------------------------------------------

    def accounts(self, only_active: bool = False) -> list[Account]:
        resp = self._call("/api/Account/search", {"onlyActiveAccounts": only_active})
        return [Account.from_api(a) for a in resp.get("accounts") or []]

    def trades(self, account_id: int, start: datetime, end: datetime | None = None) -> list[dict]:
        body: dict = {"accountId": account_id, "startTimestamp": to_iso(start)}
        if end is not None:
            body["endTimestamp"] = to_iso(end)
        resp = self._call("/api/Trade/search", body, TRADE_SEARCH_ERRORS)
        return resp.get("trades") or []

    def trades_range(self, account_id: int, start: datetime, end: datetime, window_days: int = 7) -> list[dict]:
        """Fetch trades over a long period in small windows (in case the API caps
        the number of results per call), de-duplicated by trade id."""
        seen: dict[int, dict] = {}
        cur = start
        while cur < end:
            nxt = min(cur + timedelta(days=window_days), end)
            for t in self.trades(account_id, cur, nxt):
                seen[t["id"]] = t
            cur = nxt
        return sorted(seen.values(), key=lambda t: (t.get("creationTimestamp") or "", t["id"]))

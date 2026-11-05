"""Tests against a local fake TopstepX server (no real credentials needed)."""

import csv
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

from tradingcoach import cli
from tradingcoach.topstepx import TopstepXClient, TopstepXError

ACCOUNTS = [
    {"id": 1, "name": "50KTC-ACTIVE", "balance": 51000, "canTrade": True, "isVisible": True, "simulated": True},
    {"id": 2, "name": "50KTC-FAILED", "balance": 47000, "canTrade": False, "isVisible": True, "simulated": True},
    {"id": 3, "name": "EXPRESS-GONE", "balance": 0, "canTrade": False, "isVisible": False, "simulated": True},
]
TRADES = {
    1: [
        {"id": 10, "accountId": 1, "contractId": "CON.F.US.MNQ.Z26", "creationTimestamp": "2026-10-01T14:30:00Z",
         "price": 20000.0, "profitAndLoss": None, "fees": 0.37, "side": 0, "size": 1, "voided": False, "orderId": 100},
        {"id": 11, "accountId": 1, "contractId": "CON.F.US.MNQ.Z26", "creationTimestamp": "2026-10-01T14:35:00Z",
         "price": 20010.0, "profitAndLoss": 20.0, "fees": 0.37, "side": 1, "size": 1, "voided": False, "orderId": 101},
    ],
    2: [
        {"id": 20, "accountId": 2, "contractId": "CON.F.US.EP.Z26", "creationTimestamp": "2026-09-01T14:30:00Z",
         "price": 6000.0, "profitAndLoss": -150.0, "fees": 1.4, "side": 1, "size": 1, "voided": False, "orderId": 200},
    ],
}


class FakeGateway(BaseHTTPRequestHandler):
    calls: list = []

    def log_message(self, *a):
        pass

    def _send(self, payload):
        raw = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or b"{}")
        FakeGateway.calls.append((self.path, body, self.headers.get("Authorization")))
        if self.path == "/api/Auth/loginKey":
            ok = body == {"userName": "trader", "apiKey": "good-key"}
            return self._send({"success": ok, "errorCode": 0 if ok else 3, "token": "tok" if ok else None})
        if self.headers.get("Authorization") != "Bearer tok":
            self.send_response(401)
            self.end_headers()
            return
        if self.path == "/api/Account/search":
            accts = [a for a in ACCOUNTS if a["canTrade"] or not body["onlyActiveAccounts"]]
            return self._send({"success": True, "errorCode": 0, "accounts": accts})
        if self.path == "/api/Trade/search":
            acct = body["accountId"]
            if acct == 3:
                return self._send({"success": False, "errorCode": 1, "trades": None})
            trades = [t for t in TRADES.get(acct, [])
                      if body["startTimestamp"] <= t["creationTimestamp"] < body.get("endTimestamp", "9999")]
            return self._send({"success": True, "errorCode": 0, "trades": trades})
        self.send_response(404)
        self.end_headers()


class TopstepXTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), FakeGateway)
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        FakeGateway.calls.clear()
        p = mock.patch("tradingcoach.topstepx._MIN_INTERVAL", 0)
        p.start()
        self.addCleanup(p.stop)

    def test_login_and_accounts(self):
        c = TopstepXClient("trader", "good-key", self.url)
        self.assertEqual(len(c.accounts(only_active=True)), 1)
        self.assertEqual(len(c.accounts(only_active=False)), 3)
        logins = [x for x in FakeGateway.calls if x[0] == "/api/Auth/loginKey"]
        self.assertEqual(len(logins), 1)  # token reused

    def test_bad_credentials(self):
        c = TopstepXClient("trader", "bad-key", self.url)
        with self.assertRaises(TopstepXError) as ctx:
            c.login()
        self.assertIn("InvalidCredentials", str(ctx.exception))

    def test_closed_account_error_is_reported(self):
        c = TopstepXClient("trader", "good-key", self.url)
        with self.assertRaises(TopstepXError) as ctx:
            c.trades(3, cli.datetime(2026, 1, 1))
        self.assertIn("AccountNotFound", str(ctx.exception))

    def test_export_writes_csv(self):
        env = {"TOPSTEPX_USERNAME": "trader", "TOPSTEPX_API_KEY": "good-key", "TOPSTEPX_BASE_URL": self.url}
        fixed_now = cli.datetime(2026, 11, 5, tzinfo=cli.timezone.utc)
        with tempfile.TemporaryDirectory() as d, mock.patch.dict("os.environ", env), \
                mock.patch("tradingcoach.cli.datetime") as dt:
            dt.now.return_value = fixed_now
            self.assertEqual(cli.main(["export", "--out", d]), 0)
            trades = list(csv.DictReader((Path(d) / "trades.csv").read_text().splitlines()))
            accounts = {r["account_id"]: r
                        for r in csv.DictReader((Path(d) / "accounts.csv").read_text().splitlines())}
        self.assertEqual([t["trade_id"] for t in trades], ["20", "10", "11"])
        self.assertEqual(trades[0]["side"], "SELL")
        self.assertEqual(accounts["1"]["realized_pnl"], "20.0")
        self.assertEqual(accounts["2"]["realized_pnl"], "-150.0")
        self.assertTrue(accounts["3"]["status"].startswith("erreur"))


if __name__ == "__main__":
    unittest.main()

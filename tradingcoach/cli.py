"""Command line: python -m tradingcoach <check|accounts|export>."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .csv_import import CsvImportError, import_files
from .topstepx import DEFAULT_BASE_URL, TopstepXClient, TopstepXError

SIDES = {0: "BUY", 1: "SELL"}

TRADE_COLUMNS = [
    "account_id", "account_name", "trade_id", "timestamp_utc", "contract_id",
    "side", "size", "price", "pnl", "fees", "commissions", "voided", "order_id",
]


def load_dotenv(path: Path = Path(".env")) -> None:
    """Read KEY=VALUE lines from .env without overriding real env vars."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def make_client() -> TopstepXClient:
    load_dotenv()
    return TopstepXClient(
        os.environ.get("TOPSTEPX_USERNAME", ""),
        os.environ.get("TOPSTEPX_API_KEY", ""),
        os.environ.get("TOPSTEPX_BASE_URL", DEFAULT_BASE_URL),
    )


def cmd_check(args) -> int:
    client = make_client()
    client.login()
    print("✔ Connexion à l'API TopstepX réussie.")
    active = client.accounts(only_active=True)
    every = client.accounts(only_active=False)
    print(f"  Comptes actifs : {len(active)} — tous comptes (actifs + inactifs) : {len(every)}")
    return 0


def cmd_accounts(args) -> int:
    client = make_client()
    accounts = client.accounts(only_active=False)
    print(f"{'ID':>10}  {'Nom':<32} {'Solde':>12}  Trade  Visible  Simulé")
    for a in accounts:
        print(f"{a.id:>10}  {a.name:<32} {a.balance:>12.2f}  {'oui' if a.can_trade else 'non':<5}  "
              f"{'oui' if a.is_visible else 'non':<7}  {'oui' if a.simulated else 'non'}")
    return 0


def cmd_export(args) -> int:
    client = make_client()
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=round(args.months * 30.44))
    out = Path(args.out)
    (out / "raw").mkdir(parents=True, exist_ok=True)

    accounts = client.accounts(only_active=False)
    print(f"{len(accounts)} compte(s) trouvé(s). Période : {start:%Y-%m-%d} → {end:%Y-%m-%d}")

    rows, report = [], []
    for a in accounts:
        try:
            trades = client.trades_range(a.id, start, end)
            status = "ok"
        except TopstepXError as e:
            trades, status = [], f"erreur : {e}"
        (out / "raw" / f"trades_{a.id}.json").write_text(json.dumps(trades, indent=2), encoding="utf-8")
        pnl = sum(t.get("profitAndLoss") or 0 for t in trades if not t.get("voided"))
        report.append({"account_id": a.id, "account_name": a.name, "can_trade": a.can_trade,
                       "is_visible": a.is_visible, "simulated": a.simulated, "balance": a.balance,
                       "fills": len(trades), "realized_pnl": round(pnl, 2), "status": status})
        print(f"  {a.name:<32} {len(trades):>5} exécution(s)  P&L {pnl:>10.2f}  [{status}]")
        for t in trades:
            rows.append({
                "account_id": a.id, "account_name": a.name, "trade_id": t["id"],
                "timestamp_utc": t.get("creationTimestamp"), "contract_id": t.get("contractId"),
                "side": SIDES.get(t.get("side"), t.get("side")), "size": t.get("size"),
                "price": t.get("price"), "pnl": t.get("profitAndLoss"), "fees": t.get("fees"),
                "commissions": t.get("commissions"), "voided": t.get("voided"), "order_id": t.get("orderId"),
            })

    rows.sort(key=lambda r: (r["timestamp_utc"] or "", r["trade_id"]))
    with open(out / "trades.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=TRADE_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    with open(out / "accounts.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(report[0].keys()) if report else ["account_id"])
        w.writeheader()
        w.writerows(report)
    print(f"✔ {len(rows)} exécution(s) écrites dans {out / 'trades.csv'} (récap : {out / 'accounts.csv'})")
    return 0


def cmd_import_csv(args) -> int:
    out_file = Path(args.out) / "trades_csv.csv"
    try:
        rows, errors = import_files(args.files, out_file, args.account)
    except CsvImportError as e:
        print(f"✖ {e}", file=sys.stderr)
        return 1
    for err in errors:
        print(f"✖ {err}", file=sys.stderr)
    summary: dict[str, list[float]] = {}
    for r in rows:
        s = summary.setdefault(str(r["account_name"]), [0, 0.0])
        s[0] += 1
        net = r["net_pnl"]
        s[1] += float(net) if net not in (None, "") else 0.0
    print(f"{'Compte':<32} {'Trades':>7} {'P&L net':>12}")
    for name, (count, net) in sorted(summary.items()):
        print(f"{name:<32} {count:>7} {net:>12.2f}")
    print(f"✔ {len(rows)} trade(s) au total dans {out_file}")
    return 1 if errors else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="tradingcoach", description="Export de l'historique TopstepX")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="Tester la connexion à l'API").set_defaults(func=cmd_check)
    sub.add_parser("accounts", help="Lister tous les comptes (actifs et inactifs)").set_defaults(func=cmd_accounts)
    e = sub.add_parser("export", help="Exporter l'historique des trades")
    e.add_argument("--months", type=float, default=6, help="Nombre de mois à remonter (défaut : 6)")
    e.add_argument("--out", default="data", help="Dossier de sortie (défaut : data)")
    e.set_defaults(func=cmd_export)
    i = sub.add_parser("import-csv", help="Importer des CSV exportés depuis TopstepX (onglet Trades)")
    i.add_argument("files", nargs="+", help="Fichiers CSV ou dossiers contenant des CSV")
    i.add_argument("--account", help="Nom du compte (par défaut : nom du fichier, ou colonne Account)")
    i.add_argument("--out", default="data", help="Dossier de sortie (défaut : data)")
    i.set_defaults(func=cmd_import_csv)
    args = p.parse_args(argv)
    try:
        return args.func(args)
    except TopstepXError as err:
        print(f"✖ {err}", file=sys.stderr)
        return 1

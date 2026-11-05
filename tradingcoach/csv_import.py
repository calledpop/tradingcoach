"""Import trade CSV files exported from the TopstepX platform (Trades tab).

The exact export format is not officially documented, so columns are matched
by name through a list of aliases (case, spaces and symbols are ignored).
Each row is one round-trip trade (entry + exit).
"""

from __future__ import annotations

import csv
import re
from datetime import datetime
from pathlib import Path

OUTPUT_COLUMNS = [
    "account_name", "trade_id", "contract", "side", "size",
    "entry_time", "exit_time", "trade_day", "entry_price", "exit_price",
    "pnl", "fees", "commissions", "net_pnl", "source_file",
]

ALIASES = {
    "trade_id": ["id", "tradeid", "trade", "tradenumber"],
    "contract": ["contractname", "contract", "symbol", "instrument", "contractid"],
    "side": ["type", "side", "direction", "position", "marketpos"],
    "size": ["size", "qty", "quantity", "contracts"],
    "entry_time": ["enteredat", "entrytime", "entrydate", "opentime", "entered", "timeentered"],
    "exit_time": ["exitedat", "exittime", "exitdate", "closetime", "exited", "timeexited"],
    "trade_day": ["tradeday", "tradedate", "day", "date"],
    "entry_price": ["entryprice", "openprice", "avgentryprice", "entry"],
    "exit_price": ["exitprice", "closeprice", "avgexitprice", "exit"],
    "pnl": ["pnl", "profitandloss", "profit", "realizedpnl", "grosspnl", "pl"],
    "fees": ["fees", "fee"],
    "commissions": ["commissions", "commission"],
    "account_name": ["account", "accountname", "accountid"],
    # Tradovate "Performance" report: one buy fill + one sell fill per row.
    "buy_time": ["boughttimestamp"],
    "sell_time": ["soldtimestamp"],
    "buy_price": ["buyprice"],
    "sell_price": ["sellprice"],
    "buy_fill": ["buyfillid"],
    "sell_fill": ["sellfillid"],
}

DATE_FORMATS = [
    "%m/%d/%Y %H:%M:%S %z", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M", "%m/%d/%Y %I:%M:%S %p",
    "%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S%z", "%m/%d/%Y", "%Y-%m-%d",
]


class CsvImportError(Exception):
    pass


def _key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def parse_number(value: str | None) -> float | None:
    if value is None:
        return None
    s = value.strip().replace("$", "").replace("€", "").replace(" ", "").replace(" ", "")
    if not s or s in {"-", "—"}:
        return None
    negative = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    if "," in s and "." in s:
        s = s.replace(",", "")  # 1,234.50
    elif "," in s:
        s = s.replace(",", ".")  # 12,5 (French decimal)
    try:
        n = float(s)
    except ValueError:
        return None
    return -n if negative else n


def parse_date(value: str | None) -> str:
    """Return an ISO timestamp when the format is recognised, else the raw text."""
    if not value:
        return ""
    s = value.strip()
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).isoformat()
    except ValueError:
        pass
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).isoformat()
        except ValueError:
            continue
    return s


def _as_datetime(value: str | None) -> datetime | None:
    iso = parse_date(value)
    try:
        return datetime.fromisoformat(iso).replace(tzinfo=None) if iso else None
    except ValueError:
        return None


def _normalize_side(value: str | None) -> str:
    v = (value or "").strip().lower()
    if v in {"long", "buy", "bid", "0", "achat"}:
        return "LONG"
    if v in {"short", "sell", "ask", "1", "vente"}:
        return "SHORT"
    return (value or "").strip()


def _map_columns(headers: list[str]) -> dict[str, str]:
    by_key = {_key(h): h for h in headers if h}
    mapping = {}
    for field, aliases in ALIASES.items():
        for alias in aliases:
            if alias in by_key and by_key[alias] not in mapping.values():
                mapping[field] = by_key[alias]
                break
    return mapping


def read_trades_csv(path: Path, account_name: str | None = None) -> list[dict]:
    text = path.read_text(encoding="utf-8-sig")
    if not text.strip():
        return []
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(text.splitlines(), dialect=dialect)
    headers = reader.fieldnames or []
    mapping = _map_columns(headers)
    if "pnl" not in mapping or not ({"entry_time", "exit_time", "trade_day", "buy_time"} & mapping.keys()):
        raise CsvImportError(
            f"{path.name} : format non reconnu. Colonnes trouvées : {', '.join(headers)}. "
            "Il faut au moins une colonne de P&L et une colonne de date."
        )

    rows = []
    for i, raw in enumerate(reader, start=1):
        get = lambda f: raw.get(mapping[f]) if f in mapping else None  # noqa: E731
        if not any((v or "").strip() for v in raw.values() if isinstance(v, str)):
            continue
        pnl = parse_number(get("pnl"))
        fees = parse_number(get("fees"))
        commissions = parse_number(get("commissions"))
        net = None if pnl is None else round(pnl - (fees or 0) - (commissions or 0), 2)
        size = parse_number(get("size"))
        side, entry_time, exit_time = _normalize_side(get("side")), parse_date(get("entry_time")), parse_date(get("exit_time"))
        entry_price, exit_price = parse_number(get("entry_price")), parse_number(get("exit_price"))
        trade_id = (get("trade_id") or "").strip()
        if "buy_time" in mapping and "sell_time" in mapping:  # Tradovate: infer direction from fill order
            bought, sold = _as_datetime(get("buy_time")), _as_datetime(get("sell_time"))
            buy_price, sell_price = parse_number(get("buy_price")), parse_number(get("sell_price"))
            long_trade = bought is None or sold is None or bought <= sold
            side = "LONG" if long_trade else "SHORT"
            first, last = (get("buy_time"), get("sell_time")) if long_trade else (get("sell_time"), get("buy_time"))
            entry_time, exit_time = parse_date(first), parse_date(last)
            entry_price, exit_price = (buy_price, sell_price) if long_trade else (sell_price, buy_price)
            if not trade_id and (get("buy_fill") or get("sell_fill")):
                trade_id = f"{(get('buy_fill') or '').strip()}-{(get('sell_fill') or '').strip()}"
        rows.append({
            "account_name": account_name or (get("account_name") or "").strip() or path.stem,
            "trade_id": trade_id or f"{path.stem}-{i}",
            "contract": (get("contract") or "").strip(),
            "side": side,
            "size": int(size) if size is not None and size.is_integer() else size,
            "entry_time": entry_time,
            "exit_time": exit_time,
            "trade_day": (parse_date(get("trade_day")) or entry_time)[:10],
            "entry_price": entry_price,
            "exit_price": exit_price,
            "pnl": pnl,
            "fees": fees,
            "commissions": commissions,
            "net_pnl": net,
            "source_file": path.name,
        })
    return rows


def collect_files(paths: list[str]) -> list[Path]:
    files: list[Path] = []
    for p in map(Path, paths):
        if p.is_dir():
            files.extend(sorted(x for x in p.iterdir() if x.suffix.lower() == ".csv"))
        elif p.exists():
            files.append(p)
        else:
            raise CsvImportError(f"Fichier introuvable : {p}")
    return files


def import_files(paths: list[str], out_file: Path, account_name: str | None = None) -> tuple[list[dict], list[str]]:
    """Import CSV files, merging with what out_file already holds (dedup by account + trade id)."""
    merged: dict[tuple[str, str], dict] = {}
    if out_file.exists():
        with open(out_file, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                merged[(r["account_name"], r["trade_id"])] = r
    errors = []
    for path in collect_files(paths):
        try:
            for r in read_trades_csv(path, account_name):
                merged[(str(r["account_name"]), str(r["trade_id"]))] = r
        except CsvImportError as e:
            errors.append(str(e))
    rows = sorted(merged.values(), key=lambda r: (str(r["entry_time"] or r["trade_day"]), str(r["account_name"])))
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    return rows, errors

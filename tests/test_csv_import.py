import csv
import tempfile
import unittest
from pathlib import Path

from tradingcoach import cli
from tradingcoach.csv_import import parse_number, read_trades_csv

TOPSTEPX_STYLE = """﻿Id,ContractName,EnteredAt,ExitedAt,EntryPrice,ExitPrice,Fees,PnL,Size,Type,TradeDay,TradeDuration,Commissions
101,MNQZ6,10/01/2026 14:30:05 +02:00,10/01/2026 14:35:10 +02:00,20000.25,20010.25,0.74,20.00,1,Long,10/01/2026 00:00:00 +02:00,00:05:05,
102,MNQZ6,10/01/2026 15:00:00 +02:00,10/01/2026 15:02:00 +02:00,20015.00,20020.00,0.74,-10.00,1,Short,10/01/2026 00:00:00 +02:00,00:02:00,
"""

SEMICOLON_FR = """Symbol;Side;Qty;Entry Time;Exit Time;P&L;Fees
ES;Sell;2;2026-09-02 15:30:00;2026-09-02 15:40:00;(125,50);2,80
"""


class CsvImportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def write(self, name, text):
        p = self.dir / name
        p.write_text(text, encoding="utf-8")
        return p

    def test_parse_number(self):
        self.assertEqual(parse_number("$1,234.50"), 1234.5)
        self.assertEqual(parse_number("(12.5)"), -12.5)
        self.assertEqual(parse_number("12,5"), 12.5)
        self.assertIsNone(parse_number(""))

    def test_topstepx_format(self):
        rows = read_trades_csv(self.write("50KTC-001.csv", TOPSTEPX_STYLE))
        self.assertEqual(len(rows), 2)
        r = rows[0]
        self.assertEqual(r["account_name"], "50KTC-001")
        self.assertEqual(r["trade_id"], "101")
        self.assertEqual(r["side"], "LONG")
        self.assertEqual(r["size"], 1)
        self.assertEqual(r["entry_time"], "2026-10-01T14:30:05+02:00")
        self.assertEqual(r["trade_day"], "2026-10-01")
        self.assertEqual(r["net_pnl"], 19.26)
        self.assertEqual(rows[1]["side"], "SHORT")

    def test_semicolon_and_french_decimals(self):
        rows = read_trades_csv(self.write("x.csv", SEMICOLON_FR), account_name="EXPRESS")
        self.assertEqual(rows[0]["pnl"], -125.5)
        self.assertEqual(rows[0]["net_pnl"], -128.3)
        self.assertEqual(rows[0]["side"], "SHORT")
        self.assertEqual(rows[0]["account_name"], "EXPRESS")

    def test_unknown_format_is_reported(self):
        self.write("bad.csv", "foo,bar\n1,2\n")
        self.write("A.csv", TOPSTEPX_STYLE)
        out = self.dir / "out"
        code = cli.main(["import-csv", str(self.dir), "--out", str(out)])
        self.assertEqual(code, 1)  # bad.csv rejected, A.csv still imported
        rows = list(csv.DictReader((out / "trades_csv.csv").read_text().splitlines()))
        self.assertEqual(len(rows), 2)

    def test_reimport_merges_without_duplicates(self):
        a = self.write("ACC1.csv", TOPSTEPX_STYLE)
        b = self.write("ACC2.csv", TOPSTEPX_STYLE)
        out = self.dir / "out"
        self.assertEqual(cli.main(["import-csv", str(a), "--out", str(out)]), 0)
        self.assertEqual(cli.main(["import-csv", str(a), str(b), "--out", str(out)]), 0)
        rows = list(csv.DictReader((out / "trades_csv.csv").read_text().splitlines()))
        self.assertEqual(len(rows), 4)
        self.assertEqual({r["account_name"] for r in rows}, {"ACC1", "ACC2"})


if __name__ == "__main__":
    unittest.main()

"""SmartX 下单 CSV 生成器的测试（只生成文件，不提交）。"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from quant.broker import proposals  # noqa: E402
from quant.broker.smartx_csv import (  # noqa: E402
    SmartxCsvError,
    build_lines,
    normalize_symbol,
    proposal_to_order,
    write_batch,
)

ACCOUNT = "12345678"


def _proposal(pid: str = "prop-aaa", symbol: str = "600000.SH", side: str = "BUY", qty: int = 100, price: float = 10.0) -> dict:
    return {
        "proposal_id": pid,
        "symbol": symbol,
        "side": side,
        "quantity": qty,
        "order_type": "MARKET",
        "limit_price": None,
        "price_snapshot": price,
    }


QUOTES = {"600000.SH": {"last": 10.0, "limit_up": 10.5, "limit_down": 9.5}}


class SymbolTests(unittest.TestCase):
    def test_variants(self) -> None:
        cases = {
            "600000": "600000.SH",
            "600000.SH": "600000.SH",
            "sh.600000": "600000.SH",
            "SH600000": "600000.SH",
            "000001": "000001.SZ",
            "000001.SZ": "000001.SZ",
            "sz.000001": "000001.SZ",
            "830799": "830799.BJ",
        }
        for raw, expected in cases.items():
            self.assertEqual(normalize_symbol(raw), expected, raw)

    def test_bad_symbol(self) -> None:
        with self.assertRaises(SmartxCsvError):
            normalize_symbol("ABC")


class BuildLinesTests(unittest.TestCase):
    def test_order_line_matches_official_shape(self) -> None:
        lines = build_lines([proposal_to_order(_proposal(), QUOTES)], ACCOUNT)
        self.assertEqual(lines, ["1,12345678,600000.SH,10,100,1,1,0,prop-aaa,"])

    def test_sell_and_price_decimals(self) -> None:
        quotes = {"600000.SH": {"last": 27.021, "limit_up": 29.0, "limit_down": 25.0}}
        lines = build_lines([proposal_to_order(_proposal(side="SELL"), quotes)], ACCOUNT)
        self.assertEqual(lines[0].split(",")[3], "27.021")
        self.assertEqual(lines[0].split(",")[6], "2")

    def test_quotes_last_overrides_adjusted_snapshot(self) -> None:
        quotes = {"600000.SH": {"last": 11.92, "limit_up": 13.11, "limit_down": 10.73}}
        order = proposal_to_order(_proposal(price=30.3099), quotes)
        self.assertEqual(order["price"], 11.92)

    def test_cancel_line(self) -> None:
        lines = build_lines([], ACCOUNT, cancels=["40126371980117969"])
        self.assertEqual(lines, ["2,12345678,40126371980117969,"])

    def test_bad_account(self) -> None:
        with self.assertRaises(SmartxCsvError):
            build_lines([], "ABC")


class WriteBatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.mkdtemp(prefix="smartx-csv-")
        self.old = os.environ.get("NFR_BROKER_DIR")
        os.environ["NFR_BROKER_DIR"] = os.path.join(self.dir, "broker")
        self.out = os.path.join(self.dir, "in")

    def tearDown(self) -> None:
        if self.old is None:
            os.environ.pop("NFR_BROKER_DIR", None)
        else:
            os.environ["NFR_BROKER_DIR"] = self.old
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_writes_crlf_and_audit(self) -> None:
        result = write_batch([_proposal()], ACCOUNT, out_dir=self.out, quotes=QUOTES)
        with open(result["path"], "rb") as fh:
            raw = fh.read()
        self.assertTrue(raw.startswith(b"1,12345678,600000.SH,10,100,1,1,0,prop-aaa,\r\n"))
        self.assertTrue(raw.endswith(b"0\r\n"))
        self.assertTrue(os.path.exists(result["path"] + ".json"))
        with open(result["path"] + ".json", encoding="utf-8") as fh:
            audit = json.load(fh)
        self.assertEqual(audit["proposal_ids"], ["prop-aaa"])
        self.assertEqual(audit["sha256"], result["sha256"])

    def test_duplicate_proposal_rejected(self) -> None:
        write_batch([_proposal()], ACCOUNT, out_dir=self.out, quotes=QUOTES)
        with self.assertRaises(SmartxCsvError) as ctx:
            write_batch([_proposal()], ACCOUNT, out_dir=self.out, quotes=QUOTES)
        self.assertEqual(ctx.exception.code, "DUPLICATE_PROPOSAL")

    def test_price_outside_limit_rejected(self) -> None:
        quotes = {"600000.SH": {"last": 11.0, "limit_up": 10.5, "limit_down": 9.5}}
        with self.assertRaises(SmartxCsvError) as ctx:
            write_batch([_proposal()], ACCOUNT, out_dir=self.out, quotes=quotes)
        self.assertEqual(ctx.exception.code, "PRICE_OUT_OF_LIMIT")

    def test_strict_without_quotes_rejected(self) -> None:
        with self.assertRaises(SmartxCsvError) as ctx:
            write_batch([_proposal()], ACCOUNT, out_dir=self.out, strict=True, allow_unchecked=True)
        self.assertEqual(ctx.exception.code, "STRICT_WARNINGS")

    def test_no_quotes_rejected_by_default(self) -> None:
        with self.assertRaises(SmartxCsvError) as ctx:
            write_batch([_proposal()], ACCOUNT, out_dir=self.out)
        self.assertEqual(ctx.exception.code, "QUOTES_REQUIRED")

    def test_dry_run_does_not_write(self) -> None:
        result = write_batch([_proposal()], ACCOUNT, out_dir=self.out, quotes=QUOTES, dry_run=True)
        self.assertIn("csv", result)
        self.assertFalse(os.path.exists(result["path"]))


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.mkdtemp(prefix="smartx-csv-cli-")
        self.old = os.environ.get("NFR_BROKER_DIR")
        os.environ["NFR_BROKER_DIR"] = os.path.join(self.dir, "broker")
        self.out = os.path.join(self.dir, "in")

    def tearDown(self) -> None:
        if self.old is None:
            os.environ.pop("NFR_BROKER_DIR", None)
        else:
            os.environ["NFR_BROKER_DIR"] = self.old
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_cli_generates_from_proposal(self) -> None:
        from scripts.make_smartx_csv import main

        prop = proposals.create(symbol="600000.SH", side="BUY", quantity=100, order_type="LIMIT", limit_price=10.0)
        quotes = os.path.join(self.dir, "quotes.json")
        with open(quotes, "w", encoding="utf-8") as fh:
            json.dump(QUOTES, fh)
        code = main(
            ["--proposal", prop.id, "--account", ACCOUNT, "--out-dir", self.out, "--quotes", quotes]
        )
        self.assertEqual(code, 0)
        files = [name for name in os.listdir(self.out) if name.endswith(".csv")]
        self.assertEqual(len(files), 1)
        with open(os.path.join(self.out, files[0]), "rb") as fh:
            content = fh.read()
        self.assertIn(prop.id.encode(), content)
        self.assertIn(b",10,100,1,1,0,", content)


if __name__ == "__main__":
    unittest.main()

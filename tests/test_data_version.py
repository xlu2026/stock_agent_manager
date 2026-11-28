"""全文件 data_version：fundamentals 变化必须换版本，篡改必须被拦截。"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from quant.data import DataError, load_panel  # noqa: E402
from quant.providers.contract import Snapshot, write_snapshot  # noqa: E402


def _snap(book: float) -> Snapshot:
    return Snapshot(
        universe="test",
        source="fixture",
        provider="fixture",
        adjust_mode="backward",
        prices=[
            {"date": "2024-01-02", "asset": "AAA", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1, "adj_factor": 1.0}
        ],
        fundamentals=[
            {"asset": "AAA", "report_date": "2023-12-31", "available_date": "2024-04-30", "book": book, "earnings": 1.0}
        ],
        calendar=[{"date": "2024-01-02"}],
        universe_rows=[{"date": "2024-01-02", "asset": "AAA"}],
    )


class FullHashTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.mkdtemp(prefix="nfr-dv-")

    def tearDown(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_fundamentals_change_version(self) -> None:
        a = os.path.join(self.dir, "a")
        b = os.path.join(self.dir, "b")
        ma = write_snapshot(a, _snap(1.0))
        mb = write_snapshot(b, _snap(2.0))
        self.assertNotEqual(ma["data_version"], mb["data_version"])
        self.assertEqual(load_panel(a).data_version, ma["data_version"])
        self.assertEqual(load_panel(b).data_version, mb["data_version"])

    def test_tampered_file_rejected(self) -> None:
        path = os.path.join(self.dir, "a")
        write_snapshot(path, _snap(1.0))
        with open(os.path.join(path, "fundamentals.csv"), "a", encoding="utf-8") as fh:
            fh.write("AAA,2023-12-31,2024-04-30,9,9\n")
        with self.assertRaises(DataError):
            load_panel(path)


if __name__ == "__main__":
    unittest.main()

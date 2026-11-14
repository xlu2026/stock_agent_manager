"""抓取不复权报价的纯函数测试（不联网）。"""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scripts.fetch_quotes import limit_pct, limit_prices  # noqa: E402


class LimitPctTests(unittest.TestCase):
    def test_board_rules(self) -> None:
        self.assertEqual(limit_pct("601939.SH"), 0.10)
        self.assertEqual(limit_pct("000001.SZ"), 0.10)
        self.assertEqual(limit_pct("300750.SZ"), 0.20)
        self.assertEqual(limit_pct("688981.SH"), 0.20)
        self.assertEqual(limit_pct("830799.BJ"), 0.30)


class LimitPricesTests(unittest.TestCase):
    def test_main_board(self) -> None:
        low, high = limit_prices(11.92, 0.10)
        self.assertEqual((low, high), (10.73, 13.11))

    def test_chinext(self) -> None:
        low, high = limit_prices(10.0, 0.20)
        self.assertEqual((low, high), (8.0, 12.0))


if __name__ == "__main__":
    unittest.main()

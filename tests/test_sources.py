"""数据源注册表测试。"""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from quant.providers import sources  # noqa: E402


class SourceTests(unittest.TestCase):
    def test_akshare_registered(self) -> None:
        self.assertEqual(sources.list_sources(), ["akshare"])
        self.assertTrue(callable(sources.get_source("akshare")))

    def test_unknown_source(self) -> None:
        with self.assertRaises(KeyError):
            sources.get_source("qmt")


if __name__ == "__main__":
    unittest.main()

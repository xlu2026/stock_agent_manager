import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scripts.wechat_check_ip import parse_ip  # noqa: E402


class CheckIpTest(unittest.TestCase):
    def test_parse_ipv4(self) -> None:
        msg = "invalid ip 171.223.64.146 ipv6 ::ffff:171.223.64.146, not in whitelist"
        self.assertEqual(parse_ip(msg), "171.223.64.146")

    def test_parse_ipv6(self) -> None:
        msg = "invalid ip ::1, not in whitelist"
        self.assertEqual(parse_ip(msg), "::1")

    def test_parse_missing(self) -> None:
        self.assertIsNone(parse_ip("some other error"))

    def test_none_input(self) -> None:
        self.assertIsNone(parse_ip(None))


if __name__ == "__main__":
    unittest.main()

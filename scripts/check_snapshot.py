"""给一份数据快照做体检。

    python scripts/check_snapshot.py <快照目录>

退出码：0 = 可以加载；1 = 有 fail，不要用这份数据。
"""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from quant.console import force_utf8  # noqa: E402
from quant.providers.snapshot_check import check_snapshot  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    force_utf8()
    argv = argv if argv is not None else sys.argv[1:]
    if len(argv) != 1:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    result = check_snapshot(argv[0])
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["ok"]:
        fails = [c for c in result["checks"] if c["status"] == "fail"]
        print(f"\n体检未通过：{len(fails)} 项 fail，这份数据不要拿去回测。", file=sys.stderr)
        return 1
    print("\n体检通过。", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""公众号草稿接口预检：Phase 1 必答问题 1。

    python scripts/check_wechat_draft.py            # 人读 + 机器读
    python scripts/check_wechat_draft.py --json     # 只输出 JSON

第一行永远是明确结论：
    DRAFT_API_AVAILABLE
    DRAFT_API_UNAVAILABLE
"""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agents.envelope import envelope, rel, write_json  # noqa: E402
from quant.console import force_utf8  # noqa: E402
from writing.wechat import probe_draft_api  # noqa: E402

OUT = os.path.join(ROOT, "output", "reports", "draft_precheck.json")


def run() -> dict:
    probe = probe_draft_api()
    available = bool(probe["available"])
    verdict = "DRAFT_API_AVAILABLE" if available else "DRAFT_API_UNAVAILABLE"

    env = envelope(
        agent="wechat-draft-precheck",
        kind="wechat.draft_precheck",
        status="ok" if available else "blocked",
        id_=verdict,
        summary={
            "verdict": verdict,
            "available": available,
            "reason": probe["reason"],
            "detail": probe["detail"],
            "errcode": probe.get("errcode"),
            "api_probed": probe.get("api"),
            "probe_mode": probe.get("probe"),
            "fallback": None if available else "生成 Markdown 到 output/articles/",
            "creds_source": probe.get("creds_source"),
        },
        artifacts=[
            {
                "type": "backend_choice",
                "channel": "wechat_draft" if available else "markdown",
                "media_id": None,
            }
        ],
        compliance={"checked": True, "violations": [], "published": False, "publish_api": "absent"},
    )
    write_json(OUT, env)
    env["written_to"] = rel(OUT)
    return {"verdict": verdict, "envelope": env}


def main() -> int:
    force_utf8()
    args = sys.argv[1:]
    json_only = "--json" in args
    require = "--require-available" in args
    result = run()
    if json_only:
        print(json.dumps(result["envelope"], ensure_ascii=False, indent=2))
    else:
        print(result["verdict"])
        print(json.dumps(result["envelope"], ensure_ascii=False, indent=2))
    # 默认 0：预检本身成功，结论不阻塞流程。
    # --require-available：给 Router / CI 用，不可用时返回 1。
    if require and not result["envelope"]["summary"]["available"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

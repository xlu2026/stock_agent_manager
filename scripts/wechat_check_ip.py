r"""查看公众号接口的当前出口 IP 是否在 API IP 白名单里。

微信接口用 errcode 40164 报错时会带上它看到的出口 IP；动态宽带下这个 IP 会变，
每次发布前跑一次，把打印出来的地址加进白名单即可。

用法：
    python scripts\wechat_check_ip.py
    python scripts\wechat_check_ip.py --json

退出码：0 已在白名单；2 需要加白名单；1 其他错误（凭据缺失、网络问题等）。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from writing.wechat import WeChatError, get_access_token, load_credentials  # noqa: E402

IP_RE = re.compile(r"invalid ip ([0-9a-fA-F:.]+)")
WHITELIST_HINT = "开发者平台 → 我的业务 → 公众号 → 基础信息 → 开发密钥 → API IP 白名单"


def parse_ip(errmsg: str) -> str | None:
    """从 40164 的 errmsg 里取出微信看到的出口 IP。"""
    m = IP_RE.search(errmsg or "")
    if not m:
        return None
    return m.group(1)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="检查公众号接口出口 IP 是否在白名单")
    ap.add_argument("--json", action="store_true", help="输出 JSON，便于脚本消费")
    args = ap.parse_args(argv)

    creds = load_credentials()
    if not creds.get("appid") or not creds.get("appsecret"):
        payload = {"ok": False, "stage": "credentials", "detail": "缺少 WECHAT_APPID / WECHAT_APPSECRET"}
        print(json.dumps(payload, ensure_ascii=False) if args.json else payload["detail"])
        return 1

    try:
        get_access_token(creds["appid"], creds["appsecret"])
    except WeChatError as exc:
        ip = parse_ip(exc.errmsg)
        if ip:
            payload = {
                "ok": False,
                "stage": "whitelist",
                "ip": ip,
                "errcode": exc.errcode,
                "next": f"把 {ip} 加进 API IP 白名单：{WHITELIST_HINT}",
            }
            if args.json:
                print(json.dumps(payload, ensure_ascii=False))
            else:
                print(f"出口 IP：{ip}")
                print("状态：不在白名单（errcode 40164）")
                print(f"下一步：{WHITELIST_HINT}，把 {ip} 加进去")
            return 2
        payload = {"ok": False, "stage": "api", "errcode": exc.errcode, "detail": exc.errmsg}
        print(json.dumps(payload, ensure_ascii=False) if args.json else f"接口报错：{exc}")
        return 1
    except Exception as exc:  # 网络等
        payload = {"ok": False, "stage": "network", "detail": str(exc)}
        print(json.dumps(payload, ensure_ascii=False) if args.json else f"请求失败：{exc}")
        return 1

    payload = {"ok": True, "stage": "ok", "detail": "token 正常，当前出口 IP 已在白名单"}
    print(json.dumps(payload, ensure_ascii=False) if args.json else "状态：正常，当前出口 IP 已在白名单")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

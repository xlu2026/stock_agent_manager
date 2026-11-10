"""微信公众号草稿接口的最小客户端（纯标准库）。

能力边界（简报第 3 节）：
- 只有 ``draft`` 相关接口；**本模块不存在 freepublish**，也没有任何发布函数。
- 预检默认只做无副作用的探测（取 token + 读草稿），不会凭空创建草稿。
"""
from __future__ import annotations

import html
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

API_BASE = "https://api.weixin.qq.com"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TIMEOUT = 20

# 取 token / 读草稿时可能遇到的错误码 -> 人话
ERRCODE_HINTS = {
    -1: "微信侧系统繁忙，稍后重试",
    40001: "AppSecret 错误或 token 失效",
    40013: "AppID 无效",
    40125: "AppSecret 无效",
    40164: "调用 IP 不在白名单内（需要把本机出口 IP 加入公众号后台白名单）",
    41002: "缺少 AppID",
    42001: "token 已过期",
    45009: "接口调用次数超限",
    48001: "该接口未授权（个人订阅号通常没有草稿箱接口权限）",
    48004: "接口被封禁",
    40007: "media_id 无效（探测用的占位 ID 属预期）",
    40097: "参数不合法",
}


class WeChatError(RuntimeError):
    def __init__(self, errcode: int, errmsg: str, api: str) -> None:
        self.errcode = errcode
        self.errmsg = errmsg
        self.api = api
        super().__init__(f"[{api}] errcode={errcode} errmsg={errmsg}")


def load_credentials(root: str = ROOT) -> dict:
    """优先环境变量，其次 .env（仓库根 / DSH_HOME），不读公众号后台任何缓存。"""
    appid = os.environ.get("WECHAT_APPID", "").strip()
    secret = os.environ.get("WECHAT_APPSECRET", "").strip()
    source = "env" if (appid and secret) else None

    if not (appid and secret):
        for path in (os.path.join(root, ".env"), os.path.join(os.environ.get("DSH_HOME", ""), ".env")):
            if not path or not os.path.exists(path):
                continue
            parsed = _parse_env(path)
            appid = appid or parsed.get("WECHAT_APPID", "")
            secret = secret or parsed.get("WECHAT_APPSECRET", "")
            if appid and secret:
                source = os.path.relpath(path, root) if path.startswith(root) else path
                break

    return {
        "appid": appid,
        "appsecret": secret,
        "present": bool(appid and secret),
        "source": source,
        "appid_masked": (appid[:4] + "***" + appid[-2:]) if len(appid) > 8 else ("***" if appid else ""),
    }


def _parse_env(path: str) -> dict[str, str]:
    out: dict[str, str] = {}
    with open(path, encoding="utf-8-sig") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def _get_json(url: str, params: dict, api: str, data: bytes | None = None) -> dict:
    full = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(full, data=data, method="POST" if data is not None else "GET")
    if data is not None:
        req.add_header("Content-Type", "application/json; charset=utf-8")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace") if exc.fp else ""
        raise WeChatError(exc.code, f"HTTP {exc.code} {body[:200]}", api) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise WeChatError(-2, f"网络不可达：{exc}", api) from exc
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise WeChatError(-3, f"响应不是 JSON：{raw[:200]}", api) from exc


def get_access_token(appid: str, secret: str) -> str:
    data = _get_json(
        f"{API_BASE}/cgi-bin/token",
        {"grant_type": "client_credential", "appid": appid, "secret": secret},
        "cgi-bin/token",
    )
    if "access_token" in data:
        return data["access_token"]
    raise WeChatError(int(data.get("errcode", -1)), str(data.get("errmsg", "")), "cgi-bin/token")


def classify_draft_probe(payload: dict | None, exc: "WeChatError | None") -> dict:
    """把一次草稿探测的结果归类。payload 与 exc 二选一。

    微信的失败有两种形态：HTTP 4xx（抛异常）和 HTTP 200 + body 里的 errcode。
    两种都要判，否则 48001 会被当成"成功"。
    """
    errcode = exc.errcode if exc else int((payload or {}).get("errcode", 0) or 0)
    errmsg = exc.errmsg if exc else str((payload or {}).get("errmsg", ""))

    if errcode in (48001, 48004):
        return {
            "available": False,
            "reason": "API_UNAUTHORIZED",
            "errcode": errcode,
            "detail": ERRCODE_HINTS.get(errcode, errmsg or "接口未授权"),
            "api": "cgi-bin/draft/get",
            "probe": "draft_get",
        }
    if errcode in (40007, 40097, 40002):
        return {
            "available": True,
            "reason": "OK",
            "errcode": errcode,
            "detail": "草稿接口已授权（占位 media_id 被拒属预期）",
            "api": "cgi-bin/draft/add",
            "probe": "draft_get",
        }
    if errcode == 0:
        return {
            "available": True,
            "reason": "OK",
            "errcode": 0,
            "detail": "draft/get 探测成功",
            "api": "cgi-bin/draft/add",
            "probe": "draft_get",
        }
    return {
        "available": False,
        "reason": "PROBE_UNKNOWN",
        "errcode": errcode,
        "detail": ERRCODE_HINTS.get(errcode, errmsg or "未知错误"),
        "api": "cgi-bin/draft/get",
        "probe": "draft_get",
    }


def probe_draft_api(creds: dict | None = None) -> dict:
    """判断 draft/add 是否可用，全程无副作用。

    判据：
    - 没有凭据 -> NO_CREDENTIALS
    - token 取不到 -> TOKEN_FAILED（附微信错误码，能区分 IP 白名单 / 密钥错误）
    - 读草稿返回 48001/48004 -> API_UNAUTHORIZED（接口未授权）
    - 读草稿返回 media_id 相关错误 -> 接口通、权限在 => AVAILABLE
    """
    creds = creds or load_credentials()
    if not creds["present"]:
        return {
            "available": False,
            "reason": "NO_CREDENTIALS",
            "detail": (
                "未找到 WECHAT_APPID / WECHAT_APPSECRET；请写入环境变量或仓库根 .env。"
                "在提供凭据之前，无法判断 draft/add 是否可用。"
            ),
            "api": "cgi-bin/draft/add",
            "probe": "skipped",
            "creds_source": creds["source"],
        }

    try:
        token = get_access_token(creds["appid"], creds["appsecret"])
    except WeChatError as exc:
        return {
            "available": False,
            "reason": "TOKEN_FAILED",
            "detail": ERRCODE_HINTS.get(exc.errcode, exc.errmsg),
            "errcode": exc.errcode,
            "errmsg": exc.errmsg,
            "api": "cgi-bin/token",
            "probe": "token",
            "creds_source": creds["source"],
        }

    # 只读探测：用占位 media_id 调 draft/get，比 draft/add 安全（不会产生草稿）
    payload: dict | None = None
    exc: WeChatError | None = None
    try:
        payload = _get_json(
            f"{API_BASE}/cgi-bin/draft/get",
            {"access_token": token},
            "cgi-bin/draft/get",
            data=json.dumps({"media_id": "probe-placeholder"}).encode("utf-8"),
        )
    except WeChatError as err:
        exc = err

    result = classify_draft_probe(payload, exc)
    result["creds_source"] = creds["source"]
    return result


def _post_multipart(url: str, fields: dict[str, str], file_field: tuple[str, str, bytes, str], api: str) -> dict:
    boundary = "----dsh" + os.urandom(8).hex()
    chunks: list[bytes] = []
    for key, value in fields.items():
        chunks.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n{value}\r\n".encode("utf-8")
        )
    name, filename, content, ctype = file_field
    chunks.append(
        (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"; filename=\"{filename}\"\r\n"
            f"Content-Type: {ctype}\r\n\r\n"
        ).encode("utf-8")
    )
    chunks.append(content)
    chunks.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))
    body = b"".join(chunks)
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        raise WeChatError(exc.code, f"HTTP {exc.code}", api) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise WeChatError(-2, f"网络不可达：{exc}", api) from exc
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise WeChatError(-3, f"响应不是 JSON：{raw[:200]}", api) from exc


def upload_permanent_image(path: str) -> dict:
    """把一张图上传为永久素材，返回 media_id。草稿封面必须用它。"""
    if not os.path.exists(path):
        raise WeChatError(-4, f"图片不存在：{path}", "material/add_material")
    ext = os.path.splitext(path)[1].lower()
    ctype = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}.get(ext)
    if not ctype:
        raise WeChatError(-4, f"只支持 png/jpg 封面，收到 {ext or '未知后缀'}", "material/add_material")
    if os.path.getsize(path) > 10 * 1024 * 1024:
        raise WeChatError(-4, "封面图超过 10MB", "material/add_material")

    creds = load_credentials()
    token = get_access_token(creds["appid"], creds["appsecret"])
    with open(path, "rb") as fh:
        content = fh.read()
    data = _post_multipart(
        f"{API_BASE}/cgi-bin/material/add_material?access_token={token}&type=image",
        {},
        ("media", os.path.basename(path), content, ctype),
        "material/add_material",
    )
    if "media_id" not in data:
        raise WeChatError(int(data.get("errcode", -1)), str(data.get("errmsg", "")), "material/add_material")
    return {"media_id": data["media_id"], "url": data.get("url"), "source": path}


# --------------------------------------------------------------- 写草稿


def markdown_to_wechat_html(md: str) -> str:
    """极简 Markdown -> 微信可接受的 HTML（标题/段落/加粗/引用）。

    带少量内联样式：公众号编辑器会丢掉 class 和外部样式，但保留 style，
    所以直接粘进后台富文本编辑器也能保持基本排版。
    """
    body = re.sub(r"\A---\n.*?\n---\n", "", md, count=1, flags=re.S)
    p_style = 'style="margin:0 0 1.2em;line-height:1.9;font-size:16px;color:#333;letter-spacing:0.4px;"'
    h_style = 'style="margin:1.6em 0 0.8em;font-size:19px;font-weight:bold;color:#222;line-height:1.5;"'
    out: list[str] = []
    for block in body.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        if block.startswith("### "):
            out.append(f"<h3 {h_style}>{html.escape(block[4:])}</h3>")
        elif block.startswith("## "):
            out.append(f"<h2 {h_style}>{html.escape(block[3:])}</h2>")
        elif block.startswith("# "):
            out.append(f"<h1 {h_style}>{html.escape(block[2:])}</h1>")
        elif block.startswith("> "):
            out.append(
                '<blockquote style="margin:1.2em 0;padding:0.6em 1em;border-left:3px solid #d0d0d0;'
                f'color:#666;font-size:15px;line-height:1.8;">{html.escape(block[2:])}</blockquote>'
            )
        elif block.startswith("---"):
            out.append('<p style="text-align:center;color:#bbb;margin:2em 0;">· · ·</p>')
        else:
            # 先转义再插 <br/>：反过来的话 <br/> 会被转义成 &lt;br/&gt;，在后台显示成字面量。
            text = html.escape(block).replace("\n", "<br/>")
            text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
            out.append(f"<p {p_style}>{text}</p>")
    return "\n".join(out)


def add_draft(token: str, article: dict) -> str:
    """写一篇草稿，返回 media_id。article 需含 title/content，thumb_media_id 可选。"""
    payload = {"articles": [article]}
    data = _get_json(
        f"{API_BASE}/cgi-bin/draft/add",
        {"access_token": token},
        "cgi-bin/draft/add",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    )
    if "media_id" in data:
        return data["media_id"]
    raise WeChatError(int(data.get("errcode", -1)), str(data.get("errmsg", "")), "cgi-bin/draft/add")


def update_draft(token: str, media_id: str, article: dict, index: int = 0) -> bool:
    """原地更新草稿（改封面、改正文用这个，别新建一篇）。

    注意：draft/update 的 articles 是单个对象，不是数组——和 draft/add 不一样。
    """
    payload = {"media_id": media_id, "index": index, "articles": article}
    data = _get_json(
        f"{API_BASE}/cgi-bin/draft/update",
        {"access_token": token},
        "cgi-bin/draft/update",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    )
    errcode = int(data.get("errcode", 0) or 0)
    if errcode == 0:
        return True
    raise WeChatError(errcode, str(data.get("errmsg", "")), "cgi-bin/draft/update")


def get_draft(token: str, media_id: str) -> dict:
    data = _get_json(
        f"{API_BASE}/cgi-bin/draft/get",
        {"access_token": token},
        "cgi-bin/draft/get",
        data=json.dumps({"media_id": media_id}).encode("utf-8"),
    )
    errcode = int(data.get("errcode", 0) or 0)
    if errcode:
        raise WeChatError(errcode, str(data.get("errmsg", "")), "cgi-bin/draft/get")
    return data

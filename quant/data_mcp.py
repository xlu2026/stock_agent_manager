"""数据运维 MCP 服务端（Agent 2 专用）。

只做四件事：列快照、启动刷新作业、查作业状态、体检快照。
它不跑回测、不写实验记录、不碰下单——那是 Agent 1 的事。

    python -m quant.data_mcp

环境变量：

- `NFR_SNAPSHOT_ROOT`      快照根目录（默认 `<repo>/snapshots`）
- `NFR_BAOSTOCK_PYTHON`    装了 baostock 的解释器（刷新必需，例如 SmartX 自带的）
- `NFR_EXPORT_SCRIPT`      导出脚本路径（默认 `<repo>/scripts/export_baostock_snapshot.py`）
- `NFR_DATA_JOB_DIR`       作业状态目录（默认 `<repo>/output/data_jobs`）
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from datetime import date, datetime, timezone

from shared.mcp_stdio import McpServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_NAME = "data-ops"
SERVER_VERSION = "0.1.0"
DEFAULT_UNIVERSE = "hs300_40_pit"
DEFAULT_START = "2019-01-01"
CONFIG_PATH = os.path.join(ROOT, "config", "agent2.json")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _clock() -> dict:
    """服务端时钟：Agent 2 没有 shell，靠这个拿“今天”来命名目录。"""
    local = datetime.now().astimezone()
    return {"now": local.isoformat(timespec="seconds"), "today": local.date().isoformat()}


def _config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        return {}
    try:
        with open(CONFIG_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _setting(env_name: str, key: str, default: str = "") -> str:
    value = os.environ.get(env_name, "").strip()
    if value:
        return value
    value = str(_config().get(key) or "").strip()
    return value or default


def _job_root() -> str:
    return _setting("NFR_DATA_JOB_DIR", "job_dir", os.path.join(ROOT, "output", "data_jobs"))


def _snapshot_root() -> str:
    return _setting("NFR_SNAPSHOT_ROOT", "snapshot_root", os.path.join(ROOT, "snapshots"))


def _exporter_python() -> str:
    value = _setting("NFR_BAOSTOCK_PYTHON", "baostock_python")
    if not value:
        raise RuntimeError(
            "没有配置 baostock 解释器：设置 NFR_BAOSTOCK_PYTHON，或在 "
            f"{CONFIG_PATH} 里写 baostock_python。"
            r"例如 C:\Users\<you>\AppData\Local\Programs\xtp_rich_client\bin\cpython\python.exe"
        )
    if not os.path.exists(value):
        raise RuntimeError(f"baostock 解释器不存在：{value}（检查 {CONFIG_PATH}）")
    return value


def _exporter_script() -> str:
    value = _setting(
        "NFR_EXPORT_SCRIPT",
        "export_script",
        os.path.join(ROOT, "scripts", "export_baostock_snapshot.py"),
    )
    if not os.path.exists(value):
        raise RuntimeError(f"找不到导出脚本：{value}")
    return value


def _config_status() -> dict:
    return {
        "config_path": CONFIG_PATH,
        "config_exists": os.path.exists(CONFIG_PATH),
        "baostock_python_configured": bool(_setting("NFR_BAOSTOCK_PYTHON", "baostock_python")),
    }


def _validate_date(value: str, name: str) -> None:
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(f"{name} 必须是 YYYY-MM-DD：{value!r}") from exc


def _is_within(root: str, path: str) -> bool:
    try:
        return os.path.commonpath([os.path.abspath(root), os.path.abspath(path)]) == os.path.abspath(root)
    except ValueError:
        return False


def _manifest_info(dir_path: str) -> dict:
    path = os.path.join(dir_path, "manifest.json")
    if not os.path.exists(path):
        return {}
    try:
        manifest = _read_json(path)
    except (OSError, json.JSONDecodeError):
        return {}
    sha = str(manifest.get("sha256") or "")
    return {
        "end": manifest.get("end"),
        "data_version": "dv-" + sha[:12] if sha else None,
        "universe": manifest.get("universe"),
    }


def _has_files(path: str) -> bool:
    for _root, _dirs, files in os.walk(path):
        if files:
            return True
    return False


def _require_ascii(path: str, what: str) -> None:
    try:
        path.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError(f"{what} 必须是纯 ASCII 路径（客户端不认中文）：{path}") from exc


def _read_json(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _write_json(path: str, payload: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, path)


def _pid_alive(pid: int) -> bool:
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    import ctypes

    handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))
    if not handle:
        return False
    code = ctypes.c_ulong()
    ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
    ctypes.windll.kernel32.CloseHandle(handle)
    return code.value == 259  # STILL_ACTIVE


def _snapshot_summary(dir_path: str) -> dict | None:
    manifest_path = os.path.join(dir_path, "manifest.json")
    if not os.path.exists(manifest_path):
        return None
    manifest = _read_json(manifest_path)
    sha = str(manifest.get("sha256") or "")
    return {
        "dir": os.path.abspath(dir_path),
        "data_version": "dv-" + sha[:12] if sha else None,
        "universe": manifest.get("universe"),
        "start": manifest.get("start"),
        "end": manifest.get("end"),
        "assets": len(manifest.get("assets") or []),
        "source": manifest.get("source"),
        "schema_version": manifest.get("schema_version"),
        "point_in_time": bool((manifest.get("notes") or {}).get("universe_point_in_time")),
        "incremental": bool((manifest.get("notes") or {}).get("incremental")),
    }


def _latest_pointer() -> dict | None:
    try:
        from quant.data_pointer import read_pointer

        return read_pointer()
    except (FileNotFoundError, ValueError):
        return None


def _tool_list_snapshots(args: dict) -> dict:
    root = str(args.get("root") or _snapshot_root())
    if not os.path.isdir(root):
        return {
            **_clock(),
            "config": _config_status(),
            "latest": _latest_pointer(),
            "root": os.path.abspath(root),
            "count": 0,
            "snapshots": [],
        }
    found = []
    for name in sorted(os.listdir(root)):
        path = os.path.join(root, name)
        if not os.path.isdir(path):
            continue
        summary = _snapshot_summary(path)
        if summary:
            found.append(summary)
    found.sort(key=lambda s: (s.get("end") or "", s.get("dir") or ""))
    return {
        **_clock(),
        "config": _config_status(),
        "latest": _latest_pointer(),
        "root": os.path.abspath(root),
        "count": len(found),
        "snapshots": found,
    }


def _tool_refresh_snapshot(args: dict) -> dict:
    out_dir = str(args.get("out_dir") or "").strip()
    base_dir = str(args.get("base_dir") or "").strip() or None
    if not out_dir:
        raise ValueError("必须给 out_dir（新快照目录）")
    out_dir = os.path.abspath(out_dir)
    _require_ascii(out_dir, "out_dir")
    if base_dir:
        base_dir = os.path.abspath(base_dir)
        _require_ascii(base_dir, "base_dir")
        if base_dir == out_dir:
            raise ValueError("out_dir 不能与 base_dir 相同（会破坏旧实验的可复现性）")
        if not os.path.isdir(base_dir):
            raise ValueError(f"base_dir 不存在：{base_dir}")
    if os.path.exists(out_dir) and _has_files(out_dir):
        raise ValueError(f"out_dir 已存在且非空，请换一个新目录：{out_dir}")
    root = os.path.abspath(_snapshot_root())
    if not _is_within(root, out_dir):
        raise ValueError(f"out_dir 必须在快照根目录 {root} 下：{out_dir}")

    end = str(args.get("end") or date.today().isoformat())
    start = str(args.get("start") or DEFAULT_START)
    _validate_date(end, "end")
    _validate_date(start, "start")
    index = str(args.get("index") or "hs300")
    if index not in {"hs300", "zz500", "sz50"}:
        raise ValueError(f"index 只支持 hs300 / zz500 / sz50：{index!r}")
    raw_sample = args.get("sample")
    sample = int(40 if raw_sample is None else raw_sample)
    if not 1 <= sample <= 300:
        raise ValueError(f"sample 必须在 1~300 之间：{sample}")
    raw_timeout = args.get("timeout")
    timeout = float(20 if raw_timeout is None else raw_timeout)
    if timeout <= 0:
        raise ValueError(f"timeout 必须大于 0：{timeout}")

    incremental = bool(args.get("incremental", bool(base_dir))) and bool(base_dir)
    if incremental and base_dir:
        info = _manifest_info(base_dir)
        base_end = info.get("end")
        if base_end and end <= base_end:
            return {
                **_clock(),
                "state": "noop",
                "job_id": None,
                "message": f"已是最新：base 截止 {base_end} >= end {end}，未启动作业",
                "out_dir": out_dir,
                "base_dir": base_dir,
                "data_version": info.get("data_version"),
                "end": base_end,
            }

    python = _exporter_python()
    script = _exporter_script()
    cmd = [
        python,
        script,
        "--out",
        out_dir,
        "--universe",
        str(args.get("universe") or DEFAULT_UNIVERSE),
        "--index",
        index,
        "--sample",
        str(sample),
        "--start",
        start,
        "--end",
        end,
        "--fundamentals",
        "--timeout",
        str(timeout),
    ]
    if incremental:
        cmd += ["--incremental", "--base-dir", base_dir]

    job_id = f"job-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:4]}"
    job_dir = os.path.join(_job_root(), job_id)
    os.makedirs(job_dir, exist_ok=True)
    status = {
        "job_id": job_id,
        "state": "queued",
        "created_at": _now(),
        "out_dir": out_dir,
        "base_dir": base_dir,
        "end": end,
        "incremental": incremental,
        "timeout_seconds": float(args.get("timeout_seconds") or 0),
        "cmd": cmd,
        "log_path": os.path.join(job_dir, "log.txt"),
        "status_path": os.path.join(job_dir, "status.json"),
    }
    _write_json(status["status_path"], status)

    flags = 0x00000008 if os.name == "nt" else 0  # DETACHED_PROCESS：MCP 退出后作业继续
    proc = subprocess.Popen(
        [sys.executable, "-m", "quant.data_jobs", job_dir, "--", *cmd],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
    )
    status["pid"] = proc.pid
    _write_json(status["status_path"], status)
    return {
        **_clock(),
        "job_id": job_id,
        "state": status["state"],
        "out_dir": out_dir,
        "base_dir": base_dir,
        "incremental": incremental,
        "timeout_seconds": status["timeout_seconds"],
        "status_path": status["status_path"],
        "log_path": status["log_path"],
    }


def _load_status(job_id: str) -> dict:
    path = os.path.join(_job_root(), job_id, "status.json")
    if not os.path.exists(path):
        raise KeyError(f"作业不存在：{job_id}")
    status = _read_json(path)
    if status.get("state") in ("queued", "running") and status.get("pid"):
        if not _pid_alive(int(status["pid"])):
            status["state"] = "failed"
            status["error"] = "进程已退出但状态未更新（可能被强杀）"
            _write_json(path, status)
    return status


def _tool_refresh_status(args: dict) -> dict:
    job_id = str(args.get("job_id") or "").strip()
    if not job_id or "/" in job_id or ".." in job_id:
        raise ValueError(f"非法 job_id：{job_id!r}")
    wait = max(0.0, min(float(args.get("wait_seconds") or 0), 60.0))
    started = time.monotonic()
    while True:
        status = _load_status(job_id)
        elapsed = time.monotonic() - started
        if status["state"] not in ("queued", "running") or elapsed >= wait:
            break
        time.sleep(min(0.5, max(0.05, wait - elapsed)))
    status.update(_clock())
    status["waited_seconds"] = round(time.monotonic() - started, 1)
    return status


def _tool_check_snapshot(args: dict) -> dict:
    from quant.providers.snapshot_check import check_snapshot

    dir_path = str(args.get("dir") or "").strip()
    if not dir_path or not os.path.isdir(dir_path):
        raise ValueError(f"快照目录不存在：{dir_path}")
    return check_snapshot(os.path.abspath(dir_path))


def _kill_tree(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, check=False)
    else:
        import signal

        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass


def _tool_cancel_job(args: dict) -> dict:
    job_id = str(args.get("job_id") or "").strip()
    if not job_id or "/" in job_id or ".." in job_id:
        raise ValueError(f"非法 job_id：{job_id!r}")
    status = _load_status(job_id)
    if status.get("state") not in ("queued", "running"):
        return {**_clock(), "job_id": job_id, "state": status.get("state"), "cancelled": False, "note": "作业已结束"}
    pid = status.get("pid")
    if pid:
        _kill_tree(int(pid))
    status.update(state="failed", cancelled=True, error="用户取消", finished_at=_now())
    _write_json(os.path.join(_job_root(), job_id, "status.json"), status)
    return {**_clock(), **status}


def _tool_cleanup_jobs(args: dict) -> dict:
    keep = max(0, int(args.get("keep", 20)))
    dry = bool(args.get("dry_run", False))
    root = _job_root()
    if not os.path.isdir(root):
        return {**_clock(), "root": root, "total": 0, "removed": [], "skipped": [], "dry_run": dry}
    entries = []
    for name in os.listdir(root):
        path = os.path.join(root, name)
        if not os.path.isdir(path):
            continue
        state = None
        status_path = os.path.join(path, "status.json")
        if os.path.exists(status_path):
            try:
                state = _read_json(status_path).get("state")
            except (OSError, json.JSONDecodeError):
                state = None
        entries.append((os.path.getmtime(path), name, state))
    entries.sort(key=lambda row: row[0], reverse=True)
    victims = [row for row in entries[keep:] if row[2] not in ("queued", "running")]
    if not dry:
        for _mtime, name, _state in victims:
            shutil.rmtree(os.path.join(root, name), ignore_errors=True)
    return {
        **_clock(),
        "root": root,
        "total": len(entries),
        "keep": keep,
        "removed": [row[1] for row in victims],
        "skipped": [row[1] for row in entries if row[2] in ("queued", "running")],
        "dry_run": dry,
    }


TOOLS: list[dict] = [
    {
        "name": "list_snapshots",
        "description": "列出快照根目录下所有快照（data_version / 区间 / 标的数 / 是否时点成分），同时返回服务端 today/now 供命名目录。",
        "inputSchema": {
            "type": "object",
            "properties": {"root": {"type": "string", "description": "快照根目录，默认取 NFR_SNAPSHOT_ROOT"}},
            "additionalProperties": False,
        },
        "handler": _tool_list_snapshots,
    },
    {
        "name": "refresh_snapshot",
        "description": (
            "启动一次数据刷新作业（后台进程），立刻返回 job_id。"
            "给了 base_dir 默认走增量；不覆盖已有目录；out_dir 必须是新的 ASCII 路径。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "out_dir": {"type": "string", "description": "新快照目录（必须不存在或为空）"},
                "base_dir": {"type": "string", "description": "增量所基于的旧快照目录（可选）"},
                "end": {"type": "string", "description": "结束日期 YYYY-MM-DD，默认今天"},
                "incremental": {"type": "boolean", "description": "是否增量，默认给了 base_dir 就增量"},
                "universe": {"type": "string"},
                "index": {"type": "string", "enum": ["hs300", "zz500", "sz50"]},
                "sample": {"type": "integer", "minimum": 1, "maximum": 300},
                "start": {"type": "string"},
                "timeout": {"type": "number"},
                "timeout_seconds": {"type": "number", "minimum": 0, "maximum": 86400, "description": "作业超时秒数，0=不限"},
            },
            "required": ["out_dir"],
            "additionalProperties": False,
        },
        "handler": _tool_refresh_snapshot,
    },
    {
        "name": "refresh_status",
        "description": (
            "查询刷新作业状态：state / 退出码 / 新 data_version / 体检结果 / 日志路径。"
            "可传 wait_seconds 让服务端阻塞等待状态变化（最多 60 秒），避免高频轮询。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string"},
                "wait_seconds": {"type": "number", "minimum": 0, "maximum": 60, "description": "阻塞等待秒数，默认 0"},
            },
            "required": ["job_id"],
            "additionalProperties": False,
        },
        "handler": _tool_refresh_status,
    },
    {
        "name": "cancel_job",
        "description": "取消一个 queued/running 的刷新作业（杀进程树），状态标为 cancelled。",
        "inputSchema": {
            "type": "object",
            "properties": {"job_id": {"type": "string"}},
            "required": ["job_id"],
            "additionalProperties": False,
        },
        "handler": _tool_cancel_job,
    },
    {
        "name": "cleanup_jobs",
        "description": "清理旧作业目录：保留最近 keep 个，running/queued 不删。dry_run=true 只预览。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "keep": {"type": "integer", "minimum": 0, "maximum": 1000},
                "dry_run": {"type": "boolean"},
            },
            "additionalProperties": False,
        },
        "handler": _tool_cleanup_jobs,
    },
    {
        "name": "check_snapshot",
        "description": "对一个快照目录跑体检（价格、覆盖率、公告日、时点成分），返回逐条检查。",
        "inputSchema": {
            "type": "object",
            "properties": {"dir": {"type": "string"}},
            "required": ["dir"],
            "additionalProperties": False,
        },
        "handler": _tool_check_snapshot,
    },
]

INSTRUCTIONS = (
    "数据运维：只负责刷新/体检快照，不跑回测、不写实验、不下单。"
    "refresh_snapshot 是后台作业，必须用 refresh_status 轮询到 succeeded 或 failed。"
)


def build_server() -> McpServer:
    return McpServer(
        name=SERVER_NAME,
        version=SERVER_VERSION,
        instructions=INSTRUCTIONS,
        tools=TOOLS,
    )


def serve() -> int:
    return build_server().serve()


if __name__ == "__main__":
    raise SystemExit(serve())

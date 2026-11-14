"""数据刷新作业的执行器。

由 `quant.data_mcp` 以独立进程启动：

    python -m quant.data_jobs <job_dir> -- <导出脚本命令...>

它负责把作业生命周期写进 `status.json`（running -> succeeded/failed），
这样即使 MCP 服务端退出，作业状态也不会丢。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATUS = "status.json"
LOG = "log.txt"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _write_json(path: str, payload: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, path)


def _read_json(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _summary(out_dir: str) -> dict:
    manifest_path = os.path.join(out_dir, "manifest.json")
    if not os.path.exists(manifest_path):
        return {}
    try:
        manifest = _read_json(manifest_path)
    except (OSError, json.JSONDecodeError):
        return {}
    sha = str(manifest.get("sha256") or "")
    return {
        "data_version": "dv-" + sha[:12] if sha else None,
        "universe": manifest.get("universe"),
        "start": manifest.get("start"),
        "end": manifest.get("end"),
        "assets": len(manifest.get("assets") or []),
        "source": manifest.get("source"),
        "schema_version": manifest.get("schema_version"),
        "notes": manifest.get("notes"),
    }


def _tail(path: str, lines: int = 20) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            rows = fh.readlines()
    except OSError:
        return ""
    return "".join(rows[-lines:]).strip()


def _kill_tree(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, check=False)
    else:
        import signal

        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass


def run_job(job_dir: str, cmd: list[str]) -> int:
    status_path = os.path.join(job_dir, STATUS)
    log_path = os.path.join(job_dir, LOG)
    status = _read_json(status_path) if os.path.exists(status_path) else {}
    status.update(state="running", started_at=_now(), pid=os.getpid(), cmd=cmd, log_path=log_path)
    _write_json(status_path, status)

    timeout = float(status.get("timeout_seconds") or 0)
    timed_out = False
    with open(log_path, "a", encoding="utf-8", errors="replace") as log:
        proc = subprocess.Popen(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        try:
            rc = proc.wait(timeout=timeout if timeout > 0 else None)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_tree(proc.pid)
            try:
                rc = proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                rc = -1

    ok = rc == 0 and not timed_out
    status.update(exit_code=rc, finished_at=_now(), state="succeeded" if ok else "failed")
    if timed_out:
        status["timed_out"] = True
        status["error"] = f"作业超过 {timeout:.0f} 秒被终止"
    out_dir = status.get("out_dir")
    summary = _summary(out_dir) if out_dir else {}
    if summary:
        status.update(summary)
    if ok and out_dir and not summary:
        # 导出脚本在“已是最新/区间无新交易日”时会正常退出但不写 manifest。
        # 这不是体检失败，要单独标出来，避免 Agent 2 误报。
        status["state"] = "succeeded"
        status["no_new_snapshot"] = True
        status["message"] = "没有生成新快照：可能已是最新，或区间内没有新交易日"
        status["log_tail"] = _tail(log_path)
    elif ok and out_dir:
        try:
            from quant.providers.snapshot_check import check_snapshot

            result = check_snapshot(out_dir)
            status["check_ok"] = result["ok"]
            status["fails"] = [c for c in result["checks"] if c["status"] == "fail"]
            if not result["ok"]:
                status["state"] = "failed"
                status["error"] = "快照体检未通过"
                status["log_tail"] = _tail(log_path)
        except Exception as exc:  # 体检本身出错也要落盘，不能静默
            status["check_ok"] = False
            status["error"] = f"体检异常：{exc}"
            status["state"] = "failed"
    elif not ok:
        status["log_tail"] = _tail(log_path)
    if status["state"] == "succeeded" and summary and status.get("check_ok"):
        try:
            from quant.data_pointer import write_pointer

            status["pointer"] = write_pointer(out_dir, job_id=status.get("job_id"))
        except Exception as exc:  # 指针写失败不影响快照本身，但要留痕
            status["pointer_error"] = str(exc)
    _write_json(status_path, status)
    return 0 if status["state"] == "succeeded" else 1


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--" not in argv:
        print("用法：python -m quant.data_jobs <job_dir> -- <command...>", file=sys.stderr)
        return 2
    split = argv.index("--")
    job_dir = argv[0]
    cmd = argv[split + 1 :]
    if not job_dir or not cmd:
        print("job_dir 或命令为空", file=sys.stderr)
        return 2
    os.makedirs(job_dir, exist_ok=True)
    return run_job(job_dir, cmd)


if __name__ == "__main__":
    raise SystemExit(main())

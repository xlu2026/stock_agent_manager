"""Agent 2 数据运维工具的测试：快照列表、刷新作业、状态、体检。"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from quant import data_jobs, data_mcp  # noqa: E402
from quant.providers.contract import Snapshot, write_snapshot  # noqa: E402


def _manifest(dir_path: str, sha: str, end: str = "2024-12-31") -> None:
    payload = {
        "schema_version": 2,
        "sha256": sha * 64,
        "universe": "hs300_40_pit",
        "start": "2019-01-02",
        "end": end,
        "assets": ["600000.SH"],
        "source": "unit-test",
        "notes": {"universe_point_in_time": True, "incremental": True},
    }
    os.makedirs(dir_path, exist_ok=True)
    with open(os.path.join(dir_path, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(payload, fh)


def _snapshot(dir_path: str) -> None:
    write_snapshot(
        dir_path,
        Snapshot(
            universe="test_pool",
            source="unit-test",
            provider="fixture",
            adjust_mode="backward",
            prices=[
                {"date": "2024-01-02", "asset": "AAA", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1, "adj_factor": 1.0}
            ],
            calendar=[{"date": "2024-01-02"}],
        ),
    )


class ListSnapshotsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = tempfile.mkdtemp(prefix="nfr-data-")

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_lists_manifests_sorted_by_end(self) -> None:
        _manifest(os.path.join(self.root, "a"), "1", end="2024-06-30")
        _manifest(os.path.join(self.root, "b"), "2", end="2025-01-31")
        os.makedirs(os.path.join(self.root, "empty"))
        result = data_mcp._tool_list_snapshots({"root": self.root})
        self.assertEqual(result["count"], 2)
        self.assertIn("today", result)
        self.assertIn("now", result)
        self.assertIn("config", result)
        self.assertIn("config_path", result["config"])
        self.assertEqual([s["end"] for s in result["snapshots"]], ["2024-06-30", "2025-01-31"])
        self.assertEqual(result["snapshots"][1]["data_version"], "dv-" + "2" * 12)
        self.assertTrue(result["snapshots"][0]["point_in_time"])


class RefreshValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.mkdtemp(prefix="nfr-refresh-")
        self.out = os.path.join(self.dir, "out")
        self.env = mock.patch.dict(os.environ, {"NFR_SNAPSHOT_ROOT": self.dir}, clear=False)
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_missing_exporter_python_is_rejected(self) -> None:
        with mock.patch.dict(os.environ, {"NFR_BAOSTOCK_PYTHON": ""}, clear=False), mock.patch.object(
            data_mcp, "_config", return_value={}
        ):
            with self.assertRaises(RuntimeError):
                data_mcp._tool_refresh_snapshot({"out_dir": self.out})

    def test_config_file_provides_python(self) -> None:
        cfg = os.path.join(self.dir, "agent2.json")
        with open(cfg, "w", encoding="utf-8") as fh:
            json.dump({"baostock_python": sys.executable}, fh)
        with mock.patch.dict(os.environ, {"NFR_BAOSTOCK_PYTHON": ""}, clear=False), mock.patch.object(
            data_mcp, "CONFIG_PATH", cfg
        ):
            self.assertEqual(data_mcp._exporter_python(), sys.executable)

    def test_non_ascii_out_dir_is_rejected(self) -> None:
        with mock.patch.dict(os.environ, {"NFR_BAOSTOCK_PYTHON": sys.executable}, clear=False):
            with self.assertRaises(ValueError):
                data_mcp._tool_refresh_snapshot({"out_dir": os.path.join(self.dir, "中文")})

    def test_out_equals_base_is_rejected(self) -> None:
        os.makedirs(self.out)
        with mock.patch.dict(os.environ, {"NFR_BAOSTOCK_PYTHON": sys.executable}, clear=False):
            with self.assertRaises(ValueError):
                data_mcp._tool_refresh_snapshot({"out_dir": self.out, "base_dir": self.out})

    def test_non_empty_out_is_rejected(self) -> None:
        os.makedirs(self.out)
        with open(os.path.join(self.out, "x.txt"), "w", encoding="utf-8") as fh:
            fh.write("x")
        with mock.patch.dict(os.environ, {"NFR_BAOSTOCK_PYTHON": sys.executable}, clear=False):
            with self.assertRaises(ValueError):
                data_mcp._tool_refresh_snapshot({"out_dir": self.out})

    def test_only_empty_dirs_counts_as_empty(self) -> None:
        os.makedirs(os.path.join(self.out, "raw"))
        self.assertFalse(data_mcp._has_files(self.out))
        with open(os.path.join(self.out, "raw", "x.csv"), "w", encoding="utf-8") as fh:
            fh.write("x")
        self.assertTrue(data_mcp._has_files(self.out))

    def test_bad_end_date_is_rejected(self) -> None:
        with mock.patch.dict(os.environ, {"NFR_BAOSTOCK_PYTHON": sys.executable}, clear=False):
            with self.assertRaises(ValueError):
                data_mcp._tool_refresh_snapshot({"out_dir": self.out, "end": "2024/12/31"})

    def test_out_outside_snapshot_root_is_rejected(self) -> None:
        other = tempfile.mkdtemp(prefix="nfr-other-")
        try:
            with mock.patch.dict(os.environ, {"NFR_BAOSTOCK_PYTHON": sys.executable}, clear=False):
                with self.assertRaises(ValueError):
                    data_mcp._tool_refresh_snapshot({"out_dir": os.path.join(other, "out")})
        finally:
            shutil.rmtree(other, ignore_errors=True)

    def test_sample_out_of_range_is_rejected(self) -> None:
        with mock.patch.dict(os.environ, {"NFR_BAOSTOCK_PYTHON": sys.executable}, clear=False):
            with self.assertRaises(ValueError):
                data_mcp._tool_refresh_snapshot({"out_dir": self.out, "sample": 0})

    def test_noop_when_end_not_after_base(self) -> None:
        base = os.path.join(self.dir, "base")
        os.makedirs(base)
        with open(os.path.join(base, "manifest.json"), "w", encoding="utf-8") as fh:
            json.dump({"sha256": "a" * 64, "end": "2024-12-31", "universe": "u"}, fh)
        result = data_mcp._tool_refresh_snapshot({"out_dir": self.out, "base_dir": base, "end": "2024-12-31"})
        self.assertEqual(result["state"], "noop")
        self.assertIsNone(result["job_id"])
        self.assertEqual(result["data_version"], "dv-" + "a" * 12)

    def test_spawns_job_and_reports_failure(self) -> None:
        job_root = os.path.join(self.dir, "jobs")
        fake = os.path.join(self.dir, "fake_export.py")
        with open(fake, "w", encoding="utf-8") as fh:
            fh.write("import sys\nsys.exit(3)\n")
        env = {
            "NFR_BAOSTOCK_PYTHON": sys.executable,
            "NFR_EXPORT_SCRIPT": fake,
            "NFR_DATA_JOB_DIR": job_root,
        }
        with mock.patch.dict(os.environ, env, clear=False):
            started = data_mcp._tool_refresh_snapshot({"out_dir": self.out, "end": "2024-12-31"})
            self.assertEqual(started["state"], "queued")
            self.assertIn("today", started)
            self.assertIn("now", started)
            status = None
            for _ in range(100):
                status = data_mcp._tool_refresh_status({"job_id": started["job_id"]})
                if status["state"] in ("succeeded", "failed"):
                    break
                time.sleep(0.1)
        self.assertIsNotNone(status)
        self.assertEqual(status["state"], "failed")
        self.assertEqual(status["exit_code"], 3)


class JobRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.mkdtemp(prefix="nfr-job-")
        self.job = os.path.join(self.dir, "job")
        os.makedirs(self.job)

    def tearDown(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_success_marks_snapshot_summary(self) -> None:
        snap = os.path.join(self.dir, "snap")
        _snapshot(snap)
        with open(os.path.join(self.job, "status.json"), "w", encoding="utf-8") as fh:
            json.dump({"job_id": "j", "state": "queued", "out_dir": snap}, fh)
        pointer = os.path.join(self.dir, "latest.json")
        with mock.patch.dict(os.environ, {"NFR_LATEST_POINTER": pointer}, clear=False):
            code = data_jobs.run_job(self.job, [sys.executable, "-c", "print('ok')"])
        self.assertEqual(code, 0)
        with open(os.path.join(self.job, "status.json"), encoding="utf-8") as fh:
            status = json.load(fh)
        self.assertEqual(status["state"], "succeeded")
        self.assertTrue(status["data_version"].startswith("dv-"))
        self.assertTrue(status["check_ok"])
        self.assertTrue(os.path.exists(pointer))

    def test_failure_keeps_exit_code(self) -> None:
        with open(os.path.join(self.job, "status.json"), "w", encoding="utf-8") as fh:
            json.dump({"job_id": "j", "state": "queued", "out_dir": None}, fh)
        code = data_jobs.run_job(self.job, [sys.executable, "-c", "import sys; sys.exit(4)"])
        self.assertEqual(code, 1)
        with open(os.path.join(self.job, "status.json"), encoding="utf-8") as fh:
            status = json.load(fh)
        self.assertEqual(status["state"], "failed")
        self.assertEqual(status["exit_code"], 4)

    def test_no_manifest_means_no_new_snapshot(self) -> None:
        out = os.path.join(self.dir, "empty-out")
        os.makedirs(out)
        with open(os.path.join(self.job, "status.json"), "w", encoding="utf-8") as fh:
            json.dump({"job_id": "j", "state": "queued", "out_dir": out}, fh)
        code = data_jobs.run_job(self.job, [sys.executable, "-c", "print('already latest')"])
        self.assertEqual(code, 0)
        with open(os.path.join(self.job, "status.json"), encoding="utf-8") as fh:
            status = json.load(fh)
        self.assertEqual(status["state"], "succeeded")
        self.assertTrue(status.get("no_new_snapshot"))
        self.assertNotIn("check_ok", status)

    def test_failure_carries_log_tail(self) -> None:
        with open(os.path.join(self.job, "status.json"), "w", encoding="utf-8") as fh:
            json.dump({"job_id": "j", "state": "queued", "out_dir": None}, fh)
        data_jobs.run_job(self.job, [sys.executable, "-c", "print('boom'); raise SystemExit(3)"])
        with open(os.path.join(self.job, "status.json"), encoding="utf-8") as fh:
            status = json.load(fh)
        self.assertIn("boom", status.get("log_tail", ""))


class StatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.mkdtemp(prefix="nfr-status-")
        self.job_root = os.path.join(self.dir, "jobs")
        self.job = os.path.join(self.job_root, "job-x")
        os.makedirs(self.job)

    def tearDown(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_dead_pid_is_marked_failed(self) -> None:
        import subprocess

        proc = subprocess.Popen([sys.executable, "-c", "pass"])
        proc.wait()
        with open(os.path.join(self.job, "status.json"), "w", encoding="utf-8") as fh:
            json.dump({"job_id": "job-x", "state": "running", "pid": proc.pid}, fh)
        with mock.patch.dict(os.environ, {"NFR_DATA_JOB_DIR": self.job_root}, clear=False):
            status = data_mcp._tool_refresh_status({"job_id": "job-x"})
        self.assertEqual(status["state"], "failed")
        self.assertIn("进程已退出", status["error"])

    def test_unknown_job_is_rejected(self) -> None:
        with mock.patch.dict(os.environ, {"NFR_DATA_JOB_DIR": self.job_root}, clear=False):
            with self.assertRaises(KeyError):
                data_mcp._tool_refresh_status({"job_id": "nope"})

    def test_wait_zero_returns_immediately(self) -> None:
        with open(os.path.join(self.job, "status.json"), "w", encoding="utf-8") as fh:
            json.dump({"job_id": "job-x", "state": "running", "pid": os.getpid()}, fh)
        with mock.patch.dict(os.environ, {"NFR_DATA_JOB_DIR": self.job_root}, clear=False):
            status = data_mcp._tool_refresh_status({"job_id": "job-x"})
        self.assertEqual(status["state"], "running")
        self.assertLess(status["waited_seconds"], 0.2)
        self.assertIn("today", status)

    def test_wait_until_state_changes(self) -> None:
        path = os.path.join(self.job, "status.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"job_id": "job-x", "state": "running", "pid": os.getpid()}, fh)

        def finish() -> None:
            time.sleep(0.4)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"job_id": "job-x", "state": "succeeded", "pid": os.getpid()}, fh)

        worker = threading.Thread(target=finish)
        worker.start()
        try:
            with mock.patch.dict(os.environ, {"NFR_DATA_JOB_DIR": self.job_root}, clear=False):
                status = data_mcp._tool_refresh_status({"job_id": "job-x", "wait_seconds": 5})
        finally:
            worker.join()
        self.assertEqual(status["state"], "succeeded")
        self.assertGreaterEqual(status["waited_seconds"], 0.3)


class CancelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.mkdtemp(prefix="nfr-cancel-")
        self.root = os.path.join(self.dir, "jobs")
        self.job = os.path.join(self.root, "job-x")
        os.makedirs(self.job)

    def tearDown(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_cancel_running_job_kills_process(self) -> None:
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        try:
            with open(os.path.join(self.job, "status.json"), "w", encoding="utf-8") as fh:
                json.dump({"job_id": "job-x", "state": "running", "pid": proc.pid}, fh)
            with mock.patch.dict(os.environ, {"NFR_DATA_JOB_DIR": self.root}, clear=False):
                result = data_mcp._tool_cancel_job({"job_id": "job-x"})
            self.assertTrue(result["cancelled"])
            self.assertEqual(result["state"], "failed")
            for _ in range(50):
                if proc.poll() is not None:
                    break
                time.sleep(0.1)
            self.assertIsNotNone(proc.poll())
        finally:
            if proc.poll() is None:
                proc.kill()

    def test_cancel_finished_job_is_noop(self) -> None:
        with open(os.path.join(self.job, "status.json"), "w", encoding="utf-8") as fh:
            json.dump({"job_id": "job-x", "state": "succeeded", "pid": 1}, fh)
        with mock.patch.dict(os.environ, {"NFR_DATA_JOB_DIR": self.root}, clear=False):
            result = data_mcp._tool_cancel_job({"job_id": "job-x"})
        self.assertFalse(result["cancelled"])


class CleanupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.mkdtemp(prefix="nfr-clean-")
        self.root = os.path.join(self.dir, "jobs")
        for name, state, age in (("job-old", "failed", 300), ("job-mid", "succeeded", 200), ("job-new", "running", 100)):
            path = os.path.join(self.root, name)
            os.makedirs(path)
            with open(os.path.join(path, "status.json"), "w", encoding="utf-8") as fh:
                json.dump({"job_id": name, "state": state}, fh)
            stamp = time.time() - age
            os.utime(path, (stamp, stamp))

    def tearDown(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_keep_one_removes_old_and_skips_running(self) -> None:
        with mock.patch.dict(os.environ, {"NFR_DATA_JOB_DIR": self.root}, clear=False):
            result = data_mcp._tool_cleanup_jobs({"keep": 1})
        self.assertEqual(set(result["removed"]), {"job-old", "job-mid"})
        self.assertEqual(result["skipped"], ["job-new"])
        self.assertFalse(os.path.exists(os.path.join(self.root, "job-old")))
        self.assertTrue(os.path.exists(os.path.join(self.root, "job-new")))

    def test_dry_run_deletes_nothing(self) -> None:
        with mock.patch.dict(os.environ, {"NFR_DATA_JOB_DIR": self.root}, clear=False):
            result = data_mcp._tool_cleanup_jobs({"keep": 0, "dry_run": True})
        self.assertTrue(result["dry_run"])
        self.assertIn("job-old", result["removed"])
        self.assertTrue(os.path.exists(os.path.join(self.root, "job-old")))


class TimeoutTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.mkdtemp(prefix="nfr-timeout-")
        self.job = os.path.join(self.dir, "job")
        os.makedirs(self.job)

    def tearDown(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_timeout_marks_failed(self) -> None:
        with open(os.path.join(self.job, "status.json"), "w", encoding="utf-8") as fh:
            json.dump({"job_id": "j", "state": "queued", "out_dir": None, "timeout_seconds": 0.5}, fh)
        started = time.monotonic()
        code = data_jobs.run_job(self.job, [sys.executable, "-c", "import time; time.sleep(5)"])
        self.assertEqual(code, 1)
        self.assertLess(time.monotonic() - started, 4)
        with open(os.path.join(self.job, "status.json"), encoding="utf-8") as fh:
            status = json.load(fh)
        self.assertEqual(status["state"], "failed")
        self.assertTrue(status.get("timed_out"))


class CheckSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.mkdtemp(prefix="nfr-check-")

    def tearDown(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_check_good_snapshot(self) -> None:
        _snapshot(self.dir)
        result = data_mcp._tool_check_snapshot({"dir": self.dir})
        self.assertTrue(result["ok"])


if __name__ == "__main__":
    unittest.main()

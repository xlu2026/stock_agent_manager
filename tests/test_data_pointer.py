"""最新快照指针：写入、读取、缺失提示。"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from quant import data_pointer  # noqa: E402
from quant.providers.contract import Snapshot, write_snapshot  # noqa: E402


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


class PointerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.mkdtemp(prefix="nfr-pointer-")
        self.pointer = os.path.join(self.dir, "latest.json")
        self.snap = os.path.join(self.dir, "snap")
        _snapshot(self.snap)
        self.env = mock.patch.dict(os.environ, {data_pointer.POINTER_ENV: self.pointer}, clear=False)
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_write_and_read(self) -> None:
        payload = data_pointer.write_pointer(self.snap, job_id="job-x")
        self.assertTrue(payload["data_version"].startswith("dv-"))
        got = data_pointer.read_pointer()
        self.assertEqual(got["dir"], os.path.abspath(self.snap))
        self.assertEqual(got["data_version"], payload["data_version"])
        self.assertEqual(got["job_id"], "job-x")

    def test_missing_pointer_raises(self) -> None:
        with self.assertRaises(FileNotFoundError):
            data_pointer.read_pointer()

    def test_missing_manifest_raises(self) -> None:
        empty = os.path.join(self.dir, "empty")
        os.makedirs(empty)
        with self.assertRaises(FileNotFoundError):
            data_pointer.write_pointer(empty)


class PointerIntegrationTests(unittest.TestCase):
    def test_job_runner_writes_pointer(self) -> None:
        import json

        from quant import data_jobs

        tmp = tempfile.mkdtemp(prefix="nfr-pointerjob-")
        try:
            job = os.path.join(tmp, "job")
            os.makedirs(job)
            snap = os.path.join(tmp, "snap")
            _snapshot(snap)
            pointer = os.path.join(tmp, "latest.json")
            with open(os.path.join(job, "status.json"), "w", encoding="utf-8") as fh:
                json.dump({"job_id": "j", "state": "queued", "out_dir": snap}, fh)
            with mock.patch.dict(os.environ, {data_pointer.POINTER_ENV: pointer}, clear=False):
                code = data_jobs.run_job(job, [sys.executable, "-c", "print('ok')"])
            self.assertEqual(code, 0)
            with open(pointer, encoding="utf-8") as fh:
                payload = json.load(fh)
            self.assertEqual(payload["dir"], os.path.abspath(snap))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()

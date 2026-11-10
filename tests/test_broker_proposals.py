"""下单提案的三段式校验：未批准、被篡改、过期、重复提交都必须被拦下。"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from quant.broker import proposals  # noqa: E402


class ProposalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.mkdtemp(prefix="nfr-prop-")
        cls._old = os.environ.get("NFR_BROKER_DIR")
        os.environ["NFR_BROKER_DIR"] = cls._tmp

    @classmethod
    def tearDownClass(cls) -> None:
        if cls._old is None:
            os.environ.pop("NFR_BROKER_DIR", None)
        else:
            os.environ["NFR_BROKER_DIR"] = cls._old
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def setUp(self) -> None:
        pdir = os.path.join(self._tmp, "proposals")
        if os.path.isdir(pdir):
            shutil.rmtree(pdir)

    def _make(self, **kw) -> proposals.Proposal:
        base = dict(symbol="SYN001", side="BUY", quantity=10, price_snapshot=100.0, experiment_id="exp-abc")
        base.update(kw)
        return proposals.create(**base)

    def test_unapproved_proposal_cannot_submit(self) -> None:
        prop = self._make()
        with self.assertRaises(proposals.ProposalError) as ctx:
            proposals.verify_for_submit(prop.id)
        self.assertEqual(ctx.exception.code, "NOT_APPROVED")

    def test_approved_proposal_passes(self) -> None:
        prop = self._make()
        proposals.approve(prop.id, approved_by="test")
        payload = proposals.verify_for_submit(prop.id)
        self.assertEqual(payload["proposal_id"], prop.id)
        self.assertEqual(payload["symbol"], "SYN001")

    def test_tampered_after_approval_is_rejected(self) -> None:
        prop = self._make()
        proposals.approve(prop.id, approved_by="test")
        path = os.path.join(self._tmp, "proposals", f"{prop.id}.json")
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        data["quantity"] = 9999  # 批准后偷偷改数量
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        with self.assertRaises(proposals.ProposalError) as ctx:
            proposals.verify_for_submit(prop.id)
        self.assertEqual(ctx.exception.code, "TAMPERED")

    def test_expired_proposal_is_rejected(self) -> None:
        prop = self._make(ttl_minutes=-1)
        with self.assertRaises(proposals.ProposalError) as ctx:
            proposals.approve(prop.id, approved_by="test")
        self.assertEqual(ctx.exception.code, "EXPIRED")

    def test_double_submit_is_rejected(self) -> None:
        prop = self._make()
        proposals.approve(prop.id, approved_by="test")
        proposals.verify_for_submit(prop.id)
        proposals.mark_submitted(prop.id, {"status": "FILLED"})
        with self.assertRaises(proposals.ProposalError) as ctx:
            proposals.verify_for_submit(prop.id)
        self.assertEqual(ctx.exception.code, "ALREADY_SUBMITTED")

    def test_missing_proposal(self) -> None:
        with self.assertRaises(proposals.ProposalError) as ctx:
            proposals.verify_for_submit("prop-doesnotexist")
        self.assertEqual(ctx.exception.code, "NO_PROPOSAL")

    def test_estimate_notional_present(self) -> None:
        prop = self._make(quantity=10, price_snapshot=100.0)
        self.assertEqual(prop.est_notional, 1000.0)
        self.assertIn("approve", proposals.approve_command(prop.id))


if __name__ == "__main__":
    unittest.main()

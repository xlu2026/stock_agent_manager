"""下单提案：把"想下什么单"和"批准下这个单"分成两个文件。

为什么不让 Agent 直接下单：模型能调用 `broker_submit_order`，就说明它能自己填
`human_confirmed=True`——那样闸门就是装饰。

所以拆成三段：

1. Agent 调 `broker_propose_order`，只生成提案（JSON 文件），**不产生任何订单**；
2. 人 在终端跑 `python -m quant.broker.approve <提案ID>`，看清内容后输入 yes，
   写入批准文件（量化 profile 没有 shell，Agent 自己跑不了这一步）；
3. Agent 调 `broker_submit_order <提案ID>`，系统校验批准文件、内容哈希、有效期、是否已提交。

批准文件里存的是**提案内容的 sha256**。提案在批准后被改动，哈希对不上，提交会被拒。
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_TTL_MINUTES = 30


class ProposalError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"[{code}] {message}")


def _base_dir() -> str:
    return os.environ.get("NFR_BROKER_DIR") or os.path.join(ROOT, "output", "broker")


def _proposal_dir() -> str:
    return os.path.join(_base_dir(), "proposals")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _canonical(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_hash(payload: dict) -> str:
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def _write(path: str, payload: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, path)


def _read(path: str) -> dict | None:
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


@dataclass
class Proposal:
    id: str
    symbol: str
    side: str
    quantity: int
    order_type: str
    limit_price: float | None
    experiment_id: str | None
    note: str
    price_snapshot: float | None
    est_notional: float | None
    created_utc: str
    expires_utc: str
    sha256: str = ""
    extra: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "proposal_id": self.id,
            "symbol": self.symbol,
            "side": self.side,
            "quantity": self.quantity,
            "order_type": self.order_type,
            "limit_price": self.limit_price,
            "experiment_id": self.experiment_id,
            "note": self.note,
            "price_snapshot": self.price_snapshot,
            "est_notional": self.est_notional,
            "created_utc": self.created_utc,
            "expires_utc": self.expires_utc,
            **self.extra,
        }


def _path(pid: str) -> str:
    return os.path.join(_proposal_dir(), f"{pid}.json")


def _approval_path(pid: str) -> str:
    return os.path.join(_proposal_dir(), f"{pid}.approved.json")


def _submitted_path(pid: str) -> str:
    return os.path.join(_proposal_dir(), f"{pid}.submitted.json")


def create(
    *,
    symbol: str,
    side: str,
    quantity: int,
    order_type: str = "MARKET",
    limit_price: float | None = None,
    experiment_id: str | None = None,
    note: str = "",
    price_snapshot: float | None = None,
    ttl_minutes: int = DEFAULT_TTL_MINUTES,
) -> Proposal:
    now = _now()
    pid = "prop-" + uuid.uuid4().hex[:10]
    price = limit_price if order_type == "LIMIT" and limit_price else price_snapshot
    prop = Proposal(
        id=pid,
        symbol=symbol,
        side=side,
        quantity=int(quantity),
        order_type=order_type,
        limit_price=limit_price,
        experiment_id=experiment_id,
        note=note,
        price_snapshot=round(price_snapshot, 4) if price_snapshot else None,
        est_notional=round(price * quantity, 2) if price else None,
        created_utc=now.isoformat(timespec="seconds"),
        expires_utc=(now + timedelta(minutes=ttl_minutes)).isoformat(timespec="seconds"),
    )
    payload = prop.as_dict()
    prop.sha256 = content_hash(payload)
    _write(_path(pid), {**payload, "sha256": prop.sha256})
    return prop


def load(pid: str) -> dict:
    payload = _read(_path(pid))
    if payload is None:
        raise ProposalError("NO_PROPOSAL", f"提案 {pid} 不存在")
    return payload


def approve(pid: str, approved_by: str = "human") -> dict:
    payload = load(pid)
    body = {k: v for k, v in payload.items() if k != "sha256"}
    if content_hash(body) != payload.get("sha256"):
        raise ProposalError("TAMPERED", "提案内容与生成时的哈希不一致，拒绝批准")
    if _now().isoformat(timespec="seconds") > payload["expires_utc"]:
        raise ProposalError("EXPIRED", f"提案 {pid} 已过期")
    record = {
        "proposal_id": pid,
        "proposal_sha256": payload["sha256"],
        "approved_utc": _now().isoformat(timespec="seconds"),
        "approved_by": approved_by,
    }
    _write(_approval_path(pid), record)
    return record


def verify_for_submit(pid: str) -> dict:
    """提交前的完整校验。任何一条不过就抛 ProposalError。"""
    payload = load(pid)

    if os.path.exists(_submitted_path(pid)):
        raise ProposalError("ALREADY_SUBMITTED", f"提案 {pid} 已经提交过，不能重复下单")

    body = {k: v for k, v in payload.items() if k != "sha256"}
    if content_hash(body) != payload.get("sha256"):
        raise ProposalError("TAMPERED", "提案内容被改动过")

    if _now().isoformat(timespec="seconds") > payload["expires_utc"]:
        raise ProposalError("EXPIRED", f"提案 {pid} 已过期（{payload['expires_utc']}）")

    approval = _read(_approval_path(pid))
    if approval is None:
        raise ProposalError(
            "NOT_APPROVED",
            f"提案 {pid} 尚未批准。请人工在终端执行： python -m quant.broker.approve {pid}",
        )
    if approval.get("proposal_sha256") != payload["sha256"]:
        raise ProposalError("TAMPERED", "批准记录对应的提案内容与当前不一致")

    return payload


def mark_submitted(pid: str, order: dict) -> None:
    _write(
        _submitted_path(pid),
        {"proposal_id": pid, "submitted_utc": _now().isoformat(timespec="seconds"), "order": order},
    )


def approve_command(pid: str) -> str:
    return f"python -m quant.broker.approve {pid}"

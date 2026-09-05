"""每日重验的三条规则，离线测试 ``revalidate.apply()``。

这些规则决定了一条 verified 记录在什么情况下会**停止**对外给肯定答复——
和「什么时候给」同样重要。deezer.com 的教训：采集失败不该等于降级。
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.policy import Decision, Evidence  # noqa: E402
from src.revalidate import apply  # noqa: E402

NOW = datetime(2026, 9, 6, tzinfo=UTC)


def old_record(**over) -> dict:
    base = {
        "domain": "example.com", "status": "verified", "confidence": 0.85,
        "last_verified": "2026-09-05T00:00:00Z", "ttl_days": 30,
        "evidence": [
            {"code": "A1", "checked_at": "2026-09-05T00:00:00Z", "source": "x",
             "data": {"org": "exampleorg", "org_verified": True, "blog": "https://example.com"}},
            {"code": "A3", "checked_at": "2026-09-05T00:00:00Z", "source": "x",
             "data": {"registrar": "MarkMonitor Inc.", "expires": "2033-01-01", "remaining_days": 2300}},
        ],
        "reasons": ["1 条独立锚点 + 2 条独立佐证"],
    }
    base.update(over)
    return base


def decision(status: str, **over) -> Decision:
    base = dict(status=status, confidence=0.5, reasons=[f"now {status}"], anchors=[],
                corroborations=[], rejected=[])
    base.update(over)
    return Decision(**base)


def evidence(registrar="MarkMonitor Inc.", org_verified=True, expires="2033-01-01"):
    return [
        Evidence("A1", {"org": "exampleorg", "org_verified": org_verified, "blog": "https://example.com"}, NOW),
        Evidence("A3", {"registrar": registrar, "expires": expires, "remaining_days": 2300}, NOW),
    ]


# ---- 规则 1：采集失败 ≠ 降级

def test_incomplete_collection_keeps_old_status_and_timestamp():
    rec, out = apply(old_record(), decision("community"), {"collection_incomplete": True},
                     evidence(), [], NOW)
    assert out.action == "kept"
    assert rec["status"] == "verified"
    assert rec["last_verified"] == "2026-09-05T00:00:00Z", "不能刷新时间戳，否则 TTL 永远不会到"
    assert rec["collection_incomplete"] is True


def test_incomplete_collection_still_accepts_improvement():
    """采集不完整但结果更好（或相同）→ 照常写入。只有变差才保留。"""
    rec, out = apply(old_record(status="provisional"), decision("verified"),
                     {"collection_incomplete": True}, evidence(), [], NOW)
    assert out.action == "upgraded"
    assert rec["status"] == "verified"


# ---- 规则 2：突变 → review_required

def test_registrar_change_triggers_review_even_if_still_verified():
    rec, out = apply(old_record(), decision("verified"), {}, evidence(registrar="NameCheap, Inc."), [], NOW)
    assert out.action == "review"
    assert rec["status"] == "review_required"
    assert any("registrar" in m for m in out.mutations)
    assert rec["history"][-1]["to"] == "review_required"


def test_lost_github_verification_triggers_review():
    _, out = apply(old_record(), decision("verified"), {}, evidence(org_verified=False), [], NOW)
    assert out.action == "review"


def test_expiry_shortened_triggers_review():
    """续费只会往后推；到期日往前跳说明换了注册记录（抢注的典型信号）。"""
    _, out = apply(old_record(), decision("verified"), {}, evidence(expires="2027-01-01"), [], NOW)
    assert out.action == "review"
    assert any("缩短" in m for m in out.mutations)


def test_anchor_conflict_triggers_review():
    _, out = apply(old_record(), decision("verified"), {}, evidence(),
                   ["anchor: ⚠ 权威给出的组织 other ≠ 指定值 exampleorg"], NOW)
    assert out.action == "review"


# ---- 规则 3：其余以新判定为准，且留痕

def test_clean_downgrade_is_recorded_in_history():
    rec, out = apply(old_record(), decision("community", reasons=["无锚点"]), {}, evidence(), [], NOW)
    assert out.action == "downgraded"
    assert rec["status"] == "community"
    assert rec["history"][-1] == {"at": "2026-09-06T00:00:00Z", "from": "verified", "to": "community", "why": "无锚点"}


def test_unchanged_refreshes_timestamp_without_history():
    rec, out = apply(old_record(), decision("verified"), {}, evidence(), [], NOW)
    assert out.action == "unchanged"
    assert rec["last_verified"] == "2026-09-06T00:00:00Z"
    assert "history" not in rec


def test_upgrade_is_recorded():
    rec, out = apply(old_record(status="provisional"), decision("verified"), {}, evidence(), [], NOW)
    assert out.action == "upgraded" and rec["history"][-1]["to"] == "verified"

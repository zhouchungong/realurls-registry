"""A dispute stops positive answers at once and stays until a human clears it; it never raises a status."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.dispute import apply_dispute, clear_dispute, on_hold  # noqa: E402
from src.revalidate import apply  # noqa: E402
from tests.test_revalidate import decision, evidence, old_record  # noqa: E402

NOW = datetime(2026, 9, 6, tzinfo=UTC)


def test_dispute_downgrades_and_holds_through_revalidation():
    rec = apply_dispute(old_record(), 12, "lookalike marked official", NOW)
    assert rec["status"] == "disputed" and on_hold(rec) and rec["history"][-1]["to"] == "disputed"
    again, out = apply(rec, decision("verified"), {}, evidence(), [], NOW)
    assert again["status"] == "disputed" and out.action == "review"


def test_clearing_lets_the_rules_decide_again():
    rec = apply_dispute(old_record(), 12, "x", NOW)
    cleared = clear_dispute(rec, "octocat", "re-checked, rejected", NOW)
    assert not on_hold(cleared) and cleared["dispute"]["cleared"]["by"] == "octocat"
    back, out = apply(cleared, decision("verified"), {}, evidence(), [], NOW)
    assert back["status"] == "verified" and out.action == "upgraded"
    worse, out2 = apply(cleared, decision("community"), {}, evidence(), [], NOW)
    assert worse["status"] == "community"   # clearing is not a promotion

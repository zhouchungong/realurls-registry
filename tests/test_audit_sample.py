"""The manual sample is the number releases are gated on; drawing must be reproducible and scoring strict."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.audit_sample import PRECISION_BAR, draw, render, score  # noqa: E402


def rows(n):
    return [{"domain": f"d{i}.example", "role": "primary", "entity_id": f"org:e{i}", "name": f"E{i}",
             "anchors": ["A1"], "file": f"entities/ai/e{i}.yaml", "confidence": 0.9} for i in range(n)]


def test_draw_is_deterministic_and_sorted():
    a = draw(rows(500), 200, seed=7)
    b = draw(rows(500), 200, seed=7)
    assert a == b and len(a) == 200 and [r["domain"] for r in a] == sorted(r["domain"] for r in a)
    assert draw(rows(500), 200, seed=8) != a


def test_small_pool_is_taken_whole():
    assert len(draw(rows(30), 200, seed=1)) == 30


def test_score_round_trip_and_bar():
    text = render("t", draw(rows(10), 10, 1), 10, 1, None)
    r = score(text)
    assert r["counts"]["empty"] == 10 and r["precision"] is None

    filled = text.replace("|  |  |", "| ok |  |", 9).replace("|  |  |", "| wrong | belongs to someone else |", 1)
    r = score(filled)
    assert r["counts"] == {"ok": 9, "wrong": 1, "unsure": 0, "empty": 0}
    assert r["precision"] == 0.9 < PRECISION_BAR
    assert r["flagged"] == [(10, "d9.example", "wrong", "belongs to someone else")]

    all_ok = text.replace("|  |  |", "| OK |  |")
    assert score(all_ok)["precision"] == 1.0

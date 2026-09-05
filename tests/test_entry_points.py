"""Pure parts of the single-record entry points (examine / owners): what gets stored and what does not."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import owners  # noqa: E402
from src.examine import examined_sql  # noqa: E402

NOW = datetime(2026, 9, 6, tzinfo=UTC)


def test_examined_sql_skips_verified_and_errors():
    rows = [
        {"domain": "a.example", "status": "verified", "checked_at": "2026-09-06T00:00:00Z", "reasons": []},
        {"domain": "b.example", "status": "error", "checked_at": "2026-09-06T00:00:00Z", "reasons": ["TimeoutError: x"]},
        {"domain": "c.example", "status": "community", "checked_at": "2026-09-06T00:00:00Z", "reasons": ["no anchor; it's 3"]},
    ]
    sql = examined_sql(rows, "v1")
    assert "a.example" not in sql and "b.example" not in sql
    assert "'c.example', 'community'" in sql and "it''s 3" in sql      # quotes escaped
    assert "ON CONFLICT(domain) DO UPDATE" in sql
    assert examined_sql(rows[:2]) == ""


def test_owner_token_is_stable_per_domain(tmp_path, monkeypatch):
    monkeypatch.setattr(owners, "SEEDS", tmp_path / "owners.jsonl")
    first = owners.issue("Kagi.com", "Kagi", "kagisearch", 7, ["other"])
    again = owners.issue("https://kagi.com/", "Kagi Inc", None, 8, [])
    assert first["domain"] == again["domain"] == "kagi.com"
    assert first["token"] == again["token"]                     # re-opening an issue never rotates the token
    assert again["issue"] == 8 and again["org_name"] == "Kagi Inc" and again["github_org"] == "kagisearch"
    assert owners.txt_record(first) == f'_realurls.kagi.com.   TXT   "realurls-site-verification={first["token"]}"'
    assert len(owners._load()) == 1

"""AI review is flag-only. These tests pin the one property that matters: it can never promote."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.revalidate import apply  # noqa: E402
from src.review_ai import apply_review, ask, clear_hold, dossier, on_hold, parse_answer  # noqa: E402
from tests.test_revalidate import decision, evidence, old_record  # noqa: E402

NOW = datetime(2026, 9, 6, tzinfo=UTC)
MODEL = "test-model"


def test_flag_demotes_verified_to_review_required_with_hold():
    rec, changed = apply_review(old_record(), {"verdict": "flag", "reason": "name and domain differ"}, MODEL, NOW)
    assert changed and rec["status"] == "review_required" and on_hold(rec)
    assert rec["history"][-1]["to"] == "review_required"
    assert rec["reasons"][0].startswith("AI review flagged")


def test_pass_changes_nothing_but_records_the_review():
    rec, changed = apply_review(old_record(), {"verdict": "pass", "reason": ""}, MODEL, NOW)
    assert not changed and rec["status"] == "verified" and not on_hold(rec)
    assert rec["ai_review"]["verdict"] == "pass"


def test_never_promotes():
    for status in ("provisional", "community", "unverified", "stale", "review_required"):
        for verdict in ("pass", "flag"):
            rec, changed = apply_review(old_record(status=status), {"verdict": verdict, "reason": "x"}, MODEL, NOW)
            assert rec["status"] == status and not changed, (status, verdict)


def test_hold_survives_daily_revalidation_until_cleared():
    held, _ = apply_review(old_record(), {"verdict": "flag", "reason": "suspicious"}, MODEL, NOW)
    rec, out = apply(held, decision("verified"), {}, evidence(), [], NOW)
    assert rec["status"] == "review_required" and out.action == "review"

    cleared = clear_hold(rec, "octocat", "checked by hand", NOW)
    assert not on_hold(cleared) and cleared["ai_review"]["cleared"]["by"] == "octocat"
    rec2, out2 = apply(cleared, decision("verified"), {}, evidence(), [], NOW)
    assert rec2["status"] == "verified" and out2.action == "upgraded"


def test_malformed_answers_are_a_pass():
    assert parse_answer("I think it's fine")["verdict"] == "pass"
    assert parse_answer('```json\n{"verdict": "FLAG", "reason": "lookalike"}\n```') == {"verdict": "flag", "reason": "lookalike"}
    assert parse_answer('{"verdict": "maybe"}')["verdict"] == "pass"


class _Block:
    def __init__(self, text): self.text = text


class _Msg:
    def __init__(self, text): self.content = [_Block(text)]


class _Messages:
    def __init__(self, text): self.text, self.calls = text, []

    def create(self, **kw):
        self.calls.append(kw)
        return _Msg(self.text)


class _Client:
    def __init__(self, text): self.messages = _Messages(text)


def test_ask_sends_only_the_dossier():
    client = _Client('{"verdict": "pass", "reason": "consistent"}')
    ent = {"entity_id": "org:example", "names": {"en": "Example"}, "canonical": {"github_org": "exampleorg"},
           "domains": [old_record()]}
    out = ask(client, MODEL, dossier(ent, ent["domains"][0]))
    assert out == {"verdict": "pass", "reason": "consistent"}
    call = client.messages.calls[0]
    assert "temperature" not in call and call["model"] == MODEL   # SDK 1.x dropped the argument
    assert "example.com" in call["messages"][0]["content"] and "exampleorg" in call["messages"][0]["content"]


def test_dossier_contains_only_stored_facts():
    ent = {"names": {"en": "Example"}, "canonical": {"github_org": "exampleorg", "sources": ["s"]},
           "domains": [old_record(), {"domain": "other.com"}]}
    d = dossier(ent, ent["domains"][0])
    assert d["entity"]["other_domains"] == ["other.com"]
    assert d["domain"]["evidence"][0] == {"code": "A1", "org": "exampleorg", "org_verified": True, "blog": "https://example.com"}

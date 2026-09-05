"""Disputes: stop the harm first, investigate second (TRUST.md 7).

A dispute on a stored domain moves it to ``disputed`` immediately and holds it there. The API stops
answering positively the moment the change is deployed (minutes, not the 48 hours we promise). The hold is
sticky: daily re-verification keeps ``disputed`` until a human clears it, exactly like the AI-review hold.

Only two things can end a hold:

* ``--clear``: the dispute was investigated and rejected; the record returns to whatever the rules say at the
  next re-verification (the reviewer never sets a status by hand).
* a rule change: if the dispute was upheld, the fix is a rule plus an adversarial case, after which the
  next re-verification yields the right status on its own; the hold is then cleared with the correction
  recorded in CORRECTIONS.md.

Usage::

    python -m src.dispute apply kagi.com --issue 12 --reason "lookalike marked official"
    python -m src.dispute clear kagi.com --reviewer octocat --note "issue #12: evidence re-checked, dispute rejected"
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ENTITIES = ROOT / "entities"


def _stamp(now: datetime) -> str:
    return now.strftime("%Y-%m-%dT%H:%M:%SZ")


def apply_dispute(dom: dict, issue_no: int | None, reason: str, now: datetime) -> dict:
    """Pure: the record with the dispute hold set and status disputed. Never raises a status."""
    rec = dict(dom)
    history = list(rec.get("history", []))
    history.append({"at": _stamp(now), "from": rec.get("status", "?"), "to": "disputed",
                    "why": f"dispute #{issue_no}: {reason}" if issue_no else f"dispute: {reason}"})
    rec["history"] = history
    rec["dispute"] = {"at": _stamp(now), "issue": issue_no, "reason": reason[:300], "hold": True}
    rec["status"] = "disputed"
    rec["reasons"] = [f"disputed (#{issue_no}): positive answers stopped while the dispute is investigated; {reason[:200]}"] \
        + list(rec.get("reasons", []))
    return rec


def clear_dispute(dom: dict, reviewer: str, note: str, now: datetime) -> dict:
    rec = dict(dom)
    d = dict(rec.get("dispute") or {})
    d.pop("hold", None)
    d["cleared"] = {"at": _stamp(now), "by": reviewer, "note": note}
    rec["dispute"] = d
    return rec


def on_hold(dom: dict) -> bool:
    return bool((dom.get("dispute") or {}).get("hold"))


def _find(domain: str):
    for path in sorted(ENTITIES.glob("*/*.yaml")):
        ent = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for i, dom in enumerate(ent.get("domains", [])):
            if dom["domain"] == domain:
                return path, ent, i
    return None, None, None


def _save(path: Path, ent: dict) -> None:
    header = ("# 本文件由流水线生成，请勿手工编辑（SECURITY.md §1）。\n"
              f"# generated_by: {ent.get('provenance', {}).get('generated_by', 'pipeline')}\n")
    path.write_text(header + yaml.safe_dump(ent, allow_unicode=True, sort_keys=False, width=110), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="dispute hold: apply / clear")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("apply")
    a.add_argument("domain")
    a.add_argument("--issue", type=int)
    a.add_argument("--reason", default="dispute filed")
    a.add_argument("--json", type=Path)
    c = sub.add_parser("clear")
    c.add_argument("domain")
    c.add_argument("--reviewer", required=True)
    c.add_argument("--note", default="")
    args = p.parse_args(argv)
    now = datetime.now(UTC)

    from src.policy import registrable_domain
    domain = registrable_domain(args.domain)
    path, ent, i = _find(domain)
    result = {"domain": domain, "found": path is not None}
    if path is None:
        print(f"{domain}: not a stored record; nothing to downgrade", file=sys.stderr)
    elif args.cmd == "apply":
        old = ent["domains"][i].get("status")
        ent["domains"][i] = apply_dispute(ent["domains"][i], args.issue, args.reason, now)
        _save(path, ent)
        result.update({"entity_id": ent.get("entity_id"), "old_status": old, "status": "disputed",
                       "file": str(path.relative_to(ROOT)).replace("\\", "/")})
        print(f"{domain}: {old} -> disputed (hold, #{args.issue})", file=sys.stderr)
    else:
        if not on_hold(ent["domains"][i]):
            print(f"{domain}: no dispute hold to clear", file=sys.stderr)
            return 1
        ent["domains"][i] = clear_dispute(ent["domains"][i], args.reviewer, args.note, now)
        ent.setdefault("provenance", {}).setdefault("reviewed_by", []).append(args.reviewer)
        _save(path, ent)
        result.update({"cleared": True})
        print(f"{domain}: dispute hold cleared by {args.reviewer}; the next re-verification decides the status", file=sys.stderr)
    if args.json:
        args.json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if result["found"] else 1


if __name__ == "__main__":
    sys.exit(main())

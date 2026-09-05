"""AI review: a second audit layer over verified records. It can only take verification away.

Why it exists
-------------
At ten thousand organisations a fixed 200-record manual sample still measures the pipeline's precision,
but it no longer *looks at* most records. This layer looks at every verified record and asks a model one
question: given the stored evidence, is there any sign this domain does **not** belong to this entity?

What it may and may not do
--------------------------
* It reads only what is already in the record (labels, canonical identity, evidence, reasons). It fetches
  nothing and judges nothing that the rules did not already collect.
* A ``flag`` moves ``verified`` to ``review_required`` and sets a hold that daily re-verification honours
  until a human clears it (``--clear``). A ``pass`` changes nothing.
* It **never promotes**. No status ever moves up because of this module; the rules in ``policy.py`` remain
  the only path to ``verified``. This is enforced in ``apply_review()`` and tested.
* Without an ``ANTHROPIC_API_KEY`` it skips loudly and flags nothing: absence of review is never a verdict.

Usage::

    python -m src.review_ai                       # every verified domain
    python -m src.review_ai --only x.com --dry-run
    python -m src.review_ai --changed-since origin/main   # only records touched on this branch
    python -m src.review_ai --clear x.com --reviewer octocat --note "issue #12: checked manually"
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
ENTITIES = ROOT / "entities"
PIPELINE_VERSION = "review_ai/0.1"
DEFAULT_MODEL = "claude-sonnet-5"

SYSTEM = """You are the second audit layer of realurls, an open registry of which domain belongs to which organisation.
Deterministic rules have already decided that the domain below is VERIFIED as belonging to the entity below.
Your only job is to look for signs that this is WRONG: that the domain is a lookalike, belongs to a different
organisation, or that the evidence was mis-attributed (for example, an anchor tied to another company because the
homepage merely linked to it). You judge ownership only, never safety or reputation.

Rules:
- Base your answer only on the dossier. Do not rely on memory of what a site "should" be; if the dossier does not
  contradict itself, that is a pass.
- Flag when: the entity name and the domain plainly belong to different organisations; the canonical GitHub
  organisation or Wikidata item clearly names another company or product; the domain is a near-lookalike of a
  well-known brand that is not the entity; or the evidence is internally inconsistent.
- Do not flag for: weak-looking evidence, missing evidence types, unfamiliar companies, or product domains
  that differ from the company name (claude.ai belonging to Anthropic is correct).
- A flag removes a public answer and costs a human review. A missed problem costs a wrong answer. Being wrong is
  worse than being silent, but a flag must still name a concrete contradiction in the dossier.

Answer with one JSON object and nothing else: {"verdict": "pass" | "flag", "reason": "<one sentence>"}"""


# ------------------------------------------------------------------ dossier

def dossier(entity: dict, dom: dict) -> dict:
    """The compact, model-facing view of one verified domain. Only stored facts, no live fetches."""
    canon = entity.get("canonical") or {}
    return {
        "entity": {
            "name": (entity.get("names") or {}).get("en"),
            "aliases": entity.get("aliases", []),
            "category": entity.get("category", []),
            "canonical_github_org": canon.get("github_org"),
            "wikidata": canon.get("wikidata"),
            "canonical_sources": canon.get("sources", []),
            "label_source": (entity.get("provenance") or {}).get("label_source"),
            "other_domains": [d["domain"] for d in entity.get("domains", []) if d["domain"] != dom["domain"]],
        },
        "domain": {
            "domain": dom["domain"],
            "role": dom.get("role"),
            "status": dom.get("status"),
            "confidence": dom.get("confidence"),
            "age_days": dom.get("age_days"),
            "evidence": [{"code": e["code"], **_compact(e.get("data", {}))} for e in dom.get("evidence", [])],
            "rejected_evidence": dom.get("rejected_evidence", []),
            "reasons": dom.get("reasons", []),
        },
    }


_KEEP = {"org", "org_name", "blog", "org_verified", "qid", "label", "site", "sitelinks", "repo", "homepage",
         "registrar", "from", "first_party_link", "structural_links", "rank", "first_snapshot", "package",
         "organization", "issuer", "backlink", "stars", "contributors"}


def _compact(data: dict) -> dict:
    return {k: v for k, v in data.items() if k in _KEEP}


# ------------------------------------------------------------------ model

def ask(client: Any, model: str, dsr: dict) -> dict:
    """One question, one JSON answer. ``client`` is an ``anthropic.Anthropic`` (or a test double)."""
    msg = client.messages.create(
        model=model, max_tokens=300, temperature=0, system=SYSTEM,
        messages=[{"role": "user", "content": json.dumps(dsr, ensure_ascii=False)}],
    )
    text = "".join(getattr(b, "text", "") for b in msg.content)
    return parse_answer(text)


def parse_answer(text: str) -> dict:
    """Tolerant of fences and prose around the JSON; anything unparseable is a *pass*, reported as such.
    A broken answer must not remove a public verdict."""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return {"verdict": "pass", "reason": "unparseable answer", "malformed": True}
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return {"verdict": "pass", "reason": "unparseable answer", "malformed": True}
    verdict = "flag" if str(obj.get("verdict", "")).lower() == "flag" else "pass"
    return {"verdict": verdict, "reason": str(obj.get("reason", ""))[:300]}


# ------------------------------------------------------------------ apply (pure)

def apply_review(dom: dict, answer: dict, model: str, now: datetime) -> tuple[dict, bool]:
    """Pure function: record the answer; on ``flag`` move a verified domain to ``review_required`` with a hold.

    Returns the new record and whether its status changed. This function cannot raise a status: it only
    ever writes ``review_required`` or leaves the status untouched.
    """
    rec = dict(dom)
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    rec["ai_review"] = {"at": stamp, "model": model, "verdict": answer["verdict"], "reason": answer.get("reason", "")}
    if answer["verdict"] != "flag" or rec.get("status") != "verified":
        return rec, False
    history = list(rec.get("history", []))
    history.append({"at": stamp, "from": rec["status"], "to": "review_required",
                    "why": f"AI review flagged: {answer.get('reason', '')}"})
    rec["history"] = history
    rec["status"] = "review_required"
    rec["reasons"] = [f"AI review flagged this record, awaiting human review: {answer.get('reason', '')}"] \
        + list(rec.get("reasons", []))
    rec["ai_review"]["hold"] = True
    return rec, True


def clear_hold(dom: dict, reviewer: str, note: str, now: datetime) -> dict:
    """A human looked and found the record fine. Removes the hold; the status is left to the next
    re-verification (the rules decide, not the reviewer)."""
    rec = dict(dom)
    ai = dict(rec.get("ai_review") or {})
    ai.pop("hold", None)
    ai["cleared"] = {"at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "by": reviewer, "note": note}
    rec["ai_review"] = ai
    return rec


def on_hold(dom: dict) -> bool:
    return bool((dom.get("ai_review") or {}).get("hold"))


# ------------------------------------------------------------------ IO

def _load() -> list[tuple[Path, dict]]:
    return [(p, yaml.safe_load(p.read_text(encoding="utf-8")) or {}) for p in sorted(ENTITIES.glob("*/*.yaml"))]


def _save(path: Path, record: dict) -> None:
    header = ("# 本文件由流水线生成，请勿手工编辑（SECURITY.md §1）。\n"
              f"# generated_by: {record.get('provenance', {}).get('generated_by', 'pipeline')}\n")
    path.write_text(header + yaml.safe_dump(record, allow_unicode=True, sort_keys=False, width=110), encoding="utf-8")


def _changed_files(ref: str) -> set[str]:
    """Entity files that differ from ``ref`` plus files not yet tracked at all: a record written by the
    pipeline minutes ago is exactly what this review exists for, and ``git diff`` alone would skip it."""
    diff = subprocess.run(["git", "diff", "--name-only", ref, "--", "entities/"], cwd=ROOT,
                          capture_output=True, text=True, check=True)
    untracked = subprocess.run(["git", "ls-files", "--others", "--exclude-standard", "--", "entities/"], cwd=ROOT,
                               capture_output=True, text=True, check=True)
    return {line.strip().replace("\\", "/") for line in (diff.stdout + untracked.stdout).splitlines() if line.strip()}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="AI review of verified records (flag-only, never promotes)")
    p.add_argument("--only", help="comma-separated domains")
    p.add_argument("--changed-since", metavar="REF", help="only entity files that differ from this git ref")
    p.add_argument("--model", default=os.environ.get("REALURLS_REVIEW_MODEL", DEFAULT_MODEL))
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", type=Path, help="write per-domain answers here")
    p.add_argument("--clear", metavar="DOMAIN", help="remove the AI hold on this domain after human review")
    p.add_argument("--reviewer", help="GitHub login of the human who reviewed (with --clear)")
    p.add_argument("--note", default="", help="what was checked (with --clear)")
    args = p.parse_args(argv)
    now = datetime.now(UTC)

    if args.clear:
        if not args.reviewer:
            p.error("--clear requires --reviewer")
        for path, ent in _load():
            for i, dom in enumerate(ent.get("domains", [])):
                if dom["domain"] == args.clear and on_hold(dom):
                    ent["domains"][i] = clear_hold(dom, args.reviewer, args.note, now)
                    ent.setdefault("provenance", {}).setdefault("reviewed_by", []).append(args.reviewer)
                    _save(path, ent)
                    print(f"cleared hold on {args.clear} ({path.relative_to(ROOT)})", file=sys.stderr)
                    return 0
        print(f"{args.clear}: no AI hold found", file=sys.stderr)
        return 1

    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        print("# review_ai: ANTHROPIC_API_KEY not set; skipped (no record was flagged, none was cleared)", file=sys.stderr)
        return 0
    import anthropic
    client = anthropic.Anthropic(api_key=key)

    wanted = {d.strip() for d in args.only.split(",")} if args.only else None
    changed = _changed_files(args.changed_since) if args.changed_since else None

    rows, flagged, seen = [], 0, 0
    for path, ent in _load():
        if changed is not None and str(path.relative_to(ROOT)).replace("\\", "/") not in changed:
            continue
        dirty = False
        for i, dom in enumerate(ent.get("domains", [])):
            if dom.get("status") != "verified" or (wanted and dom["domain"] not in wanted):
                continue
            seen += 1
            try:
                answer = ask(client, args.model, dossier(ent, dom))
            except Exception as exc:  # an API failure is not a verdict
                answer = {"verdict": "pass", "reason": f"review unavailable: {type(exc).__name__}", "error": True}
            new, changed_status = apply_review(dom, answer, args.model, now)
            rows.append({"domain": dom["domain"], "entity": ent.get("entity_id"), **answer, "demoted": changed_status})
            mark = "⚑" if answer["verdict"] == "flag" else "·"
            print(f"  {mark} {dom['domain']:<28} {answer['verdict']:<5} {answer.get('reason', '')}", file=sys.stderr)
            if changed_status:
                flagged += 1
            if not args.dry_run:
                ent["domains"][i] = new
                dirty = True
        if dirty:
            _save(path, ent)

    if args.json:
        args.json.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"# review_ai: {seen} verified records reviewed, {flagged} moved to review_required"
          f"{' (dry run)' if args.dry_run else ''}", file=sys.stderr)
    return 2 if flagged else 0


if __name__ == "__main__":
    sys.exit(main())

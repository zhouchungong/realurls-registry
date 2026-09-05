"""Recompute every stored verdict from its stored evidence under the *current* rules and drop what no longer
reaches ``verified``: domains fall out of their entity, entities with no domain left are deleted.

This is how a batch produced under yesterday's rules is brought to today's before it is reviewed, without
collecting anything again: the rules are a pure function of the stored evidence (``validate`` checks the
same thing and refuses the data otherwise). Everything dropped is listed, so the review sees it.

Usage::

    python -m src.prune --dry-run
    python -m src.prune --json .cache/pruned.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml

from src.policy import DomainFacts, Evidence, decide

ROOT = Path(__file__).resolve().parents[1]
ENTITIES = ROOT / "entities"


def recompute(doc: dict, rec: dict):
    canonical = doc.get("canonical") or {}
    facts = DomainFacts(
        domain=rec["domain"], age_days=rec.get("age_days"), age_source=rec.get("age_source"),
        expected_github_org=canonical.get("github_org"), expected_wikidata=canonical.get("wikidata"),
        anchor_sources=tuple(canonical.get("sources", [])),
        expected_names=tuple(n for n in [(doc.get("names") or {}).get("en"), *(doc.get("aliases") or []),
                                         canonical.get("github_org")] if n),
        ttl_days=rec.get("ttl_days", 30),
    )
    evidence = [Evidence(code=e["code"], data=e.get("data", {}), source=e.get("source")) for e in rec.get("evidence", [])]
    return decide(facts, evidence, now=datetime.now(UTC))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", type=Path)
    args = p.parse_args(argv)
    dropped, removed_files = [], []
    for path in sorted(ENTITIES.glob("*/*.yaml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        keep = []
        for rec in doc.get("domains", []):
            if rec.get("status") != "verified":
                keep.append(rec)   # holds, disputes and the like are not this tool's business
                continue
            d = recompute(doc, rec)
            if d.status == "verified":
                keep.append(rec)
            else:
                dropped.append({"file": str(path.relative_to(ROOT)).replace("\\", "/"), "entity_id": doc.get("entity_id"),
                                "domain": rec["domain"], "role": rec.get("role"), "now": d.status,
                                "why": (d.rejected or d.reasons)[:2]})
        if len(keep) == len(doc.get("domains", [])):
            continue
        if not args.dry_run:
            if keep:
                doc["domains"] = keep
                header = ("# 本文件由流水线生成，请勿手工编辑（SECURITY.md §1）。\n"
                          f"# generated_by: {doc.get('provenance', {}).get('generated_by', 'pipeline')}\n")
                path.write_text(header + yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=110), encoding="utf-8")
            else:
                path.unlink()
                removed_files.append(str(path.relative_to(ROOT)).replace("\\", "/"))
    for d in dropped:
        print(f"  ✂ {d['domain']:<28} {d['entity_id']:<28} → {d['now']:<12} {d['why'][0][:90] if d['why'] else ''}", file=sys.stderr)
    print(f"# dropped {len(dropped)} domain record(s), removed {len(removed_files)} empty entity file(s)"
          f"{' (dry run)' if args.dry_run else ''}", file=sys.stderr)
    if args.json:
        args.json.write_text(json.dumps({"dropped": dropped, "removed_files": removed_files}, ensure_ascii=False, indent=2),
                             encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())

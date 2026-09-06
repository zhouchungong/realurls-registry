"""Recompute the category of stored records whose category was a *fallback* (no topic said anything), with
the current rule (build_entities.fallback_category): the Wikidata item's type decides. Topic-derived categories
are not touched, because seed topics are not stored and the fallback rule cannot tell them apart otherwise:
only records in the fallback categories (open-source, saas, other) are candidates.

Usage::

    python -m src.recategorize --dry-run
    python -m src.recategorize --changed-since origin/main
"""

from __future__ import annotations

import argparse
import json
import sys

import yaml

from src.build_entities import ROOT, fallback_category
from src.collectors.thirdparty import item_flags
from src.relabel import _files

FALLBACK = {"open-source", "saas", "other"}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Recompute fallback categories of stored records from Wikidata item types")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--changed-since", metavar="REF")
    args = p.parse_args(argv)
    files = _files(args.changed_since)
    docs = {}
    for path in files:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if doc.get("category", [None])[0] in FALLBACK:
            docs[path] = doc
    flags = item_flags([d.get("wikidata") for d in docs.values() if d.get("wikidata")])
    seed_source = {}
    for seed_file in sorted((ROOT / "seeds").glob("*.jsonl")):
        for line in seed_file.read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.lstrip().startswith("#"):
                row = json.loads(line)
                seed_source.setdefault(row.get("domain"), row.get("source", "github"))
    n = 0
    for path, doc in docs.items():
        qid = doc.get("wikidata")
        f = flags.get(qid) if qid else None
        primary = next((d["domain"] for d in doc.get("domains", []) if d.get("role") == "primary"), "")
        source = seed_source.get(primary, "github")
        # "saas" is the fallback only for Wikidata-sourced entities; for GitHub-sourced ones it came from a topic
        # and stays. "open-source" is only ever a GitHub fallback.
        if doc["category"][0] == "saas" and source != "wikidata":
            continue
        new = fallback_category(source, f, primary)
        old = doc["category"][0]
        if new == old:
            continue
        n += 1
        print(f"  {path.relative_to(ROOT)}: {old} → {new}", file=sys.stderr)
        if args.dry_run:
            continue
        doc["category"] = [new]
        header = ("# 本文件由流水线生成，请勿手工编辑（SECURITY.md §1）。\n"
                  f"# generated_by: {doc.get('provenance', {}).get('generated_by', 'pipeline')}\n")
        target = ROOT / "entities" / new / path.name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(header + yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=110), encoding="utf-8")
        if target != path:
            path.unlink()
    print(f"# recategorized {n} record(s){' (dry run)' if args.dry_run else ''}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

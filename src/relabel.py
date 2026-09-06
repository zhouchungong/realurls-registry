"""Recompute ``names.en`` of stored records with the current label chain (build_entities.choose_label),
from the same sources the pipeline uses: the canonical Wikidata item's *English* label and the canonical
GitHub organization's display name. Nothing about domains or evidence is touched.

This exists because the first full-category batch stored Arabic, Korean and Tamil Wikidata labels for
WordPress, Docker and Vim, and product names (Next.js, javascript) for Vercel and Airbnb. The chain was
fixed; this brings stored records to it without re-collecting.

Usage::

    python -m src.relabel --dry-run
    python -m src.relabel --changed-since origin/main
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

import yaml

from src.build_entities import ENTITIES, ROOT, choose_label
from src.collectors.base import FetchError, fetch_json
from src.collectors.github import API, _headers
from src.collectors.thirdparty import english_label


def _gh_display(login: str) -> str:
    try:
        return str(fetch_json(f"{API}/orgs/{login}", headers=_headers(), ttl_hours=168).get("name") or "").strip()
    except FetchError:
        return ""


def _files(changed_since: str | None) -> list[Path]:
    if not changed_since:
        return sorted(ENTITIES.glob("*/*.yaml"))
    out = subprocess.run(["git", "diff", "--name-only", changed_since, "--", "entities/"], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout.split()
    untracked = subprocess.run(["git", "ls-files", "--others", "--exclude-standard", "entities/"], cwd=ROOT,
                               capture_output=True, text=True, check=True).stdout.split()
    return sorted(p for p in (ROOT / f for f in dict.fromkeys(out + untracked)) if p.exists())


def relabel(path: Path) -> tuple[str, str, str] | None:
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    canonical = doc.get("canonical") or {}
    prov = doc.setdefault("provenance", {})
    old = (doc.get("names") or {}).get("en", "")
    qid = canonical.get("wikidata")
    gh = canonical.get("github_org") or ""
    wl = english_label(qid) if qid else ""
    gh_display = _gh_display(gh) if gh else ""
    seed_org_name = old if str(prov.get("label_source", "")).startswith("seed_org_name") else ""
    repo_label = next((s.split(":", 1)[1].split("(", 1)[0] for s in canonical.get("sources", [])
                       if s.startswith("github-history:")), "")
    primary_rec = next((d for d in doc.get("domains", []) if d.get("role") == "primary"), {})
    primary = primary_rec.get("domain", "")
    names_primary = bool(qid) and any(e.get("code") == "B1" and e.get("data", {}).get("qid") == qid
                                      for e in primary_rec.get("evidence", []))
    label, source = choose_label(wikidata=qid, wikidata_label=wl, github_org=gh, gh_display=gh_display,
                                 org_name=seed_org_name, repo_label=repo_label, domain=primary,
                                 wikidata_names_primary=names_primary)
    if label == old and prov.get("label_source") == source:
        return None
    aliases = sorted({a for a in [*(doc.get("aliases") or []), old, wl, gh_display, gh]
                      if a and a != label and not re.fullmatch(r"Q\d+", a) and re.search(r"[A-Za-z0-9]", a)})
    doc["names"] = {"en": label}
    doc["aliases"] = aliases
    prov["label_source"] = source
    header = ("# 本文件由流水线生成，请勿手工编辑（SECURITY.md §1）。\n"
              f"# generated_by: {prov.get('generated_by', 'pipeline')}\n")
    return old, label, header + yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=110)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Recompute names.en of stored records with the current label chain")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--changed-since", metavar="REF")
    args = p.parse_args(argv)
    n = 0
    for path in _files(args.changed_since):
        r = relabel(path)
        if not r:
            continue
        old, new, text = r
        n += 1
        print(f"  {path.relative_to(ROOT)}: {old!r} → {new!r}", file=sys.stderr)
        if not args.dry_run:
            path.write_text(text, encoding="utf-8")
    print(f"# relabelled {n} record(s){' (dry run)' if args.dry_run else ''}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

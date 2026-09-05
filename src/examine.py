"""On-demand examination: run the pipeline on domains people asked about and we had never looked at.

Fed by the aggregate query counters (``/v1/examine-queue``), run every few minutes by
``.github/workflows/examine.yml``. Same pipeline, same rules, same writer (``build_entities``): the only
thing "on demand" changes is *which* domains get examined first.

Outcomes:
* ``verified``  → the record is written to ``entities/`` (the workflow validates, runs the corpus and the AI
  review, then merges), so the next identical query gets a positive answer.
* anything else → an ``examined`` row (domain, status, date, the rules' reasons) so the API can say
  "examined on <date>: insufficient evidence" instead of "never looked", and so the same domain is not
  re-examined every ten minutes. Re-examined after 30 days, or immediately through the owner flow.

Usage::

    python -m src.examine --queue https://api.realurls.org/v1/examine-queue --max 20 --json out.json --sql examined.sql
    python -m src.examine --domains kagi.com,example.org --json out.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from src.build_entities import build_one, write
from src.collectors.base import fetch_json
from src.policy import registrable_domain
from src.verify import verify

ROOT = Path(__file__).resolve().parents[1]
MAX_PER_RUN = 20


def _sql_str(s: str) -> str:
    return "'" + str(s).replace("'", "''") + "'"


def examine(domains: list[str], github_org: str | None = None) -> list[dict]:
    now = datetime.now(UTC)
    out = []
    for raw in domains:
        domain = registrable_domain(raw)
        if not domain or "." not in domain:
            continue
        item = {"domain": domain, "checked_at": now.strftime("%Y-%m-%dT%H:%M:%SZ")}
        try:
            record, msg = build_one({"domain": domain, "topics": [], "source": "demand", "github_org": github_org}, now)
        except Exception as exc:
            item.update({"status": "error", "reasons": [f"{type(exc).__name__}: {exc}"]})
            out.append(item)
            continue
        if record is not None:
            path = write(record)
            item.update({"status": "verified", "entity_id": record["entity_id"],
                         "file": str(path.relative_to(ROOT)).replace("\\", "/"), "reasons": []})
        else:
            d, _ = verify(domain, github_org=github_org)
            item.update({"status": d.status, "reasons": list(d.reasons)[:3], "rejected": list(d.rejected)[:6]})
        out.append(item)
        print(f"  {'✓' if item['status'] == 'verified' else '·'} {domain}: {item['status']}", file=sys.stderr)
    return out


def examined_sql(results: list[dict], dataset_version: str = "") -> str:
    rows = [r for r in results if r["status"] != "verified"]
    if not rows:
        return ""
    values = ", ".join(
        f"({_sql_str(r['domain'])}, {_sql_str(r['status'])}, {_sql_str(r['checked_at'])}, "
        f"{_sql_str('; '.join(r.get('reasons') or [])[:500])}, {_sql_str(dataset_version)})"
        for r in rows
    )
    return ("INSERT INTO examined(domain, status, checked_at, reasons, dataset_version) VALUES " + values +
            " ON CONFLICT(domain) DO UPDATE SET status = excluded.status, checked_at = excluded.checked_at, "
            "reasons = excluded.reasons, dataset_version = excluded.dataset_version;\n")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--queue", help="URL returning {items: [{domain, n}]} (the API's examine queue)")
    p.add_argument("--domains", help="comma-separated domains (instead of the queue)")
    p.add_argument("--max", type=int, default=MAX_PER_RUN)
    p.add_argument("--github-org", help="GitHub organisation hint applied to every listed domain (a lead's clue)")
    p.add_argument("--json", type=Path)
    p.add_argument("--sql", type=Path, help="write the examined-table upsert here")
    args = p.parse_args(argv)

    if args.domains:
        domains = [d.strip() for d in args.domains.split(",") if d.strip()]
    elif args.queue:
        doc = fetch_json(args.queue, ttl_hours=0)
        domains = [it["domain"] for it in doc.get("items", [])][:args.max]
    else:
        p.error("--queue or --domains required")
    print(f"# examining {len(domains)} domain(s)", file=sys.stderr)
    results = examine(domains, args.github_org)
    if args.json:
        args.json.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.sql:
        args.sql.write_text(examined_sql(results), encoding="utf-8")
    verified = sum(r["status"] == "verified" for r in results)
    print(f"# {len(results)} examined, {verified} verified", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

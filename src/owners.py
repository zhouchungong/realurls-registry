"""Owner self-attestation, self-serve: token issue, pending list, verification run.

The flow (``.github/workflows/owner-verify.yml`` drives it, this module does the work):

1. An owner opens a "Verify my domain" issue. ``issue`` mints a token for the domain (or returns the existing
   one), records the seed in ``seeds/owners.jsonl`` and prints the TXT record the owner must publish.
2. The owner publishes ``_realurls.<domain> TXT "realurls-site-verification=<token>"`` (or verifies the domain
   on their GitHub organisation, which is evidence A1 and needs no token).
3. ``check`` runs the normal pipeline on the pending seeds. A domain that reaches ``verified`` is written to
   ``entities/`` by ``build_entities`` (the only legal writer) and the workflow opens the bot pull request;
   anything else is reported back with the exact reason from the rules.

Nothing here judges anything: the token is just a fact the collector compares, and ``policy.py`` decides.
The token is not a secret (it is published in DNS); what it proves is control of the zone, and A5 anchors
that control to the entity named in the seed only because the request came from the issue that named it.

Usage::

    python -m src.owners issue kagi.com --org "Kagi" --github kagisearch --issue 42
    python -m src.owners pending
    python -m src.owners check --issue 42 --json out.json
"""

from __future__ import annotations

import argparse
import json
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEEDS = ROOT / "seeds" / "owners.jsonl"


def _load() -> list[dict]:
    if not SEEDS.exists():
        return []
    return [json.loads(line) for line in SEEDS.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")]


def _save(rows: list[dict]) -> None:
    SEEDS.parent.mkdir(exist_ok=True)
    head = "# Owner-requested verifications. token = what the owner publishes at _realurls.<domain> TXT.\n"
    SEEDS.write_text(head + "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def issue(domain: str, org_name: str, github_org: str | None, issue_no: int | None, topics: list[str]) -> dict:
    """Mint (or reuse) the token for a domain and record the seed."""
    from src.policy import registrable_domain
    domain = registrable_domain(domain)
    rows = _load()
    for r in rows:
        if r["domain"] == domain:
            r.update({k: v for k, v in {"org_name": org_name, "github_org": github_org, "issue": issue_no}.items() if v})
            _save(rows)
            return r
    row = {"domain": domain, "org_name": org_name, "github_org": github_org, "topics": topics or ["other"],
           "source": "owner", "issue": issue_no, "token": f"{domain.split('.')[0]}-{secrets.token_hex(12)}"}
    rows.append(row)
    _save(rows)
    return row


def txt_record(row: dict) -> str:
    return f'_realurls.{row["domain"]}.   TXT   "realurls-site-verification={row["token"]}"'


def check(issue_no: int | None, domain: str | None) -> list[dict]:
    """Run the pipeline on the matching pending seeds; report per domain. Writes entities/ only via build_entities."""
    from datetime import UTC, datetime

    from src.build_entities import build_one, write
    rows = [r for r in _load() if (issue_no is None or r.get("issue") == issue_no) and (domain is None or r["domain"] == domain)]
    out = []
    now = datetime.now(UTC)
    for seed in rows:
        record, msg = build_one(seed, now)
        item = {"domain": seed["domain"], "issue": seed.get("issue"), "verified": record is not None, "message": msg}
        if record is not None:
            path = write(record)
            item["file"] = str(path.relative_to(ROOT)).replace("\\", "/")
            item["entity_id"] = record["entity_id"]
        else:
            from src.verify import verify
            d, _ = verify(seed["domain"], github_org=seed.get("github_org"), token=seed.get("token"))
            item["status"] = d.status
            item["rejected"] = d.rejected
            item["reasons"] = d.reasons
        out.append(item)
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="owner self-attestation: token issue / pending / check")
    sub = p.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("issue")
    i.add_argument("domain")
    i.add_argument("--org", required=True, help="organisation name as the owner states it")
    i.add_argument("--github", help="GitHub organisation login, if any")
    i.add_argument("--issue", type=int)
    i.add_argument("--topic", action="append", default=[])
    sub.add_parser("pending")
    c = sub.add_parser("check")
    c.add_argument("--issue", type=int)
    c.add_argument("--domain")
    c.add_argument("--json", type=Path)
    args = p.parse_args(argv)

    if args.cmd == "issue":
        row = issue(args.domain, args.org, args.github, args.issue, args.topic)
        print(json.dumps({"domain": row["domain"], "token": row["token"], "txt": txt_record(row)}))
        return 0
    if args.cmd == "pending":
        for r in _load():
            print(f"{r['domain']:<30} issue #{r.get('issue') or '-'}  {r.get('org_name', '')}")
        return 0
    results = check(args.issue, args.domain)
    if args.json:
        args.json.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    for r in results:
        print(f"{'✓' if r['verified'] else '·'} {r['domain']}: {r['message']}", file=sys.stderr)
    return 0 if all(r["verified"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())

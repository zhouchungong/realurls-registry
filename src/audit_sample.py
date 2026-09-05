"""Manual precision sample: the human audit that gates every dataset release (POLICY.md §3.2).

Two commands.

``draw`` picks N verified domain records (default 200) and writes a checklist under ``audits/``: one row
per record with the entity, the anchors, a link to the evidence page and to the source YAML, and an empty
``verdict`` cell. The draw is deterministic for a given seed, so a reviewer can be handed the file and a
second reviewer can reproduce it. ``--changed-since REF`` restricts the pool to entity files that differ
from a git ref, which is how a batch pull request is sampled before merge.

``score`` reads the filled-in file, computes precision = ok / (ok + wrong), lists every ``wrong`` and
``unsure`` row, and exits non-zero when precision is below the bar or rows are still empty. The rules say
"below 99.5 %, roll back and ship nothing"; this is the number that decision is made on.

The sample size does not shrink as the dataset grows: it measures the pipeline, not the records, and it is
what proves the AI review layer is itself trustworthy.

Usage::

    python -m src.audit_sample draw --batch gh-01 --changed-since origin/main
    python -m src.audit_sample draw --batch release-2026-09 --n 200 --seed 7
    python -m src.audit_sample score audits/gh-01.md
"""

from __future__ import annotations

import argparse
import random
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ENTITIES = ROOT / "entities"
AUDITS = ROOT / "audits"
REPO = "https://github.com/zhouchungong/realurls-registry"
SITE = "https://realurls.org"
PRECISION_BAR = 0.995
VERDICTS = {"ok", "wrong", "unsure"}


def _changed_files(ref: str) -> set[str]:
    out = subprocess.run(["git", "diff", "--name-only", ref, "--", "entities/"], cwd=ROOT,
                         capture_output=True, text=True, check=True)
    return {line.strip().replace("\\", "/") for line in out.stdout.splitlines() if line.strip()}


def pool(changed_since: str | None = None) -> list[dict]:
    """Every verified domain record, as a flat row with what a reviewer needs."""
    changed = _changed_files(changed_since) if changed_since else None
    rows = []
    for path in sorted(ENTITIES.glob("*/*.yaml")):
        rel = str(path.relative_to(ROOT)).replace("\\", "/")
        if changed is not None and rel not in changed:
            continue
        ent = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for dom in ent.get("domains", []):
            if dom.get("status") != "verified":
                continue
            anchors = sorted({e["code"] for e in dom.get("evidence", [])
                              if e["code"].startswith("A") and not any(r.startswith(e["code"]) for r in dom.get("rejected_evidence", []))})
            rows.append({
                "domain": dom["domain"], "role": dom.get("role", ""), "entity_id": ent.get("entity_id", ""),
                "name": (ent.get("names") or {}).get("en", ""), "anchors": anchors, "file": rel,
                "confidence": dom.get("confidence"),
            })
    return rows


def draw(rows: list[dict], n: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    if len(rows) <= n:
        return sorted(rows, key=lambda r: r["domain"])
    return sorted(rng.sample(rows, n), key=lambda r: r["domain"])


def render(batch: str, sample: list[dict], pool_size: int, seed: int, changed_since: str | None) -> str:
    head = [
        f"# Manual precision sample: {batch}",
        "",
        f"Drawn {datetime.now(UTC).strftime('%Y-%m-%d')} · {len(sample)} of {pool_size} verified records"
        + (f" changed since `{changed_since}`" if changed_since else "") + f" · seed {seed}",
        "",
        "Fill the **verdict** column with `ok` (the domain belongs to this organisation), `wrong` (it does not, or the",
        "organisation is misidentified) or `unsure` (needs a second look). A `wrong` is a P0: fix the rule, add the case to",
        "`tests/negative_corpus.yaml`, and re-draw. Score with `python -m src.audit_sample score <this file>`.",
        "",
        "| # | domain | role | organisation | anchors | evidence | verdict | note |",
        "|---|---|---|---|---|---|---|---|",
    ]
    body = []
    for i, r in enumerate(sample, 1):
        slug = r["entity_id"].split(":", 1)[-1]
        ev = f"[page]({SITE}/e/{slug}#{r['domain']}) · [yaml]({REPO}/blob/main/{r['file']})"
        org = f"{r['name']} (`{r['entity_id']}`)"
        body.append(f"| {i} | {r['domain']} | {r['role']} | {org} | {', '.join(r['anchors']) or '—'} | {ev} |  |  |")
    return "\n".join(head + body) + "\n"


_ROW = re.compile(r"^\|\s*(\d+)\s*\|\s*([^|]+?)\s*\|[^|]*\|[^|]*\|[^|]*\|[^|]*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|\s*$")


def score(text: str) -> dict:
    counts = {"ok": 0, "wrong": 0, "unsure": 0, "empty": 0}
    flagged = []
    for line in text.splitlines():
        m = _ROW.match(line)
        if not m:
            continue
        idx, domain, verdict, note = m.groups()
        v = verdict.strip().lower()
        if v not in VERDICTS:
            counts["empty"] += 1
            continue
        counts[v] += 1
        if v != "ok":
            flagged.append((int(idx), domain, v, note.strip()))
    judged = counts["ok"] + counts["wrong"]
    precision = counts["ok"] / judged if judged else None
    return {"counts": counts, "precision": precision, "flagged": flagged}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Manual precision sample (draw a checklist / score a filled one)")
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("draw")
    d.add_argument("--batch", required=True, help="label, becomes audits/<batch>.md")
    d.add_argument("--n", type=int, default=200)
    d.add_argument("--seed", type=int, default=None, help="default: derived from the batch label")
    d.add_argument("--changed-since", metavar="REF", help="only entity files that differ from this git ref")
    s = sub.add_parser("score")
    s.add_argument("file", type=Path)
    args = p.parse_args(argv)

    if args.cmd == "draw":
        seed = args.seed if args.seed is not None else sum(args.batch.encode())
        rows = pool(args.changed_since)
        if not rows:
            print("no verified records in the pool", file=sys.stderr)
            return 1
        sample = draw(rows, args.n, seed)
        AUDITS.mkdir(exist_ok=True)
        out = AUDITS / f"{args.batch}.md"
        out.write_text(render(args.batch, sample, len(rows), seed, args.changed_since), encoding="utf-8")
        print(f"{out.relative_to(ROOT)}: {len(sample)} of {len(rows)} verified records (seed {seed})", file=sys.stderr)
        return 0

    result = score(args.file.read_text(encoding="utf-8"))
    c = result["counts"]
    print(f"ok {c['ok']} · wrong {c['wrong']} · unsure {c['unsure']} · empty {c['empty']}")
    for idx, domain, v, note in result["flagged"]:
        print(f"  #{idx} {domain}: {v}{' — ' + note if note else ''}")
    if result["precision"] is None:
        print("no judged rows yet")
        return 1
    print(f"precision {result['precision']:.4f} (bar {PRECISION_BAR})")
    if c["empty"] or c["unsure"]:
        print("not complete: empty or unsure rows remain")
        return 1
    return 0 if result["precision"] >= PRECISION_BAR else 2


if __name__ == "__main__":
    sys.exit(main())

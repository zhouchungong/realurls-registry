"""批量验证：对一批种子跑完整流水线，输出逐条结果与覆盖率摘要。

这是 M2 的核心工具。它**不写 entities/**——那是下一步（人工抽样审计通过后）的事。
它只回答一个问题：**在真实分布上，流水线能把多少条送到 verified，卡住的都卡在哪。**

用法::

    python -m src.batch .cache/seeds.jsonl --out .cache/batch-results.jsonl
    python -m src.batch --summarize .cache/batch-results.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from collections import Counter
from pathlib import Path

from src.verify import verify


def run(seeds_path: Path, out_path: Path, resume: bool = True) -> None:
    done: set[str] = set()
    if resume and out_path.exists():
        for line in out_path.read_text(encoding="utf-8").splitlines():
            try:
                done.add(json.loads(line)["domain"])
            except (json.JSONDecodeError, KeyError):
                pass

    seeds = [json.loads(line) for line in seeds_path.read_text(encoding="utf-8").splitlines()
             if line.strip() and not line.startswith("#")]
    todo = [s for s in seeds if s["domain"] not in done]
    print(f"# {len(seeds)} seeds, {len(done)} done, {len(todo)} to go", file=sys.stderr)

    with out_path.open("a", encoding="utf-8") as fh:
        for i, seed in enumerate(todo, 1):
            t0 = time.time()
            rec = {"domain": seed["domain"], "seed": seed}
            try:
                decision, result = verify(seed["domain"], github_org=seed.get("github_org"))
                ent = result.extra.get("entity_anchor")
                rec.update({
                    "status": decision.status,
                    "confidence": decision.confidence,
                    "anchors": decision.anchors,
                    "corroborations": decision.corroborations,
                    "rejected": decision.rejected,
                    "reasons": decision.reasons,
                    "anchored": bool(ent and ent.anchored),
                    "canonical_github_org": ent.github_org if ent else None,
                    "wikidata": ent.wikidata if ent else None,
                    "age_days": result.facts.get("age_days"),
                    "age_source": result.facts.get("age_source"),
                    "notes": result.notes,
                })
            except Exception as exc:  # 一条炸了不能拖死整批
                rec.update({"status": "error", "error": f"{type(exc).__name__}: {exc}",
                            "trace": traceback.format_exc()[-800:]})
            rec["elapsed_s"] = round(time.time() - t0, 1)
            fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
            fh.flush()
            print(f"[{i}/{len(todo)}] {seed['domain']:<28} {rec.get('status'):<12} "
                  f"{rec.get('elapsed_s')}s", file=sys.stderr)


def summarize(results_path: Path) -> None:
    rows = [json.loads(line) for line in results_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    n = len(rows)
    status = Counter(r.get("status") for r in rows)
    anchored = sum(1 for r in rows if r.get("anchored"))
    with_a1 = sum(1 for r in rows if "A1" in (r.get("anchors") or []))
    seed_verified = sum(1 for r in rows if r["seed"].get("org_verified"))

    print(f"总数 {n}")
    print(f"实体锚定成功      {anchored:4d}  ({anchored / n:.0%})")
    print(f"种子 org 已验证    {seed_verified:4d}  ({seed_verified / n:.0%})  ← GitHub is_verified 覆盖率")
    print(f"A1 实际采纳        {with_a1:4d}  ({with_a1 / n:.0%})  ← 既已验证又与 canonical 匹配")
    print()
    print("判定分布：")
    for s, c in status.most_common():
        print(f"  {s:<16} {c:4d}  ({c / n:.0%})")

    print("\n卡在 verified 门外的主要原因（按被拒证据代码）：")
    rej = Counter()
    for r in rows:
        if r.get("status") in ("verified", "error"):
            continue
        for item in r.get("rejected") or []:
            code = item.split(":")[0]
            why = item.split(":", 1)[1].strip()[:50] if ":" in item else ""
            rej[(code, why)] += 1
    for (code, why), c in rej.most_common(12):
        print(f"  {c:4d}  {code}  {why}")

    print("\n锚定失败的原因：")
    anc = Counter()
    for r in rows:
        if r.get("anchored"):
            continue
        for note in r.get("notes") or []:
            if note.startswith("anchor:") or note.startswith("wikidata:"):
                anc[note[:70]] += 1
                break
    for note, c in anc.most_common(6):
        print(f"  {c:4d}  {note}")

    errs = [r for r in rows if r.get("status") == "error"]
    if errs:
        print(f"\n错误 {len(errs)} 条：")
        for r in errs[:8]:
            print(f"  {r['domain']}: {r.get('error')}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("seeds", nargs="?", type=Path)
    p.add_argument("--out", type=Path, default=Path(".cache/batch-results.jsonl"))
    p.add_argument("--summarize", type=Path)
    p.add_argument("--no-resume", action="store_true")
    args = p.parse_args(argv)

    if args.summarize:
        summarize(args.summarize)
        return 0
    if not args.seeds:
        p.error("需要 seeds 文件或 --summarize")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    run(args.seeds, args.out, resume=not args.no_resume)
    return 0


if __name__ == "__main__":
    sys.exit(main())

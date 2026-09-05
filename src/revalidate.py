"""每日重验：对 ``entities/`` 里的每个域名重新采证、重新定案，并按规则更新落盘状态。

这是数据保鲜的核心。信任源最大的失败模式不是判错，是**陈旧**：域名转手了、组织易主了、
产品下线了，而我们还在说 verified。

三条规则（``apply()`` 是纯函数，有测试）：

1. **采集失败 ≠ 降级。** deezer.com 曾因一次 TLS 超时从 verified 掉到 community。
   某次重验若有采集器超时/出错（``collection_incomplete``），且新判定不如旧状态，
   则**保留旧状态、不更新 last_verified**。连续失败超过 TTL 后，policy 会自然判成 stale。
2. **突变 → review_required。** 注册商变了、到期日缩短了、GitHub 组织的验证标记没了、
   canonical 组织被权威否定了——这些是域名易主/劫持的信号。不直接降级，也不维持 verified，
   而是停掉肯定答复，等人看。
3. **其余情况以新判定为准**，升降都记 ``history``，永不静默覆盖。

身份稳定：重验沿用已落盘的 ``canonical``（来源标 ``stored``），不重新锚定——
不能因为 Wikidata 今天被人改了一笔就换掉实体身份。权威与 canonical 不一致时记 ⚠，进 review。

用法::

    python -m src.revalidate                 # 全量
    python -m src.revalidate --only ollama.com --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import yaml

from src.policy import Decision
from src.verify import verify

ROOT = Path(__file__).resolve().parents[1]
ENTITIES = ROOT / "entities"
PIPELINE_VERSION = "revalidate/0.1"

#: 这些证据字段变了，视为「关键属性突变」
MUTATION_FIELDS = {
    "A3": ("registrar",),
    "A1": ("org_verified", "org"),
}


@dataclass
class Outcome:
    domain: str
    old_status: str
    new_status: str
    action: str                     # kept | updated | downgraded | upgraded | review | unchanged
    reason: str
    incomplete: bool = False
    mutations: list[str] = field(default_factory=list)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _detect_mutations(old_rec: dict, new_evidence: list) -> list[str]:
    old = {e["code"]: e.get("data", {}) for e in old_rec.get("evidence", [])}
    new = {e.code: e.data for e in new_evidence}
    out = []
    for code, fields in MUTATION_FIELDS.items():
        if code not in old or code not in new:
            continue
        for f in fields:
            a, b = old[code].get(f), new[code].get(f)
            if a is not None and b is not None and a != b:
                out.append(f"{code}.{f}: {a!r} → {b!r}")
    # 到期日缩短（续费只会往后推；往前跳说明换了注册记录）
    try:
        oe, ne = old["A3"].get("expires"), new["A3"].get("expires")
        if oe and ne and ne < oe:
            out.append(f"A3.expires: {oe} → {ne}（缩短）")
    except KeyError:
        pass
    return out


def apply(old_rec: dict, decision: Decision, facts: dict, new_evidence: list,
          anchor_notes: list[str], now: datetime) -> tuple[dict, Outcome]:
    """纯函数：给定旧记录与本次重验结果，返回新记录与结果说明。不做 IO。"""
    domain = old_rec["domain"]
    old_status = old_rec.get("status", "unverified")
    incomplete = bool(facts.get("collection_incomplete"))
    mutations = _detect_mutations(old_rec, new_evidence)
    anchor_conflict = any("⚠" in n for n in anchor_notes)

    rec = dict(old_rec)
    history = list(old_rec.get("history", []))

    def _write_new():
        rec.update({
            "status": decision.status,
            "confidence": decision.confidence,
            "last_verified": _iso(now),
            "age_days": facts.get("age_days"),
            "age_source": facts.get("age_source"),
            "collection_incomplete": incomplete,
            "evidence": [
                {"code": e.code, "checked_at": _iso(e.checked_at or now), "source": e.source,
                 "data": dict(e.data)} for e in new_evidence
            ],
            "rejected_evidence": decision.rejected,
            "reasons": decision.reasons,
        })

    # 规则 2：突变 → review_required（无论新判定是什么）
    if mutations or anchor_conflict:
        why = "; ".join(mutations) or "锚定权威与已落盘 canonical 不一致"
        _write_new()
        rec["status"] = "review_required"
        rec["reasons"] = [f"关键属性突变：{why}"] + list(decision.reasons)
        history.append({"at": _iso(now), "from": old_status, "to": "review_required", "why": why})
        rec["history"] = history
        return rec, Outcome(domain, old_status, "review_required", "review", why, incomplete, mutations)

    # 规则 1：采集失败且结果变差 → 保留旧状态，不更新 last_verified
    if incomplete and _rank(decision.status) < _rank(old_status):
        rec["collection_incomplete"] = True
        rec["reasons"] = [f"{_iso(now)} 重验时采集不完整，新判定 {decision.status} 不采纳，保留 {old_status}"] \
                         + list(old_rec.get("reasons", []))[:3]
        return rec, Outcome(domain, old_status, old_status, "kept",
                            f"采集不完整，保留旧状态（新判定 {decision.status}）", True)

    # 规则 3：以新判定为准
    _write_new()
    if decision.status == old_status:
        return rec, Outcome(domain, old_status, decision.status, "unchanged", "无变化", incomplete)
    direction = "upgraded" if _rank(decision.status) > _rank(old_status) else "downgraded"
    why = "; ".join(decision.reasons[:2])
    history.append({"at": _iso(now), "from": old_status, "to": decision.status, "why": why})
    rec["history"] = history
    return rec, Outcome(domain, old_status, decision.status, direction, why, incomplete)


_RANK = {"verified": 5, "provisional": 4, "community": 3, "unverified": 2,
         "stale": 1, "review_required": 1, "disputed": 0, "flagged": 0}


def _rank(status: str) -> int:
    return _RANK.get(status, 2)


# ------------------------------------------------------------------ IO

def revalidate_file(path: Path, now: datetime, only: set[str] | None, dry_run: bool) -> list[Outcome]:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    canonical = doc.get("canonical") or {}
    outcomes: list[Outcome] = []
    changed = False

    for i, rec in enumerate(doc.get("domains", [])):
        domain = rec["domain"]
        if only and domain not in only:
            continue
        try:
            decision, result = verify(
                domain,
                canonical_github_org=canonical.get("github_org"),
                canonical_wikidata=canonical.get("wikidata"),
                canonical_source="stored",
            )
        except Exception as exc:
            outcomes.append(Outcome(domain, rec.get("status", "?"), rec.get("status", "?"),
                                    "kept", f"重验异常：{type(exc).__name__}: {exc}", True))
            continue
        anchor_notes = [n for n in result.notes if n.startswith("anchor:")]
        new_rec, outcome = apply(rec, decision, result.facts, result.evidence, anchor_notes, now)
        outcomes.append(outcome)
        if new_rec != rec:
            doc["domains"][i] = new_rec
            changed = True

    if changed and not dry_run:
        doc.setdefault("provenance", {})["last_revalidated_by"] = PIPELINE_VERSION
        header = ("# 本文件由流水线生成，请勿手工编辑（SECURITY.md §1）。\n"
                  f"# generated_by: {doc.get('provenance', {}).get('generated_by', '?')}\n")
        path.write_text(header + yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=110),
                        encoding="utf-8")
    return outcomes


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--only", help="只重验这些域名，逗号分隔")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", type=Path, help="把结果写成 JSON（给 CI 用）")
    args = p.parse_args(argv)

    only = {d.strip() for d in args.only.split(",")} if args.only else None
    now = datetime.now(UTC)
    all_out: list[Outcome] = []
    for path in sorted(ENTITIES.rglob("*.yaml")):
        for o in revalidate_file(path, now, only, args.dry_run):
            all_out.append(o)
            mark = {"unchanged": "·", "kept": "≈", "upgraded": "↑", "downgraded": "↓", "review": "⚠"}[o.action]
            print(f"  {mark} {o.domain:<26} {o.old_status:<12} → {o.new_status:<16} {o.reason[:70]}", file=sys.stderr)

    from collections import Counter
    c = Counter(o.action for o in all_out)
    print(f"# 重验 {len(all_out)}：无变化 {c['unchanged']}，保留(采集不完整) {c['kept']}，"
          f"升级 {c['upgraded']}，降级 {c['downgraded']}，待人工 {c['review']}", file=sys.stderr)

    if args.json:
        args.json.write_text(json.dumps([o.__dict__ for o in all_out], ensure_ascii=False, indent=2),
                             encoding="utf-8")
    # 有降级或待人工 → 非零退出，让 CI 开 Issue
    return 2 if (c["downgraded"] or c["review"]) else 0


if __name__ == "__main__":
    sys.exit(main())

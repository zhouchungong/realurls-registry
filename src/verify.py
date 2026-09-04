"""端到端验证一个域名：采集证据 → 定案 → 打印可复现的报告。

用法::

    python -m src.verify anthropic.com
    python -m src.verify claude.ai --anchor anthropic.com     # 锚点扩散
    python -m src.verify cursor.com --github-org getcursor --json

设计约束：本模块只负责**编排与呈现**，一条判定逻辑都不许写在这里。
判定全部来自 ``policy.decide()``。这样「规则即代码」才成立 ——
否则规则会悄悄散落到编排层，再也审不动。
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from typing import Any

from src.collectors import github, network, npm, rdap, site, thirdparty
from src.collectors.base import Result
from src.policy import Decision, DomainFacts, Evidence, decide, registrable_domain


def _merge(target: Result, *results: Result) -> Result:
    for r in results:
        target.evidence.extend(r.evidence)
        target.facts.update(r.facts)
        target.notes.extend(r.notes)
        for key, value in r.extra.items():
            target.extra.setdefault(key, value)
    return target


def gather(
    domain: str,
    *,
    github_org: str | None = None,
    packages: list[str] | None = None,
    anchor: str | None = None,
    token: str | None = None,
) -> Result:
    """跑完整条采集流水线。顺序有讲究：先 site 拿线索，再让其他采集器用上。"""
    domain = registrable_domain(domain)
    out = Result(facts={"domain": domain})

    hints = site.collect(domain)
    _merge(out, hints)

    org_hints = ([github_org] if github_org else []) + hints.extra.get("github_orgs", [])
    gh = github.collect(domain, hints=org_hints)
    _merge(out, gh)

    pkgs = (packages or []) + hints.extra.get("npm_packages", [])
    _merge(out, npm.collect(domain, packages=pkgs, github_org=out.extra.get("github_org")))

    _merge(out, rdap.collect(domain))
    _merge(out, network.certificate(domain))
    _merge(out, network.self_attestation(domain, expected_token=token))
    _merge(out, thirdparty.wikidata(domain))
    _merge(out, thirdparty.wayback(domain))
    _merge(out, thirdparty.tranco(domain))
    _merge(out, thirdparty.safebrowsing(domain))

    if anchor:
        _merge(out, _propagate_from(anchor, domain))

    return out


def _propagate_from(anchor: str, domain: str) -> Result:
    """A6：从一个已 verified 的锚点域名扩散归属。

    这里只负责**采集**扩散所需的两个前提（源域名状态、结构性关联），
    「够不够格」由 policy.py 的 A6 校验器判断。
    """
    r = Result()
    anchor_decision = decide(*_facts_and_evidence(gather(anchor)))
    links = network.structural_links(anchor, domain)
    _merge(r, links)

    r.evidence.append(Evidence(
        code="A6",
        data={
            "from": anchor,
            "from_status": anchor_decision.status,
            "structural_links": links.extra.get("structural_links", []),
        },
        source=f"propagate from {anchor}",
    ))
    r.note(f"propagate: 锚点 {anchor} 状态={anchor_decision.status}，"
           f"结构性关联={links.extra.get('structural_links') or '无'}")
    return r


def _facts_and_evidence(result: Result) -> tuple[DomainFacts, list[Evidence]]:
    return DomainFacts(**result.facts), result.evidence


def verify(domain: str, **kwargs: Any) -> tuple[Decision, Result]:
    result = gather(domain, **kwargs)
    return decide(*_facts_and_evidence(result)), result


# ------------------------------------------------------------------ 呈现

def _print_report(domain: str, d: Decision, r: Result) -> None:
    mark = {"verified": "✅", "provisional": "🟡", "community": "🔵",
            "flagged": "⛔", "disputed": "⚠️", "review_required": "⚠️",
            "stale": "🕓"}.get(d.status, "❔")

    print(f"\n{mark}  {domain} → {d.status}  (confidence {d.confidence})")
    print("=" * 72)

    print("\n【采集过程】")
    for note in r.notes:
        print(f"  · {note}")

    print("\n【采纳的证据】")
    if not (d.anchors or d.corroborations):
        print("  （无）")
    for ev in r.evidence:
        if ev.code in d.anchors or ev.code in d.corroborations:
            print(f"  [{ev.tier}] {ev.code}  {json.dumps(ev.data, ensure_ascii=False)}")
            if ev.source:
                print(f"         ↳ 复现：{ev.source}")

    if d.rejected:
        print("\n【被拒的证据】")
        for item in d.rejected:
            print(f"  ✗ {item}")

    print("\n【判定理由】")
    for reason in d.reasons:
        print(f"  → {reason}")

    if not d.is_official:
        print("\n  ⓘ 非 verified 状态下，API 不会给出肯定答复（TRUST.md §3）")
    print()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="验证域名归属并打印可复现的证据链")
    p.add_argument("domain")
    p.add_argument("--github-org", help="显式指定 GitHub 组织名（否则自动发现）")
    p.add_argument("--npm", action="append", default=[], help="显式指定 npm 包名，可重复")
    p.add_argument("--anchor", help="从这个已 verified 的域名做锚点扩散")
    p.add_argument("--token", help="校验 A5 自证时的期望 token")
    p.add_argument("--json", action="store_true", help="输出 JSON 而非报告")
    args = p.parse_args(argv)

    d, r = verify(args.domain, github_org=args.github_org, packages=args.npm,
                  anchor=args.anchor, token=args.token)

    if args.json:
        print(json.dumps({
            "domain": registrable_domain(args.domain),
            "decision": asdict(d),
            "evidence": [{"code": e.code, "data": e.data, "source": e.source}
                         for e in r.evidence],
            "notes": r.notes,
        }, ensure_ascii=False, indent=2, default=str))
    else:
        _print_report(registrable_domain(args.domain), d, r)

    return 0 if d.is_official else 1


if __name__ == "__main__":
    sys.exit(main())

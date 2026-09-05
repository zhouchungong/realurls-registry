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

from src.anchor import EntityAnchor, anchor
from src.collectors import appstore, github, network, npm, rdap, site, thirdparty
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
    anchor_domain: str | None = None,
    token: str | None = None,
    canonical_github_org: str | None = None,
    canonical_wikidata: str | None = None,
    canonical_source: str = "human",
    inherited_anchor: EntityAnchor | None = None,
    anchor_result: Result | None = None,
    canonical_names: tuple[str, ...] = (),
) -> Result:
    """跑完整条采集流水线。

    顺序有讲究：**先锚定实体，再采集域名证据**（REVIEW-RESULT §0）。
    锚定结果作为 ``expected_*`` 进入 DomainFacts，A1/A2/B1 只有匹配它才算数。
    """
    domain = registrable_domain(domain)
    out = Result(facts={"domain": domain})

    # 站点首页只提供线索（GitHub 组织名、包名、出站链接），本身不是证据，所以可以先于锚定跑。
    hints = site.collect(domain)
    _merge(out, hints)
    org_candidates = [o for o in (github_org,) if o] + hints.extra.get("github_orgs", [])

    # ---- 阶段 1：实体锚定 ----
    # 扩散场景下，目标域名**继承锚点域名的实体**（claude.ai 属于 Anthropic，不是属于"Claude"这个产品条目）。
    # 锚点域名自己独立锚定，绝不能反过来把目标的锚定塞给它。
    prop: Result | None = None
    if anchor_domain:
        prop = _propagate_from(anchor_domain, domain, anchor_result, hints.extra.get("outbound_domains"))
        ent = prop.extra["entity_anchor"]
    else:
        ent = inherited_anchor or anchor(
            domain, github_org_override=canonical_github_org, wikidata_override=canonical_wikidata,
            github_org_candidates=org_candidates, override_source=canonical_source,
        )
    out.notes.extend(ent.notes)
    out.facts.update(ent.as_facts())
    if canonical_names:   # stored names of an already-anchored entity (revalidation); never self-declared ones
        out.facts["expected_names"] = tuple(dict.fromkeys((*out.facts.get("expected_names", ()), *canonical_names)))
    out.extra["entity_anchor"] = ent

    # ---- 阶段 2：域名证据 ----
    # canonical 组织放在候选最前面；猜测只是搜索启发式，判定由 policy 把关
    org_hints = [o for o in (ent.github_org,) if o] + org_candidates
    _merge(out, github.collect(domain, hints=org_hints))

    # A8：已锚定仓库的 homepage → 本域名 + 首页反链。仓库事实来自锚定阶段（项目史）；
    # 若锚定走的是 Wikidata，也补查一次 canonical 组织的项目史，让 A8 有机会成立。
    if ent.github_org and not anchor_domain:
        repo_info = ent.repo_info or github.repo_history(ent.github_org, out)
        _merge(out, github.collect_repo_link(domain, ent.github_org, repo_info,
                                             hints.extra.get("github_orgs", [])))

    pkgs = (packages or []) + hints.extra.get("npm_packages", [])
    _merge(out, npm.collect(domain, packages=pkgs, github_org=out.extra.get("github_org")))

    # A9: only meaningful for an anchored entity (the validator needs names to match against).
    if out.facts.get("expected_names"):
        _merge(out, appstore.collect(domain, list(out.facts["expected_names"])))

    _merge(out, rdap.collect(domain))
    if out.facts.get("age_days") is not None:
        out.facts["age_source"] = "rdap"
    _merge(out, network.certificate(domain))
    _merge(out, network.self_attestation(domain, expected_token=token))
    _merge(out, thirdparty.wikidata(domain))
    _merge(out, thirdparty.tranco(domain))
    # Wayback always runs: skipping it when Tranco was present cost claude.ai its second corroboration
    # (B1 is rejected on propagated domains). Deciding "enough corroboration already" is policy's job, not ours.
    wb = thirdparty.wayback(domain)
    _merge(out, wb)
    _merge(out, thirdparty.safebrowsing(domain))

    # 域龄兜底：RDAP 对很多 ccTLD 返回 404。一个域名不可能比它的第一次 Wayback 快照更年轻，
    # 所以快照跨度是域龄的**下界**——够用来过 180 天门槛，且不会把新域名误判成老域名。
    if out.facts.get("age_days") is None:
        for e in wb.evidence:
            if e.code == "B4" and e.data.get("history_days"):
                out.facts["age_days"] = int(e.data["history_days"])
                out.facts["age_source"] = "wayback_lower_bound"
                out.note(f"age: RDAP 无域龄，取 Wayback 下界 {e.data['history_days']} 天")
                break

    if prop is not None:
        _merge(out, prop)

    return out


def _propagate_from(anchor_domain: str, domain: str, anchor_result: Result | None = None,
                    candidate_outbound: list[str] | None = None) -> Result:
    """A6：从一个已 verified 的锚点域名扩散归属。

    这里只负责**采集**扩散所需的三个前提（源域名状态、一方声明、结构性关联），
    「够不够格」由 policy.py 的 A6 校验器判断。锚点域名独立完成自己的实体锚定，
    并通过 ``extra["entity_anchor"]`` 交给目标域名继承。
    """
    r = Result()
    # The caller may pass the anchor's freshly gathered result (build_entities tries several siblings of
    # one primary); re-gathering it per sibling costs a full pipeline run each time for identical facts.
    anchor_result = anchor_result or gather(anchor_domain)
    anchor_decision = decide(*_facts_and_evidence(anchor_result))
    r.extra["entity_anchor"] = anchor_result.extra["entity_anchor"]

    # 一方声明：锚点自己的页面是否链接到目标域名。数据来自 site.collect 的出站域名。
    first_party = domain in anchor_result.extra.get("outbound_domains", [])

    links = network.structural_links(anchor_domain, domain)
    _merge(r, links)

    # Backlink: does the candidate's own page link to the anchor? True / False / None (page unfetchable or
    # no outbound links at all, e.g. a JavaScript app or a 403 to our fetcher): "unknown" is not "no".
    backlink = (anchor_domain in candidate_outbound) if candidate_outbound else None

    r.evidence.append(Evidence(
        code="A6",
        data={
            "from": anchor_domain,
            "from_status": anchor_decision.status,
            "first_party_link": first_party,
            "structural_links": links.extra.get("structural_links", []),
            "san_count": links.extra.get("san_count", 0),
            "backlink": backlink,
        },
        source=f"propagate from {anchor_domain}",
    ))
    r.note(f"propagate: 锚点 {anchor_domain} 状态={anchor_decision.status}，"
           f"一方声明={'有' if first_party else '无'}，"
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

    ent = r.extra.get("entity_anchor")
    print("\n【实体锚定】")
    if ent and ent.anchored:
        print(f"  {ent.wikidata or '—'}  {ent.label}  canonical GitHub = {ent.github_org or '未知'}")
        print(f"  依据：{', '.join(ent.sources)}")
    else:
        print("  未锚定 —— 控制权类证据（A1/A2）与 B1 一律不计，最多 provisional")

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
    p.add_argument("--canonical-github-org", help="人工审核过的 canonical GitHub 组织（来源记为 human）")
    p.add_argument("--canonical-wikidata", help="人工审核过的 canonical Wikidata QID")
    p.add_argument("--json", action="store_true", help="输出 JSON 而非报告")
    args = p.parse_args(argv)

    d, r = verify(args.domain, github_org=args.github_org, packages=args.npm,
                  anchor_domain=args.anchor, token=args.token,
                  canonical_github_org=args.canonical_github_org,
                  canonical_wikidata=args.canonical_wikidata)

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

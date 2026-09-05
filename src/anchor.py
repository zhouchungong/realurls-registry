"""实体锚定：在验证任何域名之前，先从**独立权威**确立实体的规范标识符。

为什么需要这一步（REVIEW-RESULT.md §0）
--------------------------------------
A1（GitHub 组织已验证域名）证明的是「某个组织控制这个域名」，不是「这个域名属于 Claude」。
攻击者完全可以为 ``claude-desktop.io`` 建一个叫 "Claude" 的组织并验证它——控制权是真的，身份是假的。

所以流程必须是两阶段：

1. **实体锚定**（本模块）：从 Wikidata 这类**攻击者难以伪造**的权威处，读出实体的 canonical
   GitHub 组织（P2037 / P1324）与 QID。门槛是条目的站点链接数（≥3 种语言的 Wikipedia 有文章）——
   建一个 Wikidata 条目是零成本的，但让三种语言的 Wikipedia 都为你写文章不是。
2. **域名验证**（``policy.py``）：A1/A2 只有在组织 == canonical 时才算数，B1 只有在 QID == canonical 时才算数。

对于在任何独立权威处都不存在的全新实体，锚定失败 → 最多 provisional。
**这是正确的**：一个在 Wikidata、应用商店、npm 都查无此人的"公司"，我们凭什么替它背书。

锚定结果本身也是数据，随实体记录一起落盘（``entities/*.yaml`` 的 ``canonical`` 块），
人类 reviewer 能一眼核对"Anthropic 的 GitHub 是 anthropics"这种事实。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.collectors import thirdparty
from src.collectors.base import Result

MIN_SITELINKS = 3   # 少于 3 种语言的 Wikipedia 收录 → 不足以作为身份权威

_GH_REPO_RE = re.compile(r"github\.com/([A-Za-z0-9-]+)(?:/|$)")


@dataclass
class EntityAnchor:
    github_org: str | None = None
    wikidata: str | None = None
    label: str = ""
    sources: tuple[str, ...] = ()
    notes: list[str] = field(default_factory=list)
    repo_info: dict | None = None      # 项目史锚定命中的仓库事实，供 A8 使用

    @property
    def anchored(self) -> bool:
        return self.github_org is not None or self.wikidata is not None

    def as_facts(self) -> dict:
        """展开成 DomainFacts 的字段。"""
        names = [n for n in (self.label or "").split("/") if n] + ([self.github_org] if self.github_org else [])
        return {
            "expected_github_org": self.github_org,
            "expected_wikidata": self.wikidata,
            "anchor_sources": self.sources,
            "expected_names": tuple(dict.fromkeys(n for n in names if not re.fullmatch(r"Q\d+", n))),
        }


def anchor_from_wikidata(domain: str) -> EntityAnchor:
    """用 Wikidata 锚定：P856 指向本域名、类型受限、站点链接达标的条目。"""
    a = EntityAnchor()
    r: Result = thirdparty.wikidata(domain)
    a.notes.extend(r.notes)

    item = r.extra.get("wikidata_item")
    if not item:
        a.notes.append("anchor: Wikidata 无符合条件的条目，实体未锚定")
        return a

    if item["sitelinks"] < MIN_SITELINKS:
        a.notes.append(
            f"anchor: {item['qid']} 仅 {item['sitelinks']} 个站点链接 < {MIN_SITELINKS}，"
            f"不足以作为身份权威，实体未锚定"
        )
        return a

    a.wikidata = item["qid"]
    a.label = item.get("label", "")
    sources = [f"wikidata:{item['qid']}/P856"]

    gh = item.get("github_username")
    if not gh and item.get("repo"):
        m = _GH_REPO_RE.search(item["repo"])
        gh = m.group(1) if m else None
        if gh:
            sources.append(f"wikidata:{item['qid']}/P1324")
    elif gh:
        sources.append(f"wikidata:{item['qid']}/P2037")

    a.github_org = gh
    a.sources = tuple(sources)
    a.notes.append(
        f"anchor: 实体已锚定 → {item['qid']}（{a.label}），canonical GitHub 组织 = {gh or '未知'}"
    )
    return a


def anchor_from_github_history(org_candidates: list[str], domain: str) -> EntityAnchor:
    """Anchor by GitHub project history: the org owns a non-fork repo ≥3 years old, ≥300 contributors, ≥5k stars.

    Wikidata covers companies, not open-source projects — 138 of 220 surveyed domains had no item at all.
    Project history is another thing an attacker cannot buy: stars can be bought, but a repository that
    started three years ago with 300 distinct contributors cannot.

    The candidate must be *tied to this domain*: its anchored repository's homepage, or the organization's
    blog field, must point at the domain. Without that check, an outbound link on the page was enough —
    supabase.com's homepage links to github.com/langchain-ai, and re-verification anchored Supabase to
    LangChain. A page linking to a famous org must never inherit that org's identity.
    """
    from src.collectors.github import org_blog, repo_history
    from src.policy import registrable_domain

    a = EntityAnchor()
    seen = set()
    for org in org_candidates:
        if not org or org.lower() in seen:
            continue
        seen.add(org.lower())
        info = repo_history(org)
        if not info:
            continue
        tied = registrable_domain(info.get("homepage") or "") == domain or registrable_domain(org_blog(org) or "") == domain
        if not tied:
            a.notes.append(f"anchor: {org} meets the project-history bar but neither {info['repo']}'s homepage "
                           f"nor the org's blog points at {domain}; not tied to this domain, skipped")
            continue
        a.github_org = org
        a.label = info["repo"]
        a.sources = (f"github-history:{info['repo']}"
                     f"(age={info['age_days'] // 365}y,contrib={info['contributors']},stars={info['stars']})",)
        a.notes.append(f"anchor: 项目史锚定 → {info['repo']}（{info['age_days'] // 365} 年，"
                       f"{info['contributors']} 贡献者，{info['stars']} 星），canonical GitHub 组织 = {org}")
        a.repo_info = info
        return a
    a.notes.append("anchor: 候选组织均无满足项目史门槛的仓库")
    return a


def anchor(domain: str, *, github_org_override: str | None = None,
           wikidata_override: str | None = None,
           github_org_candidates: list[str] | None = None,
           override_source: str = "human") -> EntityAnchor:
    """锚定入口：先 Wikidata，失败再试 GitHub 项目史。

    override 用于两种情况：人类审核过的值（``override_source="human"``），
    或每日重验时沿用已落盘的 canonical（``override_source="stored"``）——身份一旦确立就该稳定，
    不能因为 Wikidata 今天被人改了一笔就换掉。
    """
    a = anchor_from_wikidata(domain)
    if not a.github_org and github_org_candidates:
        gh = anchor_from_github_history(github_org_candidates, domain)
        a.notes.extend(gh.notes)
        if gh.github_org:
            # Wikidata 给了 QID 但没给 GitHub（常见：条目存在但无 P2037）→ 用项目史补 canonical 组织
            a.github_org = gh.github_org
            a.label = a.label or gh.label
            a.sources = a.sources + gh.sources
            a.repo_info = gh.repo_info
    if github_org_override:
        if a.github_org and a.github_org.lower() != github_org_override.lower():
            a.notes.append(f"anchor: ⚠ 权威给出的组织 {a.github_org} ≠ 指定值 {github_org_override}，"
                           "以指定值为准但需人工留意")
        a.github_org = github_org_override
        a.sources = a.sources + (f"{override_source}:github_org",)
        a.notes.append(f"anchor: canonical GitHub 组织由 {override_source} 指定为 {github_org_override}")
    if wikidata_override:
        if a.wikidata and a.wikidata != wikidata_override:
            a.notes.append(f"anchor: ⚠ 权威给出的条目 {a.wikidata} ≠ 指定值 {wikidata_override}，需人工留意")
        a.wikidata = wikidata_override
        a.sources = a.sources + (f"{override_source}:wikidata",)
    return a

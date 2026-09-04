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

_GH_REPO_RE = re.compile(r"github\.com/([A-Za-z0-9-]+)/")


@dataclass
class EntityAnchor:
    github_org: str | None = None
    wikidata: str | None = None
    label: str = ""
    sources: tuple[str, ...] = ()
    notes: list[str] = field(default_factory=list)

    @property
    def anchored(self) -> bool:
        return self.github_org is not None or self.wikidata is not None

    def as_facts(self) -> dict:
        """展开成 DomainFacts 的字段。"""
        return {
            "expected_github_org": self.github_org,
            "expected_wikidata": self.wikidata,
            "anchor_sources": self.sources,
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


def anchor(domain: str, *, github_org_override: str | None = None,
           wikidata_override: str | None = None) -> EntityAnchor:
    """锚定入口。override 用于人类审核过的 canonical 值（来源标为 ``human``）。"""
    a = anchor_from_wikidata(domain)
    if github_org_override:
        a.github_org = github_org_override
        a.sources = a.sources + ("human:github_org",)
        a.notes.append(f"anchor: canonical GitHub 组织由人工指定为 {github_org_override}")
    if wikidata_override:
        a.wikidata = wikidata_override
        a.sources = a.sources + ("human:wikidata",)
    return a

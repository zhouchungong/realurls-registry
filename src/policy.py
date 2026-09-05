"""realurls 定案引擎 —— 规则即代码。

这是整个项目唯一的真理来源：任何「某域名是否某组织官网」的判定，
都必须且只能由本模块得出。POLICY.md 是它的人类可读镜像，两者若有冲突，**以本文件为准**。

设计原则
--------
1. **precision > recall**：宁可返回 ``unverified``，绝不返回错的 ``verified``。
   项目的全部价值建立在「我们说 verified 就一定对」上。
2. **纯函数、零 IO**：不做任何网络请求。证据由 ``src/collectors/`` 采集后传入。
   这样才能离线重放、做回归测试、让第三方复现我们的每一条判定。
3. **可解释**：每个判定都带 ``reasons``，任何人能看懂我们为什么这么判。
4. **证据独立性**：相关联的证据只算一次。三条互相推导出来的证据不等于三条独立证据。
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

__all__ = [
    "Evidence",
    "DomainFacts",
    "Decision",
    "decide",
    "registrable_domain",
    "ANCHOR_CODES",
    "CORROBORATION_CODES",
]

# --------------------------------------------------------------------------------------
# 常量
# --------------------------------------------------------------------------------------

#: 锚点证据（Tier A）。至少需要 1 条有效锚点才可能达到 verified。
#:
#: 一个容易漏掉的区分：**控制权 ≠ 身份**。A1/A2/A5 证明的都是「某个主体控制这个域名」，
#: 而不是「这个域名属于实体 X」。攻击者完全可以为自己的域名建组织、做验证。
#: 所以 A1/A2/B1 必须与**预先锚定的实体身份**（``DomainFacts.expected_*``）匹配才算数，
#: 实体锚定由 ``src/anchor.py`` 从独立权威（Wikidata 等）确立。
ANCHOR_CODES: dict[str, str] = {
    "A1": "GitHub organization verified this domain (is_verified=true, blog matches, org == entity canonical)",
    "A2": "Package provenance → GitHub repository → verified organization (chain end == entity canonical)",
    "A3": "Corporate registration fingerprint (brand-protection registrar + long prepaid term + registry locks + domain age)",
    "A4": "TLS certificate Subject O= matches (OV/EV certificate)",
    "A5": "DNS TXT self-attestation (_realurls.<domain>)",
    "A6": "Propagation: first-party link from a verified domain + structural link",
    "A7": "Restricted TLD: registry only allows government bodies (.gov / .gov.cn / .gouv.fr …)",
    "A8": "Anchored repository homepage points here, and this site links back to the repository",
}

#: A8 的 homepage 不得指向这些平台域——yt-dlp 的 homepage 字段填的就是 discord.gg，
#: 不排除会把 discord.gg 绑给 yt-dlp。平台域永远不是某个项目的官网。
PLATFORM_DOMAINS: frozenset[str] = frozenset({
    "discord.gg", "discord.com", "x.com", "twitter.com", "t.me", "telegram.org", "youtube.com",
    "github.com", "github.io", "gitlab.com", "gitlab.io", "bitbucket.org", "readthedocs.io",
    "readthedocs.org", "gitbook.io", "notion.site", "notion.so", "medium.com", "substack.com",
    "linkedin.com", "facebook.com", "reddit.com", "npmjs.com", "pypi.org", "crates.io",
    "huggingface.co", "vercel.app", "netlify.app", "pages.dev", "web.app", "herokuapp.com",
    "google.com", "docs.google.com", "sites.google.com", "wordpress.com", "blogspot.com",
})

#: 「GitHub 项目史」锚定权威的门槛（src/anchor.py 使用，放这里是因为它们也是信任承诺的一部分）。
#: 星可以买；3 年前就开始、300 个不同的人来提交，买不到；把别人的历史 push 进新仓库，created_at 会暴露。
REPO_ANCHOR_MIN_AGE_DAYS = 3 * 365
REPO_ANCHOR_MIN_CONTRIBUTORS = 300
REPO_ANCHOR_MIN_STARS = 5000

#: 受限 TLD：后缀本身就是锚点。只证明「是政府站」，不证明「是哪个部门」。
RESTRICTED_GOV_SUFFIXES: frozenset[str] = frozenset({
    "gov", "mil", "gov.uk", "gov.cn", "gouv.fr", "go.jp", "gov.au", "gc.ca", "gov.br",
    "gov.in", "gov.sg", "gov.hk", "gov.tw", "gov.kr", "gov.it", "gov.za", "govt.nz",
    "gov.ie", "gob.es", "gob.mx", "gov.pl", "gov.se", "admin.ch", "gov.nl", "gov.be",
})

#: 佐证证据（Tier B）。verified 需要 >= 2 条独立佐证。
CORROBORATION_CODES: dict[str, str] = {
    "B1": "Wikidata official website (P856) on the canonical item",
    "B2": "Package registry homepage / repository field",
    "B3": "App-store developer website field",
    "B4": "Wayback Machine first snapshot + continuity",
    "B5": "Tranco / Cloudflare Radar ranking",
    "B6": "Official social profile links here",
    "B7": "Google Safe Browsing: no record",
}

#: 互相关联的锚点，同组内最多计 1 条。
#: A1 / A2 / A8 都落在「同一个 GitHub 组织」这个信任锚上——组织被接管三者一起失效，因此不独立。
CORRELATED_ANCHOR_GROUPS: list[frozenset[str]] = [frozenset({"A1", "A2", "A8"})]

#: 某锚点存在时，被其蕴含的佐证不再单独计数（避免同一事实被数两次）。
IMPLIED_CORROBORATIONS: dict[str, set[str]] = {
    "A2": {"B2"},  # provenance 已经比 homepage 字段强，homepage 不再额外加分
}

#: 品牌保护类注册商。年费数百美元起 + 企业实名，黑产用不起 —— 这是成本壁垒，不是身份证明。
#:
#: 评审时剔除了几家混进来的零售/批发注册商：Amazon Registrar（Route53，任何人 12 美元/年）、
#: Google LLC（原 Google Domains 零售）、InterNetX / Ascio（批发商，大量转售给个人）。
#: 它们在名单里时 A3 比 POLICY.md 声称的弱得多。
CORPORATE_REGISTRARS: frozenset[str] = frozenset(
    {
        "markmonitor",
        "cscglobal",
        "csc corporate domains",
        "com laude",
        "comlaude",
        "safenames",
        "brandsight",
        "nom-iq",
        "ipmirror",
        "ip mirror",
        "gandi corporate",
        "godaddy corporate domains",
        "101domain corporate",
        "lexsynergy",
    }
)

#: 置信度权重 = 「单看这一条证据，判定正确的概率」。近似独立，用 1 - Π(1-w) 合成。
#:
#: 锚点之间差异很大，不能给同一档：
#:   A5 最强 —— 只有域名控制者能写那条 TXT。
#:   A1/A2 次之 —— GitHub 已经代做了 DNS 级域名验证，且有 sigstore 链。
#:   A3 最弱 —— 企业注册指纹只证明「买得起」，是成本壁垒而非身份证明。
WEIGHTS: dict[str, float] = {
    "A5": 0.90, "A1": 0.80, "A7": 0.80, "A2": 0.75, "A4": 0.70, "A6": 0.65, "A8": 0.60, "A3": 0.55,
    "B1": 0.12, "B2": 0.08, "B3": 0.10, "B4": 0.12, "B5": 0.06, "B6": 0.10, "B7": 0.05,
}

# 阈值 —— 改动这里等于改动项目的信任承诺，必须同步改 POLICY.md 并走 CODEOWNERS 双人审批。
MIN_AGE_DAYS_FOR_VERIFIED = 180       # 新域名硬门槛（有 A5 自证可豁免）
A3_MIN_AGE_DAYS = 730                 # 企业注册指纹要求的最小域龄
A3_MIN_REMAINING_DAYS = 1095          # 到期日距今 >= 3 年（长期预付是企业行为）
A3_MIN_LOCKS = 2                      # 注册局锁数量
B4_MIN_HISTORY_DAYS = 365             # Wayback 连续性最小跨度
B5_MAX_RANK = 1_000_000               # Tranco 排名门槛
VT_MALICIOUS_THRESHOLD = 2            # VirusTotal 引擎判恶意数

PROVISIONAL_DISPLAY_DAYS = 21         # provisional 公示期

# --------------------------------------------------------------------------------------
# 数据结构
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Evidence:
    """一条证据。``data`` 里放该证据类型自己的字段，由对应校验器解释。"""

    code: str
    data: dict[str, Any] = field(default_factory=dict)
    checked_at: datetime | None = None
    source: str | None = None

    @property
    def tier(self) -> str:
        if self.code in ANCHOR_CODES:
            return "A"
        if self.code in CORROBORATION_CODES:
            return "B"
        return "?"


@dataclass(frozen=True)
class DomainFacts:
    """与证据无关的域名事实与外部信号。"""

    domain: str
    age_days: int | None = None
    age_source: str | None = None           # rdap | wayback_lower_bound | None
    # ---- 实体锚定（由 src/anchor.py 从独立权威确立；None = 未锚定）----
    expected_github_org: str | None = None
    expected_wikidata: str | None = None
    anchor_sources: tuple[str, ...] = ()    # 锚定依据，如 ("wikidata:Q116758847/P2037",)
    expected_names: tuple[str, ...] = ()    # names the anchored entity is known by (label, GitHub org); A4 must match one
    # ---- 外部信号 ----
    gsb_flagged: bool = False
    vt_malicious: int = 0
    has_conflict: bool = False          # 与另一个已 verified 实体的断言冲突
    mutation_detected: bool = False     # NS / A / 注册商 / 到期日 / GitHub 组织状态突变
    previous_status: str | None = None
    last_verified: datetime | None = None
    ttl_days: int = 30
    # 某个采集器「没采到」（超时/网络错）而非「采到了是否定」。当前不参与定案，但必须记录：
    # 每日重验时，采集失败不该直接把 verified 打成降级（deezer.com 的教训）。
    collection_incomplete: bool = False


@dataclass(frozen=True)
class Decision:
    status: str
    confidence: float
    reasons: list[str]
    anchors: list[str]
    corroborations: list[str]
    rejected: list[str]                 # 被判定为无效的证据及原因

    @property
    def is_official(self) -> bool:
        """对外 API 只有这一个状态会给出肯定答复。"""
        return self.status == "verified"


# --------------------------------------------------------------------------------------
# 工具
# --------------------------------------------------------------------------------------

#: 常见多段后缀。真实实现应接入 Public Suffix List；此处覆盖测试与主流场景。
_MULTI_PART_SUFFIXES = frozenset(
    {"co.uk", "org.uk", "ac.uk", "co.jp", "com.cn", "net.cn", "org.cn",
     "com.au", "com.br", "co.in", "com.hk", "com.tw", "co.kr",
     # 平台后缀：把 x.pages.dev 折成 pages.dev 是安全方向（永远不会把平台验证成某品牌）
     "github.io", "pages.dev", "vercel.app", "netlify.app", "web.app", "herokuapp.com"}
    | {s for s in ("gov.uk", "gov.cn", "gouv.fr", "go.jp", "gov.au", "gc.ca", "gov.br", "gov.in",
                   "gov.sg", "gov.hk", "gov.tw", "gov.kr", "gov.it", "gov.za", "govt.nz", "gov.ie",
                   "gob.es", "gob.mx", "gov.pl", "gov.se", "admin.ch", "gov.nl", "gov.be")}
)


def registrable_domain(host: str) -> str:
    """取可注册域（近似 eTLD+1）。用于「blog 域名是否等于目标域名」这类比较。"""
    host = (host or "").strip().lower().rstrip(".")
    for prefix in ("https://", "http://"):
        if host.startswith(prefix):
            host = host[len(prefix):]
    host = host.split("/")[0].split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    parts = host.split(".")
    if len(parts) <= 2:
        return host
    if ".".join(parts[-2:]) in _MULTI_PART_SUFFIXES:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def _same_site(a: str, b: str) -> bool:
    return bool(a) and bool(b) and registrable_domain(a) == registrable_domain(b)


def _combine(weights: list[float]) -> float:
    """独立证据的置信度合成：1 - Π(1 - w)。"""
    remaining = 1.0
    for w in weights:
        remaining *= 1.0 - max(0.0, min(0.99, w))
    return round(1.0 - remaining, 4)


# --------------------------------------------------------------------------------------
# 证据校验器：每条证据必须自证有效，光有 code 不算数
# --------------------------------------------------------------------------------------

Validator = Callable[[Evidence, DomainFacts], "tuple[bool, str]"]
_VALIDATORS: dict[str, Validator] = {}


def _validator(code: str) -> Callable[[Validator], Validator]:
    def wrap(fn: Validator) -> Validator:
        _VALIDATORS[code] = fn
        return fn
    return wrap


def _require_anchored_org(org: str, facts: DomainFacts) -> str:
    """A1/A2 共用：组织必须等于实体的 canonical GitHub 组织。

    没有这一步，攻击者为自己的域名建组织、做验证，就能拿到一条「锚点」——
    因为 GitHub 验证证明的只是控制权。返回空串表示通过。
    """
    if not facts.expected_github_org:
        return "entity not anchored: no canonical GitHub organization from an independent authority; proof of control is not proof of ownership"
    if (org or "").lower() != facts.expected_github_org.lower():
        return (f"organization {org} != entity canonical organization {facts.expected_github_org}"
                f" (anchored by {', '.join(facts.anchor_sources) or 'nothing'})")
    return ""


@_validator("A1")
def _v_a1(ev: Evidence, facts: DomainFacts) -> tuple[bool, str]:
    if not ev.data.get("org_verified"):
        return False, "GitHub organization has not verified this domain (is_verified != true)"
    blog = ev.data.get("blog", "")
    if not _same_site(blog, facts.domain):
        return False, f"GitHub organization blog ({blog}) is not the same registrable domain"
    if why := _require_anchored_org(ev.data.get("org", ""), facts):
        return False, why
    return True, ""


@_validator("A2")
def _v_a2(ev: Evidence, facts: DomainFacts) -> tuple[bool, str]:
    if not ev.data.get("provenance_verified"):
        return False, "package has no verifiable provenance"
    if not ev.data.get("chain_org_verified"):
        return False, "GitHub organization at the end of the provenance chain has not verified this domain"
    blog = ev.data.get("chain_blog", "")
    if not _same_site(blog, facts.domain):
        return False, f"provenance chain ends at {blog}, which does not match this domain"
    if why := _require_anchored_org(ev.data.get("chain_org", ""), facts):
        return False, why
    return True, ""


@_validator("A3")
def _v_a3(ev: Evidence, facts: DomainFacts) -> tuple[bool, str]:
    registrar = str(ev.data.get("registrar", "")).lower()
    if not any(known in registrar for known in CORPORATE_REGISTRARS):
        return False, f"registrar ({ev.data.get('registrar')}) is not a brand-protection registrar"
    if int(ev.data.get("remaining_days", 0)) < A3_MIN_REMAINING_DAYS:
        return False, f"fewer than {A3_MIN_REMAINING_DAYS} days until expiry; not the long prepaid term typical of corporate registrations"
    if len(ev.data.get("locks", [])) < A3_MIN_LOCKS:
        return False, f"fewer than {A3_MIN_LOCKS} registry locks"
    if (facts.age_days or 0) < A3_MIN_AGE_DAYS:
        return False, f"domain younger than {A3_MIN_AGE_DAYS} days"
    return True, ""


_LEGAL_SUFFIXES = {"inc", "llc", "ltd", "limited", "co", "corp", "corporation", "company", "gmbh", "ag", "sa", "sas",
                   "srl", "bv", "nv", "plc", "pty", "pte", "oy", "ab", "as", "aps", "kk", "pbc", "lp", "llp", "the"}


def _name_key(name: str) -> str:
    """Normalise an organisation name for matching: case, punctuation and legal-form suffixes removed."""
    words = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", str(name or "").lower()).split()
    return "".join(w for w in words if w not in _LEGAL_SUFFIXES)


def _names_match(subject_org: str, names: tuple[str, ...]) -> bool:
    key = _name_key(subject_org)
    if len(key) < 3:
        return False
    for n in names:
        k = _name_key(n)
        if len(k) >= 3 and (k in key or key in k):
            return True
    return False


@_validator("A4")
def _v_a4(ev: Evidence, facts: DomainFacts) -> tuple[bool, str]:
    """An OV/EV certificate proves that the organisation in O= controls the domain. It anchors the domain to
    *this entity* only if that organisation is the entity. instagram.com's certificate (O=Meta Platforms) is a
    perfect OV certificate and proved nothing about OpenShift, whose homepage merely linked to Instagram."""
    if ev.data.get("validation_type") not in {"OV", "EV"}:
        return False, "DV certificate carries no organization name (most modern tech companies use DV; this is expected)"
    org = str(ev.data.get("subject_org", "")).strip()
    if not org:
        return False, "certificate Subject has no O= field"
    if not facts.expected_names:
        return False, "entity not anchored: certificate organization cannot be tied to an identity; proof of control is not proof of ownership"
    if not _names_match(org, facts.expected_names):
        return False, f"certificate organization ({org}) is not the anchored entity ({', '.join(facts.expected_names)})"
    return True, ""


@_validator("A5")
def _v_a5(ev: Evidence, facts: DomainFacts) -> tuple[bool, str]:
    if not ev.data.get("token_match"):
        return False, "_realurls TXT record missing or token mismatch"
    return True, ""


MAX_SAN_FOR_PROPAGATION = 25  # 超过此数的证书多半是 CDN 共享证书，SAN 共现不再说明同一所有者


@_validator("A6")
def _v_a6(ev: Evidence, facts: DomainFacts) -> tuple[bool, str]:
    """锚点扩散 = 一方声明（必需）+ 结构性关联（至少一条）。

    两者缺一不可，原因各不相同：
    * 只有结构性关联：Cloudflare 等从共享池分配 NS，攻击者反复建账号能碰到同一对；
    * 只有一方声明：已 verified 域名的页脚里也有 linkedin.com / x.com，那不是自家资产。
    攻击者要同时做到「让 anthropic.com 首页链接到我」和「NS 碰撞」，前者做不到。
    """
    if ev.data.get("from_status") != "verified":
        return False, f"propagation source {ev.data.get('from')} is not itself verified, so it cannot anchor"
    if not ev.data.get("first_party_link"):
        return False, f"anchor {ev.data.get('from')} does not link to this domain; no first-party declaration"
    links = set(ev.data.get("structural_links", []))
    if not links & {"shared_ns", "cert_san", "shared_registrar"}:
        return False, "no structural link (need at least one of shared_ns / cert_san / shared_registrar)"
    if links == {"cert_san"} and int(ev.data.get("san_count", 0)) > MAX_SAN_FOR_PROPAGATION:
        return False, f"certificate has {ev.data.get('san_count')} SANs > {MAX_SAN_FOR_PROPAGATION}; looks like a shared CDN certificate"
    # A verified site links to plenty of third parties, and name-server pairs come from shared pools; a
    # third party that has its own outbound links and none of them point back at the anchor is not a
    # sibling. Unknown (page unfetchable, no links at all) is not treated as "no".
    if ev.data.get("backlink") is False:
        return False, f"this site links out but never to {ev.data.get('from')}; a sibling domain links back to its anchor"
    return True, ""


@_validator("A7")
def _v_a7(ev: Evidence, facts: DomainFacts) -> tuple[bool, str]:
    d = facts.domain.lower().rstrip(".")
    if not any(d == s or d.endswith(f".{s}") for s in RESTRICTED_GOV_SUFFIXES):
        return False, f"{d} is not under a restricted government TLD"
    return True, ""


@_validator("A8")
def _v_a8(ev: Evidence, facts: DomainFacts) -> tuple[bool, str]:
    """已锚定仓库的 homepage → 本域名，且本域名首页反向链回仓库。

    比 A1 弱（没有 DNS 级证明），所以权重 0.60。但对「GitHub 组织没做域名验证」的开源项目，
    这是唯一能把域名绑到已锚定身份上的证据。攻击者要伪造它，得控制一个已锚定的仓库——做不到。
    """
    if not ev.data.get("repo_anchored"):
        return False, f"repository {ev.data.get('repo')} does not meet the project-history anchor (non-fork, ≥3 years, ≥300 contributors, ≥5k stars)"
    if why := _require_anchored_org(ev.data.get("org", ""), facts):
        return False, why
    if registrable_domain(facts.domain) in PLATFORM_DOMAINS:
        return False, f"{facts.domain} is a platform domain and cannot be a project's own site"
    if not _same_site(ev.data.get("homepage", ""), facts.domain):
        return False, f"repository homepage ({ev.data.get('homepage')}) does not point to this domain"
    if not ev.data.get("backlink"):
        return False, "this site does not link back to the GitHub organization; no reverse confirmation"
    return True, ""


@_validator("B1")
def _v_b1(ev: Evidence, facts: DomainFacts) -> tuple[bool, str]:
    """Wikidata 条目必须就是实体锚定时确立的那一个。任何人都能建一个条目指向任何域名。"""
    if not facts.expected_wikidata:
        return False, "entity not anchored: no canonical Wikidata item, so an arbitrary item's P856 cannot corroborate"
    qid = ev.data.get("qid", "")
    if qid != facts.expected_wikidata:
        return False, f"item {qid} != entity canonical item {facts.expected_wikidata}"
    return True, ""


@_validator("B4")
def _v_b4(ev: Evidence, facts: DomainFacts) -> tuple[bool, str]:
    if int(ev.data.get("history_days", 0)) < B4_MIN_HISTORY_DAYS:
        return False, f"Wayback history shorter than {B4_MIN_HISTORY_DAYS} days"
    return True, ""


@_validator("B5")
def _v_b5(ev: Evidence, facts: DomainFacts) -> tuple[bool, str]:
    rank = ev.data.get("rank")
    if rank is None or int(rank) > B5_MAX_RANK:
        return False, f"domain not in the top {B5_MAX_RANK}"
    return True, ""


@_validator("B7")
def _v_b7(ev: Evidence, facts: DomainFacts) -> tuple[bool, str]:
    if ev.data.get("flagged"):
        return False, "Safe Browsing has a record; cannot count as positive corroboration"
    return True, ""


def _validate(ev: Evidence, facts: DomainFacts) -> tuple[bool, str]:
    if ev.code not in ANCHOR_CODES and ev.code not in CORROBORATION_CODES:
        return False, f"unknown evidence code {ev.code}"
    validator = _VALIDATORS.get(ev.code)
    if validator is None:
        return True, ""  # 无额外约束的佐证（B1/B2/B3/B6）：存在即计数
    return validator(ev, facts)


# --------------------------------------------------------------------------------------
# 定案
# --------------------------------------------------------------------------------------


def _collapse_anchors(codes: set[str]) -> set[str]:
    """同组关联锚点只保留权重最高的一条。"""
    kept = set(codes)
    for group in CORRELATED_ANCHOR_GROUPS:
        present = kept & group
        if len(present) > 1:
            best = max(present, key=lambda c: WEIGHTS.get(c, 0.0))
            kept -= present - {best}
    return kept


def decide(
    facts: DomainFacts,
    evidence: list[Evidence],
    now: datetime | None = None,
) -> Decision:
    """对单个域名做归属判定。

    返回的 ``status`` 取值：

    ``verified``        证据充分，对外给出肯定答复。
    ``provisional``     有锚点但佐证不足，公示 21 天等待异议。
    ``community``       仅有佐证，无锚点。
    ``unverified``      证据不足 / 未达门槛。API 返回「不知道」。
    ``stale``           曾经 verified 但超过 TTL 未重验，**自动失效**。
    ``review_required`` 关键属性突变（可能被抢注或劫持），暂停肯定答复。
    ``disputed``        与另一条 verified 断言冲突，需人工裁决。
    ``flagged``         被安全情报标记，永不 verified。
    """
    now = now or datetime.now(UTC)
    reasons: list[str] = []
    rejected: list[str] = []

    # ---- 阶段 1：硬性否决。任何证据都无法推翻 ----
    if facts.gsb_flagged or facts.vt_malicious >= VT_MALICIOUS_THRESHOLD:
        return Decision(
            "flagged", 0.0,
            [f"flagged by security intelligence (gsb={facts.gsb_flagged}, vt={facts.vt_malicious}); "
             f"ownership judgement stopped — defer to Google Safe Browsing / VirusTotal for safety"],
            [], [], [],
        )

    if facts.has_conflict:
        return Decision("disputed", 0.0, ["conflicts with another verified ownership claim; needs human adjudication"], [], [], [])

    if facts.mutation_detected:
        return Decision(
            "review_required", 0.0,
            ["key attributes changed (NS / A records / registrar / expiry / GitHub org status); "
             "positive answers suspended until a human reviews"],
            [], [], [],
        )

    # ---- 阶段 2：数据保鲜。过期的 verified 自动降级 ----
    if facts.previous_status == "verified" and facts.last_verified is not None:
        if now - facts.last_verified > timedelta(days=facts.ttl_days):
            return Decision(
                "stale", 0.0,
                [f"last re-verified {facts.last_verified.date()}, past the {facts.ttl_days}-day TTL; "
                 f"expired automatically until the pipeline re-collects evidence"],
                [], [], [],
            )

    # ---- 阶段 3：证据校验 ----
    valid_anchor_codes: set[str] = set()
    valid_corrob_codes: set[str] = set()
    for ev in evidence:
        ok, why = _validate(ev, facts)
        if not ok:
            rejected.append(f"{ev.code}: {why}")
            continue
        (valid_anchor_codes if ev.tier == "A" else valid_corrob_codes).add(ev.code)

    anchors = _collapse_anchors(valid_anchor_codes)
    if anchors != valid_anchor_codes:
        dropped = sorted(valid_anchor_codes - anchors)
        reasons.append(f"correlated anchors merged: {'/'.join(dropped)} not independent of the kept one, counted once")

    for anchor in anchors:
        implied = IMPLIED_CORROBORATIONS.get(anchor, set()) & valid_corrob_codes
        if implied:
            valid_corrob_codes -= implied
            reasons.append(f"{anchor} already implies {'/'.join(sorted(implied))}; corroboration not double-counted")

    # ---- 阶段 4：新域名门槛（未知域龄 fail-closed）----
    young = facts.age_days is not None and facts.age_days < MIN_AGE_DAYS_FOR_VERIFIED
    if young and "A5" not in anchors:
        return Decision(
            "unverified",
            0.0,
            [f"domain age {facts.age_days} days < {MIN_AGE_DAYS_FOR_VERIFIED}-day hard floor; "
             f"new domains are only accepted with A5 (DNS TXT self-attestation)"] + reasons,
            sorted(anchors), sorted(valid_corrob_codes), rejected,
        )
    # rdap.org 对 .de/.io/.cn/.so/.ch/.jp 等大量 ccTLD 返回 404。「查不到」不等于「够老」，
    # 在 precision 优先的系统里未知必须 fail-closed：最多 provisional，且 A5/A7 除外。
    age_unknown = facts.age_days is None and not (anchors & {"A5", "A7"})
    if age_unknown:
        reasons.append("domain age unknown (no RDAP and no Wayback lower bound); cannot reach verified — unknown is treated as worst case")

    # ---- 阶段 5：定案 ----
    n_anchor, n_corrob = len(anchors), len(valid_corrob_codes)
    confidence = _combine([WEIGHTS[c] for c in anchors | valid_corrob_codes])

    if n_anchor >= 1 and n_corrob >= 2 and not age_unknown:
        status = "verified"
        reasons.append(f"{n_anchor} independent anchor(s) + {n_corrob} independent corroboration(s): meets the verified threshold")
    elif n_anchor >= 1 and n_corrob >= 2 and age_unknown:
        status = "provisional"
        confidence = min(confidence, 0.75)
        reasons.append("evidence meets the threshold, but domain age is unknown; held at provisional")
    elif n_anchor >= 1:
        status = "provisional"
        confidence = min(confidence, 0.75)
        reasons.append(f"anchor present but only {n_corrob} corroboration(s) (need 2); in the {PROVISIONAL_DISPLAY_DAYS}-day public review window")
    elif n_corrob >= 3:
        status = "community"
        confidence = min(confidence, 0.50)
        reasons.append(f"no anchor, only {n_corrob} corroboration(s); community level, the API gives no positive answer")
    else:
        status = "unverified"
        confidence = min(confidence, 0.30)
        reasons.append(f"insufficient evidence (anchors {n_anchor}, corroborations {n_corrob})")

    return Decision(status, confidence, reasons, sorted(anchors), sorted(valid_corrob_codes), rejected)

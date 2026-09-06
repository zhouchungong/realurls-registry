"""佐证采集：B1 Wikidata / B4 Wayback / B5 Tranco / B7 Safe Browsing。

这些都不能单独证明控制权，只能说明「多个独立权威处把这个域名当作该实体的官网」。
所以它们权重都很低，且 verified 要求至少两条**互相独立**的佐证。
"""

from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from datetime import UTC, datetime

from src.collectors.base import USER_AGENT, FetchError, Result, cache_get, cache_put, fetch, fetch_json, now
from src.policy import Evidence

SPARQL = "https://query.wikidata.org/sparql"
CDX = "http://web.archive.org/cdx/search/cdx"
TRANCO = "https://tranco-list.eu/api/ranks/domain/{}"
GSB = "https://safebrowsing.googleapis.com/v4/threatMatches:find?key={}"


# ------------------------------------------------------------------ B1 Wikidata

def _p856_variants(domain: str) -> list[str]:
    return [f"{scheme}://{host}{tail}"
            for scheme in ("https", "http") for host in (domain, f"www.{domain}") for tail in ("", "/")]


def _p856_query(domains: list[str]) -> str:
    """Which typed Wikidata items declare one of these domains as official website (P856)?

    ``VALUES`` over the URL variants is an **index lookup**. An earlier ``FILTER(CONTAINS(...))`` scanned
    every P856 (millions) and timed out every time. Path-bearing P856 values are missed, acceptable: the
    canonical P856 is the site root.

    Entity type must be constrained. claude.ai's P856 once carried a junk item titled like a Chinese
    newspaper headline (Q116755258): Wikidata is editable by anyone, and adding a P856 that points at a
    phishing domain costs nothing. Without the type filter B1 would be a corroboration anyone can forge
    (SECURITY.md T7). P2037 = GitHub username, P1324 = source repository; both feed entity anchoring.
    """
    variants = " ".join(f"<{u}>" for d in domains for u in _p856_variants(d))
    return f"""
    SELECT ?item ?itemLabel ?site ?sitelinks ?github ?repo ?isOrg
           (GROUP_CONCAT(DISTINCT ?class; separator=" ") AS ?classes)
           (GROUP_CONCAT(DISTINCT ?p31; separator=" ") AS ?types) WHERE {{
      VALUES ?site {{ {variants} }}
      ?item wdt:P856 ?site .
      ?item wdt:P31/wdt:P279* ?class .
      VALUES ?class {{ wd:Q43229 wd:Q4830453 wd:Q7397 wd:Q35127 wd:Q1058914 }}
      ?item wdt:P31 ?p31 .
      BIND(EXISTS {{ ?item wdt:P31/wdt:P279* wd:Q43229 }} AS ?isOrg)
      OPTIONAL {{ ?item wikibase:sitelinks ?sitelinks }}
      OPTIONAL {{ ?item wdt:P2037 ?github }}
      OPTIONAL {{ ?item wdt:P1324 ?repo }}
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,zh". }}
    }} GROUP BY ?item ?itemLabel ?site ?sitelinks ?github ?repo ?isOrg ORDER BY DESC(?sitelinks)
    """


#: What kind of thing the item is. "organization" is an entity in its own right; "software" and "website"
#: are things an organization makes. The policy uses this to refuse propagating into a domain that belongs
#: to another organization (courant.com is the Hartford Courant's, not the Chicago Tribune's). Wikidata's
#: subclass chains are not to be trusted for this (a newspaper reaches "software" through P279*), so
#: organization-ness is ``P31/P279* organization`` plus a short list of media outlets that Wikidata models
#: as works rather than organizations.
_MEDIA_OUTLET_TYPES = {
    "Q11032", "Q1110794", "Q41298", "Q1002697", "Q737498", "Q5633421",   # newspaper, daily, magazine, periodical, journals
    "Q1616075", "Q14350", "Q15265344", "Q18127", "Q2085381",            # TV station, radio station, broadcaster, label, publisher
}


def _item_kind(binding: dict) -> str:
    classes = {c.rsplit("/", 1)[-1] for c in str(binding.get("classes", {}).get("value", "")).split()}
    types = {c.rsplit("/", 1)[-1] for c in str(binding.get("types", {}).get("value", "")).split()}
    if not classes:
        return "unknown"        # cached from before this field existed
    if str(binding.get("isOrg", {}).get("value", "")).lower() == "true" or types & _MEDIA_OUTLET_TYPES:
        return "organization"
    return "software" if "Q7397" in classes else "website"


def _site_domain(site: str) -> str:
    host = urllib.parse.urlsplit(site).hostname or ""
    return host[4:] if host.startswith("www.") else host


def _run_sparql(query: str) -> list[dict]:
    url = f"{SPARQL}?query={urllib.parse.quote(query)}&format=json"
    doc = fetch_json(url, headers={"Accept": "application/sparql-results+json"}, ttl_hours=168, timeout=60)
    return doc.get("results", {}).get("bindings", [])


WIKIDATA_BATCH = 40
_WD_KEY = "wikidata:p856:{}"


def prefetch_wikidata(domains: list[str]) -> int:
    """Bulk-resolve P856 for many domains in one SPARQL call per 40 domains, priming the per-domain cache.

    One query per domain is the scaling bottleneck (40k seeds = 40k SPARQL calls under the public
    endpoint's rate limit). Batching cuts that 40x with identical results: the per-domain path and this
    one run the same query text, so ``wikidata()`` cannot tell which filled its cache.
    """
    todo = [d for d in dict.fromkeys(domains) if cache_get(_WD_KEY.format(d), 168) is None]
    fetched = 0
    for i in range(0, len(todo), WIKIDATA_BATCH):
        chunk = todo[i:i + WIKIDATA_BATCH]
        try:
            rows = _run_sparql(_p856_query(chunk))
        except FetchError:
            continue   # per-domain lookup will retry these later
        by_domain: dict[str, list[dict]] = {d: [] for d in chunk}
        for b in rows:
            d = _site_domain(b.get("site", {}).get("value", ""))
            if d in by_domain:
                by_domain[d].append(b)
        for d, bs in by_domain.items():
            cache_put(_WD_KEY.format(d), bs[:5])
        fetched += len(chunk)
    return fetched


def _p856_bindings(domain: str) -> list[dict]:
    cached = cache_get(_WD_KEY.format(domain), 168)
    if cached is not None:
        return cached
    rows = _run_sparql(_p856_query([domain]))[:5]
    cache_put(_WD_KEY.format(domain), rows)
    return rows


def english_label(qid: str, sparql_label: str = "") -> str:
    """The item's English label, "" if it has none. The SPARQL label service is not trusted for this: in the
    first full-category batch it handed back Arabic, Korean and Tamil labels for WordPress, Docker, Vim…
    (whatever language happened to come first), and ``names.en`` must be English. A Latin-script SPARQL
    label is kept only when the entity API is unreachable."""
    try:
        ent = fetch_json(
            f"https://www.wikidata.org/w/api.php?action=wbgetentities&ids={qid}&props=labels&languages=en|en-gb|mul&format=json",
            ttl_hours=168,
        )
        labels = ent.get("entities", {}).get(qid, {}).get("labels", {})
        pick = labels.get("en") or labels.get("en-gb") or labels.get("mul") or {}
        return str(pick.get("value", "")).strip()
    except FetchError:
        latin = re.search(r"[A-Za-z]", sparql_label) and not re.search(r"[^\x00-\x7f\u00c0-\u024f]", sparql_label)
        if sparql_label and sparql_label != qid and latin:
            return sparql_label
        return ""


_FLAGS_KEY = "wikidata:flags2:{}"
_CLAIMS_KEY = "wikidata:p31p279:{}"
_FLAG_NAMES = ("isOrg", "isGov", "isEdu", "isGame", "isMedia", "isSoftwareCo", "isSoftware")
#: Root classes each flag stands for (matched through the P279 subclass chain, depth-limited).
_FLAG_ROOTS = {
    "isOrg": {"Q43229"},
    "isGov": {"Q327333", "Q2659904"},
    "isEdu": {"Q2385804", "Q31855"},
    "isGame": {"Q210167", "Q1137109", "Q7889"},
    "isMedia": {"Q11032", "Q15265344", "Q1002697"},
    "isSoftwareCo": {"Q1058914"},
}
#: Types that count only when they are the item's *direct* P31 (their subclass trees are too wide to trust:
#: Wikidata makes a newspaper a kind of software).
_DIRECT_ONLY = {
    "isMedia": {"Q1193236", "Q2085381", "Q1616075", "Q14350", "Q41298"},
    "isSoftware": {"Q7397", "Q341", "Q1130645", "Q7889", "Q9135", "Q271680", "Q188860", "Q1668024", "Q131093"},
}
_MAX_DEPTH = 8


def _claims(qids: list[str]) -> dict[str, dict[str, list[str]]]:
    """P31 and P279 targets per item, from the entity API (50 per call, cached 30 days). The query service was
    tried first: a dozen P279* EXISTS per item time out in batches and get rate-limited one by one."""
    out: dict[str, dict[str, list[str]]] = {}
    todo = []
    for q in dict.fromkeys(q for q in qids if q):
        cached = cache_get(_CLAIMS_KEY.format(q), 24 * 30)
        if cached is not None:
            out[q] = cached
        else:
            todo.append(q)
    for i in range(0, len(todo), 50):
        chunk = todo[i:i + 50]
        try:
            doc = fetch_json(f"https://www.wikidata.org/w/api.php?action=wbgetentities&ids={'|'.join(chunk)}"
                             f"&props=claims&format=json", ttl_hours=24 * 30)
        except FetchError:
            continue
        for q, ent in doc.get("entities", {}).items():
            claims = ent.get("claims", {})
            rec = {p: [c["mainsnak"]["datavalue"]["value"]["id"] for c in claims.get(p, [])
                       if c.get("mainsnak", {}).get("datavalue", {}).get("value", {}).get("id")]
                   for p in ("P31", "P279")}
            cache_put(_CLAIMS_KEY.format(q), rec)
            out[q] = rec
    return out


def _superclasses(classes: list[str]) -> set[str]:
    """Transitive P279 closure of the given classes, depth-limited, fetched in breadth-first batches."""
    seen: set[str] = set(classes)
    frontier = list(classes)
    for _ in range(_MAX_DEPTH):
        if not frontier:
            break
        claims = _claims(frontier)
        nxt = []
        for c in frontier:
            for parent in claims.get(c, {}).get("P279", []):
                if parent not in seen:
                    seen.add(parent)
                    nxt.append(parent)
        frontier = nxt
    return seen


def item_flags(qids: list[str]) -> dict[str, dict[str, bool]]:
    """What kind of thing each item is: organization / government body / educational institution / game studio
    or publisher / media outlet / software company / software. Used for categories and for choosing between a
    Wikidata label and a GitHub display name; never as evidence. Unknown items (API failed) are absent."""
    out: dict[str, dict[str, bool]] = {}
    todo = []
    for q in dict.fromkeys(q for q in qids if q):
        cached = cache_get(_FLAGS_KEY.format(q), 24 * 30)
        if cached is not None:
            out[q] = cached
        else:
            todo.append(q)
    if not todo:
        return out
    claims = _claims(todo)
    for q in todo:
        if q not in claims:
            continue
        direct = set(claims[q].get("P31", []))
        closure = _superclasses(sorted(direct))
        flags = {name: bool(closure & roots) for name, roots in _FLAG_ROOTS.items()}
        for name, types in _DIRECT_ONLY.items():
            flags[name] = flags.get(name, False) or bool(direct & types)
        cache_put(_FLAGS_KEY.format(q), flags)
        out[q] = flags
    return out


def wikidata(domain: str) -> Result:
    """Reverse lookup: which Wikidata item declares this domain as its official website (P856)."""
    r = Result()
    try:
        bindings = _p856_bindings(domain)
    except FetchError as exc:
        r.note(f"wikidata: 查询失败：{exc}")
        return r

    if not bindings:
        r.note("wikidata: 没有「组织 / 软件 / 网站」类实体把本域名声明为 P856")
        return r

    # Several items may claim the same site: a game and its studio (Doodle Jump / Lima Sky), an app and its
    # holding company (Bumble / Bumble Holding). The organization is the owner; a product page is not an
    # identity. So an organization-kind item wins over a product/website item, then sitelinks decide.
    bindings = sorted(bindings, key=lambda b: (0 if _item_kind(b) == "organization" else 1,
                                               -int(b.get("sitelinks", {}).get("value", 0))))
    top = bindings[0]
    qid = top["item"]["value"].rsplit("/", 1)[-1]
    label = english_label(qid, top.get("itemLabel", {}).get("value", ""))
    sitelinks = int(top.get("sitelinks", {}).get("value", 0))
    r.extra["wikidata"] = qid
    r.extra["wikidata_item"] = {
        "qid": qid, "label": label, "sitelinks": sitelinks,
        "github_username": top.get("github", {}).get("value"),
        "repo": top.get("repo", {}).get("value"),
    }
    r.evidence.append(Evidence(
        code="B1",
        data={"qid": qid, "label": label, "kind": _item_kind(top), "site": top["site"]["value"],
              "sitelinks": sitelinks, "competing_items": len(bindings) - 1},
        checked_at=now(),
        source=f"https://www.wikidata.org/wiki/{qid}",
    ))
    r.note(f"wikidata: {qid}（{label}）的 P856 指向本域名，{sitelinks} 个站点链接 ✓")
    if len(bindings) > 1:
        others = ", ".join(b["item"]["value"].rsplit("/", 1)[-1] for b in bindings[1:])
        r.note(f"wikidata: 另有 {len(bindings) - 1} 个实体也声明本域名（{others}）—— 需人工留意")
    return r


# ------------------------------------------------------------------ B4 Wayback

def wayback(domain: str) -> Result:
    """首次快照距今多久 —— 用来证明「这个域名长期以同一身份存在」。"""
    r = Result()
    url = (f"{CDX}?url={urllib.parse.quote(domain)}&output=json"
           f"&fl=timestamp&filter=statuscode:200&limit=1")
    try:
        rows = json.loads(fetch(url, ttl_hours=168))
    except (FetchError, json.JSONDecodeError) as exc:
        r.note(f"wayback: 查询失败：{exc}")
        return r

    if len(rows) < 2:
        r.note("wayback: 无历史快照（新站或从未被归档）")
        return r

    stamp = rows[1][0]
    first = datetime.strptime(stamp[:8], "%Y%m%d").replace(tzinfo=UTC)
    days = (now() - first).days
    r.evidence.append(Evidence(
        code="B4",
        data={"first_snapshot": first.date().isoformat(), "history_days": days},
        checked_at=now(),
        source=url,
    ))
    r.note(f"wayback: 首次快照 {first.date()}，跨度 {days} 天")
    return r


# ------------------------------------------------------------------ B5 Tranco

TRANCO_LIST = "https://tranco-list.eu/download/daily/top-1m.csv.zip"
_tranco_index: dict[str, int] | None = None
_tranco_lock = __import__("threading").Lock()


def _tranco_local() -> dict[str, int] | None:
    """The whole top-1M list, downloaded once a week into .cache. One file instead of one API call per domain."""
    global _tranco_index
    if _tranco_index is not None:
        return _tranco_index
    with _tranco_lock:
        if _tranco_index is not None:
            return _tranco_index
        return _tranco_local_locked()


def _tranco_local_locked() -> dict[str, int] | None:
    global _tranco_index
    import io
    import time
    import urllib.request
    import zipfile

    from src.collectors.base import CACHE_DIR, USER_AGENT
    path = CACHE_DIR / "tranco-top-1m.csv.zip"
    try:
        if not path.exists() or time.time() - path.stat().st_mtime > 7 * 86400:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            req = urllib.request.Request(TRANCO_LIST, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=120) as resp:
                path.write_bytes(resp.read())
        with zipfile.ZipFile(io.BytesIO(path.read_bytes())) as zf:
            name = next(n for n in zf.namelist() if n.endswith(".csv"))
            text = zf.read(name).decode("utf-8", errors="replace")
        idx: dict[str, int] = {}
        for line in text.splitlines():
            rank, _, dom = line.partition(",")
            if dom:
                idx[dom.strip().lower()] = int(rank)
        _tranco_index = idx
    except Exception:
        _tranco_index = {}   # fall back to the per-domain API below
    return _tranco_index


def tranco(domain: str) -> Result:
    r = Result()
    local = _tranco_local()
    if local:
        rank = local.get(domain)
        if rank is None:
            r.note("tranco: 域名不在榜单内（流量太小或太新）")
            return r
        r.evidence.append(Evidence(code="B5", data={"rank": rank, "source": "top-1m list"}, checked_at=now(),
                                   source=TRANCO_LIST))
        r.note(f"tranco: 排名 {rank}（本地榜单）")
        return r

    try:
        doc = fetch_json(TRANCO.format(domain), ttl_hours=168)
    except FetchError as exc:
        r.note(f"tranco: 查询失败：{exc}")
        return r

    ranks = doc.get("ranks") or []
    latest = next((x for x in ranks if x.get("rank")), None)
    if not latest:
        r.note("tranco: 域名不在榜单内（流量太小或太新）")
        return r

    r.evidence.append(Evidence(
        code="B5",
        data={"rank": latest["rank"], "date": latest.get("date")},
        checked_at=now(),
        source=TRANCO.format(domain),
    ))
    r.note(f"tranco: 排名 {latest['rank']}（{latest.get('date')}）")
    return r


# ------------------------------------------------- B7 / 硬性否决 Safe Browsing

def safebrowsing(domain: str) -> Result:
    """查 Google Safe Browsing。**即时查询，查完即弃，不落地成表**（TRUST.md §6）。"""
    r = Result()
    key = os.environ.get("GSB_API_KEY")
    if not key:
        r.note("gsb: 未设置 GSB_API_KEY，跳过（B7 与 flagged 否决均不生效）")
        return r

    body = json.dumps({
        "client": {"clientId": "realurls-registry", "clientVersion": "0.0.1"},
        "threatInfo": {
            "threatTypes": ["MALWARE", "SOCIAL_ENGINEERING", "UNWANTED_SOFTWARE"],
            "platformTypes": ["ANY_PLATFORM"],
            "threatEntryTypes": ["URL"],
            "threatEntries": [{"url": f"http://{domain}/"}, {"url": f"https://{domain}/"}],
        },
    }).encode()

    req = urllib.request.Request(
        GSB.format(key), data=body,
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            doc = json.loads(resp.read().decode())
    except Exception as exc:
        r.note(f"gsb: 查询失败：{type(exc).__name__}: {exc}")
        return r

    flagged = bool(doc.get("matches"))
    r.facts["gsb_flagged"] = flagged
    r.evidence.append(Evidence(
        code="B7", data={"flagged": flagged}, checked_at=now(), source="Google Safe Browsing v4",
    ))
    r.note(f"gsb: {'已被标记 —— 触发硬性否决' if flagged else '无记录'}")
    return r

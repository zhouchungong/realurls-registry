"""佐证采集：B1 Wikidata / B4 Wayback / B5 Tranco / B7 Safe Browsing。

这些都不能单独证明控制权，只能说明「多个独立权威处把这个域名当作该实体的官网」。
所以它们权重都很低，且 verified 要求至少两条**互相独立**的佐证。
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from src.collectors.base import USER_AGENT, FetchError, Result, fetch, fetch_json, now
from src.policy import Evidence

SPARQL = "https://query.wikidata.org/sparql"
CDX = "http://web.archive.org/cdx/search/cdx"
TRANCO = "https://tranco-list.eu/api/ranks/domain/{}"
GSB = "https://safebrowsing.googleapis.com/v4/threatMatches:find?key={}"


# ------------------------------------------------------------------ B1 Wikidata

def wikidata(domain: str) -> Result:
    """反查：哪个 Wikidata 实体把这个域名声明为 official website（P856）。

    用 ``VALUES`` 枚举常见 URL 变体做**索引查找**。早先用 ``FILTER(CONTAINS(...))``
    会全表扫描 P856（数百万条）并稳定超时 —— 那种写法在这里是不可用的。
    代价是漏掉带路径的写法，可接受：P856 的规范写法就是站点根 URL。
    """
    r = Result()
    variants = " ".join(
        f"<{scheme}://{host}{tail}>"
        for scheme in ("https", "http")
        for host in (domain, f"www.{domain}")
        for tail in ("", "/")
    )
    # 必须限定实体类型。实测 claude.ai 的 P856 上挂着一个标题是中文报纸标题的垃圾条目
    # （Q116755258）—— Wikidata 任何人可编辑，往某条目加一条 P856 指向钓鱼域名的成本为零。
    # 不做类型过滤的话，B1 就是一条可被任意人凭空制造的「佐证」。这是 SECURITY.md T7。
    # P2037 = GitHub 用户名，P1324 = 源码仓库。二者是实体锚定（src/anchor.py）的 canonical 来源。
    query = f"""
    SELECT ?item ?itemLabel ?site ?sitelinks ?github ?repo WHERE {{
      VALUES ?site {{ {variants} }}
      ?item wdt:P856 ?site .
      FILTER EXISTS {{
        ?item wdt:P31/wdt:P279* ?class .
        VALUES ?class {{ wd:Q43229 wd:Q4830453 wd:Q7397 wd:Q35127 wd:Q1058914 }}
      }}
      OPTIONAL {{ ?item wikibase:sitelinks ?sitelinks }}
      OPTIONAL {{ ?item wdt:P2037 ?github }}
      OPTIONAL {{ ?item wdt:P1324 ?repo }}
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,zh". }}
    }} ORDER BY DESC(?sitelinks) LIMIT 5
    """
    url = f"{SPARQL}?query={urllib.parse.quote(query)}&format=json"
    try:
        doc = fetch_json(url, headers={"Accept": "application/sparql-results+json"},
                         ttl_hours=168, timeout=45)
    except FetchError as exc:
        r.note(f"wikidata: 查询失败：{exc}")
        return r

    bindings = doc.get("results", {}).get("bindings", [])
    if not bindings:
        r.note("wikidata: 没有「组织 / 软件 / 网站」类实体把本域名声明为 P856")
        return r

    top = bindings[0]
    qid = top["item"]["value"].rsplit("/", 1)[-1]
    label = top.get("itemLabel", {}).get("value", "")
    sitelinks = int(top.get("sitelinks", {}).get("value", 0))
    r.extra["wikidata"] = qid
    r.extra["wikidata_item"] = {
        "qid": qid, "label": label, "sitelinks": sitelinks,
        "github_username": top.get("github", {}).get("value"),
        "repo": top.get("repo", {}).get("value"),
    }
    r.evidence.append(Evidence(
        code="B1",
        data={"qid": qid, "label": label, "site": top["site"]["value"],
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
    first = datetime.strptime(stamp[:8], "%Y%m%d").replace(tzinfo=timezone.utc)
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

def tranco(domain: str) -> Result:
    r = Result()
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

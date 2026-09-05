"""Generate candidate seeds: organisations with an official domain worth verifying.

Seeds are **candidates, not data**. Every one goes through the full pipeline; the domain comes from a
self-declared field (GitHub ``websiteUrl``, Wikidata P856) and policy will reject it unless independent
evidence supports it. A wrong candidate costs one pipeline run and nothing else.

Sources
-------
``github``   every non-fork repository above a star floor, in star bands small enough to fit the search
             API's 1,000-result window, via GraphQL: 100 repositories per call **with the owner's website
             already included**, so no per-organisation lookup is needed. ~64k repositories at ≥1,000 stars.
``wikidata`` software companies (Q1058914 and subclasses) with an official website, paged in bulk.
``topics``   the original cold-start mode: GitHub topic searches for AI / developer tools.

Output goes to ``seeds/<prefix>-NN.jsonl`` in batches; domains already in ``entities/`` or in an
existing seed file are skipped, so re-running only adds what is new.

Usage::

    python -m src.seeds --source github --min-stars 1000 --out-dir seeds --prefix gh
    python -m src.seeds --source wikidata --out-dir seeds --prefix wd
    python -m src.seeds --source topics --min-stars 3000 --limit 250 > .cache/seeds.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
from pathlib import Path

import yaml

from src.collectors.base import FetchError, cache_get, cache_put, fetch_json, post_json
from src.collectors.github import API, GRAPHQL, _headers, _token
from src.policy import registrable_domain

ROOT = Path(__file__).resolve().parents[1]
ENTITIES = ROOT / "entities"

#: Cold-start topics (AI / developer tools).
TOPICS = [
    "ai", "llm", "machine-learning", "deep-learning", "artificial-intelligence",
    "developer-tools", "devtools", "cli", "ide", "code-editor",
    "agents", "rag", "vector-database", "mlops", "inference",
]

#: Hosts that are not product organisations: personal accounts, foundations aggregating many projects, mirrors.
SKIP_OWNERS = {"microsoft", "google", "apple", "facebook", "amazon", "aws", "alibaba", "tencent"}
SKIP_DOMAINS = {"github.com", "github.io", "gitlab.com", "readthedocs.io", "pages.dev", "vercel.app",
                "netlify.app", "herokuapp.com", "npmjs.com", "pypi.org", "medium.com", "substack.com",
                "notion.site", "linktr.ee", "twitter.com", "x.com", "youtube.com", "discord.gg", "discord.com"}


def _ok_domain(blog: str) -> str:
    domain = registrable_domain(blog) if blog else ""
    if not domain or "." not in domain or domain in SKIP_DOMAINS:
        return ""
    return domain


# ------------------------------------------------------------------ source: github (star bands, GraphQL)

SEARCH_WINDOW = 1000   # GitHub search returns at most 1,000 results per query

_SEARCH_Q = """
query($q: String!, $after: String) {
  rateLimit { remaining resetAt }
  search(type: REPOSITORY, query: $q, first: 100, after: $after) {
    repositoryCount
    pageInfo { hasNextPage endCursor }
    nodes { ... on Repository {
      nameWithOwner stargazerCount isArchived
      owner { __typename login ... on Organization { websiteUrl isVerified name } }
      repositoryTopics(first: 8) { nodes { topic { name } } }
    } }
  }
}"""


def _gql(query: str, variables: dict) -> dict:
    if not _token():
        raise FetchError("GITHUB_TOKEN (or gh login) required for seed generation")
    doc = post_json(GRAPHQL, {"query": query, "variables": variables}, headers=_headers())
    if doc.get("errors") and not doc.get("data"):
        raise FetchError(f"graphql: {doc['errors'][0].get('message', '?')}")
    return doc["data"]


def _band_count(lo: int, hi: int) -> int:
    key = f"github:search-count:{lo}..{hi}"
    cached = cache_get(key, 168)
    if cached is not None:
        return cached
    n = _gql(_SEARCH_Q.replace("first: 100", "first: 1"), {"q": f"stars:{lo}..{hi} fork:false"})["search"]["repositoryCount"]
    cache_put(key, n)
    return n


def _bands(lo: int, hi: int) -> list[tuple[int, int]]:
    """Split [lo, hi] into star bands with ≤1,000 repositories each (a band of width 1 is never split further)."""
    n = _band_count(lo, hi)
    if n <= SEARCH_WINDOW or lo == hi:
        if n > SEARCH_WINDOW:
            print(f"# band {lo}..{hi} has {n} repos, only the first {SEARCH_WINDOW} are reachable", file=sys.stderr)
        return [(lo, hi)]
    mid = (lo + hi) // 2
    return _bands(lo, mid) + _bands(mid + 1, hi)


def _band_repos(lo: int, hi: int) -> list[dict]:
    key = f"github:search-band:{lo}..{hi}"
    cached = cache_get(key, 168)
    if cached is not None:
        return cached
    out, after = [], None
    while True:
        data = _gql(_SEARCH_Q, {"q": f"stars:{lo}..{hi} fork:false", "after": after})
        s = data["search"]
        out.extend(s["nodes"])
        if not s["pageInfo"]["hasNextPage"]:
            break
        after = s["pageInfo"]["endCursor"]
        if data["rateLimit"]["remaining"] < 50:
            print("# graphql: near rate limit, sleeping 60s", file=sys.stderr)
            time.sleep(60)
        time.sleep(0.5)
    cache_put(key, out)
    return out


def github_seeds(min_stars: int, max_stars: int = 1_000_000) -> list[dict]:
    bands = _bands(min_stars, max_stars)
    print(f"# github: {len(bands)} star bands for stars:{min_stars}..{max_stars}", file=sys.stderr)
    orgs: dict[str, dict] = {}
    for i, (lo, hi) in enumerate(bands, 1):
        repos = _band_repos(lo, hi)
        for repo in repos:
            owner = repo.get("owner") or {}
            login = owner.get("login", "")
            if owner.get("__typename") != "Organization" or login.lower() in SKIP_OWNERS or repo.get("isArchived"):
                continue
            domain = _ok_domain(owner.get("websiteUrl") or "")
            if not domain:
                continue
            rec = orgs.setdefault(login, {
                "domain": domain, "github_org": login, "org_name": owner.get("name") or login,
                "org_verified": bool(owner.get("isVerified")), "stars": 0, "topics": set(),
                "sample_repo": repo["nameWithOwner"], "source": "github",
            })
            if repo["stargazerCount"] > rec["stars"]:
                rec["stars"], rec["sample_repo"] = repo["stargazerCount"], repo["nameWithOwner"]
            rec["topics"].update(t["topic"]["name"] for t in repo["repositoryTopics"]["nodes"])
        print(f"# github: band {i}/{len(bands)} stars:{lo}..{hi} → {len(repos)} repos, {len(orgs)} orgs so far",
              file=sys.stderr)
    out = sorted(orgs.values(), key=lambda r: -r["stars"])
    for r in out:
        r["topics"] = sorted(r["topics"])
    return out


# ------------------------------------------------------------------ source: wikidata (software companies)

SPARQL = "https://query.wikidata.org/sparql"
WD_PAGE = 2000

_WD_Q = """
SELECT ?item ?itemLabel ?site ?github ?sitelinks WHERE {
  ?item wdt:P31/wdt:P279* wd:Q1058914 ; wdt:P856 ?site .
  OPTIONAL { ?item wdt:P2037 ?github }
  OPTIONAL { ?item wikibase:sitelinks ?sitelinks }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
} ORDER BY ?item LIMIT %d OFFSET %d
"""


def wikidata_seeds() -> list[dict]:
    out: list[dict] = []
    offset = 0
    while True:
        url = f"{SPARQL}?format=json&query={urllib.parse.quote(_WD_Q % (WD_PAGE, offset))}"
        try:
            doc = fetch_json(url, headers={"Accept": "application/sparql-results+json"}, ttl_hours=168, timeout=120)
        except FetchError as exc:
            print(f"# wikidata: page at offset {offset} failed: {exc}", file=sys.stderr)
            break
        rows = doc.get("results", {}).get("bindings", [])
        for b in rows:
            domain = _ok_domain(b["site"]["value"])
            if not domain:
                continue
            qid = b["item"]["value"].rsplit("/", 1)[-1]
            label = b.get("itemLabel", {}).get("value", "")
            out.append({
                "domain": domain, "github_org": b.get("github", {}).get("value"),
                "org_name": "" if label == qid else label, "wikidata": qid,
                "sitelinks": int(b.get("sitelinks", {}).get("value", 0)),
                "topics": ["saas"], "source": "wikidata",
            })
        print(f"# wikidata: offset {offset} → {len(rows)} rows", file=sys.stderr)
        if len(rows) < WD_PAGE:
            break
        offset += WD_PAGE
        time.sleep(2)
    return sorted(out, key=lambda r: -r["sitelinks"])


# ------------------------------------------------------------------ source: topics (cold start)

def _search(topic: str, min_stars: int, page: int) -> list[dict]:
    q = urllib.parse.quote(f"topic:{topic} stars:>={min_stars}")
    url = f"{API}/search/repositories?q={q}&sort=stars&order=desc&per_page=100&page={page}"
    try:
        return fetch_json(url, headers=_headers(), ttl_hours=168).get("items", [])
    except FetchError as exc:
        print(f"# search {topic} p{page}: {exc}", file=sys.stderr)
        return []


def collect_seeds(min_stars: int, limit: int, pages: int = 2) -> list[dict]:
    seen_orgs: dict[str, dict] = {}
    for topic in TOPICS:
        for page in range(1, pages + 1):
            for repo in _search(topic, min_stars, page):
                owner = repo.get("owner") or {}
                login = owner.get("login", "")
                if owner.get("type") != "Organization" or login.lower() in SKIP_OWNERS:
                    continue
                rec = seen_orgs.setdefault(login, {"org": login, "stars": 0, "repos": [], "topics": set()})
                rec["stars"] = max(rec["stars"], repo.get("stargazers_count", 0))
                rec["repos"].append(repo["full_name"])
                rec["topics"].add(topic)
            time.sleep(0.5)  # the search API has its own 30/min limit

    out = []
    for login, rec in sorted(seen_orgs.items(), key=lambda kv: -kv[1]["stars"]):
        if len(out) >= limit:
            break
        try:
            org = fetch_json(f"{API}/orgs/{login}", headers=_headers(), ttl_hours=168)
        except FetchError as exc:
            print(f"# org {login}: {exc}", file=sys.stderr)
            continue
        domain = _ok_domain(org.get("blog") or "")
        if not domain:
            continue
        out.append({
            "domain": domain, "github_org": login, "org_name": org.get("name") or login,
            "org_verified": bool(org.get("is_verified")), "stars": rec["stars"],
            "topics": sorted(rec["topics"]), "sample_repo": rec["repos"][0], "source": "topics",
        })
    return out


# ------------------------------------------------------------------ output

def known_domains(out_dir: Path | None) -> set[str]:
    """Domains already in entities/ or in an existing seed file: never emitted twice."""
    known: set[str] = set()
    for p in ENTITIES.glob("*/*.yaml"):
        ent = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        known.update(d["domain"] for d in ent.get("domains", []))
    if out_dir and out_dir.exists():
        for p in out_dir.glob("*.jsonl"):
            for line in p.read_text(encoding="utf-8").splitlines():
                if line.strip() and not line.startswith("#"):
                    known.add(json.loads(line)["domain"])
    return known


def write_batches(seeds: list[dict], out_dir: Path, prefix: str, batch_size: int) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    existing = sorted(out_dir.glob(f"{prefix}-*.jsonl"))
    start = len(existing) + 1
    paths = []
    for i in range(0, len(seeds), batch_size):
        path = out_dir / f"{prefix}-{start + i // batch_size:02d}.jsonl"
        path.write_text("".join(json.dumps(s, ensure_ascii=False) + "\n" for s in seeds[i:i + batch_size]),
                        encoding="utf-8")
        paths.append(path)
    return paths


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--source", choices=["github", "wikidata", "topics"], default="topics")
    p.add_argument("--min-stars", type=int, default=3000)
    p.add_argument("--max-stars", type=int, default=1_000_000)
    p.add_argument("--limit", type=int, default=250, help="topics source only")
    p.add_argument("--pages", type=int, default=2, help="topics source only")
    p.add_argument("--out-dir", type=Path, help="write seeds/<prefix>-NN.jsonl batches instead of stdout")
    p.add_argument("--prefix", default="seeds")
    p.add_argument("--batch-size", type=int, default=2500)
    args = p.parse_args(argv)

    if args.source == "github":
        seeds = github_seeds(args.min_stars, args.max_stars)
    elif args.source == "wikidata":
        seeds = wikidata_seeds()
    else:
        seeds = collect_seeds(args.min_stars, args.limit, args.pages)

    known = known_domains(args.out_dir)
    fresh, seen = [], set()
    for s in seeds:
        if s["domain"] in known or s["domain"] in seen:
            continue
        seen.add(s["domain"])
        fresh.append(s)
    print(f"# {len(seeds)} candidates, {len(fresh)} new (skipped {len(seeds) - len(fresh)} already known)", file=sys.stderr)

    if args.out_dir:
        for path in write_batches(fresh, args.out_dir, args.prefix, args.batch_size):
            print(f"# wrote {path}", file=sys.stderr)
    else:
        for s in fresh:
            print(json.dumps(s, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

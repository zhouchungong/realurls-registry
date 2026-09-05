"""生成冷启动种子：从 GitHub 高星仓库反推组织与官网域名。

为什么从 GitHub 而不是 Wikidata 出发
------------------------------------
M2 第一步是**覆盖率摸底**——想知道流水线对"人们真正会问的 AI / 开发工具"能验证多少。
如果种子取自 Wikidata（已有 P856/P2037 的条目），锚定率会被人为抬高，摸底就失真了。
GitHub star 数是一个与"是否被 Wikidata 收录"无关的流行度信号，偏差更小。

产出的是**候选**，不是数据。每条都要过完整流水线，域名来自组织的 ``blog`` 字段，
policy 会用 A1 校验它——猜错的候选会被拒掉，不会污染结果。

用法::

    python -m src.seeds --min-stars 3000 --limit 250 > .cache/seeds.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse

from src.collectors.base import FetchError, fetch_json
from src.collectors.github import API, _headers
from src.policy import registrable_domain

#: 首发品类的 GitHub topic。宁可多抓再过滤，也不要漏。
TOPICS = [
    "ai", "llm", "machine-learning", "deep-learning", "artificial-intelligence",
    "developer-tools", "devtools", "cli", "ide", "code-editor",
    "agents", "rag", "vector-database", "mlops", "inference",
]

#: 不是产品组织的宿主：个人账号、基金会聚合、镜像
SKIP_OWNERS = {"microsoft", "google", "apple", "facebook", "amazon", "aws", "alibaba", "tencent"}


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
            time.sleep(0.5)  # search API 有独立的 30 次/分钟限制

    out = []
    for login, rec in sorted(seen_orgs.items(), key=lambda kv: -kv[1]["stars"]):
        if len(out) >= limit:
            break
        try:
            org = fetch_json(f"{API}/orgs/{login}", headers=_headers(), ttl_hours=168)
        except FetchError as exc:
            print(f"# org {login}: {exc}", file=sys.stderr)
            continue
        blog = org.get("blog") or ""
        domain = registrable_domain(blog) if blog else ""
        if not domain or "." not in domain or domain in {"github.com", "github.io"}:
            continue
        out.append({
            "domain": domain,
            "github_org": login,
            "org_name": org.get("name") or login,
            "org_verified": bool(org.get("is_verified")),
            "stars": rec["stars"],
            "topics": sorted(rec["topics"]),
            "sample_repo": rec["repos"][0],
        })
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--min-stars", type=int, default=3000)
    p.add_argument("--limit", type=int, default=250)
    p.add_argument("--pages", type=int, default=2)
    args = p.parse_args(argv)
    seeds = collect_seeds(args.min_stars, args.limit, args.pages)
    for s in seeds:
        print(json.dumps(s, ensure_ascii=False))
    print(f"# {len(seeds)} seeds", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

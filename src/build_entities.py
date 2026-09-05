"""由流水线生成 ``entities/``——这是该目录**唯一合法的写入路径**（SECURITY.md §1）。

输入：一份种子（域名 + GitHub 组织线索）。
过程：对每个域名重新跑 ``verify()``（有 HTTP 缓存，很快），只有判定为 ``verified`` 的才落盘。
输出：``entities/<category>/<slug>.yaml``，含完整证据（含被拒证据及原因）、实体锚定与出处。

几条刻意的选择
--------------
* **实体标签取自锚定来源**（Wikidata 标签或仓库名），不取自 GitHub 组织自填的 ``name``——
  那是攻击者能随便填的字段。组织自填的名字只进 ``aliases``。
* **一个域名只能归一个实体**。摸底里 tencent.com 从两个组织各命中一次，取第一次，
  第二次记 note 跳过；真冲突（两个不同实体都 verified 同一域名）应由 policy 判 disputed，不该到这里。
* **落盘的是本次运行的事实快照**（``last_verified``、``age_days``、每条证据的 ``checked_at``），
  每日重验会覆盖它；``first_seen`` 若已存在则保留。

用法::

    python -m src.build_entities .cache/seeds.jsonl --only-verified
    python -m src.build_entities .cache/seeds.jsonl --domains n8n.io,ollama.com
    python -m src.build_entities seeds/batch-01.jsonl --shard 3/16    # one of 16 parallel CI runners
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml

from src.verify import verify

ROOT = Path(__file__).resolve().parents[1]
ENTITIES = ROOT / "entities"
PIPELINE_VERSION = "build_entities/0.2"
MAX_PROPAGATE = 8   # outbound domains tried per verified primary

CATEGORIES = {"ai", "developer-tools", "saas", "security", "infrastructure", "open-source", "hardware", "finance", "government", "other"}

#: GitHub topic → schema category. Unmapped topics fall back to ``open-source`` for GitHub-sourced seeds
#: (the organisation is known to us through a repository) and ``saas`` for Wikidata software companies.
TOPIC_CATEGORY = {
    "ai": "ai", "llm": "ai", "machine-learning": "ai", "deep-learning": "ai", "artificial-intelligence": "ai",
    "agents": "ai", "rag": "ai", "inference": "ai", "nlp": "ai", "computer-vision": "ai", "llmops": "ai",
    "generative-ai": "ai", "chatgpt": "ai", "openai": "ai", "transformers": "ai", "pytorch": "ai", "tensorflow": "ai",
    "vector-database": "infrastructure", "mlops": "infrastructure", "database": "infrastructure", "kubernetes": "infrastructure",
    "docker": "infrastructure", "cloud": "infrastructure", "devops": "infrastructure", "monitoring": "infrastructure",
    "observability": "infrastructure", "serverless": "infrastructure", "cdn": "infrastructure", "networking": "infrastructure",
    "sql": "infrastructure", "postgresql": "infrastructure", "redis": "infrastructure", "kafka": "infrastructure",
    "storage": "infrastructure", "backend": "infrastructure", "api": "infrastructure",
    "developer-tools": "developer-tools", "devtools": "developer-tools", "cli": "developer-tools", "ide": "developer-tools",
    "code-editor": "developer-tools", "testing": "developer-tools", "ci": "developer-tools", "compiler": "developer-tools",
    "programming-language": "developer-tools", "framework": "developer-tools", "sdk": "developer-tools",
    "build-tool": "developer-tools", "package-manager": "developer-tools", "linter": "developer-tools",
    "security": "security", "cybersecurity": "security", "pentesting": "security", "authentication": "security",
    "encryption": "security", "vulnerability": "security", "privacy": "security", "password-manager": "security",
    "saas": "saas", "crm": "saas", "analytics": "saas", "productivity": "saas", "note-taking": "saas", "cms": "saas",
    "ecommerce": "saas", "collaboration": "saas", "project-management": "saas", "low-code": "saas", "no-code": "saas",
    "hardware": "hardware", "iot": "hardware", "embedded": "hardware", "robotics": "hardware", "firmware": "hardware",
    "3d-printing": "hardware", "raspberry-pi": "hardware", "arduino": "hardware",
    "fintech": "finance", "payments": "finance", "blockchain": "finance", "cryptocurrency": "finance", "trading": "finance",
}


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s or "unnamed"


def _categories(topics: list[str], source: str | None = None) -> list[str]:
    cats = []
    for t in topics:
        c = TOPIC_CATEGORY.get(t) or (t if t in CATEGORIES else None)   # a category name is its own topic
        if c and c not in cats:
            cats.append(c)
    if cats:
        return cats
    if source == "wikidata":
        return ["saas"]
    if source == "github":
        return ["open-source"]
    return ["developer-tools"] if source in (None, "topics") else ["other"]   # cold-start topic seeds only


def _iso(dt: datetime | None) -> str:
    return (dt or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_one(seed: dict, now: datetime) -> tuple[dict | None, str]:
    domain = seed["domain"]
    # seed 里带 anchor → 走锚点扩散（A6）：目标域名继承锚点域名的实体，role 由 seed 指定（默认 product）
    decision, result = verify(domain, github_org=seed.get("github_org"), anchor_domain=seed.get("anchor"),
                              token=seed.get("token"))
    if decision.status != "verified":
        return None, f"{domain}: {decision.status}，不落盘"

    ent = result.extra["entity_anchor"]
    if not ent or not ent.anchored:
        return None, f"{domain}: verified 但实体未锚定？这不该发生，请检查"  # 防御：policy 不该放行

    org_name = (seed.get("org_name") or "").strip()
    gh_display = next((str(e.data.get("org_name") or "").strip() for e in result.evidence if e.code == "A1"), "")
    label, label_source = choose_label(wikidata=ent.wikidata, wikidata_label=ent.label if ent.wikidata else "",
                                       github_org=ent.github_org, gh_display=gh_display, org_name=org_name,
                                       repo_label=ent.label if not ent.wikidata else "", domain=domain)
    aliases = sorted({a for a in (org_name, seed.get("github_org", ""), ent.label or "", gh_display)
                      if a and a != label and not re.fullmatch(r"Q\d+", a)})

    entity_id = f"org:{_slug(ent.github_org or label)}"
    record = {
        "schema_version": "1.0",
        "entity_id": entity_id,
        "names": {"en": label},
        "aliases": aliases,
        "category": _categories(seed.get("topics", []), seed.get("source")),
        "wikidata": ent.wikidata,
        "canonical": {
            "github_org": ent.github_org,
            "wikidata": ent.wikidata,
            "sources": list(ent.sources),
        },
        "domains": [{
            "domain": domain,
            "role": seed.get("role") or ("product" if seed.get("anchor") else "primary"),
            "status": decision.status,
            "confidence": decision.confidence,
            "first_seen": now.date().isoformat(),
            "last_verified": _iso(now),
            "ttl_days": 30,
            "age_days": result.facts.get("age_days"),
            "age_source": result.facts.get("age_source"),
            "collection_incomplete": bool(result.facts.get("collection_incomplete")),
            "evidence": [
                {"code": e.code, "checked_at": _iso(e.checked_at), "source": e.source,
                 "data": {k: v for k, v in e.data.items()}}
                for e in result.evidence
            ],
            "rejected_evidence": decision.rejected,
            "reasons": decision.reasons,
        }],
        "provenance": {
            "generated_by": PIPELINE_VERSION,
            "policy_version": _policy_version(),
            "label_source": label_source,
            "reviewed_by": [],
            "source_issue": None,
        },
    }
    # Auto-propagation: every outbound domain on the verified primary's homepage is a candidate sibling
    # (claude.ai on anthropic.com). Each one goes through the full A6 path — first-party link is given,
    # structural links and corroborations are collected fresh; policy decides. Platform domains never qualify.
    if not seed.get("anchor") and seed.get("propagate", True):
        from src.policy import PLATFORM_DOMAINS, registrable_domain
        seen = {domain}
        stored = _stored_domains()
        for cand in result.extra.get("outbound_domains", [])[:MAX_PROPAGATE]:
            cand = registrable_domain(cand)
            if not cand or cand in seen or cand in PLATFORM_DOMAINS:
                continue
            if cand in stored and stored[cand] != record["entity_id"]:
                print(f"  · {cand}: already held by {stored[cand]}; not propagated", file=sys.stderr)
                continue
            seen.add(cand)
            # Cheap pre-check: the A6 rule rejects a candidate whose page links out but never back to the anchor,
            # so look at its homepage first and skip the full pipeline for the obvious third parties.
            from src.collectors import site as site_collector
            outbound = site_collector.collect(cand).extra.get("outbound_domains", [])
            if outbound and domain not in outbound:
                print(f"  · {cand}: links out but not back to {domain}; skipped", file=sys.stderr)
                continue
            try:
                d2, r2 = verify(cand, anchor_domain=domain, anchor_result=result)
            except Exception as exc:  # one bad sibling must not sink the entity
                print(f"  · {cand}: propagation error {type(exc).__name__}", file=sys.stderr)
                continue
            if d2.status != "verified":
                print(f"  · {cand}: {d2.status} (propagated from {domain}, not stored)", file=sys.stderr)
                continue
            record["domains"].append({
                "domain": cand, "role": "product", "status": d2.status, "confidence": d2.confidence,
                "first_seen": now.date().isoformat(), "last_verified": _iso(now), "ttl_days": 30,
                "age_days": r2.facts.get("age_days"), "age_source": r2.facts.get("age_source"),
                "collection_incomplete": bool(r2.facts.get("collection_incomplete")),
                "evidence": [{"code": e.code, "checked_at": _iso(e.checked_at), "source": e.source, "data": dict(e.data)}
                             for e in r2.evidence],
                "rejected_evidence": d2.rejected, "reasons": d2.reasons,
            })
            print(f"  ↳ {cand}: verified {d2.confidence:.2f} (propagated from {domain})", file=sys.stderr)

    return record, f"{domain}: verified {decision.confidence:.2f} → {entity_id}"


def choose_label(*, wikidata: str | None, wikidata_label: str, github_org: str | None, gh_display: str,
                 org_name: str, repo_label: str, domain: str) -> tuple[str, str]:
    """The display name and where it came from (POLICY.md §0).

    Wikidata's English label wins when it names the organization: it is the one source nobody self-declares.
    It loses when the item is a *product* of the organization (vercel.com resolved to the Next.js item,
    airbnb.tech to the style-guide repository): then the entity is the organization and the organization's
    own name (GitHub display name, then login) is the label, with the Wikidata label kept as an alias. A
    "org/repo" from project-history anchoring is never a display name.
    """
    from src.policy import _name_key
    wl = (wikidata_label or "").strip()
    if wl and re.fullmatch(r"Q\d+", wl):
        wl = ""
    if wl and not re.search(r"[A-Za-z]", wl):
        wl = ""   # not an English label; never shown as names.en
    gh_login = (github_org or "").strip()
    org_names = [n for n in (gh_login, gh_display, org_name) if n]

    def _matches(a: str, b: str) -> bool:
        ka, kb = _name_key(a), _name_key(b)
        return bool(ka and kb) and (ka in kb or kb in ka)

    if wl and (not gh_login or any(_matches(wl, n) for n in org_names)):
        return wl, f"wikidata:{wikidata}"
    if org_name and org_name.lower() != gh_login.lower():
        return org_name, "seed_org_name(self-declared)"
    if gh_display:
        return gh_display, "github_org_display_name(self-declared)"
    if gh_login:
        return gh_login, "github_org_login"
    if wl:
        return wl, f"wikidata:{wikidata}"
    if repo_label and "/" in repo_label:
        return repo_label.split("/", 1)[1], "github_repo_name"
    return org_name or domain, "fallback"


_STORED: dict[str, str] | None = None


def _stored_domains() -> dict[str, str]:
    """domain → entity_id for everything already in entities/ (read once per process)."""
    global _STORED
    if _STORED is None:
        _STORED = {}
        for p in ENTITIES.glob("*/*.yaml"):
            doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            for d in doc.get("domains", []):
                _STORED[d["domain"]] = doc.get("entity_id", "")
    return _STORED


def _policy_version() -> str:
    import subprocess
    try:
        out = subprocess.run(["git", "log", "-1", "--format=%h", "--", "src/policy.py"],
                             cwd=ROOT, capture_output=True, text=True, timeout=10)
        return f"policy.py@{out.stdout.strip() or 'unknown'}"
    except Exception:
        return "policy.py@unknown"


def write(record: dict) -> Path:
    slug = record["entity_id"].split(":", 1)[1]
    # An entity already on disk keeps its file: a seed with different topics must update that record,
    # not create a second file for the same entity_id under another category.
    existing = sorted(ENTITIES.glob(f"*/{slug}.yaml"))
    path = existing[0] if existing else ENTITIES / record["category"][0] / f"{slug}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():  # 保留 first_seen；其余以本次为准
        old = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        old_domains = {d["domain"]: d for d in old.get("domains", [])}
        for d in record["domains"]:
            if d["domain"] in old_domains:
                d["first_seen"] = old_domains[d["domain"]].get("first_seen", d["first_seen"])
        # 同一实体的其他域名（之前收录过的）保留
        for dom, rec in old_domains.items():
            if dom not in {d["domain"] for d in record["domains"]}:
                record["domains"].append(rec)

    header = ("# 本文件由流水线生成，请勿手工编辑（SECURITY.md §1）。\n"
              f"# generated_by: {PIPELINE_VERSION}\n")
    body = yaml.safe_dump(record, allow_unicode=True, sort_keys=False, width=110)
    path.write_text(header + body, encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("seeds", type=Path)
    p.add_argument("--domains", help="只处理这些域名，逗号分隔")
    p.add_argument("--only-verified", action="store_true", help="跳过无 GitHub 验证且无其他线索的种子")
    p.add_argument("--shard", help="i/N: process only seeds with index ≡ i (mod N); for parallel CI runners")
    p.add_argument("--no-prefetch", action="store_true", help="skip bulk prefetch (Wikidata/GitHub/Tranco)")
    args = p.parse_args(argv)

    from src.prefetch import prefetch, shard
    seeds = [json.loads(line) for line in args.seeds.read_text(encoding="utf-8").splitlines()
             if line.strip() and not line.startswith("#")]
    if args.domains:
        wanted = {d.strip() for d in args.domains.split(",")}
        seeds = [s for s in seeds if s["domain"] in wanted]
    seeds = shard(seeds, args.shard)
    if not args.no_prefetch:
        prefetch(seeds)

    now = datetime.now(UTC)
    seen_domains: set[str] = set()
    written, skipped = 0, 0
    for seed in seeds:
        if seed["domain"] in seen_domains:
            print(f"  · {seed['domain']}: 已由另一条种子写入，跳过", file=sys.stderr)
            continue
        try:
            record, msg = build_one(seed, now)
        except Exception as exc:
            print(f"  ✗ {seed['domain']}: {type(exc).__name__}: {exc}", file=sys.stderr)
            skipped += 1
            continue
        if record is None:
            print(f"  · {msg}", file=sys.stderr)
            skipped += 1
            continue
        seen_domains.add(seed["domain"])
        path = write(record)
        written += 1
        print(f"  ✓ {msg}  → {path.relative_to(ROOT)}", file=sys.stderr)

    print(f"# 写入 {written}，跳过 {skipped}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

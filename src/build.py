"""把 ``entities/`` 编译成分发产物 ``dist/``。

产物：
* ``registry.json``   —— 全量，给人和小工具；含每条证据
* ``domains.json``    —— 域名 → {entity, status, confidence}，给 Workers/MCP 做 O(1) 查询
* ``domains.txt``     —— 只列 verified 域名，一行一个，给安全工具白名单消费
* ``registry.sqlite`` —— entities / domains / aliases 三张表，给 D1 或本地查询
* ``manifest.json``   —— 版本（git rev）、生成时间、条数、每个产物的 sha256

签名在 CI 里做（cosign keyless，见 .github/workflows/release.yml）；本脚本只负责让产物**可复现**：
同一份 entities/ 必须生成字节相同的 registry.json / domains.json / domains.txt（键排序、无时间戳）。
manifest.json 是唯一带时间戳的文件。

用法::

    python -m src.build            # → dist/
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ENTITIES = ROOT / "entities"
DIST = ROOT / "dist"

#: 对外只有这一个状态给肯定答复（TRUST.md §3）。其余状态导出时保留，但 domains.txt 只含 verified。
OFFICIAL = "verified"


def _git_rev() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short=12", "HEAD"], cwd=ROOT,
                             capture_output=True, text=True, timeout=10)
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_entities() -> list[dict]:
    docs = []
    for p in sorted(ENTITIES.rglob("*.yaml")):
        d = yaml.safe_load(p.read_text(encoding="utf-8"))
        d["_file"] = str(p.relative_to(ROOT)).replace("\\", "/")
        docs.append(d)
    return sorted(docs, key=lambda d: d["entity_id"])


def build(out_dir: Path = DIST) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    entities = load_entities()

    # registry.json —— 全量（去掉内部字段）
    full = [{k: v for k, v in e.items() if not k.startswith("_")} for e in entities]
    (out_dir / "registry.json").write_text(
        json.dumps(full, ensure_ascii=False, sort_keys=True, indent=1), encoding="utf-8")

    # domains.json —— 查询索引
    index: dict[str, dict] = {}
    for e in entities:
        for d in e["domains"]:
            index[d["domain"]] = {
                "entity_id": e["entity_id"],
                "name": e["names"]["en"],
                "role": d.get("role", "primary"),
                "status": d["status"],
                "official": d["status"] == OFFICIAL,
                "confidence": d.get("confidence"),
                "last_verified": d.get("last_verified"),
                "anchors": sorted({ev["code"] for ev in d.get("evidence", [])
                                   if ev["code"].startswith("A")
                                   and not any(r.startswith(ev["code"] + ":")
                                               for r in d.get("rejected_evidence", []))}),
                "wikidata": e.get("wikidata"),
                "github_org": (e.get("canonical") or {}).get("github_org"),
            }
    (out_dir / "domains.json").write_text(
        json.dumps(dict(sorted(index.items())), ensure_ascii=False, sort_keys=True, indent=1),
        encoding="utf-8")

    # entities.json —— 按名字/别名找实体用（API 的 /v1/entity 与 MCP 的 get_official_url）
    ents = {}
    for e in entities:
        # 派生别名（导出时算，不写回 YAML）：verified 域名的标签（claude.ai → claude）、
        # 项目史锚定的仓库名（run-llama/llama_index → llama_index、llama index）。
        # 用户问 "Claude Code 官网" 时，能靠 "claude" 命中 Anthropic。
        derived = set()
        for d in e["domains"]:
            if d["status"] == OFFICIAL:
                derived.add(d["domain"].split(".")[0])
        for s in (e.get("canonical") or {}).get("sources", []):
            if s.startswith("github-history:"):
                repo = s.split(":", 1)[1].split("(")[0].split("/")[-1]
                derived.update({repo, repo.replace("_", " ").replace("-", " ")})
        ents[e["entity_id"]] = {
            "name": e["names"]["en"],
            "aliases": sorted({*e.get("aliases", []), *derived} - {e["names"]["en"]}),
            "wikidata": e.get("wikidata"),
            "github_org": (e.get("canonical") or {}).get("github_org"),
            "category": e.get("category", []),
            "domains": [{"domain": d["domain"], "role": d.get("role", "primary"), "status": d["status"]}
                        for d in e["domains"]],
        }
    (out_dir / "entities.json").write_text(
        json.dumps(dict(sorted(ents.items())), ensure_ascii=False, sort_keys=True, indent=1),
        encoding="utf-8")

    # domains.txt —— 白名单
    verified = sorted(d for d, v in index.items() if v["official"])
    (out_dir / "domains.txt").write_text("\n".join(verified) + "\n", encoding="utf-8")

    # registry.sqlite
    db_path = out_dir / "registry.sqlite"
    if db_path.exists():
        db_path.unlink()
    con = sqlite3.connect(db_path)
    con.executescript("""
        CREATE TABLE entities(entity_id TEXT PRIMARY KEY, name TEXT, wikidata TEXT, github_org TEXT,
                              category TEXT, canonical_json TEXT);
        CREATE TABLE domains(domain TEXT PRIMARY KEY, entity_id TEXT, role TEXT, status TEXT,
                             official INTEGER, confidence REAL, last_verified TEXT, evidence_json TEXT);
        CREATE TABLE aliases(alias TEXT, entity_id TEXT);
        CREATE INDEX idx_alias ON aliases(alias);
        CREATE INDEX idx_domain_entity ON domains(entity_id);
    """)
    for e in entities:
        con.execute("INSERT INTO entities VALUES (?,?,?,?,?,?)", (
            e["entity_id"], e["names"]["en"], e.get("wikidata"),
            (e.get("canonical") or {}).get("github_org"),
            ",".join(e.get("category", [])), json.dumps(e.get("canonical") or {}, ensure_ascii=False)))
        for a in {e["names"]["en"].lower(), *[x.lower() for x in e.get("aliases", [])]}:
            con.execute("INSERT INTO aliases VALUES (?,?)", (a, e["entity_id"]))
        for d in e["domains"]:
            con.execute("INSERT INTO domains VALUES (?,?,?,?,?,?,?,?)", (
                d["domain"], e["entity_id"], d.get("role", "primary"), d["status"],
                int(d["status"] == OFFICIAL), d.get("confidence"), d.get("last_verified"),
                json.dumps({"evidence": d.get("evidence", []),
                            "rejected_evidence": d.get("rejected_evidence", []),
                            "reasons": d.get("reasons", [])}, ensure_ascii=False)))
    con.commit()
    con.close()

    # registry.sql — loads the whole dataset into Cloudflare D1 (wrangler d1 execute --file).
    # Built into *_new tables and swapped at the end so readers never see a half-loaded set.
    # Multi-row INSERTs keep the statement count small (D1 batches per statement).
    write_sql(out_dir / "registry.sql", entities, index, verified, _git_rev())

    manifest = {
        "schema_version": "1.0",
        "dataset_version": _git_rev(),
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "counts": {
            "entities": len(entities),
            "domains": len(index),
            "verified": len(verified),
            "by_status": {s: sum(1 for v in index.values() if v["status"] == s)
                          for s in sorted({v["status"] for v in index.values()})},
        },
        "files": {name: {"sha256": _sha256(out_dir / name), "bytes": (out_dir / name).stat().st_size}
                  for name in ("registry.json", "domains.json", "entities.json", "domains.txt", "registry.sqlite", "registry.sql")},
        "license": "CC-BY-SA-4.0",
        "trust": "https://github.com/zhouchungong/realurls-registry/blob/main/TRUST.md",
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                                           encoding="utf-8")
    return manifest


def _q(v) -> str:
    """SQL literal. Only strings/ints/floats/None/bools reach here."""
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, (int, float)):
        return repr(v)
    return "'" + str(v).replace("'", "''") + "'"


def write_sql(path: Path, entities: list[dict], index: dict, verified: list[str], version: str) -> None:
    from datetime import UTC, datetime

    rows_e, rows_d, rows_a = [], [], []
    for e in entities:
        canonical = e.get("canonical") or {}
        aliases = sorted({e["names"]["en"].lower(), *[x.lower() for x in e.get("aliases", [])]})
        # derived aliases, same rule as entities.json
        for d in e["domains"]:
            if d["status"] == OFFICIAL:
                aliases.append(d["domain"].split(".")[0])
        for s in canonical.get("sources", []):
            if s.startswith("github-history:"):
                repo = s.split(":", 1)[1].split("(")[0].split("/")[-1]
                aliases += [repo.lower(), repo.replace("_", " ").replace("-", " ").lower()]
        rows_e.append((e["entity_id"], e["names"]["en"], e.get("wikidata"), canonical.get("github_org"),
                       ",".join(e.get("category", [])), json.dumps(canonical, ensure_ascii=False),
                       json.dumps(sorted(set(aliases) - {e["names"]["en"].lower()}), ensure_ascii=False),
                       (e.get("provenance") or {}).get("label_source")))
        for a in sorted(set(aliases)):
            rows_a.append((a, e["entity_id"]))
        for d in e["domains"]:
            rows_d.append((d["domain"], e["entity_id"], d.get("role", "primary"), d["status"],
                           int(d["status"] == OFFICIAL), d.get("confidence"), d.get("last_verified"),
                           json.dumps(index[d["domain"]]["anchors"]),
                           json.dumps({"evidence": d.get("evidence", []), "rejected_evidence": d.get("rejected_evidence", []),
                                       "reasons": d.get("reasons", []), "age_days": d.get("age_days"),
                                       "age_source": d.get("age_source"), "first_seen": d.get("first_seen"),
                                       "ttl_days": d.get("ttl_days"), "history": d.get("history", [])}, ensure_ascii=False)))

    def inserts(table: str, cols: str, rows: list[tuple], max_bytes: int = 60_000) -> list[str]:
        """Multi-row INSERTs, each kept under D1's per-statement size limit (SQLITE_TOOBIG near 100 KB)."""
        out: list[str] = []
        cur: list[str] = []
        size = 0
        for r in rows:
            v = "(" + ", ".join(_q(x) for x in r) + ")"
            if cur and size + len(v.encode()) > max_bytes:
                out.append(f"INSERT INTO {table} ({cols}) VALUES\n" + ",\n".join(cur) + ";")
                cur, size = [], 0
            cur.append(v)
            size += len(v.encode()) + 2
        if cur:
            out.append(f"INSERT INTO {table} ({cols}) VALUES\n" + ",\n".join(cur) + ";")
        return out

    stmts = [
        "DROP TABLE IF EXISTS entities_new; DROP TABLE IF EXISTS domains_new; "
        "DROP TABLE IF EXISTS aliases_new; DROP TABLE IF EXISTS meta_new;",
        "CREATE TABLE entities_new(entity_id TEXT PRIMARY KEY, name TEXT NOT NULL, wikidata TEXT, github_org TEXT, "
        "category TEXT, canonical_json TEXT, aliases_json TEXT, label_source TEXT);",
        "CREATE TABLE domains_new(domain TEXT PRIMARY KEY, entity_id TEXT NOT NULL, role TEXT, status TEXT NOT NULL, "
        "official INTEGER NOT NULL, confidence REAL, last_verified TEXT, anchors_json TEXT, record_json TEXT);",
        "CREATE TABLE aliases_new(alias TEXT NOT NULL, entity_id TEXT NOT NULL);",
        "CREATE TABLE meta_new(key TEXT PRIMARY KEY, value TEXT);",
        *inserts("entities_new", "entity_id, name, wikidata, github_org, category, canonical_json, aliases_json, label_source", rows_e),
        *inserts("domains_new", "domain, entity_id, role, status, official, confidence, last_verified, anchors_json, record_json", rows_d),
        *inserts("aliases_new", "alias, entity_id", rows_a),
        "INSERT INTO meta_new (key, value) VALUES " + ", ".join(
            f"({_q(k)}, {_q(v)})" for k, v in {
                "dataset_version": version,
                "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "entities": len(entities), "domains": len(index), "verified": len(verified),
            }.items()) + ";",
        "CREATE INDEX idx_domains_new_entity ON domains_new(entity_id); CREATE INDEX idx_aliases_new_alias ON aliases_new(alias); "
        "CREATE INDEX idx_domains_new_official ON domains_new(official);",
        # swap
        "DROP TABLE IF EXISTS entities; DROP TABLE IF EXISTS domains; DROP TABLE IF EXISTS aliases; DROP TABLE IF EXISTS meta;",
        "ALTER TABLE entities_new RENAME TO entities; ALTER TABLE domains_new RENAME TO domains; "
        "ALTER TABLE aliases_new RENAME TO aliases; ALTER TABLE meta_new RENAME TO meta;",
    ]
    path.write_text("\n".join(stmts) + "\n", encoding="utf-8")


def main() -> int:
    m = build()
    print(f"dist/ ← {m['counts']['entities']} entities, {m['counts']['domains']} domains "
          f"({m['counts']['verified']} verified), version {m['dataset_version']}")
    for name, info in m["files"].items():
        print(f"  {name:<18} {info['bytes']:>8} B  {info['sha256'][:16]}…")
    return 0


if __name__ == "__main__":
    sys.exit(main())

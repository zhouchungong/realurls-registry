"""校验 ``entities/`` 下的数据文件。

CI 会跑这个。除 JSON Schema 之外，还检查若干**只有本项目才在乎**的不变量：

* 已声明的 ``status`` 必须与 ``policy.decide()`` 的结果一致 —— 数据不能凭空写 verified。
* ``non_affiliated`` 的 ``signals`` 里不得出现定性词汇（TRUST.md §6 的法律边界）。
* ``entity_id`` 全局唯一，域名不得跨实体重复归属。

用法::

    python -m src.validate
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml

try:
    from jsonschema import Draft202012Validator
except ImportError:  # pragma: no cover - 可选依赖
    Draft202012Validator = None

from src.policy import DomainFacts, Evidence, decide

ROOT = Path(__file__).resolve().parents[1]
ENTITIES = ROOT / "entities"
SCHEMA = ROOT / "schema" / "entity.schema.json"

#: 禁止出现在 non_affiliated.signals 里的定性词汇。
#: 我们只罗列客观信号，定性属于有资质的安全厂商与执法机构。
FORBIDDEN_TERMS = ("钓鱼", "诈骗", "恶意", "欺诈", "phishing", "scam", "malicious", "fraud")

#: 未跑采集流水线时无法复算的状态 —— M0 阶段占位记录使用。
SKIP_RECHECK = {"unverified", "flagged", "disputed", "review_required", "stale"}


def _load_all() -> list[tuple[Path, dict]]:
    return [(p, yaml.safe_load(p.read_text(encoding="utf-8")))
            for p in sorted(ENTITIES.rglob("*.yaml"))]


def _check_schema(errors: list[str], path: Path, doc: dict) -> None:
    if Draft202012Validator is None:
        return
    import json
    validator = Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8")))
    for err in validator.iter_errors(doc):
        errors.append(f"{path}: schema: {'/'.join(str(p) for p in err.path)}: {err.message}")


def _check_status_matches_policy(errors: list[str], path: Path, doc: dict) -> None:
    """声明的 status 必须能由证据复算出来。防止有人手写一个 verified 进去。"""
    for rec in doc.get("domains", []):
        declared = rec["status"]
        if declared in SKIP_RECHECK:
            continue
        evidence = [
            Evidence(code=e["code"], data=e.get("data", {}), source=e.get("source"))
            for e in rec.get("evidence", [])
        ]
        canonical = doc.get("canonical") or {}
        age = rec.get("age_days") if "age_days" in rec else _age_days(rec)
        facts = DomainFacts(
            domain=rec["domain"],
            age_days=age,
            age_source=rec.get("age_source") or ("rdap" if age is not None else None),
            expected_github_org=canonical.get("github_org"),
            expected_wikidata=canonical.get("wikidata"),
            anchor_sources=tuple(canonical.get("sources", [])),
            expected_names=tuple(n for n in [(doc.get("names") or {}).get("en"), *(doc.get("aliases") or []),
                                             canonical.get("github_org")] if n),
            ttl_days=rec.get("ttl_days", 30),
        )
        got = decide(facts, evidence, now=datetime.now(UTC))
        if got.status != declared:
            errors.append(
                f"{path}: {rec['domain']}: 声明 status={declared}，"
                f"但由证据复算得到 {got.status}（{'; '.join(got.reasons)}）"
            )


def _age_days(rec: dict) -> int | None:
    """从 A3 证据里的注册日推算域龄；没有则返回 None（policy 会跳过新域名门槛）。"""
    for e in rec.get("evidence", []):
        created = e.get("data", {}).get("created")
        if created:
            d = datetime.fromisoformat(str(created)).replace(tzinfo=UTC)
            return (datetime.now(UTC) - d).days
    return None


def _check_neutral_language(errors: list[str], path: Path, doc: dict) -> None:
    for item in doc.get("non_affiliated", []):
        for signal in item.get("signals", []):
            low = str(signal).lower()
            for term in FORBIDDEN_TERMS:
                if term in low:
                    errors.append(
                        f"{path}: non_affiliated[{item.get('domain')}]: "
                        f"signals 含定性词汇「{term}」。只允许客观信号，见 TRUST.md §6"
                    )


def _check_uniqueness(errors: list[str], docs: list[tuple[Path, dict]]) -> None:
    seen_entities: dict[str, Path] = {}
    seen_domains: dict[str, tuple[Path, str]] = {}
    for path, doc in docs:
        eid = doc.get("entity_id")
        if eid in seen_entities:
            errors.append(f"{path}: entity_id {eid} 与 {seen_entities[eid]} 重复")
        seen_entities[eid] = path
        for rec in doc.get("domains", []):
            dom = rec["domain"]
            if dom in seen_domains and seen_domains[dom][1] != eid:
                errors.append(
                    f"{path}: 域名 {dom} 已归属于 {seen_domains[dom][1]}"
                    f"（{seen_domains[dom][0]}）—— 归属冲突必须标为 disputed 而非重复收录"
                )
            seen_domains[dom] = (path, eid)


def main() -> int:
    docs = _load_all()
    errors: list[str] = []
    for path, doc in docs:
        _check_schema(errors, path, doc)
        _check_status_matches_policy(errors, path, doc)
        _check_neutral_language(errors, path, doc)
    _check_uniqueness(errors, docs)

    if errors:
        print(f"✗ {len(errors)} 个问题：\n" + "\n".join(f"  - {e}" for e in errors))
        return 1
    print(f"✓ {len(docs)} 个实体文件全部通过校验")
    return 0


if __name__ == "__main__":
    sys.exit(main())

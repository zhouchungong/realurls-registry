"""定案引擎回归测试。

两组：
  * 正样本 —— 手工构造的真实场景，验证该判 verified 的确实判了。
  * 负样本 —— 由 ``negative_corpus.yaml`` 驱动，**任何一条判成 verified 都是 P0 事故**。

精度约束（POLICY.md §3）：precision >= 99.5%。负样本全绿是这个约束的最低保障。
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.policy import (  # noqa: E402
    Decision,
    DomainFacts,
    Evidence,
    decide,
    registrable_domain,
)

NOW = datetime(2026, 9, 5, tzinfo=timezone.utc)
CORPUS = Path(__file__).parent / "negative_corpus.yaml"


# ---------------------------------------------------------------------------- helpers


def ev(code: str, **data) -> Evidence:
    return Evidence(code=code, data=data, checked_at=NOW)


#: 实体锚定结果（src/anchor.py 从 Wikidata Q116758847 的 P2037 得到 canonical GitHub 组织）
ANTHROPIC_ANCHOR = dict(
    expected_github_org="anthropics",
    expected_wikidata="Q116758847",
    anchor_sources=("wikidata:Q116758847/P2037",),
)


def anthropic_facts(**overrides) -> DomainFacts:
    base = dict(domain="anthropic.com", age_days=9104, age_source="rdap", **ANTHROPIC_ANCHOR)
    base.update(overrides)
    return DomainFacts(**base)


def anthropic_evidence() -> list[Evidence]:
    """anthropic.com 的真实证据集（数值来自 2026-09-05 实测）。"""
    return [
        ev("A1", org_verified=True, blog="https://anthropic.com", org="anthropics"),
        ev("A3", registrar="MarkMonitor Inc.", remaining_days=2584,
           locks=["delete", "transfer", "update"]),
        ev("B1", qid="Q116758847"),
        ev("B4", history_days=1800),
    ]


# ------------------------------------------------------------------------- 正样本


def test_anthropic_com_is_verified():
    d = decide(anthropic_facts(), anthropic_evidence(), now=NOW)
    assert d.status == "verified"
    assert d.is_official
    assert "A1" in d.anchors and "A3" in d.anchors
    assert d.confidence > 0.9


def test_propagated_sibling_domain_is_verified():
    """claude.ai 靠「一方声明 + 结构性关联」从 anthropic.com 继承归属。"""
    facts = DomainFacts(domain="claude.ai", age_days=1500, **ANTHROPIC_ANCHOR)
    d = decide(
        facts,
        [
            ev("A6", **{"from": "anthropic.com", "from_status": "verified",
                        "first_party_link": True, "structural_links": ["shared_ns"]}),
            ev("B5", rank=120),
            ev("B4", history_days=1400),
        ],
        now=NOW,
    )
    assert d.status == "verified"
    assert d.anchors == ["A6"]


def test_gov_restricted_tld_is_an_anchor():
    """后缀本身就是锚点：注册局只让政府机构注册。"""
    facts = DomainFacts(domain="travel.state.gov", age_days=None)
    d = decide(facts, [ev("A7"), ev("B4", history_days=6000), ev("B5", rank=2000)], now=NOW)
    assert d.status == "verified"
    assert d.anchors == ["A7"]


def test_gov_suffix_check_is_strict():
    facts = DomainFacts(domain="state-gov.com", age_days=2000)
    d = decide(facts, [ev("A7"), ev("B4", history_days=1000), ev("B5", rank=2000)], now=NOW)
    assert "A7" not in d.anchors


def test_unknown_age_caps_at_provisional_even_with_full_evidence():
    """REVIEW-RESULT §0b：未知按最坏情况处理。"""
    facts = anthropic_facts(age_days=None, age_source=None)
    d = decide(facts, anthropic_evidence(), now=NOW)
    assert d.status == "provisional"
    assert not d.is_official
    assert any("域龄未知" in r for r in d.reasons)


def test_wayback_lower_bound_counts_as_known_age():
    facts = anthropic_facts(age_days=1800, age_source="wayback_lower_bound")
    assert decide(facts, anthropic_evidence(), now=NOW).status == "verified"


def test_unanchored_entity_cannot_use_control_proofs():
    """REVIEW-RESULT §0：控制权 ≠ 身份。没有 canonical 组织时 A1 一律不算。"""
    facts = DomainFacts(domain="anthropic.com", age_days=9104)  # 没有 expected_*
    d = decide(facts, anthropic_evidence(), now=NOW)
    assert "A1" not in d.anchors
    assert any("实体未锚定" in r for r in d.rejected)
    assert d.status != "verified" or "A1" not in d.anchors


def test_dns_self_attestation_overrides_young_domain_guard():
    """A5 是唯一能豁免 180 天新域名门槛的锚点 —— 因为它需要对方主动配合。"""
    facts = DomainFacts(domain="newproduct.example", age_days=20)
    d = decide(facts, [ev("A5", token_match=True), ev("B3"), ev("B6")], now=NOW)
    assert d.status == "verified"


# ------------------------------------------------------------- 状态机与保鲜


def test_expired_ttl_downgrades_to_stale():
    facts = anthropic_facts(previous_status="verified",
                            last_verified=NOW - timedelta(days=45), ttl_days=30)
    d = decide(facts, anthropic_evidence(), now=NOW)
    assert d.status == "stale"
    assert not d.is_official


def test_fresh_ttl_stays_verified():
    facts = anthropic_facts(previous_status="verified",
                            last_verified=NOW - timedelta(days=10), ttl_days=30)
    assert decide(facts, anthropic_evidence(), now=NOW).status == "verified"


def test_mutation_suspends_positive_answer():
    facts = anthropic_facts(mutation_detected=True)
    assert decide(facts, anthropic_evidence(), now=NOW).status == "review_required"


def test_conflict_becomes_disputed():
    facts = DomainFacts(domain="contested.example", age_days=2000, has_conflict=True)
    assert decide(facts, anthropic_evidence(), now=NOW).status == "disputed"


def test_security_flag_overrides_all_evidence():
    """硬否决必须压过任意数量的正向证据。"""
    facts = anthropic_facts(gsb_flagged=True)
    d = decide(facts, anthropic_evidence(), now=NOW)
    assert d.status == "flagged"
    assert d.confidence == 0.0


# ------------------------------------------------------- 证据独立性与门槛

EXAMPLE_ANCHOR = dict(expected_github_org="exampleorg", expected_wikidata="Q1",
                      anchor_sources=("wikidata:Q1/P2037",))


def example_facts(**overrides) -> DomainFacts:
    base = dict(domain="example.com", age_days=2000, **EXAMPLE_ANCHOR)
    base.update(overrides)
    return DomainFacts(**base)


def test_correlated_anchors_count_once():
    """A2 的信任链最终落到 A1，二者不独立，只能计 1 条锚点。"""
    d = decide(
        example_facts(),
        [
            ev("A1", org_verified=True, blog="https://example.com", org="exampleorg"),
            ev("A2", provenance_verified=True, chain_org_verified=True,
               chain_blog="https://example.com", chain_org="exampleorg"),
        ],
        now=NOW,
    )
    assert d.anchors == ["A1"]
    assert d.status == "provisional"  # 锚点只有 1 条且无佐证
    assert any("不独立" in r for r in d.reasons)


def test_provenance_implies_package_homepage():
    """A2 已蕴含 B2，B2 不得重复计数把佐证凑到 2 条。"""
    d = decide(
        example_facts(),
        [
            ev("A2", provenance_verified=True, chain_org_verified=True,
               chain_blog="https://example.com", chain_org="exampleorg"),
            ev("B2"),
            ev("B1", qid="Q1"),
        ],
        now=NOW,
    )
    assert "B2" not in d.corroborations
    assert d.status == "provisional"


def test_anchor_without_enough_corroboration_is_provisional():
    d = decide(example_facts(),
               [ev("A1", org_verified=True, blog="https://example.com", org="exampleorg"),
                ev("B1", qid="Q1")], now=NOW)
    assert d.status == "provisional"
    assert not d.is_official


def test_corroboration_only_is_community_never_official():
    d = decide(example_facts(), [ev("B1", qid="Q1"), ev("B2"), ev("B3"), ev("B6")], now=NOW)
    assert d.status == "community"
    assert not d.is_official


def test_young_domain_cannot_be_verified_without_self_attestation():
    facts = example_facts(domain="brandnew.example", age_days=30)
    d = decide(
        facts,
        [ev("A1", org_verified=True, blog="https://brandnew.example", org="exampleorg"),
         ev("B1", qid="Q1"), ev("B6")],
        now=NOW,
    )
    assert d.status == "unverified"


def test_rejected_evidence_is_explained():
    """每条被拒证据都必须带原因 —— 可解释性是对外承诺的一部分。"""
    d = decide(example_facts(),
               [ev("A1", org_verified=False, blog="https://example.com", org="exampleorg")],
               now=NOW)
    assert d.rejected and "A1" in d.rejected[0]
    assert d.status == "unverified"


def test_wikidata_item_must_match_canonical():
    """任何人都能建一个 Wikidata 条目指向任何域名；只有锚定时确立的那个条目才算。"""
    d = decide(example_facts(),
               [ev("A1", org_verified=True, blog="https://example.com", org="exampleorg"),
                ev("B1", qid="Q999"), ev("B4", history_days=1000)], now=NOW)
    assert "B1" not in d.corroborations
    assert d.status == "provisional"


def test_unknown_evidence_code_is_rejected():
    facts = DomainFacts(domain="example.com", age_days=2000)
    d = decide(facts, [Evidence(code="Z9")], now=NOW)
    assert any("未知证据代码" in r for r in d.rejected)


# ------------------------------------------------------------------ 工具函数


@pytest.mark.parametrize(
    "host,expected",
    [
        ("https://anthropic.com", "anthropic.com"),
        ("https://www.anthropic.com/index", "anthropic.com"),
        ("docs.claude.com", "claude.com"),
        ("a.b.example.co.uk", "example.co.uk"),
        ("shop.example.com.cn", "example.com.cn"),
        ("example.com:443", "example.com"),
    ],
)
def test_registrable_domain(host, expected):
    assert registrable_domain(host) == expected


# ------------------------------------------------------------------ 负样本


def _load_corpus() -> list[tuple[str, DomainFacts, list[Evidence]]]:
    data = yaml.safe_load(CORPUS.read_text(encoding="utf-8"))
    out = []
    for case in data["cases"]:
        facts = DomainFacts(**case["facts"])
        evidence = [Evidence(code=e["code"], data=e.get("data", {})) for e in case["evidence"]]
        out.append((case["id"], facts, evidence))
    return out


CORPUS_CASES = _load_corpus()


@pytest.mark.parametrize("case_id,facts,evidence", CORPUS_CASES, ids=[c[0] for c in CORPUS_CASES])
def test_negative_corpus_never_verified(case_id: str, facts: DomainFacts, evidence: list[Evidence]):
    d: Decision = decide(facts, evidence, now=NOW)
    assert not d.is_official, (
        f"P0：负样本 {case_id}（{facts.domain}）被判为 verified。\n"
        f"锚点={d.anchors} 佐证={d.corroborations}\n"
        f"理由={d.reasons}"
    )


def test_corpus_is_not_empty():
    """防止语料被误删后测试假绿。"""
    assert len(CORPUS_CASES) >= 15

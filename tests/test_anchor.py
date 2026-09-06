"""Entity anchoring must be tied to the domain being verified.

Regression for a real incident: supabase.com's homepage links to github.com/langchain-ai, and the
project-history anchor accepted the first candidate that met the bar — so re-verification anchored
Supabase to LangChain. An outbound link to a famous organization must never confer that org's identity.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import anchor as anchor_mod  # noqa: E402
from src.collectors import github  # noqa: E402

FAKE_REPOS = {
    "langchain-ai": {"repo": "langchain-ai/langchain", "org": "langchain-ai", "stars": 145668, "age_days": 1400,
                     "contributors": 3731, "homepage": "https://langchain.com", "created_at": "2022-10-17T00:00:00Z"},
    "supabase": {"repo": "supabase/supabase", "org": "supabase", "stars": 108852, "age_days": 2500,
                 "contributors": 2033, "homepage": "https://supabase.com", "created_at": "2019-10-12T00:00:00Z"},
}
FAKE_BLOGS = {"langchain-ai": "https://www.langchain.com", "supabase": "https://supabase.com"}


def _patch(monkeypatch):
    monkeypatch.setattr(github, "repo_history", lambda org, r=None: FAKE_REPOS.get(org))
    monkeypatch.setattr(github, "org_blog", lambda org: FAKE_BLOGS.get(org, ""))
    github.org_blog.cache_clear() if hasattr(github.org_blog, "cache_clear") else None


def test_outbound_link_to_famous_org_does_not_anchor(monkeypatch):
    _patch(monkeypatch)
    a = anchor_mod.anchor_from_github_history(["langchain-ai"], "supabase.com")
    assert a.github_org is None
    assert any("not tied to this domain" in n for n in a.notes)


def test_org_tied_by_repo_homepage_anchors(monkeypatch):
    _patch(monkeypatch)
    a = anchor_mod.anchor_from_github_history(["langchain-ai", "supabase"], "supabase.com")
    assert a.github_org == "supabase"
    assert a.sources[0].startswith("github-history:supabase/supabase")


def test_org_tied_by_blog_only_anchors(monkeypatch):
    _patch(monkeypatch)
    FAKE_REPOS["supabase"] = {**FAKE_REPOS["supabase"], "homepage": ""}   # repo has no homepage, org blog does
    a = anchor_mod.anchor_from_github_history(["supabase"], "supabase.com")
    assert a.github_org == "supabase"



def _appstore(seller, app="Merge Dragons!", age_days=2000, ratings=50000):
    from src.collectors.base import Result
    from src.policy import Evidence

    def collect(domain, names=None):
        r = Result()
        r.evidence.append(Evidence(code="A9", data={"seller": seller, "app": app, "seller_url": f"https://{domain}",
                                                     "age_days": age_days, "ratings": ratings,
                                                     "apps": [{"app": app, "seller": seller, "age_days": age_days, "ratings": ratings}]}))
        return r
    return collect


def test_thin_wikidata_item_is_anchored_by_apple_verified_seller(monkeypatch):
    from src.collectors import appstore
    item = {"qid": "Q1", "label": "Dream Games", "sitelinks": 2}
    monkeypatch.setattr(appstore, "collect", _appstore("Dream Games Dijital Teknolojiler A.S."))
    a = anchor_mod.anchor_from_appstore("dreamgames.com", item)
    assert a.anchored and a.wikidata == "Q1" and any(s.startswith("appstore:") for s in a.sources)


def test_thin_wikidata_item_stays_unanchored_without_matching_seller_or_history(monkeypatch):
    from src.collectors import appstore
    item = {"qid": "Q1", "label": "Dream Games", "sitelinks": 2}
    monkeypatch.setattr(appstore, "collect", _appstore("Someone Else Ltd"))
    assert not anchor_mod.anchor_from_appstore("dreamgames.com", item).anchored
    monkeypatch.setattr(appstore, "collect", _appstore("Dream Games", age_days=300, ratings=50000))
    assert not anchor_mod.anchor_from_appstore("dreamgames.com", item).anchored
    monkeypatch.setattr(appstore, "collect", _appstore("Dream Games", age_days=3000, ratings=40))
    assert not anchor_mod.anchor_from_appstore("dreamgames.com", item).anchored

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

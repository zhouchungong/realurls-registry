"""A9 candidate: App Store history. An established app, sold by an Apple-verified legal entity, whose
seller URL points at this domain.

Why this is an anchor and not a corroboration
---------------------------------------------
Apple verifies organisation developer accounts against a D-U-N-S record before an app can be sold under a
company name, so ``sellerName`` is a legal identity Apple checked, not a free-text field. The listing's
release date and rating count are facts an attacker cannot manufacture for a lookalike domain: a years-old
app with thousands of ratings, sold by a verified company, pointing at this domain, is the commercial
counterpart of the project-history anchor (A8). The thresholds live in ``policy.py``; this module only
reports what the store says.

The search API is public and unauthenticated (about 20 requests a minute). We search by the entity's
names and by the domain label, keep apps whose seller URL resolves to the target domain, and report the
strongest one. Nothing here judges.
"""

from __future__ import annotations

import urllib.parse
from datetime import UTC, datetime

from src.collectors.base import FetchError, Result, fetch_json, now
from src.policy import Evidence, registrable_domain

SEARCH = "https://itunes.apple.com/search"


def _search(term: str) -> list[dict]:
    url = f"{SEARCH}?{urllib.parse.urlencode({'term': term, 'entity': 'software', 'limit': 25})}"
    return fetch_json(url, ttl_hours=168, timeout=30).get("results", [])


def collect(domain: str, names: list[str] | None = None) -> Result:
    """Look for apps sold to this domain. ``names`` are the entity's names (label, aliases, org)."""
    r = Result()
    domain = registrable_domain(domain)
    terms = [n for n in dict.fromkeys([*(names or []), domain.split(".")[0]]) if n and len(n) >= 3]
    apps: dict[int, dict] = {}
    for term in terms[:3]:
        try:
            for a in _search(term):
                url = a.get("sellerUrl") or ""
                if url and registrable_domain(url) == domain:
                    apps[a["trackId"]] = a
        except FetchError as exc:
            r.note(f"appstore: search for {term!r} failed: {exc}")
            continue
    if not apps:
        r.note("appstore: no app whose seller URL points at this domain")
        return r

    def age_days(a: dict) -> int:
        try:
            return (now() - datetime.fromisoformat(a["releaseDate"].replace("Z", "+00:00")).astimezone(UTC)).days
        except (KeyError, ValueError):
            return 0

    # The strongest listing is the one that is both old and rated: sort by the smaller of the two normalised
    # scores so a young app with many ratings does not outrank an old app with a real footprint.
    def strength(a: dict) -> float:
        return min(age_days(a) / 730, int(a.get("userRatingCount") or 0) / 1000)

    ranked = sorted(apps.values(), key=strength, reverse=True)
    best = ranked[0]
    r.evidence.append(Evidence(
        code="A9",
        data={
            "app": best.get("trackName"), "track_id": best.get("trackId"),
            "seller": best.get("sellerName"), "artist": best.get("artistName"),
            "seller_url": best.get("sellerUrl"), "released": (best.get("releaseDate") or "")[:10],
            "age_days": age_days(best), "ratings": int(best.get("userRatingCount") or 0),
            "apps_for_domain": len(apps),
            "apps": [{"app": a.get("trackName"), "seller": a.get("sellerName"), "released": (a.get("releaseDate") or "")[:10],
                      "age_days": age_days(a), "ratings": int(a.get("userRatingCount") or 0)} for a in ranked[:3]],
        },
        checked_at=now(),
        source=f"{SEARCH}?term={urllib.parse.quote(terms[0])}&entity=software",
    ))
    r.note(f"appstore: {len(apps)} app(s) sold to {domain}; strongest {best.get('trackName')!r} by "
           f"{best.get('sellerName')!r}, {age_days(best)} days on the store, {best.get('userRatingCount', 0)} ratings")
    return r

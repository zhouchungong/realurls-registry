"""Live smoke test: real requests against the deployed site, API and MCP endpoint, for the cases that
unit tests with a small in-memory dataset cannot catch (an alias that breaks a SQL pattern, a category that
does not render, a name lookup that throws). Any non-200 or wrong verdict fails the deploy.

    python scripts/smoke.py                # against production
    python scripts/smoke.py --base https://staging.example   # (site host; the API host is derived)
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

CASES = [
    # (label, method, url, body, checks)   checks: status, and substrings / json predicates
    ("home", "GET", "{site}/", None, {"contains": "<title>Realurls"}),
    ("browse", "GET", "{site}/browse", None, {"contains": "All organizations"}),
    ("category pages", "GET", "{site}/c/{category}", None, {"contains": "verified organizations"}),
    ("verified domain page", "GET", "{site}/d/anthropic.com", None, {"status": (200, 302)}),
    ("unknown domain page", "GET", "{site}/d/zzz-smoke-unknown-domain.example", None, {"contains": "not in the registry"}),
    ("unknown name page", "GET", "{site}/d/zzzsmokeunknownname", None, {"contains": "not in the registry"}),
    ("lookalike page", "GET", "{site}/d/anthroppic.com", None, {"contains": "not a known domain"}),
    ("verify page", "GET", "{site}/verify", None, {"contains": "TXT"}),
    ("api resolve verified", "GET", "{api}/v1/resolve?domain=anthropic.com", None, {"json": {"verdict": "official"}}),
    ("api resolve unknown", "GET", "{api}/v1/resolve?domain=zzz-smoke-unknown-domain.example", None, {"json": {"verdict": "unknown"}}),
    ("api resolve invalid", "GET", "{api}/v1/resolve?domain=zzzsmokeunknownname", None, {"json": {"verdict": "invalid"}}),
    ("api entity known", "GET", "{api}/v1/entity?q=anthropic", None, {"json": {"verdict": "official"}}),
    ("api entity unknown", "GET", "{api}/v1/entity?q=zzzsmokeunknownname", None, {"json": {"verdict": "unknown"}}),
    ("api manifest", "GET", "{api}/v1/manifest", None, {"json_has": "dataset_version"}),
    ("api demand", "GET", "{api}/v1/demand", None, {"json_has": "items"}),
    ("api domains.txt", "GET", "{api}/v1/domains.txt", None, {"contains": "anthropic.com"}),
    ("mcp get_official_url unknown", "POST", "{api}/mcp",
     {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
      "params": {"name": "get_official_url", "arguments": {"name": "zzzsmokeunknownname"}}},
     {"contains": "could not confirm"}),
    ("mcp verify_url unknown", "POST", "{api}/mcp",
     {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "verify_url", "arguments": {"url": "https://zzz-smoke-unknown-domain.example/x"}}},
     {"contains": "could not confirm"}),
    ("mcp get_official_url known", "POST", "{api}/mcp",
     {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "get_official_url", "arguments": {"name": "anthropic"}}},
     {"contains": "anthropic.com"}),
]


def fetch(method: str, url: str, body: dict | None) -> tuple[int, str]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"User-Agent": "realurls-smoke", "Accept": "application/json, text/html",
                                          **({"Content-Type": "application/json"} if data else {})})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:   # noqa: S310 (fixed hosts)
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def categories(api: str) -> list[str]:
    _, body = fetch("GET", f"{api}/v1/manifest", None)
    try:
        cats = json.loads(body).get("counts", {}).get("categories") or {}
        return sorted(cats) if isinstance(cats, dict) else []
    except json.JSONDecodeError:
        return []


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="https://realurls.org")
    args = p.parse_args(argv)
    site = args.base.rstrip("/")
    api = site.replace("://", "://api.") if "://api." not in site else site
    cats = categories(api)
    if not cats:
        try:
            sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
            from src.build_entities import CATEGORIES
            cats = sorted(CATEGORIES)
        except ImportError:
            cats = ["ai", "developer-tools", "saas", "security", "infrastructure", "open-source",
                    "hardware", "finance", "government", "games", "media", "other"]
    failures = 0
    for label, method, url, body, checks in CASES:
        targets = [url.format(site=site, api=api, category=c) for c in cats] if "{category}" in url \
            else [url.format(site=site, api=api)]
        for target in targets:
            status, text = fetch(method, target, body)
            ok = status in checks.get("status", (200,))
            why = f"HTTP {status}"
            if ok and "contains" in checks and checks["contains"].lower() not in text.lower():
                ok, why = False, f"missing {checks['contains']!r}"
            if ok and ("json" in checks or "json_has" in checks):
                try:
                    doc = json.loads(text)
                except json.JSONDecodeError:
                    ok, why = False, "not JSON"
                else:
                    for k, v in checks.get("json", {}).items():
                        if doc.get(k) != v:
                            ok, why = False, f"{k}={doc.get(k)!r}, expected {v!r}"
                    if "json_has" in checks and checks["json_has"] not in doc:
                        ok, why = False, f"no {checks['json_has']!r} field"
            print(f"  {'✓' if ok else '✗'} {label:<30} {target.replace(site, '').replace(api, 'api:') or '/':<50} {why}")
            failures += 0 if ok else 1
    print(f"# smoke: {failures} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

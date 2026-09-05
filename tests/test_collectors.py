"""采集器的离线单元测试。

只测**解析逻辑**，不发网络请求。采集器的职责是「把外部世界翻译成 Evidence」，
翻译错了比采不到更危险 —— 采不到只是少一条证据，翻译错会凭空造出一条假证据。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.collectors import rdap, site  # noqa: E402
from src.collectors.github import _candidates  # noqa: E402

# ------------------------------------------------------------------ site

SAMPLE_HTML = """
<html><body>
  <a href="https://github.com/anthropics">GitHub</a>
  <a href="https://github.com/features/copilot">保留路径，不是组织</a>
  <a href="https://www.npmjs.com/package/@anthropic-ai/sdk">SDK</a>
  <a href="https://claude.ai/login">Claude</a>
  <a href="https://docs.claude.com/">Docs</a>
  <a href="/relative/path">相对链接应被忽略</a>
  <a href="https://www.wikidata.org/wiki/Q116758847">Wikidata</a>
</body></html>
"""


def _parse(html: str, domain: str = "anthropic.com"):
    parser = site._LinkExtractor()
    parser.feed(html)
    import re
    orgs = {m.group(1) for m in site.GITHUB_ORG_RE.finditer(html)} - site.GITHUB_RESERVED
    pkgs = {m.group(1) for m in site.NPM_PKG_RE.finditer(html)}
    qids = {m.group(1) for m in re.finditer(site.WIKIDATA_RE, html)}
    return parser.hrefs, orgs, pkgs, qids


def test_site_extracts_github_org_and_skips_reserved_paths():
    _, orgs, _, _ = _parse(SAMPLE_HTML)
    assert "anthropics" in orgs
    assert "features" not in orgs, "github.com/features 是保留路径，不是组织"


def test_site_extracts_scoped_npm_package():
    _, _, pkgs, _ = _parse(SAMPLE_HTML)
    assert "@anthropic-ai/sdk" in pkgs


def test_site_extracts_wikidata_qid():
    _, _, _, qids = _parse(SAMPLE_HTML)
    assert qids == {"Q116758847"}


def test_site_outbound_domains_exclude_self_and_relative():
    from src.policy import registrable_domain
    hrefs, _, _, _ = _parse(SAMPLE_HTML)
    self_site = registrable_domain("anthropic.com")
    siblings = {
        registrable_domain(h) for h in hrefs
        if h.startswith(("http://", "https://"))
    } - {self_site}
    assert "claude.ai" in siblings and "claude.com" in siblings
    assert not any(s.startswith("/") for s in siblings)


def test_site_handles_malformed_html_without_crashing():
    parser = site._LinkExtractor()
    parser.feed('<a href="https://example.com">未闭合 <div><a href=')
    assert "https://example.com" in parser.hrefs


# ------------------------------------------------------------------ rdap

RDAP_DOC = {
    "entities": [
        {"roles": ["registrar"],
         "vcardArray": ["vcard", [["version", {}, "text", "4.0"],
                                  ["fn", {}, "text", "MarkMonitor Inc."]]]},
    ],
    "events": [{"eventAction": "registration", "eventDate": "2001-10-02T18:10:32Z"}],
    "status": ["client delete prohibited", "client transfer prohibited"],
}


def test_rdap_extracts_registrar_from_vcard():
    assert rdap._registrar(RDAP_DOC) == "MarkMonitor Inc."


def test_rdap_registrar_missing_is_empty_not_crash():
    assert rdap._registrar({"entities": [{"roles": ["technical"]}]}) == ""


def test_rdap_parses_zulu_timestamp():
    parsed = rdap._parse_date("2001-10-02T18:10:32Z")
    assert parsed is not None and parsed.year == 2001
    assert parsed.tzinfo is not None, "必须是 aware datetime，否则与 now() 相减会抛异常"


def test_rdap_bad_date_returns_none():
    assert rdap._parse_date("不是日期") is None


# ------------------------------------------------------------------ github

def test_github_candidates_put_hints_first():
    got = _candidates("cursor.com", ["anysphere"])
    assert got[0] == "anysphere", "显式 hint 必须优先于猜测"
    assert "cursor" in got


def test_github_candidates_are_deduped_case_insensitively():
    got = _candidates("anthropic.com", ["Anthropic", "anthropic"])
    assert len([g for g in got if g.lower() == "anthropic"]) == 1

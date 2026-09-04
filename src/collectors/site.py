"""抓取站点首页，提取「线索」——注意：**首页内容本身不是证据**。

任何人都能在自己的网站上写「我是 Anthropic」。所以这里产出的东西一律只用于两个目的：

1. **给其他采集器指路**（发现 GitHub 组织、npm 包、Wikidata 条目）。
2. **锚点扩散的输入**（已 verified 域名的出站链接，见 ``propagate.py``）。

第 2 点成立的前提是「源域名已经 verified」—— 这个前提由 ``policy.py`` 的 A6 校验器把关，
不在这里判断。
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

from src.collectors.base import FetchError, Result, fetch
from src.policy import registrable_domain

GITHUB_ORG_RE = re.compile(r"github\.com/([A-Za-z0-9][A-Za-z0-9-]{0,38})(?:/|\"|'|\s|$)")
NPM_PKG_RE = re.compile(r"npmjs\.com/package/((?:@[a-z0-9-~][\w.-]*/)?[a-z0-9-~][\w.-]*)")
WIKIDATA_RE = re.compile(r"wikidata\.org/(?:wiki|entity)/(Q\d+)")

#: 这些 github 路径段不是组织名
GITHUB_RESERVED = frozenset({
    "features", "topics", "trending", "collections", "events", "sponsors", "about",
    "pricing", "enterprise", "login", "join", "explore", "marketplace", "apps",
    "orgs", "settings", "notifications", "search", "readme", "site", "security",
})


class _LinkExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        for key, value in attrs:
            if key == "href" and value:
                self.hrefs.append(value)


def collect(domain: str) -> Result:
    r = Result()
    html = None
    for candidate in (f"https://{domain}/", f"https://www.{domain}/"):
        try:
            html = fetch(candidate, ttl_hours=24)
            r.extra["fetched_url"] = candidate
            break
        except FetchError as exc:
            r.note(f"site: {exc}")
    if html is None:
        r.note(f"site: 无法抓取 {domain} 首页；后续采集器将只能依赖显式 hints")
        return r

    parser = _LinkExtractor()
    try:
        parser.feed(html)
    except Exception as exc:  # 残缺 HTML 很常见，不该让整条流水线挂掉
        r.note(f"site: HTML 解析中断（{type(exc).__name__}），改用正则兜底")

    orgs = {m.group(1) for m in GITHUB_ORG_RE.finditer(html)} - GITHUB_RESERVED
    r.extra["github_orgs"] = sorted(orgs)
    r.extra["npm_packages"] = sorted({m.group(1) for m in NPM_PKG_RE.finditer(html)})
    wikidata = {m.group(1) for m in WIKIDATA_RE.finditer(html)}
    if wikidata:
        r.extra["wikidata"] = sorted(wikidata)[0]

    # 出站的同族域名候选 —— 仅供 propagate.py 使用，此处不作任何归属判断
    self_site = registrable_domain(domain)
    siblings = set()
    for href in parser.hrefs:
        if href.startswith(("http://", "https://")):
            other = registrable_domain(href)
            if other and other != self_site and "." in other:
                siblings.add(other)
    r.extra["outbound_domains"] = sorted(siblings)

    r.note(
        f"site: 首页发现 GitHub 组织 {r.extra['github_orgs'] or '无'}，"
        f"npm 包 {len(r.extra['npm_packages'])} 个，出站域名 {len(siblings)} 个"
    )
    return r

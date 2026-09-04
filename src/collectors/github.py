"""A1：GitHub 组织已验证域名。

这是本项目对「AI / 开发者工具」品类最强、也最便宜的一条锚点：
``is_verified == true`` 意味着 **GitHub 已经代我们完成了 DNS 级别的域名控制权验证**。

关于「猜组织名」
----------------
我们会从域名推测候选组织名（anthropic.com → anthropic / anthropics / …）。
猜错没有风险 —— **猜测只是搜索启发式，判定由 policy.py 的 A1 校验器严格把关**：
组织必须 ``is_verified`` 且其 ``blog`` 的可注册域必须等于目标域名。猜错的候选会被直接拒掉。
"""

from __future__ import annotations

import os

from src.collectors.base import FetchError, Result, fetch_json, now
from src.policy import Evidence, registrable_domain

API = "https://api.github.com"


def _headers() -> dict[str, str]:
    # 未授权 60 次/小时，授权后 5000 次/小时。冷启动跑上万条时必须给 token。
    token = os.environ.get("GITHUB_TOKEN")
    h = {"Accept": "application/vnd.github+json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _candidates(domain: str, hints: list[str] | None) -> list[str]:
    label = registrable_domain(domain).split(".")[0]
    guesses = [label, f"{label}s", label.replace("-", ""), f"{label}-ai", f"{label}ai"]
    seen, out = set(), []
    for name in (hints or []) + guesses:
        low = name.lower()
        if low not in seen:
            seen.add(low)
            out.append(name)
    return out


def collect(domain: str, hints: list[str] | None = None) -> Result:
    r = Result()
    if not os.environ.get("GITHUB_TOKEN"):
        r.note("github: 未设置 GITHUB_TOKEN，速率限制 60 次/小时（冷启动前务必配置）")

    for login in _candidates(domain, hints):
        try:
            org = fetch_json(f"{API}/orgs/{login}", headers=_headers(), ttl_hours=24)
        except FetchError as exc:
            if "HTTP 404" not in str(exc):
                r.note(f"github: 查询组织 {login} 失败：{exc}")
            continue

        blog = org.get("blog") or ""
        verified = bool(org.get("is_verified"))
        matches = registrable_domain(blog) == registrable_domain(domain)

        if verified and matches:
            r.evidence.append(Evidence(
                code="A1",
                data={"org": login, "org_verified": True, "blog": blog,
                      "org_name": org.get("name"), "created_at": org.get("created_at")},
                checked_at=now(),
                source=f"{API}/orgs/{login}",
            ))
            r.extra["github_org"] = login
            r.note(f"github: 组织 {login} 已验证域名，blog={blog} ✓")
            return r

        if matches and not verified:
            # 有意义的负面信息：组织存在、blog 指向本域名，但**没做**域名验证。
            # 这正是负样本 fake-github-org-unverified 的形态，必须记录下来。
            r.evidence.append(Evidence(
                code="A1",
                data={"org": login, "org_verified": False, "blog": blog},
                checked_at=now(),
                source=f"{API}/orgs/{login}",
            ))
            r.extra.setdefault("github_org", login)
            r.note(f"github: 组织 {login} 的 blog 指向本域名，但未通过 GitHub 域名验证")
            return r

        if verified:
            r.note(f"github: 组织 {login} 已验证，但 blog={blog or '空'} 指向别的域名，不采纳")

    r.note("github: 未找到与本域名匹配的已验证组织")
    return r

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

import functools
import os
import shutil
import subprocess
from datetime import UTC

from src.collectors.base import FetchError, Result, fetch_json, now
from src.policy import Evidence, registrable_domain

API = "https://api.github.com"


@functools.lru_cache(maxsize=1)
def _token() -> str | None:
    """认证顺序：环境变量 GITHUB_TOKEN → 已登录的 gh CLI。

    借用 gh 的认证意味着 token 不需要出现在任何配置文件或对话里。
    未授权 60 次/小时，授权后 5000 次/小时——冷启动跑上万条时必须二者有其一。
    """
    if env := os.environ.get("GITHUB_TOKEN"):
        return env
    if shutil.which("gh"):
        try:
            out = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=10)
            if out.returncode == 0 and out.stdout.strip():
                return out.stdout.strip()
        except (subprocess.SubprocessError, OSError):
            pass
    return None


def auth_source() -> str:
    if os.environ.get("GITHUB_TOKEN"):
        return "env:GITHUB_TOKEN"
    return "gh-cli" if _token() else "none"


def _headers() -> dict[str, str]:
    h = {"Accept": "application/vnd.github+json"}
    if token := _token():
        h["Authorization"] = f"Bearer {token}"
    return h


# ---------------------------------------------------------------------------
# 「GitHub 项目史」锚定权威 + A8
# ---------------------------------------------------------------------------

def _contributor_count(full_name: str) -> int:
    """用 Link 头的 last page 数出贡献者数，只花一次请求。"""
    import re
    import urllib.request

    url = f"{API}/repos/{full_name}/contributors?per_page=1&anon=true"
    req = urllib.request.Request(url, headers={**_headers(), "User-Agent": "realurls-registry"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        link = resp.headers.get("Link", "")
    m = re.search(r'page=(\d+)>; rel="last"', link)
    return int(m.group(1)) if m else 1


def repo_history(org: str, r: Result | None = None) -> dict | None:
    """在组织下找一个满足项目史门槛的仓库；找到即返回其事实，找不到返回 None。

    门槛定义在 policy.py（REPO_ANCHOR_*）——它们是信任承诺的一部分，不在这里改。
    """
    from datetime import datetime

    from src.policy import (
        REPO_ANCHOR_MIN_AGE_DAYS,
        REPO_ANCHOR_MIN_CONTRIBUTORS,
        REPO_ANCHOR_MIN_STARS,
    )
    r = r or Result()
    # /orgs/{org}/repos 不支持按星排序（只支持 created/updated/pushed/full_name），
    # tensorflow 这种上百仓库的组织按字母序取前 30 个根本拿不到主仓库。用 search API 按星取。
    import urllib.parse
    q = urllib.parse.quote(f"org:{org} fork:false")
    try:
        repos = fetch_json(f"{API}/search/repositories?q={q}&sort=stars&order=desc&per_page=8",
                           headers=_headers(), ttl_hours=168).get("items", [])
    except FetchError as exc:
        r.note(f"github: 搜索组织 {org} 的仓库失败：{exc}")
        return None

    repos = [x for x in repos if not x.get("fork")]
    for repo in repos:
        stars = repo.get("stargazers_count", 0)
        if stars < REPO_ANCHOR_MIN_STARS:
            break
        created = datetime.fromisoformat(repo["created_at"].replace("Z", "+00:00"))
        age_days = (datetime.now(UTC) - created).days
        if age_days < REPO_ANCHOR_MIN_AGE_DAYS:
            continue
        try:
            contributors = _contributor_count(repo["full_name"])
        except Exception as exc:
            r.note(f"github: 数 {repo['full_name']} 贡献者失败：{type(exc).__name__}")
            continue
        if contributors < REPO_ANCHOR_MIN_CONTRIBUTORS:
            continue
        return {
            "repo": repo["full_name"], "org": org, "stars": stars,
            "age_days": age_days, "contributors": contributors,
            "homepage": repo.get("homepage") or "",
            "created_at": repo["created_at"],
        }
    return None


def collect_repo_link(domain: str, org: str, repo_info: dict | None,
                      site_github_orgs: list[str]) -> Result:
    """A8：已锚定仓库的 homepage 指向本域名 + 本域名首页反向链回该组织。

    只翻译事实，不判断——是否算数由 policy.py 的 A8 校验器决定。
    """
    r = Result()
    if not repo_info:
        r.note(f"github: 组织 {org} 无满足项目史门槛的仓库，A8 不适用")
        return r
    backlink = org.lower() in {o.lower() for o in site_github_orgs}
    r.evidence.append(Evidence(
        code="A8",
        data={
            "repo": repo_info["repo"], "org": org, "repo_anchored": True,
            "homepage": repo_info["homepage"], "backlink": backlink,
            "stars": repo_info["stars"], "age_days": repo_info["age_days"],
            "contributors": repo_info["contributors"],
        },
        checked_at=now(),
        source=f"{API}/repos/{repo_info['repo']}",
    ))
    r.note(f"github: A8 候选 {repo_info['repo']} homepage={repo_info['homepage'] or '空'}，"
           f"首页反链={'有' if backlink else '无'}")
    return r


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
    src = auth_source()
    if src == "none":
        r.note("github: 无认证（未设 GITHUB_TOKEN，gh 也未登录），速率限制 60 次/小时")
    else:
        r.note(f"github: 认证来源 {src}，5000 次/小时")

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

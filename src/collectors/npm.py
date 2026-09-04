"""A2：包 provenance → GitHub 仓库 → 已验证组织。B2：包 homepage 字段。

信任模型说明（重要）
--------------------
npm 的 attestation 端点返回 sigstore bundle。**我们目前不做 sigstore 签名的密码学验证**
（那需要引入完整的 sigstore 客户端）。我们做的是：通过 TLS 向
``registry.npmjs.org`` 索取该包的 attestation，解出其中 in-toto 声明的源仓库。

因此 A2 的信任锚是「npm registry 的 TLS + npm 对发布流程的把关」，
与 A1 的信任锚（api.github.com 的 TLS + GitHub 的域名验证）是同一量级，**而非**
「sigstore 密码学证明」。POLICY.md 里如实标注了这一点。

补上真正的签名验证是明确的加固项（TODO），但它不改变当前的信任层级 ——
能伪造 npm registry HTTPS 响应的攻击者，同样能伪造 GitHub API 响应。
"""

from __future__ import annotations

import base64
import json
import re

from src.collectors.base import FetchError, Result, fetch_json, now
from src.policy import Evidence, registrable_domain

REGISTRY = "https://registry.npmjs.org"
REPO_RE = re.compile(r"github\.com[:/]([A-Za-z0-9-]+)/([A-Za-z0-9._-]+)")


def _repo_org(text: str) -> str | None:
    m = REPO_RE.search(text or "")
    return m.group(1) if m else None


def _attestation_repo_org(pkg: str, version: str, r: Result) -> str | None:
    """从 npm attestation 的 in-toto 声明里解出源仓库归属组织。"""
    url = f"{REGISTRY}/-/npm/v1/attestations/{pkg}@{version}"
    try:
        doc = fetch_json(url, ttl_hours=168)
    except FetchError as exc:
        r.note(f"npm: 未取到 {pkg}@{version} 的 attestation（{exc}）")
        return None

    for att in doc.get("attestations", []):
        envelope = (att.get("bundle") or {}).get("dsseEnvelope") or {}
        payload = envelope.get("payload")
        if not payload:
            continue
        try:
            statement = json.loads(base64.b64decode(payload))
        except Exception as exc:
            r.note(f"npm: attestation payload 解析失败（{type(exc).__name__}）")
            continue
        blob = json.dumps(statement)
        org = _repo_org(blob)
        if org:
            return org
    return None


def collect(domain: str, packages: list[str] | None = None,
            github_org: str | None = None) -> Result:
    r = Result()
    if not packages:
        r.note("npm: 没有候选包名（可用 --npm 指定，或由站点首页链接自动发现）")
        return r

    for pkg in packages[:5]:
        try:
            doc = fetch_json(f"{REGISTRY}/{pkg.replace('/', '%2F')}", ttl_hours=72)
        except FetchError as exc:
            r.note(f"npm: 取包 {pkg} 失败：{exc}")
            continue

        latest_tag = (doc.get("dist-tags") or {}).get("latest")
        latest = (doc.get("versions") or {}).get(latest_tag, {})

        homepage = latest.get("homepage") or doc.get("homepage") or ""
        if homepage and registrable_domain(homepage) == registrable_domain(domain):
            r.evidence.append(Evidence(
                code="B2",
                data={"package": pkg, "homepage": homepage},
                checked_at=now(),
                source=f"{REGISTRY}/{pkg}",
            ))
            r.note(f"npm: {pkg} 的 homepage 指向本域名 ✓")

        if not (latest.get("dist") or {}).get("attestations"):
            r.note(f"npm: {pkg}@{latest_tag} 无 provenance attestation")
            continue

        chain_org = _attestation_repo_org(pkg, latest_tag, r)
        if not chain_org:
            r.note(f"npm: {pkg} 有 attestation 但未能解出源仓库")
            continue

        # 链末端组织是否已验证域名，交给 github 采集器复用；这里只记录链条本身。
        r.evidence.append(Evidence(
            code="A2",
            data={
                "package": pkg,
                "version": latest_tag,
                "provenance_verified": True,
                "provenance_check": "registry-tls",   # 非 sigstore 密码学验证，见模块 docstring
                "chain_org": chain_org,
                "chain_org_verified": bool(github_org and chain_org.lower() == github_org.lower()),
                "chain_blog": f"https://{domain}" if github_org and
                              chain_org.lower() == github_org.lower() else "",
            },
            checked_at=now(),
            source=f"{REGISTRY}/-/npm/v1/attestations/{pkg}@{latest_tag}",
        ))
        r.note(f"npm: {pkg} provenance → github.com/{chain_org}")

    return r

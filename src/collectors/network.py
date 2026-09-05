"""A4 证书组织字段、A5 DNS TXT 自证，以及锚点扩散需要的结构性关联信号。

关于 A4 的现实
--------------
实测 ``anthropic.com`` 的 462 张有效证书全部来自 Let's Encrypt 与 Google Trust Services，
**都是 DV 证书，Subject 里没有任何组织信息**。所以 A4 对现代科技公司基本不会触发，
它只对银行、政府、老牌上市公司有效。这是预期行为，不是采集失败。

顺带纠正一个常见的反向直觉：**使用免费/短周期证书不是可疑信号**。
今天绝大多数大厂（含 Cloudflare 全线）都在用 ACME 90 天证书。
"""

from __future__ import annotations

import socket
import ssl
import urllib.parse

from src.collectors.base import FetchError, Result, fetch_json, now
from src.policy import Evidence

DOH = "https://cloudflare-dns.com/dns-query?name={}&type={}"
DOH_HEADERS = {"Accept": "application/dns-json"}


def _dns(name: str, rrtype: str) -> list[str]:
    url = DOH.format(urllib.parse.quote(name), rrtype)
    doc = fetch_json(url, headers=DOH_HEADERS, ttl_hours=6)
    return [a["data"].strip('"').rstrip(".") for a in doc.get("Answer", [])]


# ------------------------------------------------------------------ A4 证书

def certificate(domain: str) -> Result:
    r = Result()
    ctx = ssl.create_default_context()
    cert = None
    last_exc: Exception | None = None
    # 重试一次：220 条批跑里 deezer.com 因一次握手超时丢了 A4，从 verified 掉到 community。
    # 「没采到」和「采到了是否定」是两回事——采集失败不该直接变成降级（见 SECURITY.md T5 的保鲜设计）。
    for attempt, timeout in enumerate((10, 20), 1):
        try:
            with socket.create_connection((domain, 443), timeout=timeout) as sock:
                with ctx.wrap_socket(sock, server_hostname=domain) as tls:
                    cert = tls.getpeercert()
            break
        except Exception as exc:
            last_exc = exc
    if cert is None:
        r.note(f"tls: 握手失败（重试 2 次）：{type(last_exc).__name__}: {last_exc}")
        r.facts["collection_incomplete"] = True
        return r

    subject = {k: v for rdn in cert.get("subject", ()) for k, v in rdn}
    issuer = {k: v for rdn in cert.get("issuer", ()) for k, v in rdn}
    org = subject.get("organizationName", "")
    sans = [v for k, v in cert.get("subjectAltName", ()) if k == "DNS"]
    r.extra["cert_sans"] = sans

    r.evidence.append(Evidence(
        code="A4",
        data={
            "subject_org": org,
            "validation_type": "OV" if org else "DV",
            "issuer": issuer.get("organizationName", ""),
            "san_count": len(sans),
        },
        checked_at=now(),
        source=f"TLS handshake {domain}:443",
    ))
    if org:
        r.note(f"tls: 证书 Subject O={org}（OV/EV）")
    else:
        r.note(f"tls: DV 证书无组织信息（签发方 {issuer.get('organizationName', '未知')}）—— 属预期，不减分")
    return r


# ------------------------------------------------------------------ A5 自证

def self_attestation(domain: str, expected_token: str | None = None) -> Result:
    """查 ``_realurls.<domain>`` 的 TXT 记录。域名控制者对自己的域名有最终解释权。"""
    r = Result()
    try:
        records = _dns(f"_realurls.{domain}", "TXT")
    except FetchError as exc:
        r.note(f"dns: _realurls TXT 查询失败：{exc}")
        return r

    tokens = [t.split("=", 1)[1] for t in records if t.startswith("realurls-site-verification=")]
    if not tokens:
        r.note("dns: 无 _realurls TXT 记录（A5 未启用；冷启动阶段属常态）")
        return r

    match = expected_token in tokens if expected_token else False
    r.evidence.append(Evidence(
        code="A5",
        data={"token_match": match, "found": len(tokens)},
        checked_at=now(),
        source=f"_realurls.{domain} TXT",
    ))
    r.note(f"dns: 发现 {len(tokens)} 条自证 token，匹配={match}")
    return r


# --------------------------------------------------- 锚点扩散用的结构性信号

def structural_links(domain: str, other: str) -> Result:
    """判断两个域名是否共享基础设施 —— 用于 A6 的结构性关联要求。

    单独出现不构成任何证据；只有当源域名**已经 verified** 时，
    它才能把归属扩散到同族域名（校验逻辑在 policy.py 的 A6 里）。
    """
    r = Result()
    links: list[str] = []

    try:
        ns_a = {n.lower() for n in _dns(domain, "NS")}
        ns_b = {n.lower() for n in _dns(other, "NS")}
        if ns_a & ns_b:
            links.append("shared_ns")
            r.note(f"link: {domain} 与 {other} 共享 NS {sorted(ns_a & ns_b)[:2]}")
    except FetchError as exc:
        r.note(f"link: NS 比对失败：{exc}")

    cert = certificate(domain)
    raw_sans = cert.extra.get("cert_sans", [])
    sans = {s.lstrip("*.").lower() for s in raw_sans}
    if any(s == other or s.endswith(f".{other}") for s in sans):
        links.append("cert_san")
        r.note(f"link: {domain} 的证书 SAN 覆盖 {other}（共 {len(raw_sans)} 个 SAN）")

    r.extra["structural_links"] = links
    r.extra["san_count"] = len(raw_sans)   # policy 用它识别 CDN 共享证书
    if not links:
        r.note(f"link: {domain} 与 {other} 无结构性关联 —— 不能扩散")
    return r

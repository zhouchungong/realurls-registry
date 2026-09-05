"""A3：企业注册指纹 + 域龄。

**重要背景**：GDPR 之后 ``.com`` 的注册人字段基本全被隐去。实测 ``anthropic.com`` 的
RDAP 响应里只剩注册商，没有任何 registrant 组织信息。所以「RDAP 注册主体 = 实体法定名称」
这条路走不通，本采集器**不试图**从 RDAP 读取所有者身份。

我们改用的是**成本壁垒**：企业级注册商（年费数百美元 + 企业实名）+ 长期预付 +
注册局锁 + 多年域龄。它证明不了「是谁」，但能证明「不是随手注册的一次性域名」。
权重因此在所有锚点里最低（0.55）。
"""

from __future__ import annotations

from datetime import datetime

from src.collectors.base import FetchError, Result, fetch_json, now
from src.policy import Evidence

BOOTSTRAP = "https://rdap.org/domain/{}"


def _parse_date(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _registrar(doc: dict) -> str:
    for entity in doc.get("entities", []):
        if "registrar" in (entity.get("roles") or []):
            vcard = entity.get("vcardArray") or []
            if len(vcard) > 1:
                for field in vcard[1]:
                    if field and field[0] == "fn":
                        return str(field[3])
    return ""


def collect(domain: str) -> Result:
    r = Result()
    try:
        doc = fetch_json(BOOTSTRAP.format(domain), ttl_hours=72)
    except FetchError as exc:
        r.note(f"rdap: 查询失败：{exc}（域龄未知，policy 将跳过新域名门槛判断）")
        return r

    events = {e.get("eventAction"): _parse_date(e.get("eventDate", "")) for e in doc.get("events", [])}
    created, expires = events.get("registration"), events.get("expiration")
    registrar = _registrar(doc)
    locks = [s.replace("client ", "").replace(" prohibited", "")
             for s in doc.get("status", []) if "prohibited" in s]

    if created:
        r.facts["age_days"] = (now() - created).days
    else:
        r.note("rdap: 响应中没有注册日期，域龄未知")

    remaining = (expires - now()).days if expires else 0

    r.evidence.append(Evidence(
        code="A3",
        data={
            "registrar": registrar,
            "created": created.date().isoformat() if created else None,
            "expires": expires.date().isoformat() if expires else None,
            "remaining_days": remaining,
            "locks": locks,
        },
        checked_at=now(),
        source=BOOTSTRAP.format(domain),
    ))
    r.note(
        f"rdap: 注册商={registrar or '未知'}，注册于 "
        f"{created.date() if created else '未知'}，剩余 {remaining} 天，{len(locks)} 把锁"
    )

    # 记录下来供人查阅：注册人确实是空的，不是我们漏采了。
    has_registrant = any("registrant" in (e.get("roles") or []) for e in doc.get("entities", []))
    if not has_registrant:
        r.note("rdap: 无 registrant 实体（GDPR 隐去），符合预期，不作为缺陷")

    return r

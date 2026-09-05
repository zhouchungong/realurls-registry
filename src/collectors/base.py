"""采集器公共设施：带缓存的 HTTP、统一的返回结构。

三条规矩：

1. **一切响应落盘缓存**（``.cache/``）。证据必须可离线重放 —— 否则我们无法向别人
   证明「当时看到的就是这个」，也无法在改规则后回放历史数据。
2. **采集器不做判断**。它们只把外部世界翻译成 ``Evidence``，是否算数由 ``policy.py`` 决定。
   这条边界一旦模糊，规则就会散落到十个文件里，再也审不动。
3. **失败要说话，不要静默**。拿不到数据时返回 note，而不是当作「没有这条证据」。
   「没查到」和「查了但没有」在信任系统里是两回事。
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.policy import Evidence

CACHE_DIR = Path(__file__).resolve().parents[2] / ".cache"
USER_AGENT = "realurls-registry/0.0.1 (+https://github.com/zhouchungong/realurls-registry)"
DEFAULT_TTL_HOURS = 24


@dataclass
class Result:
    """一个采集器的产出。"""

    evidence: list[Evidence] = field(default_factory=list)
    facts: dict[str, Any] = field(default_factory=dict)   # 合并进 DomainFacts 的字段
    notes: list[str] = field(default_factory=list)        # 人类可读的采集过程说明
    extra: dict[str, Any] = field(default_factory=dict)   # 供其他采集器使用的中间结果

    def note(self, msg: str) -> None:
        self.notes.append(msg)


class FetchError(Exception):
    pass


def _cache_path(url: str) -> Path:
    return CACHE_DIR / f"{hashlib.sha256(url.encode()).hexdigest()[:32]}.json"


def fetch(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    ttl_hours: float = DEFAULT_TTL_HOURS,
    timeout: int = 20,
    accept_status: tuple[int, ...] = (200,),
) -> str:
    """GET 一个 URL，返回文本。命中缓存则不发请求。

    非 ``accept_status`` 的响应抛 :class:`FetchError` —— 调用方必须显式处理，
    不允许把「404」和「拿到了空数据」混为一谈。
    """
    cache = _cache_path(url)
    if cache.exists():
        payload = json.loads(cache.read_text(encoding="utf-8"))
        if time.time() - payload["fetched_at"] < ttl_hours * 3600:
            if payload["status"] not in accept_status:
                raise FetchError(f"{url} -> HTTP {payload['status']}（缓存）")
            return payload["body"]

    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status, body = resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        status, body = exc.code, exc.read().decode("utf-8", errors="replace")
    except Exception as exc:  # 网络层错误不缓存 —— 下次应该重试
        raise FetchError(f"{url} -> {type(exc).__name__}: {exc}") from exc

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(
        json.dumps({"url": url, "status": status, "body": body, "fetched_at": time.time()}),
        encoding="utf-8",
    )
    if status not in accept_status:
        raise FetchError(f"{url} -> HTTP {status}")
    return body


def fetch_json(url: str, **kwargs: Any) -> Any:
    return json.loads(fetch(url, **kwargs))


def now() -> datetime:
    return datetime.now(UTC)

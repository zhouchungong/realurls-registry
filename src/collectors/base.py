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
    status, body = _request(req, timeout)

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(
        json.dumps({"url": url, "status": status, "body": body, "fetched_at": time.time()}),
        encoding="utf-8",
    )
    if status not in accept_status:
        raise FetchError(f"{url} -> HTTP {status}")
    return body


RETRY_STATUSES = (429, 500, 502, 503, 504)
MAX_ATTEMPTS = 4


def _request(req: urllib.request.Request, timeout: int) -> tuple[int, str]:
    """One HTTP exchange with bounded retries on transient failures (429 / 5xx / network errors).

    At 40k seeds a 0.5% transient-failure rate is 200 lost lookups per run, and a lost lookup is recorded
    as "not found" downstream. Retries use exponential backoff and honour ``Retry-After``. Only transient
    statuses retry; 4xx other than 429 is the server's answer and is returned as-is.
    """
    last_exc: Exception | None = None
    for attempt in range(MAX_ATTEMPTS):
        wait = 2.0 ** attempt
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            if exc.code not in RETRY_STATUSES or attempt == MAX_ATTEMPTS - 1:
                return exc.code, body
            retry_after = exc.headers.get("Retry-After")
            if retry_after and retry_after.isdigit():
                wait = min(float(retry_after), 60.0)
            last_exc = exc
        except Exception as exc:  # network-layer error: never cached, retried, then raised
            last_exc = exc
            if attempt == MAX_ATTEMPTS - 1:
                break
        time.sleep(wait)
    raise FetchError(f"{req.full_url} -> {type(last_exc).__name__}: {last_exc}") from last_exc


def cache_get(key: str, ttl_hours: float) -> Any | None:
    """Read a bulk-prefetched payload by logical key (not a URL). Same on-disk format as fetch()."""
    cache = _cache_path(key)
    if not cache.exists():
        return None
    payload = json.loads(cache.read_text(encoding="utf-8"))
    if time.time() - payload["fetched_at"] >= ttl_hours * 3600:
        return None
    return json.loads(payload["body"])


def cache_put(key: str, value: Any, *, status: int = 200) -> None:
    """Store a payload under a logical key or a URL. A URL key primes ``fetch()`` for that exact URL,
    which is how bulk prefetchers feed the per-domain collectors without changing them."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _cache_path(key).write_text(
        json.dumps({"url": key, "status": status, "body": json.dumps(value), "fetched_at": time.time()}),
        encoding="utf-8",
    )


def cache_status(key: str, ttl_hours: float) -> int | None:
    """HTTP status of a cached entry (None if absent or expired). Lets prefetchers skip cached 404s."""
    cache = _cache_path(key)
    if not cache.exists():
        return None
    payload = json.loads(cache.read_text(encoding="utf-8"))
    if time.time() - payload["fetched_at"] >= ttl_hours * 3600:
        return None
    return int(payload["status"])


def post_json(url: str, payload: Any, *, headers: dict[str, str] | None = None, timeout: int = 60) -> Any:
    """POST JSON and return the decoded response. Not cached here: callers cache by logical key."""
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), method="POST",
        headers={"User-Agent": USER_AGENT, "Content-Type": "application/json", **(headers or {})},
    )
    status, body = _request(req, timeout)
    if status != 200:
        raise FetchError(f"{url} -> HTTP {status}")
    return json.loads(body)


def fetch_json(url: str, **kwargs: Any) -> Any:
    return json.loads(fetch(url, **kwargs))


def now() -> datetime:
    return datetime.now(UTC)

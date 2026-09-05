"""Bulk prefetch and sharding for seed runs.

The per-domain pipeline spends most of its 25 seconds waiting on rate-limited APIs, one call per
domain. This module pulls the same facts for a whole seed file in a few bulk calls and writes them
into the collectors' cache, so ``verify()`` runs unchanged and simply finds the answers already there.
Nothing here judges anything: the collectors still translate, ``policy.py`` still decides.

Used by ``build_entities`` and ``batch`` before their per-seed loop, and by the CI matrix that splits a
seed file across runners (``--shard i/N``).
"""

from __future__ import annotations

import sys

from src.collectors import github, thirdparty
from src.collectors.thirdparty import _tranco_local


def prefetch(seeds: list[dict]) -> None:
    domains = [s["domain"] for s in seeds]
    orgs = [s.get("github_org") for s in seeds if s.get("github_org")]
    guesses: list[str] = []
    for s in seeds:
        guesses.extend(github._candidates(s["domain"], [s["github_org"]] if s.get("github_org") else None))

    _tranco_local()
    n_wd = thirdparty.prefetch_wikidata(domains)
    n_org = github.prefetch_orgs(guesses)
    n_repo = github.prefetch_repos(orgs)
    print(f"# prefetch: wikidata {n_wd}, github orgs {n_org}, github repos {n_repo} (rest was cached)",
          file=sys.stderr)


def shard(seeds: list[dict], spec: str | None) -> list[dict]:
    """``"3/16"`` keeps every seed whose index ≡ 3 (mod 16). Deterministic, so shards never overlap."""
    if not spec:
        return seeds
    i, n = (int(x) for x in spec.split("/"))
    if not 0 <= i < n:
        raise ValueError(f"shard {spec}: index must be in [0, {n})")
    return [s for k, s in enumerate(seeds) if k % n == i]

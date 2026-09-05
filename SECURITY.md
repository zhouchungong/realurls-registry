# SECURITY.md

中文版：[docs/zh/SECURITY.md](docs/zh/SECURITY.md)

## Threat model

What makes this repository unusual: **we are the highest-value target ourselves.**

A poisoned "real official sites" database does more harm than the problem it solves — we would hand users to phishing sites, and users would drop their guard precisely because they trust us.

### Threats

| # | threat | mitigation |
|---|---|---|
| T1 | A crafted pull request launders a lookalike domain into the data | **Humans cannot write data.** The community submits leads (issues); data is produced only by the pipeline (§1) |
| T2 | A tired reviewer approves a bad change | Data PRs are opened by the bot with the full evidence and reasoning attached; two-person approval via `CODEOWNERS` |
| T3 | GitHub Actions supply-chain poisoning | Every action is **pinned to a commit SHA**, never a floating tag |
| T4 | Maintainer account compromise | Mandatory 2FA, branch protection, no force-push, the bot uses OIDC rather than long-lived tokens |
| T5 | A listed domain expires and is re-registered, or is hijacked | Daily re-verification plus mutation monitoring (NS/A/registrar/expiry/org status) → `review_required` |
| T6 | Data tampered with in transit | Every release is **cosign-signed**; API responses carry the dataset version and content hashes |
| T7 | An upstream source is poisoned or captured (e.g. a GitHub organization changes hands) | No single piece of evidence decides; ≥1 anchor + ≥2 independent corroborations; correlated evidence counted once. **Seen in practice:** anyone can add a Wikidata P856 claim — for `claude.ai` we once retrieved a junk item whose label was a Chinese newspaper headline (Q116755258). Item types are now restricted (`P31/P279*` ∈ organization/company/software/website) and ordered by sitelink count |
| T8 | The rules are loosened gradually | Threshold changes need two-person approval, the full adversarial corpus, and a dataset diff stating the impact (POLICY.md §4) |
| T9 | Dependency poisoning (a hijacked PyPI package) | Dependencies pinned to exact versions with hashes; CI installs with `--require-hashes` |

### Explicitly out of scope

- We do **not** try to detect malicious site content — that is the job of antivirus and security vendors.
- We do **not** claim to withstand a nation-state, targeted attack. If you can simultaneously forge a GitHub organization verification, a corporate registration fingerprint and years of Wayback history, we cannot stop you and do not pretend to.

## 1. The write path (the only legitimate one)

```
issue form (a lead) → bot collects evidence → policy.decide() → enough: bot merges after corpus + AI review
                                                               → not enough: closed automatically, missing piece named
                              ↓
                     humans review (read only, never edit)
```

Any **direct human commit** touching `entities/**.yaml` must be rejected by CI. That rule itself has a test.

## 2. Reporting

- **A data error** (a lookalike marked official, an official domain attributed wrongly): the most serious class of issue we have. Open an issue with the `dispute` template or email `dispute@realurls.org`. **Within 48 hours** the record is downgraded to `disputed` and positive API answers stop — harm first, investigation second.
- **A code or infrastructure vulnerability**: please do not open a public issue; email `security@realurls.org`.

## 3. Our commitments

- Every correction stays in git history and in `CORRECTIONS.md`; **nothing is quietly deleted**.
- After any serious misjudgement we publish a post-mortem: how it happened, why the rules did not catch it, which adversarial case was added.

A trust source that hides its own error record does not deserve trust.

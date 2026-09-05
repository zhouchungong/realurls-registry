# POLICY.md — the decision rules

This file is the human-readable mirror of [`src/policy.py`](src/policy.py).
**If they disagree, the code wins** — and please open an issue saying the document is stale. 中文版：[docs/zh/POLICY.md](docs/zh/POLICY.md)

---

## 0. Anchor the entity first, then judge the domain

**Control is not identity.** A1 (GitHub-verified organization domain), A2 (package provenance) and A5 (DNS self-attestation) all prove that *some party controls this domain* — not that *this domain belongs to entity X*. An attacker can perfectly well register `claude-desktop.io`, create a GitHub organization named "Claude" and verify it. The control is real; the identity is fake.
(This exact chain was constructed during review; before the fix it was judged verified at 0.85. See `attacker-controlled-verified-org` in `tests/negative_corpus.yaml`.)

So the decision has two phases:

```
Phase 1  Entity anchoring (src/anchor.py)
         Establish the entity's canonical identifiers from an independent authority — either:
           ① a Wikidata item whose P856 points at the domain, whose type is organization/company/
              software/website, and which has ≥ 3 sitelinks
              → canonical GitHub organization = the item's P2037 or P1324; canonical Wikidata = its QID
           ② GitHub project history: the organization owns a non-fork repository created ≥ 3 years ago
              with ≥ 300 contributors and ≥ 5,000 stars
              → canonical GitHub organization = that organization; the repository is recorded in canonical.sources
         or a human-reviewed value (recorded as human:*, stored with the entity for reviewers to check)
         Display name (names.en): the Wikidata label if there is one, otherwise the GitHub organization's
         display name — a self-declared field used for display only, never for judgement, and labelled
         self-declared in provenance.label_source

Phase 2  Domain verification (src/policy.py)
         A1 / A2 count only if the organization == the canonical GitHub organization
         B1      counts only if the QID == the canonical Wikidata item
```

**An entity that cannot be anchored tops out at provisional.** A "company" that exists in neither Wikidata, an app store nor a package registry is not one we can vouch for. The threshold is sitelink count, not mere existence: creating a Wikidata item costs nothing; getting three language editions of Wikipedia to write about you does not.

**Why authority ② exists:** in a survey of 220 real organizations, Wikidata could anchor only 17% — it covers companies, not open-source projects, and half of our first category is open-source projects. Project history is another thing an attacker cannot buy: stars can be purchased, but a repository that started three years ago with 300 distinct contributors cannot; pushing someone else's history into a new repository exposes `created_at`; forks inherit upstream contributors, so forks are excluded. The survey contained openclaw.ai (0.8 years, 380k stars) and career-ops.org (0.3 years, 70k stars, 356 contributors) — exactly why the age floor exists. **Star counts alone would be a disaster.**

In propagation (A6) the target domain **inherits the anchor domain's entity**: claude.ai belongs to Anthropic (Q116758847), not to the "Claude" product item.

## 1. Evidence tiers

### 1.1 Anchors (Tier A) — at least 1 required

An anchor answers "who controls this domain" and is either hard to forge or expensive to fake.

| code | evidence | weight | validity |
|---|---|---|---|
| **A5** | DNS TXT self-attestation `_realurls.<domain>` | 0.90 | token matches |
| **A1** | GitHub organization verified this domain | 0.80 | `is_verified == true`, `blog` registrable domain == target, **and org == canonical GitHub org** |
| **A7** | Restricted government TLD | 0.80 | suffix ∈ `.gov` `.gov.uk` `.gov.cn` `.gouv.fr` `.go.jp` … (registries that only accept government bodies; proves "a government site", not "which department") |
| **A2** | Package provenance → repository → verified organization | 0.75 | provenance verified, **and** chain-end org verified, **and** its blog matches, **and chain end == canonical GitHub org** |
| **A9** | App Store history | 0.55 | an app sold to this domain (seller URL) by an Apple-verified company, where the seller or the app is named like the anchored entity, on the store **at least 2 years with at least 1,000 ratings**. The commercial counterpart of A8: Apple checks the seller's legal identity, and the years on the store cannot be bought |
| **A4** | TLS certificate Subject `O=` | 0.70 | **OV/EV** certificate whose `O=` names **the anchored entity** (label or canonical GitHub organization, legal suffixes ignored). An OV certificate for another organization proves control, not ownership |
| **A6** | Propagation | 0.65 | source domain is itself `verified`, **and the source's page links to this domain (first-party declaration)**, **and** ≥1 structural link; with `cert_san` alone, SAN count ≤ 25; **and** this domain's page, if it has outbound links at all, links back to the source |
| **A8** | Anchored repository homepage → this domain | 0.60 | repository meets the project-history bar, **and** org == canonical, **and** homepage registrable domain == this domain, **and** this site links back to the org, **and** this domain is not a platform domain (discord.gg / x.com / github.io …) |
| **A3** | Corporate registration fingerprint | 0.55 | **brand-protection** registrar, **and** ≥1095 days to expiry, **and** ≥2 registry locks, **and** domain age ≥730 days |

**Why A6 needs both conditions:** with structural links only, Cloudflare and others hand out nameserver pairs from a shared pool, and an attacker can recreate accounts until they collide; with the first-party link only, a verified site's footer also links to linkedin.com and x.com, which are not its assets. An attacker would need both "make anthropic.com's homepage link to me" and "collide on the NS pair" — the first is out of reach.

**Why A8 is weighted below A1:** A1 has a DNS-level control check performed by GitHub; A8 has only repository metadata. But for open-source projects whose organization never verified a domain (60% of the survey), A8 is the only evidence that ties the domain to an anchored identity. The platform-domain exclusion is a field lesson: yt-dlp's homepage field says discord.gg. The back-link requirement guards against a domain changing hands while the repository still points at it.

**A3's registrar list is brand-protection registrars only** (MarkMonitor, CSC, Com Laude, Safenames, Nom-IQ, IP Mirror, GoDaddy Corporate…). Review removed Amazon Registrar (Route 53 — anyone, $12/year), Google LLC, InterNetX and Ascio (wholesale). **Why A3 is the weakest anchor:** a corporate fingerprint proves "can afford it" (brand-protection registrars charge hundreds a year and require corporate identity). It is a cost barrier, not identity. It stops 99% of commodity abuse and none of a funded, targeted attack.

**A2's trust anchor, stated plainly:** we do **not** perform sigstore cryptographic verification yet. We fetch the attestation from `registry.npmjs.org` over TLS and read the source repository from its in-toto statement. A2's trust anchor is therefore "npm's TLS plus npm's publishing controls" — **the same tier as A1's** (GitHub's TLS plus GitHub's domain verification), not a cryptographic proof. Real signature verification is a listed hardening item; it does not change the tier, because anyone who can forge npm's HTTPS responses can forge GitHub's.

**Why A1 is weighted so high:** `is_verified == true` means GitHub already performed a DNS-level domain-control verification for us. It is a strong chain we get for free, with very high coverage in the AI / developer-tools category.

### 1.2 Corroborations (Tier B) — verified needs ≥ 2

Corroborations cannot prove control; they show that several independent authorities treat the domain as the entity's official site.

| code | evidence | weight | validity |
|---|---|---|---|
| B1 | Wikidata P856 | 0.12 | item type ∈ organization/company/software/website (`P31/P279*`) **and QID == canonical Wikidata** |
| B4 | Wayback first snapshot + continuity | 0.12 | history ≥ 365 days |
| B3 | App-store developer website field | 0.10 | — |
| B6 | Official social profile links | 0.10 | — |
| B2 | Package registry homepage / repository | 0.08 | — |
| B5 | Tranco / Radar ranking | 0.06 | rank ≤ 1,000,000 |
| B7 | Google Safe Browsing: no record | 0.05 | not flagged (a flag can **never** count as positive corroboration) |

**Why B1 restricts the item type:** anyone can edit Wikidata, and adding a P856 claim pointing at a phishing domain costs nothing. Our first query returned, for `claude.ai`, a junk item whose label was a Chinese newspaper headline (Q116755258). Without the type filter, B1 would be a corroboration anyone can manufacture. See SECURITY.md T7.

### 1.3 Independence of evidence (easy to miss, critical)

**Three pieces of evidence derived from each other are not three independent pieces.**

- **A1 / A2 / A8 count once**: all three rest on the same GitHub organization; if the organization is taken over, all three fall together. Only the highest-weighted one is counted.
- **A2 implies B2**: provenance is far stronger than a `homepage` field, so B2 is not counted again.

See `CORRELATED_ANCHOR_GROUPS` and `IMPLIED_CORROBORATIONS`.

---

## 2. Decision flow

```
① Hard vetoes (no amount of evidence overrides them)
   ├── Safe Browsing flag, or ≥2 VirusTotal engines malicious   → flagged
   ├── conflicts with another verified claim                     → disputed
   └── key attribute changed (NS/A/registrar/expiry/org status)  → review_required

② Freshness
   └── previous_status == verified and past TTL (default 30 days) → stale

③ Validate evidence → drop invalid pieces → merge correlated pieces

④ Domain-age floor (unknown is treated as worst case)
   ├── age < 180 days and no A5                                  → unverified
   └── age unknown and no A5/A7                                  → provisional at most
       (rdap.org returns 404 for many ccTLDs — .de .io .cn .so .ch .jp …
         The pipeline uses the first Wayback snapshot as a lower bound on age — a domain
         cannot be younger than its first snapshot — and only counts age as unknown when
         that fails too.)

⑤ Verdict
   ├── anchors ≥1 and corroborations ≥2  → verified
   ├── anchors ≥1                        → provisional (21-day public review)
   ├── corroborations ≥3                 → community
   └── otherwise                         → unverified
```

**Every rejected piece of evidence carries a reason**, shown verbatim in API responses and on entity pages. Explainability is part of the public promise, not a debugging feature.

### 2.1 Confidence

Independent evidence is combined as `confidence = 1 − Π(1 − w)`.

Caps: `provisional` 0.75, `community` 0.50, `unverified` 0.30; hard vetoes are 0.
**Confidence is used for ordering and display only; it never decides the status** — the status comes solely from the counting rules above. This is deliberate: a weighted score that can be "farmed" would eventually be reverse-engineered and pushed over the threshold.

---

## 3. The precision constraint

**Precision ≥ 99.5%** is the project's only non-negotiable metric. Coverage is a soft goal.

How it is enforced:

1. **Adversarial regression** (`tests/negative_corpus.yaml`): every case asserts `!= verified`. Any case turning green is a P0 incident.
2. **Manual sampling**: before each dataset release, 200 `verified` records are checked by hand. Below 99.5%, the rules are rolled back and nothing ships. The draw is reproducible (`python -m src.audit_sample draw --batch <name>`), the filled checklist is committed under `audits/` so anyone can re-check it, and `score` computes the number the decision is made on.
3. **Every fixed false positive adds a case to the adversarial corpus.**
5. **On-demand examination** (`src/examine.py`, every ten minutes): a domain someone asked about and we had never examined goes through the same pipeline. A record that reaches `verified` is merged by the bot after the adversarial corpus and the AI review pass, without waiting for a batch; it joins the pool the next manual sample is drawn from. Anything less is recorded as *examined* with the rules' reasons, so the API answers "examined on this date, insufficient evidence" rather than "never looked".
4. **AI review, a second audit layer** (`src/review_ai.py`): every `verified` record is read by a language model that is asked one question — is there any sign in the stored evidence that this domain does *not* belong to this entity? A flag moves the record to `review_required` and holds it there until a human clears it. **This layer can only take verification away; it never grants it.** Nothing becomes `verified` because a model said so — the counting rules above remain the only path. The manual sample in point 2 is what proves the layer itself is trustworthy, which is why its size does not shrink as the dataset grows.

---

## 4. Changing this policy

Any change to a threshold or weight in `src/policy.py` **changes the project's public trust promise**. Therefore:

1. this file must be updated in the same change;
2. two-person approval via `CODEOWNERS`;
3. the full adversarial corpus must pass, and a diff against the current dataset must state how many records move up or down;
4. the rationale goes in the commit message, permanently.

**Changes that lower the bar (make more things verified) deserve extra suspicion** — that is precisely what an attacker wants us to do.

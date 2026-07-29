# ERRATA — Boundstone Benchmark № 001

`METHODOLOGY.md` was frozen on **2026-07-25** (tag `methodology-v1.0`, sha256
`24fb254ed62b0aef493520e60d29652234405cb7e77a7dcedfa1f636ee34969d`). It commits
to this file in three places:

> §Status — "any post-freeze correction appears in `ERRATA.md`, **never as an
> edit to this file**."

> §2 — if counsel advises a vendor's terms prohibit our participation as a
> competitor, "that vendor's column may be anonymized ('Vendor D') or withdrawn
> before publication; the event and reason will be recorded in `ERRATA.md`."

> §8 — "factual scoring errors are corrected with the correction logged in
> `ERRATA.md`. Nothing in this file changes post-freeze."

This file therefore exists **before any results do**, so that it is visibly not a
retrofit. Everything below is append-only and dated.

---

## Scoring corrections

**None.** No scored run has been conducted. Run № 001 collection has not started.

When one occurs, the entry format is:

```
### YYYY-MM-DD — <one-line summary>
**What was wrong:** …
**How it was found:** …
**Which rows/vendors/dimensions are affected:** …
**Corrected figures:** before → after
**Commit:** <sha>
```

---

## Category shortfalls

**None yet.** The frozen §3 composition (A 40 · B 25 · C 135 · D 15 · E 5 ·
F 350 · G 125 · H 150 · I 155 = 1,000) has not been finalised. Counts cannot be
silently rebalanced; any shortfall is recorded here at publication with its
cause.

Known risks, declared in advance rather than after the fact:

| Category | Risk |
|---|---|
| B (25) | Google Voice / TextNow signups are US-oriented and may geo-block an Australian operator |
| C (135) | Owner-attested volunteers require a paid panel; recruitment is the project's critical path |
| E (5) | A port rejection would reduce N; §3 already permits E to be reported descriptively if N is too small |

---

## Post-freeze vocabulary and adapter decisions

These are **not** methodology changes. §2 marked vendor endpoints and field paths
as draft-until-verified, and `mappings.json` is the designed place to record
vendor vocabulary. They are logged here anyway, because each was decided *after*
the freeze and each affects how a vendor's answer is scored — and a reader
auditing this benchmark should not have to read `git log` to find them.

### 2026-07-25 — vendor adapters verified against live accounts (`432bac1`, `a51c5b6`)

Endpoints and field paths were confirmed by probing paid self-serve accounts.
Three mechanisms were added to the harness in the process:

- **1Lookup**: the V2 platform moved everything (host, auth, request shape). Their
  API answers structurally invalid input with **HTTP 400**, so `http400_means_invalid`
  records that a 400 is a vendor *answer* of "invalid", not a transport failure.
  Validity is returned as a **status string**, so `valid_strings` maps the observed
  vocabulary; an unrecognised value fails loudly rather than being guessed.
- **Trestle**: a raw `+` in the query decodes as a space and their gateway answers a
  misleading `403 INVALID_API_KEY`. Fixed by percent-encoding. Separately, their WAF
  fingerprints Python's TLS and rejects it regardless of headers, so this vendor is
  queried via a **curl transport**. Documented openly as ordinary-customer behaviour,
  not evasion.
- **Twilio**: draft paths were exact. NANP-shaped invalid numbers answer
  `200 / valid:false`.

### 2026-07-26 — two vendor vocabulary values mapped after the rehearsal run (`b562a5e`)

An 80-row rehearsal against all four vendors (320 live lookups, synthetic rows
only, **not** a scored run) surfaced 17 unmapped line-type values. Normalisation
refused to produce output until they were resolved — the intended loud-fail
behaviour. Two decisions were required:

- **1Lookup `UNKNOWN` → abstain.** It accompanies `number_status: INVALID`, i.e.
  an explicit no-information answer. §5 defines abstain as no data or an explicit
  unknown, so it is **excluded from the denominator rather than scored as wrong**.
  ⚠️ *This call is generous to the vendor.* It is recorded here explicitly so the
  choice is visible rather than buried, and can be challenged in the dispute
  window.
- **NumVerify `paging` → OTHER.** A real line class (carrier "Spok Inc.", a paging
  network) outside the five scored families, matching the existing
  `special_services` precedent.

Neither altered a scoring rule. `METHODOLOGY.md` was unmodified and its checksum
verified before each commit.

### 2026-07-29 — category E pre-port carrier recorded as ONVOY

Telnyx's port confirmation named the losing carrier as **ONVOY, LLC - PA**, not
Twilio (Twilio resells over Onvoy). This was recorded as the pre-port carrier for
category E, on the reasoning that an LRN/OCN dip returns the underlying carrier
and that recording the reseller would penalise a vendor for answering correctly.

### 2026-07-30 — CORRECTION: the above was wrong. Carrier truth is Twilio.

**What was wrong:** the 2026-07-29 entry assumed vendors would report the
underlying carrier. They do not.

**How it was found:** probing owned numbers before the category D release closed
that window. Two vendors independently return the same value:

| Vendor | Carrier returned |
|---|---|
| Trestle | `Twilio - SMS/MMS-SVR` |
| Twilio Lookup | `Twilio - SMS/MMS-SVR` |
| 1Lookup | *no carrier* (`N/A`) — an abstain |

The same holds for a category E number mid-port. Onvoy appears **only** in the
porting/NPAC system, which is a different register from the OCN/LRN data
validation vendors read.

**Corrected position:** `truth_carrier` for owned Twilio DIDs (categories A, D,
and E pre-port) is **Twilio**. That is who we buy from, who bills us, and whose
console administers the numbers — it is what we can actually attest to, which is
what §3 requires. Recording "Onvoy" would have scored a correct vendor **wrong**,
which is precisely the error the earlier entry claimed to be preventing, in the
opposite direction.

**Effect on published figures:** none. No scored run has occurred; this was
caught before collection.

**Kept for reference:** the private provenance store retains
`underlying_carrier_pre_port = ONVOY, LLC - PA` as a separate, clearly-labelled
column. It is a true fact about the numbers and relevant to the port, but it is
**not** the carrier ground truth for scoring.

**Why this is logged rather than silently fixed:** the first entry was published
before it was verified against a live vendor response. The correction is the
mechanism working as intended.

---

## Open items that may become entries

- **Trestle terms-of-service counsel question (§2).** Unresolved. If counsel
  advises their terms prohibit participation by a competitor, their column is
  anonymised to "Vendor D" or withdrawn, and the event is recorded here. Scoring
  of the remaining vendors would not change.
- ~~**Category A/D carrier of record.**~~ **CLOSED 2026-07-30** — probed against
  live vendors before the category D release; see the correction above.
  `truth_carrier` is **Twilio** for all owned DIDs, and this was verified rather
  than inferred from the pool they came from.
- **NumVerify free-tier exhaustion.** The 2026-07-30 probe returned
  `usage_limit_reached` on NumVerify's free tier — independent confirmation that
  the paid plan §2 commits to ("public paid plan") must be active before
  collection, not just at publication.

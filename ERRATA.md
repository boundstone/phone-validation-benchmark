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

### 2026-07-29 — category E pre-port carrier recorded as the underlying carrier, not the reseller

Category E ground truth is "before/after carrier known" (§3). The five numbers
were purchased through **Twilio**, but the carrier of record — and what an LRN/OCN
dip returns — is **ONVOY, LLC - PA**, since Twilio resells over Onvoy. Recording
the reseller as truth would have scored a vendor **wrong for correctly answering
"Onvoy"**. The private provenance store now carries `underlying_carrier_pre_port`
as a column distinct from the reseller.

No methodology change: §3's wording already means the carrier of record. This is
recorded because the distinction is easy to get wrong and materially affects the
carrier dimension.

---

## Open items that may become entries

- **Trestle terms-of-service counsel question (§2).** Unresolved. If counsel
  advises their terms prohibit participation by a competitor, their column is
  anonymised to "Vendor D" or withdrawn, and the event is recorded here. Scoring
  of the remaining vendors would not change.
- **Category A/D carrier of record.** The owned DIDs came from the same Twilio
  pool as category E and are therefore likely also Onvoy, but this has not been
  probed. Any carrier expectation for those rows will be confirmed against a live
  lookup before collection, and recorded here if it changes a stated assumption.

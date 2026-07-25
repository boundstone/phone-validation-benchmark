# Boundstone Phone-Validation Benchmark № 001 — Pre-Registered Methodology

**Version:** 1.0-draft (becomes 1.0-frozen upon publication to the public repository; the SHA-256 of the frozen file and the git tag `methodology-v1.0` constitute the freeze)
**Author:** Boundstone (boundstone.io)
**Status:** No vendor has been queried as of this document's freeze. Scoring rules below cannot change after freeze; any post-freeze correction appears in `ERRATA.md`, never as an edit to this file.

---

## 1. What is being tested

The accuracy of four commercial phone-validation APIs on 1,000 North American (NANP) phone numbers with known ground truth, across the dimensions vendors themselves advertise: **validity, line type, carrier, and ported status** — plus a descriptive (unscored) look at liveness claims.

**Why this benchmark exists:** phone-validation vendors publish accuracy claims (e.g., "99.97%") with no dataset, no methodology, and no reproducibility. No public phone-validation benchmark existed at the time of registration. We operate a competing product (see §10, Conflicts), which is precisely why every rule here is fixed before results exist.

## 2. Vendors and exact products under test

| Vendor | Product / endpoint | Tier | Fields consumed |
|---|---|---|---|
| 1Lookup | Phone Validation (1lookup.io) | public self-serve paid credits | validity, line type, carrier, ported where returned |
| Trestle | Phone Validation API (v1, current) | public self-serve $0.015/query | is_valid, line_type, carrier, activity_score (descriptive) |
| Twilio | Lookup v2 + Line Type Intelligence package | public PAYG | valid, line_type_intelligence.type, carrier_name |
| NumVerify (APILayer) | Standard API | public paid plan | valid, line_type, carrier |

All accounts are ordinary public self-serve accounts paid at list price. No sales contact, no negotiated tiers, no vendor is notified before the run. **Legal gate, declared up front:** if counsel advises that a vendor's terms of service prohibit our participation as a competitor, that vendor's column may be anonymized ("Vendor D") or withdrawn before publication; the event and reason will be recorded in `ERRATA.md`. The scoring of remaining vendors does not change.

Boundstone's own API is **not** in run № 001 — self-exclusion: we author and fund this benchmark, and our product launched only days before the freeze. From the first quarterly re-run after our public launch, Boundstone is tested under this identical protocol and its scores published, win or lose.

## 3. Dataset composition (1,000 numbers)

| Cat. | Description | Count | Ground truth | Scored dimensions |
|---|---|---|---|---|
| A | Owned active DIDs (Twilio, Telnyx; local + toll-free) | 40 | Strong: valid, active, carrier, VoIP/toll-free line type | validity, line type, carrier |
| B | Self-created VoIP/app numbers (Google Voice, TextNow, …) | 25 | Strong: valid, active, non-fixed VoIP | validity, line type, carrier |
| C | Opt-in volunteer numbers (real mobile + landline), written consent per the template in `CONSENT.md` | 135 | Strong: valid, active; line type & carrier attested by owner (current bill/carrier app screenshot, held privately) | validity, line type, carrier |
| D | Owned-then-released numbers (in carrier aging ≥4 weeks at run date; release dates logged) | 15 | Weak–moderate | descriptive only |
| E | Owned numbers ported between carriers by us (port dates logged) | 5 | Moderate: before/after carrier known | ported status (descriptive if N deemed too small: reported, no headline use) |
| F | Unallocated NPA-NXX (from NANPA CO-code assignment files; download date pinned in `DATA_SNAPSHOT.md`) | 350 | Strong at snapshot date: not a valid allocated number | validity |
| G | Fictional range 555-0100–555-0199 (ATIS-0300115) | 125 | Strong: reserved non-working | validity |
| H | Impossible formats (wrong length; NPA/NXX starting 0/1; N11; all-same-digit) | 150 | Strong: definitionally invalid under NANP rules | validity |
| I | Valid-format, allocated NPA-NXX + random line number | 155 | Format/allocation: strong. Subscriber status: unknown by design | validity (see definition §4.1); liveness claims descriptive |

Design principle: cheap unlimited synthetic rows (F–I, 780) carry the **validity** test; scarce strong-ground-truth real rows (A–C, 200) carry the **line-type/carrier** test, which is where vendor claims actually diverge. US mobile ground truth comes **only** from category C and any eSIM lines we own — purchased DIDs are VoIP-class and are never presented as mobile ground truth.

## 4. Ground-truth definitions (fixed)

1. **Valid** = well-formed NANP number within an **allocated** numbering block at the pinned NANPA snapshot date. Validity is *not* liveness: a valid number may have no active subscriber (category I is valid). A vendor calling an I-row "invalid" is **wrong**; calling it "inactive/unknown subscriber" is not penalized on the validity dimension.
2. **Line type** families: `mobile`, `landline`, `fixed_voip`, `non_fixed_voip`, `toll_free`. Vendor vocabularies are mapped to these families by the public mapping table in `scoring/mappings.json`, committed at freeze.
3. **Carrier** = current serving carrier at run date, matched at brand level after normalization (`Verizon Wireless` ≡ `Verizon`). For MVNOs, host-network answers earn partial credit (§5).
4. **Ported** = number has moved serving carrier at least once (category E only).

## 5. Scoring rubric (fixed)

Per row and dimension, a vendor answer is one of: **correct (1.0) · partial (0.5) · wrong (0) · abstain (excluded)**.

- **Abstain** = no data returned for that field, an explicit "unknown", a documented-unsupported response, or a failed request after retries (§6). Abstentions are excluded from the accuracy denominator and reported separately as an **abstention rate**. *Rationale fixed now: not knowing is honest; being wrong is not. We refuse to let silence be scored as error — or as accuracy.*
- **Partial (0.5)** is earned only for: correct line-type super-family (any-VoIP vs. specific VoIP subtype); MVNO host network instead of MVNO brand; carrier correct but stale by one port event (E rows).
- **Validity** answers map: vendor "valid" → valid; vendor "invalid" → invalid. Confidence scores ≥/< 0.5 (where a vendor returns only a score) map to valid/invalid; the exact per-vendor mapping is in `scoring/mappings.json` at freeze.

**Headline metrics, fixed now:**
- Per vendor: **Validity accuracy** (categories A–C, E–I), **Line-type accuracy** (A–C), **Carrier accuracy** (A–C), each with 95% bootstrap CIs (10,000 resamples), plus abstention rate per dimension.
- **Composite = unweighted mean of the three accuracies.** If a vendor's abstention rate on a dimension exceeds 20%, that dimension is flagged in every table where it appears.
- No other aggregate will be invented after results are known.
- D-row (disconnected) and activity/liveness outputs are reported **descriptively only** — no accuracy claim in either direction.

## 6. Run protocol (fixed)

- All vendors queried within the same **72-hour window**; per-row queries for all vendors within 24 hours of each other. E.164 formatting for every request.
- Published rate limits respected. Transport errors/5xx: up to 2 retries spaced ≥60s; then abstain (logged).
- Raw responses archived verbatim, privately (see §7). Scoring runs from the archive by the public scripts in `scoring/` — anyone can re-run scoring from published verdicts, and an auditor can re-run it from raw archives.

## 7. Publication & redaction policy (fixed)

- **Public in full:** synthetic rows (F–I) and owned-number rows (A, B, D, E) — the numbers, ground truth, and per-vendor verdicts.
- **Redacted:** category C volunteer rows appear as opaque row IDs + last-4 digits; **CNAM/name data is never published**. (Hashing is not anonymization for a 10-digit space; we don't pretend otherwise.)
- **Derived verdicts, not raw payloads, are published per vendor row** (correct/partial/wrong/abstain + our normalized field values). Verbatim vendor responses stay in the private archive, available to a neutral auditor or accredited journalist under NDA. This satisfies reproducibility without republishing any vendor's licensed data.
- Scripts, mappings, consent template, NANPA snapshot references: all public in this repository at freeze.

## 8. Vendor dispute process (fixed)

Each tested vendor is emailed at publication of this methodology (pre-results) and again **14 days before results publication** with their per-row verdicts on the public rows. Disputes: methodology disputes are answered publicly; factual scoring errors are corrected with the correction logged in `ERRATA.md`. Nothing in this file changes post-freeze.

## 9. Re-runs

Quarterly, same method, fresh dataset built to the §3 recipe (new synthetic draws; volunteer refresh with re-consent). Methodology changes between runs require a version bump (v1.1, v2.0…), a fresh freeze, and a public diff. Never mid-run.

## 10. Conflicts of interest (declared)

Boundstone operates a competing phone/email/IP validation API and funds this benchmark entirely. Mitigations, fixed at freeze: pre-registered method (this file), public dataset and scoring code, per-vendor dispute window, private raw archive available to a neutral auditor, our own product tested under identical rules from the first re-run after launch, and publication of our scores regardless of outcome.

## 11. Freeze verification

At publication the repository is tagged `methodology-v1.0` and the SHA-256 of this file is posted at boundstone.io/methodology and in the repository README. To verify nothing changed after results: `shasum -a 256 METHODOLOGY.md` and compare.

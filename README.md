# Boundstone Benchmark № 001 — Phone Validation

Pre-registered public benchmark of commercial phone-validation APIs. The methodology is frozen **before any vendor is queried** — see [`METHODOLOGY.md`](METHODOLOGY.md).

**Freeze verification:** at freeze this repo is tagged `methodology-v1.0` and the SHA-256 of `METHODOLOGY.md` is published at [boundstone.io/methodology](https://boundstone.io/methodology) and below.

```
sha256(METHODOLOGY.md) = 24fb254ed62b0aef493520e60d29652234405cb7e77a7dcedfa1f636ee34969d
```

## Repository layout (populated in this order)

- `METHODOLOGY.md` — the frozen pre-registration (this is the artifact everything else answers to)
- `CONSENT.md` — the written-consent template for volunteer numbers (category C)
- `DATA_SNAPSHOT.md` — pinned NANPA file download dates + hashes
- `scoring/mappings.json` — per-vendor field→family mappings (drafted; vendor blocks verified against live responses and committed at freeze)
- `scoring/score.py` — the METHODOLOGY §5 scorer: stdlib-only Python 3.9+, `python3 score.py dataset.csv answers.csv > report.json`. Bootstrap CIs use a pinned seed (1001) so re-runs are byte-identical.
- `scoring/test_score.py` — golden tests, one per rubric rule (partial-credit cases, abstain exclusion, the >20% abstention flag, category boundaries). `python3 test_score.py` — 12 tests, all fictional-range numbers.
- `scoring/run_vendors.py` — the §6 collection runner, **built**: `collect` (same-window queries, per-vendor rate intervals, ≥60s-spaced retries then logged abstain, verbatim private archive, resumable), `normalize` (archive → `answers.csv` in score.py's contract; refuses to publish any line-type value missing from `mappings.json`), `verify-windows` (checks the 72 h run / 24 h per-row rules from archive timestamps), `probe <vendor> <e164>` (one raw call — the at-freeze verification step for each adapter). Vendor endpoints/field paths are draft-until-probed, same convention as `mappings.json`; credentials are env-vars only; Boundstone's adapter exists but is refused for run № 001 without `--include-boundstone` (§2).
- `scoring/test_run_vendors.py` — golden tests for the collection rules (retry spacing, 4xx-vs-5xx handling, Twilio 404-as-answer, verbatim archiving, unmapped-vocabulary refusal, end-to-end contract). `python3 test_run_vendors.py` — 14 tests, no network, fictional-range numbers.
- `dataset/` — public rows (synthetic + owned in full; volunteer rows redacted), published with results
- `results/` — per-vendor verdicts + aggregate tables with bootstrap CIs, published after the vendor dispute window
- `ERRATA.md` — every post-freeze correction, dated; this file is the only thing that ever changes a number

## Conflict of interest, stated plainly

Boundstone funds this benchmark and operates a competing validation API. That is why the method is frozen first, the dataset and scripts are public, vendors get their verdicts 14 days before publication, and our own product is scored under the identical protocol from the first re-run after launch — win or lose.

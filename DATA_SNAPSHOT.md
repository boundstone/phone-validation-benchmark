# Data snapshot — Benchmark № 001

METHODOLOGY.md §3 requires the NANPA download date to be pinned: central
office codes migrate between assigned and available over time, so the
synthetic categories are only true as of the snapshot below.

- **NANPA CO Code Assignment files — 'File Updated' date: 07/25/2026**
- Downloaded and built: 2026-07-25
- Source: https://www.nanpa.com/reports/co-code-reports/cocodes_assign
  (per-region *Available* files + *Utilized_AllStates_Public*)
- Fictional range: ATIS-0300115, 555-0100–555-0199 only

Usable after filtering (NANP-structural codes only, available minus utilized):
97,938 unallocated codes, 201,438 allocated codes.

Generator: `scoring/build_synthetic.py`, seed 1001 — re-running against
the same snapshot reproduces the synthetic rows byte-for-byte.
The raw NANPA archives are not committed (they are large and publicly
downloadable at the URL above); the pinned date is what makes the build
reproducible.

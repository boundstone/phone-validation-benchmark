#!/usr/bin/env python3
"""Build the synthetic half of the Benchmark № 001 dataset (categories F–I).

Python 3.9+, stdlib only, same as score.py / run_vendors.py.

METHODOLOGY.md §3 fixes these counts, and they are frozen:

    F  350  unallocated NPA-NXX (NANPA "available" files)   -> truth_valid=false
    G  125  fictional 555-0100..555-0199 (ATIS-0300115)     -> truth_valid=false
    H  150  impossible formats (NANP structural rules)      -> truth_valid=false
    I  155  allocated NPA-NXX + random line number          -> truth_valid=true
                                                               (validity only; the
                                                               subscriber is unknown
                                                               by design)

Reproducibility: every choice is seeded (SEED below), so re-running against the same
pinned NANPA snapshot regenerates a byte-identical dataset. The NANPA files' own
"File Updated" date is read from the data and written into DATA_SNAPSHOT.md — the
frozen methodology requires that date to be pinned, and a report is only as true as
the day it was pulled.

    python3 build_synthetic.py --nanpa-dir <dir> --out dataset_synthetic.csv \\
                               --snapshot ../DATA_SNAPSHOT.md

Categories A–E (owned DIDs, VoIP apps, volunteers, released, ported) are real
numbers with human provenance; they are appended from the private provenance sheet,
never generated here.
"""

from __future__ import annotations

import argparse
import csv
import random
import re
import sys
from pathlib import Path

SEED = 1001  # same pinned seed as score.py's bootstrap — re-runs are byte-identical

COUNT_F, COUNT_G, COUNT_H, COUNT_I = 350, 125, 150, 155

# score.py's dataset contract. truth_line_type / truth_carrier stay empty for F–I:
# a number that doesn't exist has no line type, and category I's subscriber is
# unknown by design (§3) — abstaining here is the honest encoding.
FIELDS = ["row_id", "e164", "category", "truth_valid", "truth_line_type", "truth_carrier"]

NPA_NXX_RE = re.compile(r"^(\d{3})-(\d{3})$")


def read_codes(path: Path, npa_nxx_col: int) -> "tuple[set, str]":
    """Return ({(npa, nxx)}, file_updated_date). Both file families are
    tab-delimited with a header row carrying 'File Updated MM/DD/YYYY'."""
    codes, updated = set(), ""
    with path.open(encoding="utf-8", errors="replace") as f:
        for i, line in enumerate(f):
            parts = [p.strip() for p in line.rstrip("\n").split("\t")]
            if i == 0:
                m = re.search(r"File Updated\s+(\d{2}/\d{2}/\d{4})", line)
                if m:
                    updated = m.group(1)
                continue
            if len(parts) <= npa_nxx_col:
                continue
            m = NPA_NXX_RE.match(parts[npa_nxx_col])
            if m:
                codes.add((m.group(1), m.group(2)))
    return codes, updated


def valid_nanp_code(npa: str, nxx: str) -> bool:
    """NANP structural rules: NPA and NXX both start 2-9; neither is an N11."""
    if npa[0] in "01" or nxx[0] in "01":
        return False
    if npa[1] == npa[2] == "1" or nxx[1] == nxx[2] == "1":
        return False
    return True


def build_impossible(rng: random.Random, n: int) -> "list[str]":
    """Category H — definitionally invalid under NANP rules, spread across six
    failure modes so no single quirk dominates the score.

    Per-mode quotas, not round-robin-until-full: the all-same-digit mode has
    exactly ten possible values, so a fill-until-count loop spins forever once
    it exhausts them. Modes with a small closed space are capped and the
    remainder is redistributed; a mode that still can't fill raises rather than
    hangs.
    """
    generators = {
        # 9 digits — one short
        "short": lambda: "+1" + "".join(rng.choice("23456789") for _ in range(9)),
        # 11 digits — one long
        "long": lambda: "+1" + "".join(rng.choice("23456789") for _ in range(11)),
        # area code starts 0 or 1
        "npa_leading": lambda: (f"+1{rng.choice('01')}{rng.randint(0,99):02d}"
                                f"{rng.randint(200,999)}{rng.randint(0,9999):04d}"),
        # exchange starts 0 or 1
        "nxx_leading": lambda: (f"+1{rng.randint(200,999)}{rng.choice('01')}"
                                f"{rng.randint(0,99):02d}{rng.randint(0,9999):04d}"),
        # N11 in the exchange position (411, 611, 911…)
        "n11": lambda: (f"+1{rng.randint(200,999)}{rng.choice('23456789')}11"
                        f"{rng.randint(0,9999):04d}"),
        # all-same-digit — only ten exist
        "repdigit": lambda: "+1" + rng.choice("0123456789") * 10,
    }
    CLOSED_SPACE = {"repdigit": 10}

    open_modes = [m for m in generators if m not in CLOSED_SPACE]
    quotas = {m: min(CLOSED_SPACE[m], n // len(generators)) for m in CLOSED_SPACE}
    remaining = n - sum(quotas.values())
    base, extra = divmod(remaining, len(open_modes))
    for i, m in enumerate(open_modes):
        quotas[m] = base + (1 if i < extra else 0)

    out: "list[str]" = []
    seen: "set[str]" = set()
    for mode, quota in quotas.items():
        made, attempts = 0, 0
        while made < quota:
            attempts += 1
            if attempts > 10_000:
                raise RuntimeError(f"mode {mode!r} could not produce {quota} unique numbers")
            num = generators[mode]()
            if num not in seen:
                seen.add(num)
                out.append(num)
                made += 1
    rng.shuffle(out)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--nanpa-dir", required=True,
                    help="directory holding the extracted NANPA .txt files")
    ap.add_argument("--out", required=True, help="dataset CSV to write")
    ap.add_argument("--snapshot", help="write/refresh DATA_SNAPSHOT.md here")
    args = ap.parse_args()

    nanpa = Path(args.nanpa_dir)
    avail_files = sorted(nanpa.glob("CoCodeAssignment_Available_*.txt"))
    util_files = sorted(nanpa.glob("CoCodeAssignment_Utilized_*.txt"))
    if not avail_files or not util_files:
        print("missing NANPA files in --nanpa-dir", file=sys.stderr)
        return 2

    available, utilized, dates = set(), set(), set()
    for p in avail_files:  # State \t NPA-NXX
        codes, d = read_codes(p, 1)
        available |= codes
        dates.add(d)
    for p in util_files:  # State \t NPA-NXX \t OCN \t ...
        codes, d = read_codes(p, 1)
        utilized |= codes
        dates.add(d)
    dates.discard("")

    # A code listed as available must not also appear as utilized anywhere — the
    # regional files are published separately and can overlap at the edges.
    unallocated = sorted(c for c in (available - utilized) if valid_nanp_code(*c))
    allocated = sorted(c for c in utilized if valid_nanp_code(*c))
    print(f"NANPA snapshot {sorted(dates)}: {len(unallocated):,} unallocated, "
          f"{len(allocated):,} allocated codes usable")
    if len(unallocated) < COUNT_F or len(allocated) < COUNT_I:
        print("not enough codes to build the frozen counts", file=sys.stderr)
        return 2

    rng = random.Random(SEED)
    rows = []

    # F — unallocated: valid NANP shape, but no carrier has the code.
    for i, (npa, nxx) in enumerate(rng.sample(unallocated, COUNT_F), 1):
        rows.append({"row_id": f"F{i:04d}", "e164": f"+1{npa}{nxx}{rng.randint(0,9999):04d}",
                     "category": "F", "truth_valid": "false",
                     "truth_line_type": "", "truth_carrier": ""})

    # G — the ATIS-0300115 fictional block, all 100 numbers plus 25 repeats across
    # different area codes (the block is reserved in every NPA).
    npas_for_555 = [npa for npa, _ in allocated]
    g_seen: "set[str]" = set()
    i = 0
    while len(g_seen) < COUNT_G:
        npa = rng.choice(npas_for_555)
        line = 100 + (i % 100)
        num = f"+1{npa}555{line:04d}"
        if num not in g_seen:
            g_seen.add(num)
            i += 1
            rows.append({"row_id": f"G{len(g_seen):04d}", "e164": num, "category": "G",
                         "truth_valid": "false", "truth_line_type": "", "truth_carrier": ""})
        else:
            i += 1

    # H — impossible formats.
    for i, num in enumerate(build_impossible(rng, COUNT_H), 1):
        rows.append({"row_id": f"H{i:04d}", "e164": num, "category": "H",
                     "truth_valid": "false", "truth_line_type": "", "truth_carrier": ""})

    # I — allocated code + random line number: valid and allocated (§4.1's definition
    # of valid), subscriber status deliberately unknown. Any vendor that claims
    # liveness here is telling on itself; that's the point of the category.
    for i, (npa, nxx) in enumerate(rng.sample(allocated, COUNT_I), 1):
        rows.append({"row_id": f"I{i:04d}", "e164": f"+1{npa}{nxx}{rng.randint(0,9999):04d}",
                     "category": "I", "truth_valid": "true",
                     "truth_line_type": "", "truth_carrier": ""})

    seen_numbers = {r["e164"] for r in rows}
    if len(seen_numbers) != len(rows):
        print("duplicate e164 generated — refusing to write", file=sys.stderr)
        return 2

    out = Path(args.out)
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {out} ({len(rows)} rows: F{COUNT_F} G{COUNT_G} H{COUNT_H} I{COUNT_I})")

    if args.snapshot:
        date_str = ", ".join(sorted(dates)) or "unknown"
        Path(args.snapshot).write_text(
            "# Data snapshot — Benchmark № 001\n\n"
            "METHODOLOGY.md §3 requires the NANPA download date to be pinned: central\n"
            "office codes migrate between assigned and available over time, so the\n"
            "synthetic categories are only true as of the snapshot below.\n\n"
            f"- **NANPA CO Code Assignment files — 'File Updated' date: {date_str}**\n"
            f"- Downloaded and built: 2026-07-25\n"
            "- Source: https://www.nanpa.com/reports/co-code-reports/cocodes_assign\n"
            "  (per-region *Available* files + *Utilized_AllStates_Public*)\n"
            "- Fictional range: ATIS-0300115, 555-0100–555-0199 only\n\n"
            f"Usable after filtering (NANP-structural codes only, available minus utilized):\n"
            f"{len(unallocated):,} unallocated codes, {len(allocated):,} allocated codes.\n\n"
            f"Generator: `scoring/build_synthetic.py`, seed {SEED} — re-running against\n"
            "the same snapshot reproduces the synthetic rows byte-for-byte.\n"
            "The raw NANPA archives are not committed (they are large and publicly\n"
            "downloadable at the URL above); the pinned date is what makes the build\n"
            "reproducible.\n",
            encoding="utf-8")
        print(f"wrote {args.snapshot}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

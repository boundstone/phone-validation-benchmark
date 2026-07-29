#!/usr/bin/env python3
"""Category C volunteer intake — validate, dedupe, quota-track.

Implements the rules in research/05d-volunteer-intake-spec.md §8 so that no
unusable row can reach the dataset, and so that PII never reaches this repo.

⚠️ THIS REPOSITORY IS PUBLIC (github.com/boundstone/phone-validation-benchmark).
Volunteer numbers, names, emails and screenshots MUST NOT be written here.
Everything this tool records goes to the PRIVATE store:

    ~/Documents/boundstone-benchmark/volunteers.csv

METHODOLOGY §7 publishes category C as an opaque row ID plus last-4 only. The
working dataset that carries full numbers is produced by `export`, also into the
private store, and is used only at collection time.

Stdlib only, matching score.py and run_vendors.py.

    python3 intake.py add --phone +14155550123 --carrier Verizon \\
        --line-type mobile --name "Jane Doe" --email jane@example.com \\
        --consent-date 2026-08-03 --screenshot jane-verizon.png
    python3 intake.py validate submissions.csv     # dry run, nothing written
    python3 intake.py status                       # quota + progress
    python3 intake.py export                       # private dataset for collection
"""

from __future__ import annotations

import argparse
import csv
import datetime
import pathlib
import re
import sys

PRIVATE = pathlib.Path.home() / "Documents" / "boundstone-benchmark"
VOLUNTEERS = PRIVATE / "volunteers.csv"
PROVENANCE = PRIVATE / "provenance.csv"          # owned DIDs (categories A/D/E)
SYNTHETIC = pathlib.Path(__file__).parent / "dataset_synthetic.csv"

# The only families score.py accepts (mappings.json line_type_families).
FAMILIES = ("mobile", "landline", "fixed_voip", "non_fixed_voip", "toll_free")

# Frozen §3 targets for category C, and the 05b mix target.
TARGET_TOTAL = 135
TARGET_MOBILE = 90
TARGET_FIXED = 30

VOLUNTEER_FIELDS = [
    "row_id", "e164", "truth_line_type", "truth_carrier",
    "name", "email", "consent_date", "screenshot", "added_at_utc",
]


# --------------------------------------------------------------------------
# pure validation — golden-tested in test_intake.py
# --------------------------------------------------------------------------

def normalize_e164(raw: str) -> "str | None":
    """Return +1XXXXXXXXXX, or None if it isn't a structurally valid NANP number.

    Accepts the shapes volunteers actually type: (415) 555-0123, 415-555-0123,
    1 415 555 0123, +14155550123.
    """
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11 and digits[0] == "1":
        digits = digits[1:]
    if len(digits) != 10:
        return None
    npa, nxx = digits[:3], digits[3:6]
    # same structural rules as build_synthetic.valid_nanp_code — kept identical
    # so a number we would generate as "impossible" can never enter as truth
    if npa[0] in "01" or nxx[0] in "01":
        return None
    if npa[1] == npa[2] == "1" or nxx[1] == nxx[2] == "1":
        return None
    return "+1" + digits


def normalize_line_type(raw: str) -> "str | None":
    """Map what a volunteer says onto a scorer family.

    ⚠️ Deliberately does NOT accept a bare 'landline' synonym for cable phone
    service. 05d §5 requires the two-step question precisely because most people
    call Xfinity/Spectrum/FiOS voice a landline when it is fixed_voip. Recording
    it as landline would mark a CORRECT vendor wrong on the graded dimension.
    """
    if not raw:
        return None
    s = raw.strip().lower().replace("-", "_").replace(" ", "_")
    direct = {
        "mobile": "mobile", "cell": "mobile", "cellular": "mobile",
        "cell_phone": "mobile", "mobile_phone": "mobile",
        "landline": "landline", "copper": "landline",
        "phone_company": "landline", "traditional": "landline",
        "fixed_voip": "fixed_voip", "cable": "fixed_voip",
        "cable_voip": "fixed_voip", "internet_phone": "fixed_voip",
        "non_fixed_voip": "non_fixed_voip", "app": "non_fixed_voip",
        "toll_free": "toll_free",
    }
    return direct.get(s)


def check_row(rec: dict, seen: set) -> "list[str]":
    """Return a list of problems. Empty list == acceptable row."""
    problems = []

    e164 = normalize_e164(rec.get("phone", ""))
    if not e164:
        problems.append(f"phone {rec.get('phone','')!r} is not a structurally valid NANP number")
    elif e164 in seen:
        problems.append(f"{e164} is a duplicate of an existing row")

    fam = normalize_line_type(rec.get("line_type", ""))
    if not fam:
        problems.append(
            f"line_type {rec.get('line_type','')!r} does not map to a family "
            f"({', '.join(FAMILIES)}) — ask the two-step question in 05d §5")
    elif fam == "non_fixed_voip":
        problems.append("app-based number (non_fixed_voip) — screened out of category C per frozen §3")
    elif fam == "toll_free":
        problems.append("toll-free is not a category C line type")

    if not (rec.get("carrier") or "").strip():
        problems.append("carrier is empty — record the brand on their bill, not the host network")
    if not (rec.get("consent_date") or "").strip():
        problems.append("no consent date — frozen §3 requires written consent per CONSENT.md")
    if not (rec.get("screenshot") or "").strip():
        problems.append("no attestation screenshot — it is the only ground-truth control")

    return problems


def quota(rows: "list[dict]") -> dict:
    mob = sum(1 for r in rows if r["truth_line_type"] == "mobile")
    fixed = sum(1 for r in rows if r["truth_line_type"] in ("landline", "fixed_voip"))
    return {
        "total": len(rows), "mobile": mob, "fixed": fixed,
        "total_remaining": max(0, TARGET_TOTAL - len(rows)),
        "mobile_remaining": max(0, TARGET_MOBILE - mob),
        "fixed_remaining": max(0, TARGET_FIXED - fixed),
    }


# --------------------------------------------------------------------------
# storage
# --------------------------------------------------------------------------

def load_volunteers() -> "list[dict]":
    if not VOLUNTEERS.exists():
        return []
    with VOLUNTEERS.open() as f:
        return list(csv.DictReader(f))


def known_numbers() -> set:
    """Every number already in play — volunteers, owned DIDs, synthetic rows."""
    seen = set()
    for r in load_volunteers():
        seen.add(r["e164"])
    if PROVENANCE.exists():
        with PROVENANCE.open() as f:
            for r in csv.DictReader(f):
                seen.add(r["e164"])
    if SYNTHETIC.exists():
        with SYNTHETIC.open() as f:
            for r in csv.DictReader(f):
                seen.add(r["e164"])
    return seen


def next_row_id(rows: "list[dict]") -> str:
    n = max((int(r["row_id"][1:]) for r in rows if r["row_id"].startswith("C")), default=0)
    return f"C{n + 1:04d}"


def append_volunteer(rec: dict) -> str:
    PRIVATE.mkdir(parents=True, exist_ok=True)
    rows = load_volunteers()
    rid = next_row_id(rows)
    out = {
        "row_id": rid,
        "e164": normalize_e164(rec["phone"]),
        "truth_line_type": normalize_line_type(rec["line_type"]),
        "truth_carrier": rec["carrier"].strip(),
        "name": rec.get("name", "").strip(),
        "email": rec.get("email", "").strip(),
        "consent_date": rec["consent_date"].strip(),
        "screenshot": rec["screenshot"].strip(),
        "added_at_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    new = not VOLUNTEERS.exists()
    with VOLUNTEERS.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=VOLUNTEER_FIELDS)
        if new:
            w.writeheader()
        w.writerow(out)
    return rid


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------

def cmd_add(a) -> int:
    rec = {
        "phone": a.phone, "carrier": a.carrier, "line_type": a.line_type,
        "name": a.name, "email": a.email,
        "consent_date": a.consent_date, "screenshot": a.screenshot,
    }
    problems = check_row(rec, known_numbers())
    if problems:
        print("✗ rejected:")
        for p in problems:
            print("   -", p)
        return 1
    rid = append_volunteer(rec)
    q = quota(load_volunteers())
    print(f"✓ {rid}  {normalize_e164(a.phone)}  {normalize_line_type(a.line_type)}  {a.carrier}")
    print(f"  progress: {q['total']}/{TARGET_TOTAL} "
          f"(mobile {q['mobile']}/{TARGET_MOBILE}, fixed {q['fixed']}/{TARGET_FIXED})")
    return 0


def cmd_validate(a) -> int:
    """Dry-run a batch CSV. Writes nothing."""
    path = pathlib.Path(a.file)
    if not path.exists():
        print(f"✗ no such file: {path}")
        return 1
    seen = known_numbers()
    ok = bad = 0
    with path.open() as f:
        for i, rec in enumerate(csv.DictReader(f), start=2):
            problems = check_row(rec, seen)
            if problems:
                bad += 1
                print(f"✗ line {i}: {rec.get('phone','')!r}")
                for p in problems:
                    print("   -", p)
            else:
                ok += 1
                seen.add(normalize_e164(rec["phone"]))   # catch in-file duplicates
    print(f"\n{ok} acceptable, {bad} rejected (nothing written — this is a dry run)")
    return 1 if bad else 0


def cmd_status(a) -> int:
    rows = load_volunteers()
    q = quota(rows)
    print(f"category C: {q['total']}/{TARGET_TOTAL} rows")
    print(f"  mobile {q['mobile']}/{TARGET_MOBILE}   (need {q['mobile_remaining']} more)")
    print(f"  fixed  {q['fixed']}/{TARGET_FIXED}   (need {q['fixed_remaining']} more)")
    if q["fixed_remaining"] and q["total"]:
        print("  ⚠️ fixed-address lines are the scarce half — recruit for them "
              "explicitly or you will finish at 135 mobiles and no landlines")
    by_carrier = {}
    for r in rows:
        by_carrier[r["truth_carrier"]] = by_carrier.get(r["truth_carrier"], 0) + 1
    if by_carrier:
        print("  carriers:", ", ".join(f"{k}×{v}" for k, v in sorted(by_carrier.items())))
    return 0


def cmd_export(a) -> int:
    """Write the scoring-shaped category C rows to the PRIVATE store."""
    rows = load_volunteers()
    if not rows:
        print("no volunteers yet")
        return 1
    out = PRIVATE / "dataset_C.csv"
    with out.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["row_id", "e164", "category", "truth_valid", "truth_line_type", "truth_carrier"])
        for r in rows:
            w.writerow([r["row_id"], r["e164"], "C", "true", r["truth_line_type"], r["truth_carrier"]])
    print(f"✓ wrote {len(rows)} category C rows → {out}")
    print("  PRIVATE store, deliberately: this repo is public and §7 publishes")
    print("  category C as row ID + last-4 only.")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="add one volunteer")
    a.add_argument("--phone", required=True)
    a.add_argument("--carrier", required=True)
    a.add_argument("--line-type", required=True, dest="line_type")
    a.add_argument("--consent-date", required=True, dest="consent_date")
    a.add_argument("--screenshot", required=True)
    a.add_argument("--name", default="")
    a.add_argument("--email", default="")
    a.set_defaults(fn=cmd_add)

    v = sub.add_parser("validate", help="dry-run a batch CSV, write nothing")
    v.add_argument("file")
    v.set_defaults(fn=cmd_validate)

    s = sub.add_parser("status", help="quota and progress")
    s.set_defaults(fn=cmd_status)

    e = sub.add_parser("export", help="write scoring-shaped C rows to the private store")
    e.set_defaults(fn=cmd_export)

    args = p.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())

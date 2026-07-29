#!/usr/bin/env python3
"""Golden tests for intake.py — one test per rule in 05d §8.

No network, no writes, fictional numbers only (555-01XX is the ATIS-0300115
reserved range, which is why category G exists).

    python3 test_intake.py
"""

from __future__ import annotations

import sys

from intake import check_row, normalize_e164, normalize_line_type, quota

FAILURES = []


def check(name, got, want):
    if got != want:
        FAILURES.append(f"{name}\n    got:  {got!r}\n    want: {want!r}")


# --- normalize_e164 -------------------------------------------------------

def test_e164_accepts_the_shapes_people_type():
    for raw in ["+14155550123", "14155550123", "4155550123",
                "(415) 555-0123", "415-555-0123", "1 415 555 0123"]:
        check(f"e164 accepts {raw!r}", normalize_e164(raw), "+14155550123")


def test_e164_rejects_wrong_length():
    check("9 digits", normalize_e164("415555012"), None)
    check("11 digits not starting 1", normalize_e164("24155550123"), None)
    check("empty", normalize_e164(""), None)


def test_e164_rejects_npa_or_nxx_starting_0_or_1():
    # same structural rule as build_synthetic.valid_nanp_code
    check("NPA starts 1", normalize_e164("1155550123"), None)
    check("NPA starts 0", normalize_e164("0155550123"), None)
    check("NXX starts 1", normalize_e164("4151550123"), None)
    check("NXX starts 0", normalize_e164("4150550123"), None)


def test_e164_rejects_n11():
    check("NPA is N11 (411)", normalize_e164("4115550123"), None)
    check("NXX is N11 (911)", normalize_e164("4159110123"), None)


# --- normalize_line_type --------------------------------------------------

def test_line_type_maps_common_words():
    for raw in ["mobile", "Mobile", "cell", "CELL PHONE", "cellular"]:
        check(f"{raw!r} → mobile", normalize_line_type(raw), "mobile")
    for raw in ["landline", "phone company", "copper"]:
        check(f"{raw!r} → landline", normalize_line_type(raw), "landline")
    for raw in ["fixed_voip", "fixed voip", "cable", "internet phone"]:
        check(f"{raw!r} → fixed_voip", normalize_line_type(raw), "fixed_voip")


def test_line_type_rejects_unmapped_rather_than_guessing():
    # loud failure beats a silent wrong family — the whole point of 05d §5
    check("'home phone' is ambiguous", normalize_line_type("home phone"), None)
    check("'voip' alone is ambiguous", normalize_line_type("voip"), None)
    check("empty", normalize_line_type(""), None)


# --- check_row ------------------------------------------------------------

GOOD = {
    "phone": "+14155550123", "carrier": "Verizon", "line_type": "mobile",
    "consent_date": "2026-08-03", "screenshot": "v1.png",
}


def test_good_row_passes():
    check("clean row", check_row(dict(GOOD), set()), [])


def test_duplicate_is_rejected():
    problems = check_row(dict(GOOD), {"+14155550123"})
    check("duplicate flagged", len(problems), 1)
    check("duplicate message", "duplicate" in problems[0], True)


def test_app_number_is_screened_out_of_category_c():
    rec = dict(GOOD, line_type="app")
    problems = check_row(rec, set())
    check("non_fixed_voip rejected", any("screened out" in p for p in problems), True)


def test_toll_free_is_not_a_category_c_line_type():
    rec = dict(GOOD, line_type="toll_free")
    check("toll_free rejected", any("toll-free" in p for p in check_row(rec, set())), True)


def test_missing_consent_is_rejected():
    rec = dict(GOOD, consent_date="")
    check("consent required", any("consent" in p for p in check_row(rec, set())), True)


def test_missing_screenshot_is_rejected():
    rec = dict(GOOD, screenshot="")
    check("screenshot required", any("screenshot" in p for p in check_row(rec, set())), True)


def test_missing_carrier_is_rejected():
    rec = dict(GOOD, carrier="  ")
    check("carrier required", any("carrier is empty" in p for p in check_row(rec, set())), True)


def test_multiple_problems_all_reported():
    rec = {"phone": "123", "carrier": "", "line_type": "banana",
           "consent_date": "", "screenshot": ""}
    check("all five reported", len(check_row(rec, set())), 5)


# --- quota ----------------------------------------------------------------

def test_quota_counts_fixed_as_landline_plus_fixed_voip():
    rows = ([{"truth_line_type": "mobile"}] * 5
            + [{"truth_line_type": "landline"}] * 2
            + [{"truth_line_type": "fixed_voip"}] * 3)
    q = quota(rows)
    check("total", q["total"], 10)
    check("mobile", q["mobile"], 5)
    check("fixed = landline + fixed_voip", q["fixed"], 5)
    check("mobile remaining", q["mobile_remaining"], 85)
    check("fixed remaining", q["fixed_remaining"], 25)


def test_quota_never_reports_negative_remaining():
    q = quota([{"truth_line_type": "mobile"}] * 200)
    check("no negative remaining", q["mobile_remaining"], 0)
    check("no negative total remaining", q["total_remaining"], 0)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    if FAILURES:
        print(f"✗ {len(FAILURES)} failure(s):\n")
        for f in FAILURES:
            print("  " + f)
        sys.exit(1)
    print(f"✓ intake: {len(tests)} test groups passed")

#!/usr/bin/env python3
"""Golden tests for score.py — each METHODOLOGY §5 rule has a named case.
All numbers are from the ATIS fictional range (+1 XXX 555-01XX). Run:

    python3 test_score.py
"""

import csv
import io
import json
import tempfile
import unittest
from pathlib import Path

import score


def run_scorer(dataset_rows, answer_rows):
    def write(rows, header):
        f = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False)
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        for r in rows:
            w.writerow(r)
        f.close()
        return f.name

    ds = write(dataset_rows, ["row_id", "e164", "category", "truth_valid",
                              "truth_line_type", "truth_carrier", "truth_ported", "prior_carrier"])
    an = write(answer_rows, ["vendor", "row_id", "valid", "line_type", "carrier", "error"])
    return score.main(ds, an)


def ds_row(row_id, cat, valid="true", lt="", carrier="", prior=""):
    return {"row_id": row_id, "e164": f"+1415555{row_id[-4:]}", "category": cat,
            "truth_valid": valid, "truth_line_type": lt, "truth_carrier": carrier,
            "truth_ported": "", "prior_carrier": prior}


def ans(vendor, row_id, valid="", lt="", carrier="", error=""):
    return {"vendor": vendor, "row_id": row_id, "valid": valid,
            "line_type": lt, "carrier": carrier, "error": error}


class Rubric(unittest.TestCase):
    def test_validity_correct_wrong_and_abstain_excluded(self):
        # §5: abstain excluded from denominator, reported as a rate.
        r = run_scorer(
            [ds_row("0100", "F", valid="false"), ds_row("0101", "F", valid="false"),
             ds_row("0102", "I", valid="true")],
            [ans("v", "0100", valid="false"),   # correct
             ans("v", "0101", valid="true"),    # wrong
             ans("v", "0102")],                 # abstain
        )["vendors"]["v"]["validity"]
        self.assertEqual(r["accuracy"], 0.5)
        self.assertEqual(r["scored_rows"], 2)
        self.assertEqual(r["abstentions"], 1)
        self.assertAlmostEqual(r["abstention_rate"], 1 / 3, places=3)

    def test_category_I_valid_row_scored_valid(self):
        # §4.1: category I is VALID; vendor "invalid" is wrong.
        r = run_scorer([ds_row("0103", "I", valid="true")],
                       [ans("v", "0103", valid="false")])
        self.assertEqual(r["vendors"]["v"]["validity"]["accuracy"], 0.0)

    def test_category_D_never_scored(self):
        # §5: D rows are descriptive only.
        r = run_scorer([ds_row("0104", "D", valid="true")],
                       [ans("v", "0104", valid="true")])
        self.assertEqual(r["vendors"]["v"]["validity"]["scored_rows"], 0)

    def test_line_type_super_family_partial(self):
        # §5(a): any-VoIP vs specific VoIP subtype = 0.5, both directions.
        r = run_scorer(
            [ds_row("0105", "B", lt="non_fixed_voip"), ds_row("0106", "B", lt="non_fixed_voip")],
            [ans("v", "0105", valid="true", lt="VOIP_UNSPECIFIED"),
             ans("v", "0106", valid="true", lt="fixed_voip")],
        )["vendors"]["v"]["line_type"]
        self.assertEqual(r["accuracy"], 0.5)
        self.assertEqual(r["scored_rows"], 2)

    def test_line_type_flm_is_abstain_and_other_is_wrong(self):
        r = run_scorer(
            [ds_row("0107", "C", lt="mobile"), ds_row("0108", "C", lt="mobile")],
            [ans("v", "0107", valid="true", lt="AMBIGUOUS_FLM"),
             ans("v", "0108", valid="true", lt="OTHER")],
        )["vendors"]["v"]["line_type"]
        self.assertEqual(r["abstentions"], 1)   # either-or answer = no information
        self.assertEqual(r["accuracy"], 0.0)    # OTHER = committed, wrong

    def test_carrier_brand_normalization(self):
        # §4.3: Verizon Wireless ≡ Verizon.
        r = run_scorer([ds_row("0109", "C", lt="mobile", carrier="Verizon")],
                       [ans("v", "0109", valid="true", lt="mobile", carrier="Verizon Wireless")])
        self.assertEqual(r["vendors"]["v"]["carrier"]["accuracy"], 1.0)

    def test_carrier_mvno_host_partial(self):
        # §5(b): host network instead of MVNO brand = 0.5.
        r = run_scorer([ds_row("0110", "C", lt="mobile", carrier="Mint Mobile")],
                       [ans("v", "0110", valid="true", lt="mobile", carrier="T-Mobile")])
        self.assertEqual(r["vendors"]["v"]["carrier"]["accuracy"], 0.5)

    def test_category_E_stale_port_partial_is_descriptive_only(self):
        # §5(c) + §3: E rows report the stale-port partial but never enter
        # the headline carrier dimension (A–C only).
        r = run_scorer(
            [ds_row("0111", "E", carrier="T-Mobile", prior="Verizon")],
            [ans("v", "0111", valid="true", carrier="Verizon")],
        )["vendors"]["v"]
        self.assertEqual(r["carrier"]["scored_rows"], 0)
        self.assertEqual(r["category_E_descriptive"][0]["carrier_score"], 0.5)

    def test_error_row_abstains_every_dimension(self):
        # §6: failed after retries = abstain, logged.
        r = run_scorer(
            [ds_row("0112", "C", lt="mobile", carrier="AT&T")],
            [ans("v", "0112", valid="true", lt="mobile", carrier="AT&T", error="timeout after 2 retries")],
        )["vendors"]["v"]
        self.assertEqual(r["validity"]["abstentions"], 1)
        self.assertEqual(r["line_type"]["abstentions"], 1)
        self.assertEqual(r["carrier"]["abstentions"], 1)

    def test_abstention_flag_over_20_percent(self):
        rows = [ds_row(f"01{i:02d}", "F", valid="false") for i in range(20, 30)]
        answers = [ans("v", f"01{i:02d}", valid="" if i < 23 else "false") for i in range(20, 30)]
        r = run_scorer(rows, answers)["vendors"]["v"]["validity"]
        self.assertEqual(r["abstention_rate"], 0.3)
        self.assertTrue(r["abstention_flag"])

    def test_composite_is_unweighted_mean_and_requires_all_three(self):
        r = run_scorer(
            [ds_row("0130", "F", valid="false"),
             ds_row("0131", "C", lt="mobile", carrier="Verizon")],
            [ans("v", "0130", valid="false"),
             ans("v", "0131", valid="true", lt="landline", carrier="Verizon")],
        )["vendors"]["v"]
        # validity 1.0 (2 rows correct), line_type 0.0, carrier 1.0 → mean 2/3
        self.assertAlmostEqual(r["composite"], round(2 / 3, 4), places=4)
        r2 = run_scorer([ds_row("0132", "F", valid="false")],
                        [ans("v", "0132", valid="false")])["vendors"]["v"]
        self.assertIsNone(r2["composite"])

    def test_bootstrap_ci_reproducible(self):
        # Pinned seed → identical CIs across runs.
        a = run_scorer([ds_row("0133", "F", valid="false"), ds_row("0134", "F", valid="false"),
                        ds_row("0135", "I", valid="true")],
                       [ans("v", "0133", valid="false"), ans("v", "0134", valid="true"),
                        ans("v", "0135", valid="true")])
        b = run_scorer([ds_row("0133", "F", valid="false"), ds_row("0134", "F", valid="false"),
                        ds_row("0135", "I", valid="true")],
                       [ans("v", "0133", valid="false"), ans("v", "0134", valid="true"),
                        ans("v", "0135", valid="true")])
        self.assertEqual(a["vendors"]["v"]["validity"]["ci95"],
                         b["vendors"]["v"]["validity"]["ci95"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

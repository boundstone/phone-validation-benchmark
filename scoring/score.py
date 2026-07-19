#!/usr/bin/env python3
"""Boundstone Benchmark № 001 — public scorer.

Implements METHODOLOGY.md §4 (ground truth), §5 (rubric, headline metrics)
exactly. Python 3.9+, stdlib only — anyone can re-run scoring from the
published per-vendor answers:

    python3 score.py dataset.csv answers.csv > report.json

dataset.csv columns:
    row_id, e164, category (A–I), truth_valid (true/false),
    truth_line_type (family or empty), truth_carrier (or empty),
    truth_ported (true/false/empty)

answers.csv columns (normalized vendor answers, one row per vendor×number):
    vendor, row_id, valid (true/false/empty=abstain),
    line_type (family, VOIP_UNSPECIFIED, AMBIGUOUS_FLM, OTHER, or empty=abstain),
    carrier (string or empty=abstain), error (non-empty forces abstain on all
    dimensions for the row — §6 failed-after-retries rule)

Rubric (§5): correct 1.0 · partial 0.5 · wrong 0 · abstain excluded from the
denominator, reported as an abstention rate. Partial is earned ONLY for:
  (a) correct line-type super-family (any-VoIP vs a specific VoIP subtype),
  (b) MVNO host network instead of MVNO brand,
  (c) carrier correct but stale by one port event (category E rows).
Headline metrics (§5): validity accuracy on A–C,E–I · line-type on A–C ·
carrier on A–C · composite = unweighted mean of the three · 95% bootstrap CIs
(10,000 resamples, seed pinned below) · >20% abstention flags the dimension.
Category D and liveness outputs are descriptive only and never scored here.
"""

from __future__ import annotations  # so `X | None` annotations run on Python 3.9 too

import csv
import json
import random
import statistics
import sys
from pathlib import Path

BOOTSTRAP_RESAMPLES = 10_000
BOOTSTRAP_SEED = 1001  # pinned so CIs are byte-reproducible on re-runs
ABSTENTION_FLAG_THRESHOLD = 0.20

MAPPINGS = json.loads((Path(__file__).parent / "mappings.json").read_text())
VOIP_FAMILIES = set(MAPPINGS["voip_super_family"])

VALIDITY_CATEGORIES = {"A", "B", "C", "E", "F", "G", "H", "I"}  # §5: A–C, E–I
LINETYPE_CATEGORIES = {"A", "B", "C"}
CARRIER_CATEGORIES = {"A", "B", "C"}


def norm_carrier(raw: str) -> str:
    """§4.3 brand-level normalization: Verizon Wireless ≡ Verizon."""
    s = "".join(c if c.isalnum() or c.isspace() else " " for c in raw.lower())
    words = [w for w in s.split() if w not in set(MAPPINGS["carrier_normalize"]["drop_suffixes"])]
    joined = " ".join(words).strip()
    for brand, aliases in MAPPINGS["carrier_normalize"]["brand_aliases"].items():
        if joined == brand or joined in aliases:
            return brand
    return joined


def score_validity(truth_valid: bool, answer: str) -> float | None:
    """Returns 1.0/0.0, or None for abstain."""
    if answer == "":
        return None
    return 1.0 if (answer == "true") == truth_valid else 0.0


def score_line_type(truth_family: str, answer: str) -> float | None:
    if answer == "" or answer == "OTHER":
        return None if answer == "" else 0.0
    if answer == "AMBIGUOUS_FLM":
        # A vendor answering "fixed_line_or_mobile" has not committed to a
        # family. §5 defines abstain as "no data / explicit unknown" — an
        # either-or answer carries no line-type information: abstain.
        return None
    if answer == truth_family:
        return 1.0
    if answer == "VOIP_UNSPECIFIED" and truth_family in VOIP_FAMILIES:
        return 0.5  # §5(a): correct super-family, unspecified subtype
    if answer in VOIP_FAMILIES and truth_family in VOIP_FAMILIES:
        return 0.5  # §5(a): specific subtype, wrong subtype, right super-family
    return 0.0


def score_carrier(truth_carrier: str, answer: str, prior_carrier: str = "") -> float | None:
    if answer == "":
        return None
    truth = norm_carrier(truth_carrier)
    got = norm_carrier(answer)
    if got == truth:
        return 1.0
    host = MAPPINGS["mvno_hosts"].get(truth)
    if host and got == norm_carrier(host):
        return 0.5  # §5(b): host network instead of MVNO brand
    if prior_carrier and got == norm_carrier(prior_carrier):
        return 0.5  # §5(c): stale by one port event (E rows)
    return 0.0


def bootstrap_ci(scores: list[float]) -> tuple[float, float]:
    if not scores:
        return (float("nan"), float("nan"))
    rng = random.Random(BOOTSTRAP_SEED)
    n = len(scores)
    means = sorted(statistics.fmean(rng.choices(scores, k=n)) for _ in range(BOOTSTRAP_RESAMPLES))
    lo = means[int(0.025 * BOOTSTRAP_RESAMPLES)]
    hi = means[int(0.975 * BOOTSTRAP_RESAMPLES) - 1]
    return (round(lo, 4), round(hi, 4))


def dimension_summary(scores: list[float], abstains: int) -> dict:
    attempted = len(scores)
    total = attempted + abstains
    acc = round(statistics.fmean(scores), 4) if scores else None
    lo, hi = bootstrap_ci(scores)
    rate = round(abstains / total, 4) if total else 0.0
    return {
        "accuracy": acc,
        "ci95": [lo, hi] if scores else None,
        "scored_rows": attempted,
        "abstentions": abstains,
        "abstention_rate": rate,
        "abstention_flag": rate > ABSTENTION_FLAG_THRESHOLD,  # §5: >20% flagged
    }


def main(dataset_path: str, answers_path: str) -> dict:
    with open(dataset_path, newline="") as f:
        rows = {r["row_id"]: r for r in csv.DictReader(f)}
    vendors: dict[str, dict[str, list | int]] = {}

    with open(answers_path, newline="") as f:
        answer_rows = list(csv.DictReader(f))
    for a in answer_rows:
        row = rows.get(a["row_id"])
        if row is None:
            raise SystemExit(f"answers reference unknown row_id {a['row_id']}")
        v = vendors.setdefault(a["vendor"], {
            "validity": [], "validity_abstain": 0,
            "line_type": [], "line_type_abstain": 0,
            "carrier": [], "carrier_abstain": 0,
            "e_rows": [],  # descriptive: ported/carrier detail for category E
        })
        cat = row["category"].strip().upper()
        errored = bool(a.get("error", "").strip())

        if cat in VALIDITY_CATEGORIES:
            s = None if errored else score_validity(row["truth_valid"].strip() == "true", a["valid"].strip())
            if s is None:
                v["validity_abstain"] += 1
            else:
                v["validity"].append(s)

        if cat in LINETYPE_CATEGORIES and row["truth_line_type"].strip():
            s = None if errored else score_line_type(row["truth_line_type"].strip(), a["line_type"].strip())
            if s is None:
                v["line_type_abstain"] += 1
            else:
                v["line_type"].append(s)

        if cat in CARRIER_CATEGORIES and row["truth_carrier"].strip():
            s = None if errored else score_carrier(row["truth_carrier"].strip(), a["carrier"].strip())
            if s is None:
                v["carrier_abstain"] += 1
            else:
                v["carrier"].append(s)

        if cat == "E":  # reported, never in headline carrier accuracy (§3/§5)
            v["e_rows"].append({
                "row_id": a["row_id"],
                "carrier_score": None if errored else score_carrier(
                    row["truth_carrier"].strip(), a["carrier"].strip(),
                    prior_carrier=row.get("prior_carrier", "").strip()),
            })

    report: dict = {
        "benchmark": "boundstone-001",
        "methodology": "METHODOLOGY.md (see checksum in repo tag)",
        "rubric": "correct=1.0 partial=0.5 wrong=0 abstain=excluded (METHODOLOGY §5)",
        "bootstrap": {"resamples": BOOTSTRAP_RESAMPLES, "seed": BOOTSTRAP_SEED},
        "vendors": {},
    }
    for name, v in sorted(vendors.items()):
        dims = {
            "validity": dimension_summary(v["validity"], v["validity_abstain"]),
            "line_type": dimension_summary(v["line_type"], v["line_type_abstain"]),
            "carrier": dimension_summary(v["carrier"], v["carrier_abstain"]),
        }
        accs = [d["accuracy"] for d in dims.values() if d["accuracy"] is not None]
        composite = round(statistics.fmean(accs), 4) if len(accs) == 3 else None
        report["vendors"][name] = {
            **dims,
            "composite": composite,  # §5: unweighted mean of the three, else null
            "composite_note": None if composite is not None else
                "composite requires all three dimensions to have scored rows",
            "category_E_descriptive": v["e_rows"],
        }
    return report


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    print(json.dumps(main(sys.argv[1], sys.argv[2]), indent=2))

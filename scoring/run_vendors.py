#!/usr/bin/env python3
"""Boundstone Benchmark № 001 — vendor collection harness (METHODOLOGY.md §6).

Python 3.9+, stdlib only, same as score.py. Collection and normalization are
deliberately SEPARATE stages: raw responses are archived verbatim first
(§6/§7), and answers.csv is derived from the archive afterwards — so the
vendor-vocabulary mappings can be finalized at freeze and normalization
re-run without touching any vendor a second time.

    python3 run_vendors.py probe <vendor> <e164>            # one live call, raw dump
    python3 run_vendors.py collect <dataset.csv> --run-id run001 [--vendors a,b]
    python3 run_vendors.py normalize <run-id>               # archive -> answers.csv
    python3 run_vendors.py verify-windows <run-id>          # check §6 timing rules

§6 rules implemented here:
  * E.164 for every request.
  * Published rate limits respected (conservative per-vendor min intervals,
    override with --interval vendor=seconds).
  * Transport errors / 5xx: up to 2 retries spaced >=60s, then abstain —
    recorded in the archive with the error, surfaced in answers.csv `error`.
  * Raw responses archived verbatim and privately (archive/ is never
    published; §7 publishes derived verdicts only).
  * Collection is idempotent/resumable: rows with an existing archive file
    are skipped, so an interrupted run continues where it stopped.

Vendor adapters (§2). Endpoints and field paths are DRAFT until verified
against a live self-serve account at freeze — same convention as the vendor
blocks in mappings.json. Verify each with `probe` before a real run.
Boundstone's own API is NOT part of run № 001 (§2 self-exclusion: we author
and fund this benchmark); its adapter exists for the quarterly re-runs and
requires the explicit --include-boundstone flag.

Credentials come only from environment variables (never argv, never files in
this repo): ONELOOKUP_API_KEY, TRESTLE_API_KEY, TWILIO_ACCOUNT_SID +
TWILIO_AUTH_TOKEN, NUMVERIFY_API_KEY, BOUNDSTONE_API_KEY.
"""

from __future__ import annotations

import argparse
import base64
import csv
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
ARCHIVE_ROOT = HERE / "archive"  # private — never published (§7)
MAPPINGS = json.loads((HERE / "mappings.json").read_text())

RETRIES = 2          # §6: up to 2 retries ...
RETRY_SPACING_S = 60  # ... spaced >=60s
ROW_WINDOW_H = 24    # §6: per-row cross-vendor proximity
RUN_WINDOW_H = 72    # §6: whole-run window
TIMEOUT_S = 30

USER_AGENT = "boundstone-benchmark/001 (methodology: boundstone.io/methodology)"


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def dig(obj, path: str):
    """Dotted-path lookup: 'line_type_intelligence.type' -> nested value."""
    cur = obj
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


# --------------------------------------------------------------------------
# Adapters — request shape per vendor. status: 'verified' only after a live
# probe at freeze; anything 'draft' must be probed before a scored run.
# --------------------------------------------------------------------------

def _req_onelookup(e164: str):
    # V2 platform contract (probed 2026-07-25): POST app.1lookup.io/api/v1/phone,
    # Bearer auth, body {"phone_number": ...}. The pre-freeze draft guessed
    # api.1lookup.io + x-api-key, which never resolved.
    key = os.environ["ONELOOKUP_API_KEY"]
    return urllib.request.Request(
        "https://app.1lookup.io/api/v1/phone",
        data=json.dumps({"phone_number": e164}).encode(),
        headers={
            "authorization": f"Bearer {key}",
            "content-type": "application/json",
            "user-agent": USER_AGENT,
        },
        method="POST",
    )


def _req_trestle(e164: str):
    # The + MUST be URL-encoded (%2B): a raw + in the query string decodes as a
    # space and their gateway answers a misleading 403 INVALID_API_KEY (probed
    # 2026-07-25 — cost a day of chasing key scopes that were fine all along).
    key = os.environ["TRESTLE_API_KEY"]
    return urllib.request.Request(
        f"https://api.trestleiq.com/3.0/phone_intel?phone={urllib.parse.quote(e164, safe='')}",
        headers={"x-api-key": key, "user-agent": USER_AGENT},
    )


def _req_twilio(e164: str):
    sid, tok = os.environ["TWILIO_ACCOUNT_SID"], os.environ["TWILIO_AUTH_TOKEN"]
    auth = base64.b64encode(f"{sid}:{tok}".encode()).decode()
    return urllib.request.Request(
        f"https://lookups.twilio.com/v2/PhoneNumbers/{e164}?Fields=line_type_intelligence",
        headers={"authorization": f"Basic {auth}", "user-agent": USER_AGENT},
    )


def _req_numverify(e164: str):
    key = os.environ["NUMVERIFY_API_KEY"]
    return urllib.request.Request(
        f"https://apilayer.net/api/validate?access_key={key}&number={e164.lstrip('+')}&format=1",
        headers={"user-agent": USER_AGENT},
    )


def _req_boundstone(e164: str):
    key = os.environ["BOUNDSTONE_API_KEY"]
    return urllib.request.Request(
        "https://api.boundstone.io/v1/verify/phone",
        data=json.dumps({"phone": e164}).encode(),
        headers={
            "authorization": f"Bearer {key}",
            "content-type": "application/json",
            "user-agent": USER_AGENT,
        },
        method="POST",
    )


VENDORS = {
    # field paths into the raw JSON; None means the vendor doesn't return it
    # (normalized to abstain ""). 4xx handling: 'answer' means a 4xx body is
    # still a vendor answer (archived + normalized); 'error' means 4xx is a
    # failure (abstain, logged) pending review at freeze.
    "onelookup": {
        "status": "probed 2026-07-25 — V2 (app.1lookup.io) live-verified; unknown vocab fails loudly",
        "request": _req_onelookup,
        "env": ["ONELOOKUP_API_KEY"],
        "valid_path": "data.classification.number_status",
        # Observed: ACTIVE. Others inferred from their status vocabulary —
        # anything not listed logs as unmapped and blocks publication.
        "valid_strings": {"true": ["ACTIVE"], "false": ["INACTIVE", "INVALID", "DISCONNECTED"]},
        "line_type_path": "data.classification.line_type",
        "carrier_path": "data.insights.raw_api_fields.network",
        "min_interval_s": 1.1, "on_4xx": "error", "http400_means_invalid": True,
    },
    "trestle": {
        "status": "probed 2026-07-25 — endpoint+fields verified live; curl transport (their WAF blocks Python TLS)",
        "request": _req_trestle,
        "env": ["TRESTLE_API_KEY"],
        "transport": "curl",
        "valid_path": "is_valid", "line_type_path": "line_type", "carrier_path": "carrier",
        "min_interval_s": 1.1, "on_4xx": "error",
    },
    "twilio": {
        "status": "probed 2026-07-25 — valid:true and valid:false (200, INVALID_BUT_POSSIBLE) shapes verified live; 404 flag kept per docs",
        "request": _req_twilio,
        "env": ["TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN"],
        "valid_path": "valid",
        "line_type_path": "line_type_intelligence.type",
        "carrier_path": "line_type_intelligence.carrier_name",
        # Twilio Lookup returns 404 for numbers it cannot resolve — that is a
        # vendor answer (invalid), not a transport failure.
        "min_interval_s": 1.1, "on_4xx": "answer", "http404_means_invalid": True,
    },
    "numverify": {
        "status": "probed 2026-07-25 — apilayer endpoint + draft field paths verified live",
        "request": _req_numverify,
        "env": ["NUMVERIFY_API_KEY"],
        "valid_path": "valid", "line_type_path": "line_type", "carrier_path": "carrier",
        "min_interval_s": 1.5, "on_4xx": "error",
    },
    "boundstone": {
        "status": "live — excluded from run № 001 by §2; quarterly re-runs only",
        "request": _req_boundstone,
        "env": ["BOUNDSTONE_API_KEY"],
        "valid_path": "valid", "line_type_path": "line_type", "carrier_path": None,
        "min_interval_s": 1.1, "on_4xx": "answer",
    },
}

RUN_001_VENDORS = ["onelookup", "trestle", "twilio", "numverify"]  # §2


# --------------------------------------------------------------------------
# Collection
# --------------------------------------------------------------------------

def curl_argv(req, timeout_s: int) -> list:
    """Build a curl command equivalent to a urllib Request (headers + URL).

    Why curl exists as a transport at all: Trestle's WAF fingerprints and
    rejects Python's TLS ClientHello with a misleading 403 INVALID_API_KEY
    (verified 2026-07-25: same key + same request 200s from curl/Node and
    403s from urllib regardless of headers, ALPN or cipher tweaks). Calling
    their documented endpoint with our paid key through a standard client is
    ordinary customer behavior — documented here rather than worked around
    silently.
    """
    argv = ["curl", "-sS", "-m", str(timeout_s), "-w", "\n%{http_code}"]
    for k, v in req.header_items():
        argv += ["-H", f"{k}: {v}"]
    if req.data is not None:
        argv += ["-X", req.get_method(), "--data-binary", req.data.decode("utf-8")]
    argv.append(req.full_url)
    return argv


def fetch_once(vendor: str, e164: str):
    """One HTTP attempt. Returns (http_status, body_text) or raises on transport error."""
    req = VENDORS[vendor]["request"](e164)
    if VENDORS[vendor].get("transport") == "curl":
        proc = subprocess.run(curl_argv(req, TIMEOUT_S), capture_output=True, text=True,
                              timeout=TIMEOUT_S + 5)
        if proc.returncode != 0:  # transport error — retryable per §6
            raise OSError(f"curl exit {proc.returncode}: {proc.stderr.strip()[:200]}")
        body, _, status = proc.stdout.rpartition("\n")
        return int(status), body
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:  # non-2xx still has a body — keep it
        return e.code, e.read().decode("utf-8", "replace")


def collect_row(vendor: str, row_id: str, e164: str, out_path: Path) -> None:
    """§6 retry protocol; archives exactly what happened, verbatim."""
    attempts = []
    for attempt in range(1 + RETRIES):
        if attempt:
            time.sleep(RETRY_SPACING_S)
        ts = utcnow()
        try:
            status, body = fetch_once(vendor, e164)
        except Exception as exc:  # transport error — retryable per §6
            attempts.append({"at": ts, "transport_error": f"{type(exc).__name__}: {exc}"})
            continue
        attempts.append({"at": ts, "http_status": status, "body": body})
        if status < 500:  # 5xx retries per §6; anything else is final
            break
    record = {
        "vendor": vendor, "row_id": row_id, "e164": e164,
        "collected_at": utcnow(), "attempts": attempts,
    }
    out_path.write_text(json.dumps(record, ensure_ascii=False, indent=1))


def cmd_collect(args) -> int:
    vendors = args.vendors.split(",") if args.vendors else list(RUN_001_VENDORS)
    if "boundstone" in vendors and not args.include_boundstone:
        print("boundstone is excluded from run № 001 (§2); pass --include-boundstone "
              "for a quarterly re-run.", file=sys.stderr)
        return 2
    intervals = {v: VENDORS[v]["min_interval_s"] for v in vendors}
    for spec in args.interval or []:
        v, s = spec.split("=", 1)
        intervals[v] = float(s)

    missing = [v for v in vendors for e in VENDORS[v]["env"] if not os.environ.get(e)]
    if missing:
        print(f"missing credentials for: {sorted(set(missing))} — set the env vars "
              f"listed in the module docstring. No vendor was queried.", file=sys.stderr)
        return 2

    rows = list(csv.DictReader(open(args.dataset, newline="", encoding="utf-8")))
    run_dir = ARCHIVE_ROOT / args.run_id
    manifest_path = run_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {
        "run_id": args.run_id, "dataset": str(args.dataset), "row_count": len(rows),
        "methodology": "METHODOLOGY.md v1.0", "started_at": utcnow(), "vendors": {},
    }

    for vendor in vendors:
        vdir = run_dir / vendor
        vdir.mkdir(parents=True, exist_ok=True)
        vman = manifest["vendors"].setdefault(vendor, {"started_at": utcnow(), "adapter_status": VENDORS[vendor]["status"]})
        done = skipped = 0
        for row in rows:
            out = vdir / f"{row['row_id']}.json"
            if out.exists():  # resumable — never re-query a collected row
                skipped += 1
                continue
            collect_row(vendor, row["row_id"], row["e164"], out)
            done += 1
            time.sleep(intervals[vendor])
            if done and done % 50 == 0:
                print(f"[{vendor}] {done} collected ({skipped} already archived)")
        vman["finished_at"] = utcnow()
        vman["collected"] = done
        vman["skipped_existing"] = skipped
        manifest_path.write_text(json.dumps(manifest, indent=1))
        print(f"[{vendor}] complete: {done} new, {skipped} already archived")
    return 0


# --------------------------------------------------------------------------
# Normalization: archive -> answers.csv (score.py's input contract)
# --------------------------------------------------------------------------

def normalize_record(vendor: str, record: dict, unmapped: list) -> dict:
    """Map one archived record to an answers.csv row. Abstain-on-error per §6."""
    row = {"vendor": vendor, "row_id": record["row_id"],
           "valid": "", "line_type": "", "carrier": "", "error": ""}
    final = next((a for a in reversed(record["attempts"]) if "http_status" in a), None)
    if final is None:  # all attempts were transport errors
        row["error"] = record["attempts"][-1].get("transport_error", "transport_error")
        return row
    status = final["http_status"]
    cfg = VENDORS[vendor]
    if status == 404 and cfg.get("http404_means_invalid"):
        row["valid"] = "false"
        return row
    # 1Lookup V2 (probed 2026-07-25) answers an unparseable/invalid number with
    # HTTP 400 INVALID_INPUT — a vendor answer (invalid), not a transport
    # failure, same reasoning as Twilio's 404. Other 4xx (401/403/429) still
    # fall through to on_4xx handling.
    if status == 400 and cfg.get("http400_means_invalid"):
        row["valid"] = "false"
        return row
    if status >= 500 or (400 <= status < 500 and cfg["on_4xx"] == "error"):
        row["error"] = f"http_{status}"
        return row
    try:
        body = json.loads(final["body"])
    except ValueError:
        row["error"] = "unparseable_body"
        return row

    v = dig(body, cfg["valid_path"]) if cfg["valid_path"] else None
    if isinstance(v, bool):
        row["valid"] = "true" if v else "false"
    elif isinstance(v, (int, float)):  # confidence-score vendors (mappings _rule)
        row["valid"] = "true" if v >= MAPPINGS["validity_map"]["score_threshold"] else "false"
    elif isinstance(v, str) and "valid_strings" in cfg:
        # Status-string vendors (1Lookup V2 number_status). Unknown values are
        # OUR mapping gap — logged for review, dimension abstains, run fails
        # loudly at the end (same contract as unmapped line types).
        vs = cfg["valid_strings"]
        if v in vs["true"]:
            row["valid"] = "true"
        elif v in vs["false"]:
            row["valid"] = "false"
        else:
            unmapped.append({"vendor": vendor, "row_id": record["row_id"], "raw": f"validity:{v}"})

    lt_raw = dig(body, cfg["line_type_path"]) if cfg["line_type_path"] else None
    if lt_raw is not None and lt_raw != "":
        table = MAPPINGS["line_type_map"].get(vendor, {})
        mapped = table.get(str(lt_raw))
        if mapped is None:
            # A value our mapping doesn't know is OUR gap, not the vendor's
            # answer. Never silently publish: log for freeze review and leave
            # the dimension abstained; the run fails loudly at the end.
            unmapped.append({"vendor": vendor, "row_id": record["row_id"], "raw": str(lt_raw)})
        else:
            row["line_type"] = mapped

    carrier = dig(body, cfg["carrier_path"]) if cfg["carrier_path"] else None
    if isinstance(carrier, str):
        row["carrier"] = carrier  # raw string; score.py owns brand normalization
    return row


def cmd_normalize(args) -> int:
    run_dir = ARCHIVE_ROOT / args.run_id
    if not run_dir.is_dir():
        print(f"no archive at {run_dir}", file=sys.stderr)
        return 2
    answers, unmapped = [], []
    for vdir in sorted(p for p in run_dir.iterdir() if p.is_dir()):
        for f in sorted(vdir.glob("*.json")):
            answers.append(normalize_record(vdir.name, json.loads(f.read_text()), unmapped))
    out = run_dir / "answers.csv"
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["vendor", "row_id", "valid", "line_type", "carrier", "error"])
        w.writeheader()
        w.writerows(answers)
    print(f"wrote {out} ({len(answers)} rows)")
    if unmapped:
        review = run_dir / "unmapped-line-types.json"
        review.write_text(json.dumps(unmapped, indent=1))
        print(f"REFUSING to treat {len(unmapped)} unmapped line-type value(s) as answers — "
              f"finalize mappings.json (see {review}) and re-run normalize.", file=sys.stderr)
        return 1
    return 0


# --------------------------------------------------------------------------
# §6 window verification
# --------------------------------------------------------------------------

def cmd_verify_windows(args) -> int:
    run_dir = ARCHIVE_ROOT / args.run_id
    per_row: dict[str, list[datetime]] = {}
    all_ts: list[datetime] = []
    for vdir in (p for p in run_dir.iterdir() if p.is_dir()):
        for f in vdir.glob("*.json"):
            rec = json.loads(f.read_text())
            ts = datetime.fromisoformat(rec["collected_at"])
            per_row.setdefault(rec["row_id"], []).append(ts)
            all_ts.append(ts)
    if not all_ts:
        print("empty archive", file=sys.stderr)
        return 2
    run_span_h = (max(all_ts) - min(all_ts)).total_seconds() / 3600
    worst_row_h = max(((max(v) - min(v)).total_seconds() / 3600 for v in per_row.values()), default=0.0)
    ok_run, ok_row = run_span_h <= RUN_WINDOW_H, worst_row_h <= ROW_WINDOW_H
    print(json.dumps({
        "run_span_hours": round(run_span_h, 2), "run_window_ok": ok_run,
        "worst_row_spread_hours": round(worst_row_h, 2), "row_window_ok": ok_row,
    }, indent=1))
    return 0 if (ok_run and ok_row) else 1


# --------------------------------------------------------------------------
# Probe — one live call, raw dump (freeze verification of adapters/mappings)
# --------------------------------------------------------------------------

def cmd_probe(args) -> int:
    vendor = args.vendor
    if vendor not in VENDORS:
        print(f"unknown vendor {vendor!r}; known: {list(VENDORS)}", file=sys.stderr)
        return 2
    missing = [e for e in VENDORS[vendor]["env"] if not os.environ.get(e)]
    if missing:
        print(f"set {missing} first", file=sys.stderr)
        return 2
    print(f"# adapter status: {VENDORS[vendor]['status']}", file=sys.stderr)
    status, body = fetch_once(vendor, args.e164)
    print(f"# http {status}", file=sys.stderr)
    print(body)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("collect", help="query vendors per §6, archive verbatim")
    c.add_argument("dataset")
    c.add_argument("--run-id", required=True)
    c.add_argument("--vendors", help=f"comma list (default: {','.join(RUN_001_VENDORS)})")
    c.add_argument("--interval", action="append", metavar="vendor=seconds",
                   help="override a vendor's min request interval")
    c.add_argument("--include-boundstone", action="store_true",
                   help="quarterly re-runs only — §2 excludes boundstone from № 001")
    c.set_defaults(fn=cmd_collect)

    n = sub.add_parser("normalize", help="archive -> answers.csv for score.py")
    n.add_argument("run_id")
    n.set_defaults(fn=cmd_normalize)

    w = sub.add_parser("verify-windows", help="check §6 72h run / 24h per-row windows")
    w.add_argument("run_id")
    w.set_defaults(fn=cmd_verify_windows)

    pr = sub.add_parser("probe", help="one live call, raw response to stdout")
    pr.add_argument("vendor")
    pr.add_argument("e164")
    pr.set_defaults(fn=cmd_probe)

    args = p.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())

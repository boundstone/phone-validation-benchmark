#!/usr/bin/env python3
"""Golden tests for run_vendors.py — each METHODOLOGY §6 collection rule has a
named case. All numbers are from the ATIS fictional range (+1 XXX 555-01XX);
no network access anywhere (fetch_once is monkeypatched). Run:

    python3 test_run_vendors.py
"""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import run_vendors as rv


def record(vendor, attempts, row_id="r1", e164="+14155550100"):
    return {"vendor": vendor, "row_id": row_id, "e164": e164,
            "collected_at": "2026-07-16T00:00:00+00:00", "attempts": attempts}


def ok(body, status=200):
    return {"at": "2026-07-16T00:00:00+00:00", "http_status": status,
            "body": json.dumps(body) if isinstance(body, dict) else body}


class NormalizeRules(unittest.TestCase):
    def test_boolean_valid_and_mapped_line_type(self):
        """Happy path: bool valid used directly, vocab mapped via mappings.json."""
        row = rv.normalize_record("numverify", record("numverify", [ok(
            {"valid": True, "line_type": "mobile", "carrier": "Fictional Wireless"})]), [])
        self.assertEqual((row["valid"], row["line_type"], row["carrier"], row["error"]),
                         ("true", "mobile", "Fictional Wireless", ""))

    def test_dotted_paths_twilio_shape(self):
        """Nested field paths (line_type_intelligence.type) resolve."""
        row = rv.normalize_record("twilio", record("twilio", [ok(
            {"valid": True, "line_type_intelligence": {"type": "nonFixedVoip",
                                                       "carrier_name": "Fictional VoIP Co"}})]), [])
        self.assertEqual(row["line_type"], "non_fixed_voip")
        self.assertEqual(row["carrier"], "Fictional VoIP Co")

    def test_twilio_404_is_an_invalid_answer_not_an_error(self):
        """Lookup v2 404 == vendor answered 'cannot resolve' -> valid:false."""
        row = rv.normalize_record("twilio", record("twilio", [ok("Not Found", 404)]), [])
        self.assertEqual((row["valid"], row["error"]), ("false", ""))

    def test_5xx_after_retries_forces_abstain(self):
        """§6: failed after retries -> error column set, all dimensions empty."""
        row = rv.normalize_record("numverify", record("numverify",
                                                      [ok("boom", 500), ok("boom", 502), ok("boom", 503)]), [])
        self.assertEqual(row["error"], "http_503")
        self.assertEqual((row["valid"], row["line_type"], row["carrier"]), ("", "", ""))

    def test_transport_only_attempts_force_abstain(self):
        row = rv.normalize_record("numverify", record("numverify", [
            {"at": "2026-07-16T00:00:00+00:00", "transport_error": "TimeoutError: timed out"},
            {"at": "2026-07-16T00:01:00+00:00", "transport_error": "TimeoutError: timed out"},
            {"at": "2026-07-16T00:02:00+00:00", "transport_error": "TimeoutError: timed out"},
        ]), [])
        self.assertIn("TimeoutError", row["error"])

    def test_retry_recovery_uses_final_attempt(self):
        """A 5xx followed by a 200 within the retry budget is a clean answer."""
        row = rv.normalize_record("numverify", record("numverify", [
            ok("boom", 500), ok({"valid": False, "line_type": "landline", "carrier": ""})]), [])
        self.assertEqual((row["valid"], row["line_type"], row["error"]), ("false", "landline", ""))

    def test_unmapped_line_type_is_logged_never_published(self):
        """A vocab value missing from mappings.json abstains + lands in review."""
        unmapped = []
        row = rv.normalize_record("numverify", record("numverify", [ok(
            {"valid": True, "line_type": "quantum_entangled", "carrier": ""})]), unmapped)
        self.assertEqual(row["line_type"], "")
        self.assertEqual(unmapped[0]["raw"], "quantum_entangled")

    def test_confidence_score_validity_threshold(self):
        """mappings.json _rule: numeric valid maps via score_threshold (0.5)."""
        hi = rv.normalize_record("trestle", record("trestle", [ok({"is_valid": 0.9, "line_type": "Mobile", "carrier": ""})]), [])
        lo = rv.normalize_record("trestle", record("trestle", [ok({"is_valid": 0.2, "line_type": "Mobile", "carrier": ""})]), [])
        self.assertEqual((hi["valid"], lo["valid"]), ("true", "false"))

    def test_unparseable_body_is_an_error(self):
        row = rv.normalize_record("numverify", record("numverify", [ok("<html>oops</html>")]), [])
        self.assertEqual(row["error"], "unparseable_body")


class CollectProtocol(unittest.TestCase):
    def _patched(self, outcomes):
        """Patch fetch_once to pop scripted outcomes and never sleep for real."""
        calls = {"n": 0, "sleeps": []}

        def fake_fetch(vendor, e164):
            out = outcomes[min(calls["n"], len(outcomes) - 1)]
            calls["n"] += 1
            if isinstance(out, Exception):
                raise out
            return out

        real_fetch, real_sleep = rv.fetch_once, rv.time.sleep
        rv.fetch_once = fake_fetch
        rv.time.sleep = lambda s: calls["sleeps"].append(s)
        self.addCleanup(lambda: (setattr(rv, "fetch_once", real_fetch),
                                 setattr(rv.time, "sleep", real_sleep)))
        return calls

    def test_5xx_retries_twice_spaced_60s(self):
        calls = self._patched([(503, "down"), (503, "down"), (503, "down")])
        with tempfile.TemporaryDirectory() as d:
            rv.collect_row("numverify", "r1", "+14155550100", Path(d) / "r1.json")
            rec = json.loads((Path(d) / "r1.json").read_text())
        self.assertEqual(calls["n"], 3)  # 1 attempt + 2 retries, then stop
        self.assertEqual(calls["sleeps"], [60, 60])  # §6: spaced >=60s
        self.assertEqual([a["http_status"] for a in rec["attempts"]], [503, 503, 503])

    def test_2xx_stops_immediately_no_retry(self):
        calls = self._patched([(200, "{\"valid\": true}")])
        with tempfile.TemporaryDirectory() as d:
            rv.collect_row("numverify", "r1", "+14155550100", Path(d) / "r1.json")
        self.assertEqual(calls["n"], 1)
        self.assertEqual(calls["sleeps"], [])

    def test_4xx_is_final_not_retried(self):
        """§6 retries are for transport/5xx only — a 400 is the vendor's last word."""
        calls = self._patched([(400, "bad request")])
        with tempfile.TemporaryDirectory() as d:
            rv.collect_row("numverify", "r1", "+14155550100", Path(d) / "r1.json")
        self.assertEqual(calls["n"], 1)

    def test_archive_is_verbatim(self):
        body = "{\"valid\": true, \"weird_field\": \"kept exactly \\u2014 verbatim\"}"
        self._patched([(200, body)])
        with tempfile.TemporaryDirectory() as d:
            rv.collect_row("numverify", "r1", "+14155550100", Path(d) / "r1.json")
            rec = json.loads((Path(d) / "r1.json").read_text())
        self.assertEqual(rec["attempts"][0]["body"], body)


class EndToEnd(unittest.TestCase):
    def test_normalize_run_produces_score_py_contract(self):
        """A fake archive normalizes into exactly the answers.csv score.py reads."""
        with tempfile.TemporaryDirectory() as d:
            run = Path(d) / "run-test" / "numverify"
            run.mkdir(parents=True)
            (run / "r1.json").write_text(json.dumps(record("numverify", [ok(
                {"valid": True, "line_type": "toll_free", "carrier": "Fictional Telecom"})])))
            real_root = rv.ARCHIVE_ROOT
            rv.ARCHIVE_ROOT = Path(d)
            try:
                code = rv.cmd_normalize(SimpleNamespace(run_id="run-test"))
            finally:
                rv.ARCHIVE_ROOT = real_root
            out = (Path(d) / "run-test" / "answers.csv").read_text().splitlines()
        self.assertEqual(code, 0)
        self.assertEqual(out[0], "vendor,row_id,valid,line_type,carrier,error")
        self.assertEqual(out[1], "numverify,r1,true,toll_free,Fictional Telecom,")




class OneLookupV2Rules(unittest.TestCase):
    """Adapter rules pinned from the 2026-07-25 live probes of their V2 platform."""

    V2 = {"data": {"classification": {"number_status": "ACTIVE", "line_type": "MOBILE"},
                   "insights": {"raw_api_fields": {"network": "Fictional Wireless"}}}}

    def test_v2_shape_maps_all_three_dimensions(self):
        row = rv.normalize_record("onelookup", record("onelookup", [ok(self.V2)]), [])
        self.assertEqual((row["valid"], row["line_type"], row["carrier"], row["error"]),
                         ("true", "mobile", "Fictional Wireless", ""))

    def test_http400_is_an_invalid_answer_not_an_error(self):
        """V2 answers unparseable numbers with 400 INVALID_INPUT — a vendor answer."""
        row = rv.normalize_record("onelookup", record("onelookup", [ok(
            {"success": False, "error": {"code": "INVALID_INPUT"}}, 400)]), [])
        self.assertEqual((row["valid"], row["error"]), ("false", ""))

    def test_unknown_status_string_abstains_and_logs(self):
        """A number_status we haven't mapped is OUR gap: abstain + loud log."""
        body = {"data": {"classification": {"number_status": "SUSPENDED_MAYBE"}}}
        unmapped = []
        row = rv.normalize_record("onelookup", record("onelookup", [ok(body)]), unmapped)
        self.assertEqual(row["valid"], "")
        self.assertEqual(len(unmapped), 1)
        self.assertIn("SUSPENDED_MAYBE", unmapped[0]["raw"])

    def test_other_4xx_still_an_error_not_an_answer(self):
        """401/403/429 must NOT be treated as vendor answers (on_4xx stays 'error')."""
        row = rv.normalize_record("onelookup", record("onelookup", [ok(
            {"error": "unauthorized"}, 401)]), [])
        self.assertEqual((row["valid"], row["error"]), ("", "http_401"))


if __name__ == "__main__":
    unittest.main(verbosity=2)

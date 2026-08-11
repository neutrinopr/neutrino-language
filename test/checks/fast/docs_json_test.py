"""[fast] Every committed `docs/**/*.json` must be valid JSON — so a machine-readable
artifact (e.g. the  S1 measurement report m6_tablegen_pilot_s1_measurements.json) cannot
land malformed while all other CI is green. No build, no schema — a pure stdlib parse smoke,
with a non-vacuous floor so a wrong dir / eroded set can never pass on zero files."""

import json
import os
import unittest

from _fastcase import FastCase, REPO


class DocsJson(FastCase):
    def test_all_docs_json_parse(self):
        files = self.globr("docs/**/*.json")
        self.require_floor("committed docs/ JSON artifacts", len(files), 3)
        bad = []
        for f in files:
            try:
                json.load(open(f, encoding="utf-8"))
            except (ValueError, OSError) as ex:
                bad.append(f"{os.path.relpath(f, REPO)}: {ex}")
        self.assertEqual(bad, [], "malformed committed docs/ JSON:\n" + "\n".join(bad))

    def test_s1_measurement_report_present_and_records_a_decision(self):
        # The  S1 pilot's machine-readable result must exist, parse, and carry an explicit
        # pilot decision (the pre-registered proceed/stop outcome) — not silently drop or truncate.
        #  (C0 correction) renamed the field to `pilotDecision` alongside the historical text.
        p = os.path.join(REPO, "docs", "process", "m6_tablegen_pilot_s1_measurements.json")
        self.assertTrue(os.path.isfile(p), "S1 measurement report is missing")
        data = json.load(open(p, encoding="utf-8"))
        self.assertIn("pilotDecision", data, "S1 measurement report records no decision")
        self.assertTrue(str(data["pilotDecision"]).strip(), "S1 decision is empty")


if __name__ == "__main__":
    unittest.main()

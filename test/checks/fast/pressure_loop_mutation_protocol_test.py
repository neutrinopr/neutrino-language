#!/usr/bin/env python3
import json
import os

from _fastcase import FastCase, REPO


SCRIPT = "scripts/gates/check_pressure_loop_mutation_protocol.py"
FIXTURE = os.path.join(REPO, "examples/pressure-loop-mutations/s3a-representative.json")


class PressureLoopMutationProtocol(FastCase):
    def load_fixture(self):
        return self.load_json(FIXTURE)

    def write_fixture(self, obj):
        path = os.path.join(self.tmp, "mutation-protocol.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(obj, fh)
        return path

    def test_committed_protocol_passes(self):
        self.val_ok("pressure-loop mutation protocol", SCRIPT, FIXTURE)

    def test_selftest_is_non_vacuous(self):
        self.val_ok("pressure-loop mutation protocol selftest", SCRIPT, "--selftest")

    def test_report_contains_all_representative_categories(self):
        result = self.val_ok("pressure-loop mutation report", SCRIPT, FIXTURE, "--json")
        report = json.loads(result.stdout.decode("utf-8"))
        self.assertTrue(report["ok"])
        categories = {c["category"] for c in report["report"]["cases"]}
        self.assertEqual(categories, {
            "dropped-l2-obligation",
            "runtime-binding-moved-into-semantic-identity",
            "backend-inference-introduced",
            "bound-terminal-removed",
            "correlated-evidence-substituted",
        })
        for case in report["report"]["cases"]:
            self.assertIn(case["expectedDiagnostic"], case["observedDiagnostics"])

    def test_zero_case_matrix_rejected(self):
        obj = self.load_fixture()
        obj["cases"] = []
        rejected = self.val_reject("zero mutation cases rejected", SCRIPT, self.write_fixture(obj), "--json")
        self.assertIn("pressure_loop_mutation.zero_case", rejected.stdout.decode("utf-8", "replace"))

    def test_missing_category_rejected(self):
        obj = self.load_fixture()
        obj["cases"] = obj["cases"][:-1]
        rejected = self.val_reject("missing mutation category rejected", SCRIPT, self.write_fixture(obj), "--json")
        self.assertIn("pressure_loop_mutation.missing_category", rejected.stdout.decode("utf-8", "replace"))

    def test_wrong_expected_diagnostic_rejected(self):
        obj = self.load_fixture()
        obj["cases"][0]["expectedDiagnostic"] = "pressure_loop_mutation.never"
        rejected = self.val_reject("non-biting mutation expectation rejected", SCRIPT, self.write_fixture(obj), "--json")
        self.assertIn("pressure_loop_mutation.not_caught", rejected.stdout.decode("utf-8", "replace"))

    def test_unknown_mutation_field_rejected(self):
        obj = self.load_fixture()
        obj["cases"][0]["mutation"]["ignored"] = "unreviewed"
        rejected = self.val_reject("unknown mutation field rejected", SCRIPT, self.write_fixture(obj), "--json")
        self.assertIn("pressure_loop_mutation.mutation_schema", rejected.stdout.decode("utf-8", "replace"))

    def test_non_string_evidence_locus_rejected(self):
        obj = self.load_fixture()
        obj["cases"][2]["mutation"]["value"] = ["backend-inference"]
        rejected = self.val_reject("non-string evidence locus rejected", SCRIPT, self.write_fixture(obj), "--json")
        self.assertIn("pressure_loop_mutation.mutation_schema", rejected.stdout.decode("utf-8", "replace"))

    def test_gate_integrity_probes_bite(self):
        for probe in [
            "zero-cases",
            "missing-category",
            "wrong-expected-diagnostic",
            "fabricated-independence",
            "unknown-mutation-field",
            "non-string-evidence-locus",
        ]:
            with self.subTest(probe=probe):
                self.val_reject("pressure-loop mutation protocol probe", SCRIPT, "--probe", probe)


if __name__ == "__main__":
    import unittest
    unittest.main()

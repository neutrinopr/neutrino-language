#!/usr/bin/env python3
import json
import os

from _fastcase import FastCase, REPO


SCRIPT = "scripts/validators/validate_pressure_loop_register.py"


class PressureLoopRegister(FastCase):
    def good(self):
        return {
            "kind": "neutrino.pressure-loop-register",
            "schemaVersion": 2,
            "rows": [
                {
                    "rowId": "r-001",
                    "requirement": "Evidence event carries an observation source.",
                    "provenance": {"source": "M6_L2_BRIDGE_ADR Decision 4", "authorityWeightTier": "1"},
                    "outcome": "accepted",
                    "class": None,
                    "disposition": "L1_CORE",
                    "failedVerifierObligation": None,
                    "minimalCounterexample": None,
                    "owner": "translator",
                    "linkedDecision": None,
                    "supportStatus": "present",
                    "currentArtifactOperation": "SolStmt::emitEvent",
                    "evidenceRefs": [{"type": "executable", "ref": "test/ir/l2/domain_semantics_emit.mlir"}],
                },
                {
                    "rowId": "r-002",
                    "requirement": "Hybrid settlement obligation coverage.",
                    "provenance": {"source": "stress-corpus/case-042", "authorityWeightTier": "2"},
                    "outcome": "accepted",
                    "class": None,
                    "disposition": "L2_REFINEMENT",
                    "failedVerifierObligation": None,
                    "minimalCounterexample": None,
                    "owner": "translator",
                    "linkedDecision": None,
                    "supportStatus": "partial",
                    "currentArtifactOperation": "L2Reduction::emitSettlementEdge",
                    "evidenceRefs": [{"type": "executable", "ref": "fixtures/pressure-loop/hybrid-settlement.l2.json"}],
                },
                {
                    "rowId": "r-003",
                    "requirement": "Hybrid settlement obligation coverage.",
                    "provenance": {"source": "stress-corpus/case-042/uncovered", "authorityWeightTier": "2"},
                    "outcome": "unresolved",
                    "class": "2",
                    "disposition": "UNSUPPORTED_REFUSED",
                    "failedVerifierObligation": "No executable L2 edge covers the external settlement reversal obligation.",
                    "minimalCounterexample": None,
                    "owner": "translator",
                    "linkedDecision": None,
                    "supportStatus": "absent",
                    "currentArtifactOperation": None,
                    "evidenceRefs": [{"type": "refusal", "ref": "neutrino-"}],
                },
                {
                    "rowId": "r-004",
                    "requirement": "Unfactored lifecycle branch needs an explicit layer decision.",
                    "provenance": {"source": "stress-corpus/case-042", "authorityWeightTier": "2"},
                    "outcome": "unresolved",
                    "class": "3",
                    "disposition": "LAYER_DECISION_REQUIRED",
                    "failedVerifierObligation": "No single L2 reduction can preserve both branch meanings.",
                    "minimalCounterexample": "Two accepted source obligations collapse to the same target transition.",
                    "owner": "architecture-owner",
                    "linkedDecision": "neutrino-",
                    "supportStatus": "absent",
                    "currentArtifactOperation": None,
                    "evidenceRefs": [],
                },
                {
                    "rowId": "r-005",
                    "requirement": "Runtime-only telemetry is tracked outside the static pressure-loop register.",
                    "provenance": {"source": "M6_L2_BRIDGE_ADR Runtime boundary", "authorityWeightTier": "1"},
                    "outcome": "accepted",
                    "class": None,
                    "disposition": "L3_RUNTIME",
                    "failedVerifierObligation": None,
                    "minimalCounterexample": None,
                    "owner": "runtime-owner",
                    "linkedDecision": None,
                    "supportStatus": "absent",
                    "currentArtifactOperation": None,
                    "evidenceRefs": [],
                },
            ],
        }

    def write(self, obj):
        path = os.path.join(self.tmp, "pressure-loop-register.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(obj, fh)
        return path

    def test_schema_file_is_json(self):
        self.load_json(os.path.join(REPO, "docs/schemas/pressure-loop-register.schema.json"))

    def test_positive_register_validates(self):
        self.val_ok("pressure-loop register positive", SCRIPT, self.write(self.good()))

    def test_committed_positive_fixture_validates(self):
        self.val_ok(
            "pressure-loop register committed fixture",
            SCRIPT,
            os.path.join(REPO, "examples/pressure-loop-register/v2-positive.json"),
        )

    def test_selftest_is_non_vacuous(self):
        self.val_ok("pressure-loop register selftest", SCRIPT, "--selftest")

    def test_rejects_v1_registers(self):
        obj = self.good()
        obj["schemaVersion"] = 1
        rejected = self.val_reject("v1 register rejected", SCRIPT, self.write(obj), "--json")
        self.assertIn("pressure_loop.schema_version", rejected.stdout.decode("utf-8", "replace"))

    def test_rejects_malformed_enum(self):
        obj = self.good()
        obj["rows"][0]["outcome"] = "maybe"
        rejected = self.val_reject("bad outcome rejected", SCRIPT, self.write(obj), "--json")
        self.assertIn("pressure_loop.enum", rejected.stdout.decode("utf-8", "replace"))

    def test_rejects_boolean_schema_version(self):
        obj = self.good()
        obj["schemaVersion"] = True
        rejected = self.val_reject("boolean schemaVersion rejected", SCRIPT, self.write(obj), "--json")
        self.assertIn("pressure_loop.schema_version", rejected.stdout.decode("utf-8", "replace"))

    def test_rejects_unhashable_enum_values_without_traceback(self):
        obj = self.good()
        obj["rows"][0]["outcome"] = []
        obj["rows"][1]["provenance"]["authorityWeightTier"] = {}
        rejected = self.val_reject("unhashable enum values rejected", SCRIPT, self.write(obj), "--json")
        body = rejected.stdout.decode("utf-8", "replace")
        self.assertIn("pressure_loop.enum", body)
        stderr = rejected.stderr.decode("utf-8", "replace") if rejected.stderr else ""
        self.assertNotIn("Traceback", stderr + body)

    def test_decision_row_requires_counterexample_and_decision(self):
        obj = self.good()
        obj["rows"][3]["minimalCounterexample"] = None
        obj["rows"][3]["linkedDecision"] = None
        rejected = self.val_reject("decision obligations rejected", SCRIPT, self.write(obj), "--json")
        body = rejected.stdout.decode("utf-8", "replace")
        self.assertIn("pressure_loop.decision_counterexample", body)
        self.assertIn("pressure_loop.linked_decision", body)

    def test_accepted_class_one_fixture_is_explicit_failure(self):
        obj = self.good()
        obj["rows"][0]["class"] = "1"
        rejected = self.val_reject("accepted class-1 rejected", SCRIPT, self.write(obj), "--json")
        self.assertIn("pressure_loop.accepted_class", rejected.stdout.decode("utf-8", "replace"))

    def test_unresolved_requires_failed_verifier_obligation(self):
        obj = self.good()
        obj["rows"][2]["failedVerifierObligation"] = None
        rejected = self.val_reject("unresolved obligation rejected", SCRIPT, self.write(obj), "--json")
        self.assertIn("pressure_loop.unresolved_obligation", rejected.stdout.decode("utf-8", "replace"))

    def test_decision_required_must_be_class_three(self):
        obj = self.good()
        obj["rows"][3]["class"] = "2"
        rejected = self.val_reject("decision class rejected", SCRIPT, self.write(obj), "--json")
        self.assertIn("pressure_loop.decision_contract", rejected.stdout.decode("utf-8", "replace"))

    def test_unsupported_refused_requires_refusal_evidence(self):
        obj = self.good()
        obj["rows"][2]["evidenceRefs"] = []
        rejected = self.val_reject("refusal evidence rejected", SCRIPT, self.write(obj), "--json")
        self.assertIn("pressure_loop.unsupported_refused", rejected.stdout.decode("utf-8", "replace"))

    def test_present_and_partial_require_executable_artifact_evidence(self):
        obj = self.good()
        obj["rows"][0]["currentArtifactOperation"] = None
        obj["rows"][1]["evidenceRefs"] = []
        rejected = self.val_reject("artifact evidence rejected", SCRIPT, self.write(obj), "--json")
        body = rejected.stdout.decode("utf-8", "replace")
        self.assertIn("pressure_loop.support_artifact", body)

    def test_partial_requires_absent_sibling(self):
        obj = self.good()
        obj["rows"][2]["requirement"] = "Different uncovered obligation"
        rejected = self.val_reject("partial sibling rejected", SCRIPT, self.write(obj), "--json")
        self.assertIn("pressure_loop.partial_sibling", rejected.stdout.decode("utf-8", "replace"))

    def test_runtime_descriptive_rows_must_not_fabricate_artifacts(self):
        obj = self.good()
        obj["rows"][4]["currentArtifactOperation"] = "fakeRuntimeArtifact"
        rejected = self.val_reject("orthogonal row rejected", SCRIPT, self.write(obj), "--json")
        self.assertIn("pressure_loop.orthogonal_disposition", rejected.stdout.decode("utf-8", "replace"))

    def test_duplicate_row_id_rejected(self):
        obj = self.good()
        obj["rows"][1]["rowId"] = obj["rows"][0]["rowId"]
        rejected = self.val_reject("duplicate rowId rejected", SCRIPT, self.write(obj), "--json")
        self.assertIn("pressure_loop.duplicate_row", rejected.stdout.decode("utf-8", "replace"))


if __name__ == "__main__":
    import unittest
    unittest.main()

"""[fast]  /  S8 pay-for-result forcing classifications and evidence."""

import json
import os
import sys
import unittest

from _fastcase import REPO, FastCase

sys.path.insert(0, os.path.join(REPO, "scripts", "generators"))

SCRIPT = "scripts/generators/run_pressure_loop_forcing.py"
VALIDATOR = "scripts/validators/validate_pressure_loop_register.py"
REGISTER = os.path.join(REPO, "examples/pressure-loop-register/s8-pay-for-result.json")
EVIDENCE = os.path.join(REPO, "examples/pressure-loop-forcing/evidence/plf-s8-pay-for-result-core.pay-for-result.json")


class PressureLoopS8PayForResult(FastCase):
    def test_selftest_covers_exact_contract_and_parity_non_vacuously(self):
        self.val_ok("pay-for-result composite selftest", SCRIPT, "--selftest")

    def test_committed_register_splits_core_tooling_gap_and_runtime(self):
        self.val_ok("S8 pay-for-result register validates", VALIDATOR, REGISTER)
        reg = self.load_json(REGISTER)
        self.assertEqual(reg["schemaVersion"], 2)
        rows = {row["rowId"]: row for row in reg["rows"]}
        self.assertEqual(set(rows), {
            "plf-s8-pay-for-result-core",
            "plf-s8-pay-for-result-execution-gap",
            "plf-s8-pay-for-result-runtime",
        })

        core = rows["plf-s8-pay-for-result-core"]
        self.assertEqual((core["outcome"], core["disposition"], core["supportStatus"]), ("accepted", "L1_CORE", "partial"))
        self.assertIsNone(core["class"])
        self.assertEqual(core["evidenceRefs"][0]["type"], "executable")

        gap = rows["plf-s8-pay-for-result-execution-gap"]
        self.assertEqual((gap["outcome"], gap["class"], gap["supportStatus"]), ("unresolved", "1", "absent"))
        self.assertIn("deadline", gap["failedVerifierObligation"])
        self.assertIn("prior state", gap["failedVerifierObligation"])
        self.assertEqual(gap["requirement"], core["requirement"])

        runtime = rows["plf-s8-pay-for-result-runtime"]
        self.assertEqual((runtime["outcome"], runtime["disposition"], runtime["supportStatus"]), ("accepted", "L3_RUNTIME", "absent"))
        self.assertEqual(runtime["evidenceRefs"], [])
        self.assertIsNone(runtime["currentArtifactOperation"])

    def test_committed_evidence_is_exact_and_honest(self):
        ev = self.load_json(EVIDENCE)
        self.assertEqual(ev["kind"], "pay-for-result-proof")
        reduction = ev["reduction"]
        self.assertTrue(reduction["balanced"])
        self.assertEqual([e["kind"] for e in reduction["effects"]], ["debit", "credit"])
        self.assertEqual([e["name"] for e in reduction["effects"]], ["bounty_out", "bounty_in"])
        self.assertEqual(reduction["attestationPolicies"], ["result_proof"])
        self.assertEqual(reduction["attestation"]["observerSet"], {
            "assurance": "A3",
            "independence": "independent",
            "ref": "result_validators",
            "role": None,
        })
        self.assertEqual(reduction["replay"], {"allTransitionsReject": True, "idempotent": True, "key": "job_id"})

        parity = ev["parity"]
        self.assertTrue(parity["directPlanEqualsPlanFromSpec"])
        self.assertTrue(parity["sourceReductionEqualsSpecReduction"])
        self.assertTrue(parity["acceptedDirectTraceEqualsFromSpecTrace"])
        self.assertTrue(parity["unacceptedDirectTraceEqualsFromSpecTrace"])
        self.assertEqual(len(parity["l2Bindings"]), 10)
        self.assertEqual(set(parity["l2Features"]), {b["feature"] for b in parity["l2Bindings"]})

        accepted = ev["acceptedSettlement"]
        self.assertEqual(accepted["postedKeys"], ["J-1"])
        self.assertEqual([(d["effect"], d["delta"]) for d in accepted["deltas"]], [("bounty_out", -1000), ("bounty_in", 1000)])
        self.assertEqual(ev["unacceptedNoSettlement"]["deltas"], [])
        self.assertEqual(ev["unacceptedNoSettlement"]["postedKeys"], [])
        self.assertIn("--from-spec", ev["unacceptedNoSettlement"]["fromSpecArgv"])

        self.assertEqual(ev["mixedGuardBoundary"]["anchor"], "kernel.balance.unbalanced")
        self.assertIn("does not claim", ev["mixedGuardBoundary"]["note"])
        self.assertFalse(ev["executionGap"]["deadline"]["behaviorallyExecuted"])
        self.assertFalse(ev["executionGap"]["secondInvocation"]["behaviorallyExecuted"])

        blob = json.dumps(ev)
        for leak in ("/Volumes", "/private", "/var/folders"):
            self.assertNotIn(leak, blob)


if __name__ == "__main__":
    unittest.main()

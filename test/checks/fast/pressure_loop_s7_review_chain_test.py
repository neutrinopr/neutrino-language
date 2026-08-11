"""[fast]  /  S7: the bounded review-chain COMPOSITE forcing.

A review chain is an ordered, escalating sequence of bounded stages. Its leaf stages
reduce through the authoritative L2 bridge to the closed requirement set — so this is
NOT a missing L1 primitive (v1's LANGUAGE_DECISION was wrong). What has no
representation is the cross-stage ORCHESTRATION: an explicit recursive stage->stage
relation is refused by the reducer (l2.reduce edges must target L1 features), and the
source-level ordered expression is refused before any dispatch. Per ADR M6_L2_BRIDGE
§7 that overload of a single L2 is an earned LAYER_DECISION_REQUIRED — the
pre-registered rule that admits the review-chain orchestration stratum.

The harness DERIVES the row only from the full closed conjunction (exact leaf
binding multiset + lossiness; declaration-order invariance; concept-target/cycle
refusal; ordered refusal before dispatch; exact accept/refuse terminals; unmet-quorum
no-effect; authority pinned). Timeout/fallback and second-execution replay are
recorded as declared-but-not-executed (a trace-CLI tooling gap), not gates. This test
pins the committed earned artifacts, proves the derivation reproduces, and defers to
the harness selftest for the per-element non-vacuity. The BUILT-tool witness is the
sibling lit test test/ir/l2/review_chain_forcing.test.
"""

import json
import os
import sys
import unittest

from _fastcase import REPO, FastCase

sys.path.insert(0, os.path.join(REPO, "scripts", "generators"))

SCRIPT = "scripts/generators/run_pressure_loop_forcing.py"
VALIDATOR = "scripts/validators/validate_pressure_loop_register.py"
REGISTER = os.path.join(REPO, "examples/pressure-loop-register/s7-review-chain.json")
EVIDENCE = os.path.join(REPO, "examples/pressure-loop-forcing/evidence/plf-s7-review-chain-overload.orchestration-overload.json")


class PressureLoopS7ReviewChain(FastCase):
    def test_selftest_covers_the_full_conjunction_non_vacuously(self):
        # The harness selftest emits the composite row from a faithful mock AND proves
        # every conjunction element is load-bearing (leaf-fails / l2-fails / wrong-binding
        # / lossiness-drift / permutation-mismatch / recursive-succeeds / recursive-*-drift
        # / ordered-succeeds / ordered-code-drift / loss-witness / dispatch-on-reject /
        # terminal-missing / wrong-terminal / timeout-drift / anchor-drift / authority-
        # missing / miss-posts each withhold the row).
        self.val_ok("composite forcing selftest", SCRIPT, "--selftest")

    def test_committed_register_carries_earned_layer_row(self):
        self.val_ok("S7 review-chain register validates", VALIDATOR, REGISTER)
        reg = self.load_json(REGISTER)
        self.assertEqual(reg["schemaVersion"], 2)
        (row,) = reg["rows"]
        self.assertEqual(row["rowId"], "plf-s7-review-chain-overload")
        self.assertEqual(row["outcome"], "unresolved")
        self.assertEqual(row["disposition"], "LAYER_DECISION_REQUIRED")
        self.assertEqual(row["class"], "3")
        self.assertEqual(row["supportStatus"], "absent")
        # The obligation names the LOST RELATION, not the spelling of the refused token.
        self.assertEqual(row["failedVerifierObligation"],
                         "L2 cannot preserve the required assessor-before-reviewer dependency through reduction")
        self.assertNotIn("after", row["failedVerifierObligation"])
        # Authority is pinned:  (decision), ADR §7,  (layer rule).
        for token in ("neutrino-", "M6_L2_BRIDGE", "neutrino-"):
            self.assertIn(token, row["linkedDecision"])
        self.assertIn("declaration-order invariant", row["minimalCounterexample"])
        self.assertIn("recursive stage->stage relation is refused", row["minimalCounterexample"])
        self.assertEqual(row["evidenceRefs"][0]["type"], "refusal")

    def test_committed_evidence_captures_every_conjunction_element(self):
        ev = self.load_json(EVIDENCE)
        self.assertEqual(ev["kind"], "orchestration-overload-proof")
        # leaf coordination-plan carries both gates as an unordered set (corroborating).
        self.assertEqual(sorted(ev["leafReduction"]["attestationPolicies"]),
                         ["assessor_report", "reviewer_signoff"])
        # (1) AUTHORITATIVE L2 reduction: the FULL binding multiset (concept + feature
        # + relation + inducedBy + edge), not just concept names.
        self.assertEqual(ev["l2Reduction"]["exitCode"], 0)
        self.assertEqual(sorted(b["concept"] for b in ev["l2Reduction"]["bindings"]),
                         ["assessor_review", "reviewer_signoff"])
        self.assertTrue(all(b["feature"] == "attestation:quorum" and b["relation"] == "expands"
                            for b in ev["l2Reduction"]["bindings"]))
        # lossiness is carried via the domain-semantics edge records (the projection omits it).
        self.assertTrue(all(r["lossiness"] == "lossless" for r in ev["l2SemanticEdges"]["reductions"]))
        # (2) declaration-order invariance (NOT semantic ordering loss on its own).
        self.assertTrue(ev["declarationOrderInvariance"]["canonicalGraphIdentical"])
        # (3) recursive stage->stage CYCLE refused by the reducer — pinned tuple.
        self.assertEqual(ev["recursiveRefusal"]["op"], "l2.reduce")
        self.assertEqual(ev["recursiveRefusal"]["obligation"], "reduction edge targets undeclared L1 feature")
        self.assertEqual(ev["recursiveRefusal"]["anchor"], "stage_b")
        self.assertNotEqual(ev["recursiveRefusal"]["exitCode"], 0)
        # (4) source-level ordered refused before dispatch with pinned code + anchor.
        self.assertEqual(ev["orderedRefusal"]["code"], "source.parse")
        self.assertEqual(ev["orderedRefusal"]["token"], "after")
        self.assertEqual(ev["orderedRefusal"]["anchor"], "award_out")
        self.assertEqual(ev["orderedRefusal"]["noDispatch"], {"ok": False, "artifacts": []})
        # (5) explicit accept + refuse terminals; unmet quorum posts no partial effect.
        self.assertTrue(ev["terminals"].get("success") and ev["terminals"].get("aborted"))
        self.assertGreater(ev["unmetQuorumNoEffect"]["metDeltas"], 0)
        self.assertEqual(ev["unmetQuorumNoEffect"]["missDeltas"], 0)
        self.assertEqual(ev["unmetQuorumNoEffect"]["missBalances"], [])
        # timeout/replay are recorded HONESTLY as declared-not-executed (trace CLI gap),
        # not asserted as behaviorally verified.
        rt = ev["runtimeDisciplineDeclaredNotExecuted"]
        self.assertFalse(rt["timeoutFallback"]["behaviorallyExecuted"])
        self.assertFalse(rt["replayIdempotency"]["behaviorallyExecuted"])
        # the declared timeout/fallback are DERIVED from the stage's capability-spec.
        self.assertEqual(rt["timeoutFallback"]["declared"], {"timeout": "PT72H", "fallback": "abort"})
        self.assertEqual(rt["timeoutFallback"]["source"], "stage capability-spec attestations[0]")
        # exact accept/refuse terminal values.
        self.assertEqual(ev["terminals"], {"success": "CLOSED", "aborted": "REJECTED"})
        # Evidence is reproducible: no absolute worktree/tmp paths leaked.
        blob = json.dumps(ev)
        for leak in ("/Volumes", "/private", "/var/folders"):
            self.assertNotIn(leak, blob)


if __name__ == "__main__":
    unittest.main()

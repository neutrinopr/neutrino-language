#!/usr/bin/env python3
"""[fast]  M7 S0-C1 slot-descriptor authority bijection (modelling only).

No build. Asserts the bijection gate and its non-vacuity selftest pass, and that
the C1 exit bar holds: one derivation per witnessed census row, zero unnamed
residuals, and the three future authorities still empty.
"""
import json
import os

from _fastcase import FastCase, REPO

SCRIPT = "scripts/gates/check_slot_descriptor_bijection.py"
MODEL = "docs/slot-descriptor-bijection.json"
MIN_DERIVATIONS = 100


class SlotDescriptorBijection(FastCase):
    def test_bijection_matches_committed_model(self):
        self.val_ok("slot-descriptor bijection", SCRIPT)

    def test_selftest_is_non_vacuous(self):
        self.val_ok("slot-descriptor bijection selftest", SCRIPT, "--selftest")


class SlotDescriptorBijectionModel(FastCase):
    def setUp(self):
        super().setUp()
        with open(os.path.join(REPO, MODEL), encoding="utf-8") as f:
            self.model = json.load(f)

    def test_one_derivation_per_witnessed_row(self):
        m = self.model
        self.require_floor("derivations", m["totals"]["derivations"], MIN_DERIVATIONS)
        self.assertEqual(
            m["totals"]["derivations"], m["censusRows"],
            "C1 requires exactly one derivation per witnessed C0 census row")

    def test_zero_unnamed_residuals(self):
        """The C1 exit bar: every former UNSOURCED row is now an owned contract
        item, a typed derivation, or a named open adjudication."""
        self.assertEqual(self.model["unnamedResiduals"], 0)
        self.assertEqual(self.model["authorityTotals"]["unresolved-decision"], 0,
                         "a residual must be owned plus adjudicated, never filed "
                         "directly under unresolved-decision")
        self.assertGreaterEqual(len(self.model["decisions"]), 5)
        # The public exit exposes EXACTLY the derived residuals.
        self.assertEqual(
            self.model["residualDecisions"],
            sorted(n for n, d in self.model["decisions"].items()
                   if d["status"] != "resolved"))

    def test_future_authorities_stay_empty(self):
        """finalized-projection / target-profile / deploy-coordinate may not be
        populated aspirationally — only when a typed input is wired and witnessed."""
        for authority, count in self.model["futureAuthorities"].items():
            self.assertEqual(count, 0, f"{authority} gained rows without a witnessed "
                                       "typed input")

    def test_every_derivation_is_a_complete_chain(self):
        for row in self.model["derivations"]:
            where = row["fieldAddress"]
            self.assertTrue(row["transformation"], f"{where}: no transformation")
            self.assertTrue(row["canonicalOrder"], f"{where}: no canonical order")
            self.assertTrue(row["validationOwner"], f"{where}: no validation owner")
            self.assertTrue(row["sourceRef"] or row["contractItem"],
                            f"{where}: neither a source nor a contract item")


class SlotDescriptorBijectionC2(FastCase):
    """S0-C2: the decision ledger and cross-artifact resolutions."""

    def setUp(self):
        super().setUp()
        with open(os.path.join(REPO, MODEL), encoding="utf-8") as f:
            self.model = json.load(f)

    def test_every_decision_is_adjudicated(self):
        """No decision may sit statusless, and an unresolved one must state its
        consequence — a decision is made here, never silently deferred."""
        for name, decision in self.model["decisions"].items():
            self.assertIn(decision["status"],
                          ("resolved", "requires-generator-change"), name)
            self.assertTrue(decision.get("resolution"), f"{name}: no adjudication")
            if decision["status"] != "resolved":
                self.assertTrue(decision.get("consequence"),
                                f"{name}: unresolved with no stated consequence")

    def test_every_invariant_is_resolved(self):
        """Each cross-artifact invariant is either one shared derivation or two
        explicitly distinct identities — never left flagged-and-unowned."""
        for inv in self.model["crossArtifactInvariants"]:
            self.assertIn(inv["sharing"], ("one-derivation", "distinct-identities"),
                          inv["group"])
            self.assertTrue(inv.get("enforced"), f"{inv['group']} not enforced")

    def test_confirmable_flag_matches_the_ledger(self):
        """S0-BIJECTION-CONFIRMED is available only with zero open decisions and
        zero unresolved invariants; the flag is computed, not asserted."""
        c2 = self.model["checkpointC2"]
        expected = (c2["decisionsResolved"] == c2["decisionsTotal"]
                    and c2["invariantsUnresolved"] == 0)
        self.assertEqual(c2["bijectionConfirmable"], expected)


if __name__ == "__main__":
    import unittest

    unittest.main()

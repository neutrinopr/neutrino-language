#!/usr/bin/env python3
"""[fast]  M7 S0-C0 slot-descriptor authority census (probe/census only).

No build: the census reads the committed slot artifacts and their capability-spec
inputs. Asserts the gate + its non-vacuity selftest pass, and that the EMPIRICAL
result stays recorded rather than smoothed — two observed authorities plus
explicitly named UNSOURCED rows, with the three unobserved taxonomy authorities
carried at zero.
"""
import json

from _fastcase import FastCase

SCRIPT = "scripts/gates/check_slot_descriptor_authority.py"
INVENTORY = "docs/slot-descriptor-authority-inventory.json"
# Floors: the committed artifacts carry far more than this; a wrong dir or an
# eroded corpus must not pass on near-zero work.
MIN_FIELDS = 100
MIN_ARTIFACTS = 7
MIN_DOMAINS = 4


class SlotDescriptorAuthority(FastCase):
    def test_census_matches_committed_inventory(self):
        self.val_ok("slot-descriptor authority census", SCRIPT)

    def test_selftest_is_non_vacuous(self):
        self.val_ok("slot-descriptor authority selftest", SCRIPT, "--selftest")


class SlotDescriptorAuthorityInventory(FastCase):
    def setUp(self):
        super().setUp()
        import os
        from _fastcase import REPO
        with open(os.path.join(REPO, INVENTORY), encoding="utf-8") as f:
            self.inventory = json.load(f)

    def test_inventory_is_whole_and_non_vacuous(self):
        inv = self.inventory
        self.assertEqual(inv["kind"], "neutrino.slot-descriptor-authority-inventory")
        self.assertEqual(inv["checkpoint"], "S0-C0")
        self.require_floor("censused fields", inv["totals"]["fields"], MIN_FIELDS)
        self.require_floor("censused artifacts", len(inv["artifacts"]), MIN_ARTIFACTS)
        self.require_floor("representative domains", len(inv["domains"]), MIN_DOMAINS)
        self.assertEqual(inv["totals"]["fields"], len(inv["fields"]))

    def test_every_counted_field_is_witnessed(self):
        """Every counted row is an OBSERVATION, not a declaration: it must be
        witnessed by at least one committed domain. An unwitnessed row would make
        the S0-C3 authority totals partly speculative. Reachable-but-unexercised
        emitter branches are recorded as findings instead."""
        for row in self.inventory["fields"]:
            self.assertTrue(
                row["observedIn"],
                f"{row['fieldAddress']} is counted but witnessed by no domain — "
                "it belongs in unexercisedEmitterBranches, not in the authority rows")

    def test_every_field_is_individually_justified(self):
        """No row may be classified without per-field evidence: a spec-authored
        row needs a sourcePath, an UNSOURCED row needs a named reason, and every
        row cites the emitter that produces it."""
        for row in self.inventory["fields"]:
            where = row["fieldAddress"]
            self.assertTrue(row["emitter"], f"{where} cites no emitter")
            if row["authority"] == "capability-spec":
                self.assertTrue(row["sourcePath"], f"{where} has no sourcePath")
            elif row["authority"] == "UNSOURCED":
                self.assertTrue(row["unsourcedKind"], f"{where} names no reason")

    def test_empirical_authority_result_is_preserved(self):
        """The census records what the generator actually does. Only TWO
        authorities are observed; the other three carry zero rows and are named.
        This assertion is what keeps a later change from quietly reclassifying
        literals into an aspirational partition."""
        totals = self.inventory["authorityTotals"]
        self.assertGreater(totals["capability-spec"], 0)
        self.assertGreater(totals["UNSOURCED"], 0)
        for authority in ("finalized-projection", "target-profile",
                          "deploy-coordinate"):
            self.assertEqual(
                totals[authority], 0,
                f"{authority} gained rows — the slot renderer reads only the "
                "self-emitted capability-spec (SlotTarget.cpp:24-35). If that "
                "changed, this census needs a fresh architect ruling, not a "
                "re-bank")
        self.assertEqual(
            sorted(self.inventory["unobservedAuthorities"]),
            ["deploy-coordinate", "finalized-projection", "target-profile"])


if __name__ == "__main__":
    import unittest

    unittest.main()

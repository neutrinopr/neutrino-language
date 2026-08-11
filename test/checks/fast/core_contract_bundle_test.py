"""[fast] core contract bundle (): the committed bundle passes the
completeness + integrity gate, and the gate's own mutation checks fail closed."""

import json
import os
import unittest

from _fastcase import FastCase, REPO


class CoreContractBundle(FastCase):
    def test_committed_bundle_gate(self):
        self.val_ok("core-contract-bundle gate", "scripts/gates/check_core_contract_bundle.py")

    def test_gate_selftest(self):
        self.val_ok("core-contract-bundle gate selftest",
                    "scripts/gates/check_core_contract_bundle.py", "--selftest")

    def test_domain_exclusion_gate(self):
        #  slice 4: the conformance boundary imports no external domain ownership.
        self.val_ok("conformance domain-exclusion gate",
                    "scripts/gates/check_conformance_domain_exclusion.py")

    def test_domain_exclusion_selftest(self):
        self.val_ok("conformance domain-exclusion selftest",
                    "scripts/gates/check_conformance_domain_exclusion.py", "--selftest")

    def test_externalized_domain_registry_is_persistent_and_non_vacuous(self):
        with open(os.path.join(REPO, "docs", "externalized-domain-registry.json"),
                  encoding="utf-8") as stream:
            registry = json.load(stream)
        self.assertEqual(registry["registeredCount"], len(registry["domains"]))
        self.assertGreaterEqual(registry["registeredCount"], 1)
        identities = [row["id"] for row in registry["domains"]]
        self.assertEqual(identities, sorted(set(identities)))
        self.assertIn("transfer_with_memo", identities)
        self.assertIn("cross_border_delivery_payment", identities)
        for identity in identities:
            self.assertFalse(os.path.exists(
                os.path.join(REPO, "examples", "domains", identity)))


if __name__ == "__main__":
    unittest.main()

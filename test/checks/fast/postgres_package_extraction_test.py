#!/usr/bin/env python3
"""[fast]  standalone PostgreSQL backend package: reach-back audit + extraction receipt.

Pure-Python, no build: the manifest-driven reach-back audit and the extraction-receipt
emitter both run against the committed tree. This wires the  reach-back audit
(previously only documented under "Verifying today") and the  receipt into the
no-build PR tier, with a non-vacuous floor so an eroded manifest cannot pass on zero work.
"""
import json

from _fastcase import FastCase

REACHBACK = "packaging/postgres/scripts/check_package_reachback.py"
RECEIPT = "packaging/postgres/scripts/emit_extraction_receipt.py"
MANIFEST = "packaging/postgres/extraction-manifest.json"
# Floor: the extracted unit owns well more than this many authored+generated files;
# a wrong dir / gutted manifest that digests fewer trips the non-vacuous guard.
MIN_DIGESTED = 25


class PostgresPackageReachback(FastCase):
    def test_reachback_reflects_contract_completeness(self):
        """The gap header is NOT an allowlist exception: while it is undeclared it
        stays a reach-back, so the audit fails closed on the real defect."""
        import os
        from _fastcase import REPO
        with open(os.path.join(REPO, MANIFEST), encoding="utf-8") as f:
            gaps = json.load(f).get("sharedRuntimeContractGaps", {}).get("entries", [])
        if gaps:
            self.val_reject("reach-back blocked by contract gap", REACHBACK)
        else:
            self.val_ok("package reach-back audit", REACHBACK)

    def test_reachback_selftest_bites(self):
        self.val_ok("package reach-back audit selftest", REACHBACK, "--selftest")


class PostgresExtractionReceipt(FastCase):
    def test_receipt_self_check_reflects_contract_completeness(self):
        """While the  shared-runtime closure is INCOMPLETE the receipt must be
        BLOCKED — a known-incomplete dependency cannot receive a verified receipt.
        Once  re-freezes the contract this becomes an unconditional pass."""
        import os
        from _fastcase import REPO
        with open(os.path.join(REPO, MANIFEST), encoding="utf-8") as f:
            gaps = json.load(f).get("sharedRuntimeContractGaps", {}).get("entries", [])
        if gaps:
            out = self.val_reject("receipt blocked by contract gap", RECEIPT, "--check")
            self.assertIn(b"closure is INCOMPLETE", out.stdout)
        else:
            self.val_ok("extraction receipt self-check", RECEIPT, "--check")

    def test_receipt_selftest_bites(self):
        self.val_ok("extraction receipt selftest", RECEIPT, "--selftest")

    def test_receipt_is_whole_and_non_vacuous(self):
        # The emitter still produces the document while blocked; --check is what
        # fails. This asserts the document's shape either way.
        r = self.val_ok("emit extraction receipt", RECEIPT)
        receipt = json.loads(r.stdout.decode("utf-8"))
        self.assertEqual(receipt["kind"], "neutrino.postgres-extraction-receipt/1")
        digested = (len(receipt["fileDigests"]["authoredSources"])
                    + len(receipt["fileDigests"]["generatedBuildProducts"]))
        self.require_floor("extraction-receipt digested files", digested, MIN_DIGESTED)
        # Core identity + the license gate are recorded, never silently defaulted.
        self.assertEqual(
            receipt["coreIdentity"]["canonicalArtifact"], "neutrino.finalized-projection/1")
        self.assertTrue(receipt["coreIdentity"]["compatibilityManifest"]["sha256"])
        #  is a publication/ratification gate, not an execution stop. The
        # identity must stay explicitly PENDING and must never be defaulted to a
        # real license — asserting the exact marker keeps an invented value from
        # slipping in.
        self.assertEqual(receipt["licenseProvenance"]["licenseIdentity"],
                         "pending-ratification-845")
        self.assertEqual(receipt["licenseProvenance"]["unresolvedFiles"], [])

    def test_shared_runtime_is_owned_and_digested(self):
        """The recipe runtime is compiled into the package archive, so its sources
        are owned files — uncensused they would be shipped but unattested."""
        r = self.val_ok("emit extraction receipt", RECEIPT)
        receipt = json.loads(r.stdout.decode("utf-8"))
        digested = receipt["fileDigests"]["authoredSources"]
        shared = [p for p in digested if p.startswith("lib/recipe/")]
        self.require_floor("shared recipe-runtime sources digested", len(shared), 5)

    def test_internal_reference_detection_covers_numeric_fields(self):
        """A bare numeric JSON field (`{"documentId": "urn:neutrino:document:postgres-package-extraction-v1"}`) carries the same internal
        reference as `` while evading any string scan, so both kinds must be
        reported for the  publication gate."""
        r = self.val_ok("emit extraction receipt", RECEIPT)
        refs = json.loads(r.stdout.decode("utf-8"))["internalReferences"]
        kinds = {x["kind"] for x in refs}
        self.assertIn("numeric-issue-field", kinds)
        self.assertIn("text-issue-reference", kinds)


if __name__ == "__main__":
    import unittest

    unittest.main()

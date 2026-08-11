"""[fast] L2 branch-boundary compatibility (): compatible two-branch pairs accepted,
incompatible pairs fail closed."""

import os
import unittest

from _fastcase import FastCase

SIWF_ISSUER = "examples/l2-domain-semantics/core_installment_fulfillment.l2.json"
SIWF_MERCHANT = "examples/l2-domain-semantics/core_installment_fulfillment.merchant.l2.json"
CE_REL = "examples/l2-domain-semantics/core_document_escrow.release.l2.json"
CE_REF = "examples/l2-domain-semantics/core_document_escrow.refund.l2.json"


class L2BranchCompat(FastCase):
    def test_compatible_pairs_accepted(self):
        self.val_ok("branch-compat positive (issuer+merchant)",
                    "scripts/domain/validate_l2_branch_compat.py",
                    "--sidecar", SIWF_ISSUER, "--sidecar", SIWF_MERCHANT)
        # core_document_escrow () two-branch pair: release + refund compose.
        self.val_ok("branch-compat positive (release+refund)",
                    "scripts/domain/validate_l2_branch_compat.py",
                    "--sidecar", CE_REL, "--sidecar", CE_REF)

    def test_incompatible_pairs_fail_closed(self):
        n = 0
        for f in self.globr("examples/l2-domain-semantics/branch-compat/negatives/*.l2.json"):
            self.val_reject(f"branch-compat negative {os.path.basename(f)}",
                            "scripts/domain/validate_l2_branch_compat.py",
                            "--sidecar", SIWF_ISSUER, "--sidecar", f)
            n += 1
        for f in self.globr(
                "examples/l2-domain-semantics/branch-compat/core_document_escrow/negatives/*.l2.json"):
            self.val_reject(f"branch-compat CE negative {os.path.basename(f)}",
                            "scripts/domain/validate_l2_branch_compat.py",
                            "--sidecar", CE_REL, "--sidecar", f)
            n += 1
        # Ratchet floor pinned to the committed incompatible-pair count (): 4 SIWF + 1 CE.
        self.require_floor("branch-compat incompatible pairs", n, 5)


if __name__ == "__main__":
    unittest.main()

"""[fast] solidity-samples classification validator (): positive accepted, negatives
fail closed."""

import os
import unittest

from _fastcase import FastCase


class SolidityClassification(FastCase):
    def test_positive(self):
        self.val_ok("classification positive", "scripts/corpus/validate_solidity_classification.py",
                    "examples/solidity-classification/classification.json",
                    "--out", os.path.join(self.tmp, "cls"))

    def test_negatives_fail_closed(self):
        negs = self.globr("examples/solidity-classification/negatives/*.json")
        for f in negs:
            self.val_reject(f"classification negative {os.path.basename(f)}",
                            "scripts/corpus/validate_solidity_classification.py", f)
        # Ratchet floor pinned to the committed negative count (): erosion of the fail-closed
        # negatives must fail, not only a zero glob. Adding negatives still passes (>=).
        self.require_floor("classification negatives", len(negs), 5)


if __name__ == "__main__":
    unittest.main()

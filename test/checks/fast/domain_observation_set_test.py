"""[fast] M5 S0 (): domain-observation-set validator — positive accepted, negatives
(incl. AI-trust fields) fail closed."""

import os
import unittest

from _fastcase import FastCase


class DomainObservationSet(FastCase):
    def test_positive(self):
        self.val_ok("observation-set positive", "scripts/corpus/validate_domain_observation_set.py",
                    "examples/domain-observation-set/observation-set.json",
                    "--out", os.path.join(self.tmp, "obs"))

    def test_negatives_fail_closed(self):
        negs = self.globr("examples/domain-observation-set/negatives/*.json")
        for f in negs:
            self.val_reject(f"observation-set negative {os.path.basename(f)}",
                            "scripts/corpus/validate_domain_observation_set.py", f)
        # Ratchet floor pinned to the committed negative count (): the negatives (incl. the
        # AI-trust boundary cases) are the fail-closed proof; partial erosion must fail, not empty.
        self.require_floor("observation-set negatives", len(negs), 5)


if __name__ == "__main__":
    unittest.main()

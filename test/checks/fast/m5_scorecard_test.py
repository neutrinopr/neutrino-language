"""[fast] M5 S3 (): backend-genericity scorecard — the 2 M5-expressible evidence
anchors validate + are legality-green; M6 frontier not translated."""

import unittest

from _fastcase import FastCase


class M5Scorecard(FastCase):
    def test_expressible_specs_legal_frontier_honest(self):
        # Spec/classification-alignment at the capability-spec level: exactly the classification's M5
        # shapes (single_hash/merkle_root) are expressible, each committed capability-spec validates
        # + is legality-green against both target profiles, and no M6 coordination-machine shape is
        # translated here. The render gap is proven fail-closed in the full tier.
        self.val_ok("m5 scorecard", "scripts/samples/check_m5_scorecard.py")


if __name__ == "__main__":
    unittest.main()

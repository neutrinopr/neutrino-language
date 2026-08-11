"""[fast] L2 domain-semantics validator: positives accepted, negatives fail closed ( tier)."""

import os
import unittest

from _fastcase import FastCase


class L2DomainSemantics(FastCase):
    def test_positives(self):
        pos = self.globr("examples/l2-domain-semantics/*.l2.json")
        for p in pos:
            self.val_ok(f"l2 positive {os.path.basename(p)}",
                        "scripts/domain/validate_l2_domain_semantics.py", "--artifact", p)
        self.require_floor("l2 positives", len(pos), 1)

    def test_negatives_fail_closed(self):
        # Recursive: the negatives live at any depth (mirrors the shell's `find ... -name '*.json'`).
        negs = self.globr("examples/l2-domain-semantics/negatives/**/*.json")
        for f in negs:
            self.val_reject(f"l2 negative {os.path.basename(f)}",
                            "scripts/domain/validate_l2_domain_semantics.py", "--artifact", f)
        # Ratchet floor pinned to the committed negative count (): these negatives ARE the
        # fail-closed proof, so a partial erosion (34 -> a handful) must fail, not just an empty
        # glob. Adding negatives still passes (>=); removing one requires a conscious floor update.
        self.require_floor("l2 negatives", len(negs), 34)


if __name__ == "__main__":
    unittest.main()

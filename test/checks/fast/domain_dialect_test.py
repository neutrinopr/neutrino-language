"""[fast] domain-dialect validator: positive accepted, negatives fail closed."""

import os
import unittest

from _fastcase import FastCase


class DomainDialect(FastCase):
    def test_positive(self):
        self.val_ok("dialect positive", "scripts/domain/validate_domain_dialect.py",
                    "--dialect", "examples/domain-dialects/sponsored_finance.dialect.json",
                    "--out", os.path.join(self.tmp, "dlz"))

    def test_negatives_fail_closed(self):
        negs = self.globr("examples/domain-dialects/negatives/*.json")
        for f in negs:
            self.val_reject(f"dialect negative {os.path.basename(f)}",
                            "scripts/domain/validate_domain_dialect.py",
                            "--dialect", f, "--out", os.path.join(self.tmp, "dlz_neg"))
        # Ratchet floor pinned to the committed negative count (): silent erosion of the
        # fail-closed negatives must fail, not only a zero glob. Adding negatives still passes (>=).
        self.require_floor("dialect negatives", len(negs), 8)


if __name__ == "__main__":
    unittest.main()

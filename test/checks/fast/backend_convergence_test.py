#!/usr/bin/env python3
"""[fast]  structural-zero backend convergence checks."""

from _fastcase import FastCase


SCRIPT = "scripts/gates/check_backend_convergence.py"


class BackendConvergence(FastCase):
    def test_structural_zero_passes(self):
        self.val_ok("backend convergence", SCRIPT)

    def test_selftest_passes(self):
        self.val_ok("backend convergence selftest", SCRIPT, "--selftest")

    def test_tamper_witnesses_bite(self):
        for probe in (
            "missing-idiom",
            "duplicate-binding",
            "alternate-entry",
            "dormant-helper",
            "legacy-resurrection",
            "projected-field-branch",
            "projected-field-helper",
            "projected-field-helper-alias",
            "projected-field-helper-wrapper",
            "shared-driver-target-dispatch",
        ):
            out = self.val_reject(
                f"backend convergence probe {probe}", SCRIPT, "--probe", probe
            )
            self.assertIn(
                f"probe-failed-as-expected:{probe}",
                out.stdout.decode("utf-8", "replace"),
            )


if __name__ == "__main__":
    import unittest

    unittest.main()

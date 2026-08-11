#!/usr/bin/env python3
"""[fast]  closed idiom-table capability gate.

The target-printer TableGen table may contain only literal syntax/layout data and
dense positional bindings to finalized model operands. These checks mirror the
issue's non-vacuity set: disguised selector, value-dependent conditional,
alternate dispatch key, and unconsumed/extra operand.
"""

from _fastcase import FastCase


SCRIPT = "scripts/gates/check_idiom_table_capability.py"


class IdiomTableCapability(FastCase):
    def test_clean_gate_passes(self):
        self.val_ok("idiom-table capability", SCRIPT)

    def test_selftest_passes(self):
        self.val_ok("idiom-table capability selftest", SCRIPT, "--selftest")

    def test_declared_tamper_probes_bite(self):
        for probe in (
            "disguised-mode-selector",
            "generated-field-array-mismatch",
            "generated-resolver-semantic-lookup",
            "undiscovered-backend-table",
            "value-dependent-conditional",
            "alternate-dispatch-key",
            "unconsumed-extra-operand",
            "let-rebinding-scope",
            "let-nonliteral-rhs",
            "bang-outside-string",
            "control-keyword-construct",
        ):
            out = self.val_reject(f"idiom-table probe {probe}", SCRIPT, "--probe", probe)
            self.assertIn(f"probe-failed-as-expected:{probe}", out.stdout.decode("utf-8", "replace"))


if __name__ == "__main__":
    import unittest
    unittest.main()

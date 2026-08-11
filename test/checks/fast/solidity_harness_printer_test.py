"""[fast] : the Solidity Foundry .t.sol harness-printer retirement ratchet.

Companion to the / production printer ratchet, applied to the handwritten
harness path (GenSolidityTest.cpp). The gate counts handwritten `.t.sol` authoring
sites (codetext line()/block()) and fails closed: the committed baseline must equal
the current count, and a NEW handwritten site is forbidden. Here we smoke the gate +
its non-vacuity selftest, and assert the fail-closed direction directly (a fresh
authoring site raises the count and must reject).
"""

import os
import unittest

from _fastcase import PY, REPO, FastCase

GEN = os.path.join(REPO, "lib", "backends", "solidity", "harness", "GenSolidityTest.cpp")


class SolidityHarnessPrinter(FastCase):
    def test_gate_and_selftest_pass_on_committed(self):
        # --selftest smokes the gate on the committed harness AND proves the ratchet
        # bites (a rogue authoring site raises the count).
        self.val_ok("harness-printer ratchet + non-vacuity selftest",
                    "scripts/gates/check_solidity_harness_printer.py", "--selftest")

    def test_new_authoring_site_is_rejected(self):
        # The fail-closed direction, asserted directly: a fresh handwritten .t.sol
        # authoring site raises the count above the baseline and must reject.
        with open(GEN, encoding="utf-8") as fh:
            src = fh.read()
        rogue = os.path.join(self.tmp, "rogue.cpp")
        with open(rogue, "w", encoding="utf-8") as fh:
            fh.write(src + '\nstatic void _p(){ (void)line("selfdestruct();"); }\n')
        self.val_reject("a new handwritten harness authoring site must fail",
                        "scripts/gates/check_solidity_harness_printer.py", "--cpp", rogue)

    def test_substitution_at_unchanged_total_is_rejected(self):
        # Identity ratchet, not a bare total: deleting one authoring site and adding a
        # DIFFERENT one keeps the total at the baseline but must still reject — the
        # added identity is not in the base (no delete-one/add-one laundering).
        with open(GEN, encoding="utf-8") as fh:
            src = fh.read()
        sub = src.replace('line("MockQuorumGuard guard;")', 'line("EvilGuard g;")', 1)
        self.assertNotEqual(sub, src, "substitution anchor drifted; update the test")
        fixture = os.path.join(self.tmp, "sub.cpp")
        with open(fixture, "w", encoding="utf-8") as fh:
            fh.write(sub)
        self.val_reject("a delete-one/add-one substitution at unchanged total must fail",
                        "scripts/gates/check_solidity_harness_printer.py", "--cpp", fixture)

    def test_commented_and_string_line_are_not_counted(self):
        # Comment/string-aware: a commented-out or string-embedded `line(` must NOT be
        # counted (would otherwise change the total and false-trip). The gate stays OK.
        with open(GEN, encoding="utf-8") as fh:
            src = fh.read()
        noise = os.path.join(self.tmp, "noise.cpp")
        with open(noise, "w", encoding="utf-8") as fh:
            fh.write(src + '\n// (void)line("x");\nstatic const char* _s = "line(y)";\n')
        self.val_ok("a commented/string-embedded line( must not change the count",
                    "scripts/gates/check_solidity_harness_printer.py", "--cpp", noise)


if __name__ == "__main__":
    unittest.main()

"""[fast] M3 native build gate (): generated-code classification honest + native
compilation of claimed code."""

import unittest

from _fastcase import FastCase


class NativeBuildGate(FastCase):
    def test_run_gate(self):
        # --run is the REAL gate: it compiles committed native-target code with its toolchain.
        # Today there are no committed native-target artifacts so it needs no solc; it becomes a
        # hard gate the moment a .sol/.sql/etc. is claimed native-validated.
        self.val_ok("native build gate (--run)", "scripts/gates/native_build_gate.py", "--run")


if __name__ == "__main__":
    unittest.main()

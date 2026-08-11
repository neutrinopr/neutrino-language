#!/usr/bin/env python3
""" — the security-primitive carve-out gate must hold and its selftest must bite.

Runs the live default-deny gate and its full biting probe matrix as part of the fast
surface, so a PR that weakens/deletes the gate, the registry, or an enforced identity
fails here (and the  gate-integrity manifest pins this wiring).
"""
import os
import subprocess
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
GATE = os.path.join(REPO, "scripts", "gates", "check_security_primitive_carveout.py")


class SecurityPrimitiveCarveout(unittest.TestCase):
    def run_gate(self, *args):
        return subprocess.run([sys.executable, GATE, *args], text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    def test_live_gate_holds(self):
        r = self.run_gate()
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("PASS: carve-out registry OK", r.stdout)

    def test_selftest_probes_bite(self):
        r = self.run_gate("--selftest")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("SELFTEST: PASS", r.stdout)
        self.assertNotIn("[FAIL]", r.stdout)


if __name__ == "__main__":
    unittest.main()

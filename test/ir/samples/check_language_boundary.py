"""[57] M3 language boundary (): future-facing source syntax is rejected, not partially accepted.
Ported verbatim from the retired run_cpp_tests.sh [57] block ( S5l). docs/language/LANGUAGE_BOUNDARY.md draws
the M3 line: state machines / lifecycle (L2), escrow release/refund, protocol-native pacs.* terms, and
external-observation syntax are NOT core .neu grammar. The frontend parser whitelists statements,
so each must be rejected with "unexpected statement" naming the offending keyword —
proving the boundary is enforced, not just documented.

Usage: check_language_boundary.py <neutrino-translate> <fixtures-dir>
"""
import os
import subprocess
import sys

TRANSLATE, FIX = sys.argv[1:3]
fails = []

CASES = [
    ("neg_state_machine.neu", "state Open"),
    ("neg_escrow_lifecycle.neu", "escrow"),
    ("neg_protocol_native.neu", "pacs.008"),
    ("neg_external_observation.neu", "observe"),
]

for fixture, keyword in CASES:
    r = subprocess.run([TRANSLATE, os.path.join(FIX, fixture), "-o", os.devnull],
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    err = r.stderr.decode("utf-8", "replace")
    if r.returncode == 0:
        fails.append(f"{fixture} was accepted — the M3 language boundary was breached")
        continue
    if "unexpected statement" not in err.lower():
        fails.append(f"{fixture} rejected for the wrong reason: {err.strip()[:120]}")
    if keyword.lower() not in err.lower():
        fails.append(f"{fixture} rejection did not name the offending keyword '{keyword}'")

if fails:
    print("[57] language-boundary contract FAILED:", file=sys.stderr)
    for f in fails:
        print("    FAIL: " + f, file=sys.stderr)
    sys.exit(1)
print("[57] OK: state-machine / escrow / pacs.* / external-observation pseudo-syntax all rejected as "
      "unexpected statements")

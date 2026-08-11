"""[10] value model: type-aware scenario validation (money/party/currency/evidence). Ported verbatim
from the retired run_cpp_tests.sh [10] block ( S5n). A well-typed scenario is accepted; a
money / party / evidence / currency type violation each fails closed with exit 3 + scenario.invalid.

Usage: check_value_model.py <neutrino-gen> <value_types.neu> <value_types_good.json> <fixtures-dir>
"""
import os
import subprocess
import sys
import tempfile

GEN, NEU, GOOD, FIXDIR = sys.argv[1:5]
fails = []
tmp = tempfile.mkdtemp(prefix="vt10.")


def gen(scenario, sub):
    out = os.path.join(tmp, sub)
    rc = subprocess.run([GEN, "--target=postgres", "--scenario=" + scenario, NEU, "-o", out],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode
    dj = os.path.join(out, "diagnostics.json")
    return rc, (open(dj).read() if os.path.isfile(dj) else "")


rc, _ = gen(GOOD, "good")
if rc != 0:
    fails.append("good typed scenario rejected")

for bad in ("money", "party", "evidence", "currency"):
    rc, diag = gen(os.path.join(FIXDIR, f"value_types_bad_{bad}.json"), "bad_" + bad)
    if rc != 3:
        fails.append(f"bad {bad} exit={rc} (want 3)")
    if '"scenario.invalid"' not in diag:
        fails.append(f"bad {bad} missing scenario.invalid")

if fails:
    print("[10] value-model contract FAILED:", file=sys.stderr)
    for f in fails:
        print("    FAIL: " + f, file=sys.stderr)
    sys.exit(1)
print("[10] OK: typed good accepted; money/party/evidence/currency violations -> exit 3")

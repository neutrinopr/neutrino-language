"""[56] M3 conformance: accepted .neu constructs translate; pseudo-syntax blocks rejected (). Ported
verbatim from the retired run_cpp_tests.sh [56] block ( S5l). Every fixture under
test/conformance/accepted/ must translate; every fixture under test/conformance/rejected/ (capability /
topology / flow / security / binding_manifest pseudo-syntax — M3 source-level non-goals) must be
rejected, not silently ignored. Non-vacuous floors (>=2 accepted, >=5 rejected).

Usage: check_conformance.py <neutrino-translate> <conformance-dir>
"""
import glob
import os
import subprocess
import sys

TRANSLATE, CONF = sys.argv[1:3]
fails = []


def translates(f):
    return subprocess.run([TRANSLATE, f, "-o", os.devnull],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


acc = sorted(glob.glob(os.path.join(CONF, "accepted", "*.neu")))
for f in acc:
    if not translates(f):
        fails.append(f"accepted construct fixture rejected: {os.path.basename(f)}")
if len(acc) < 2:
    fails.append(f"no accepted-construct conformance fixtures found (got {len(acc)}, want >=2)")

rej = sorted(glob.glob(os.path.join(CONF, "rejected", "*.neu")))
for f in rej:
    if translates(f):
        fails.append(f"pseudo-syntax accepted (must be rejected): {os.path.basename(f)}")
if len(rej) < 5:
    fails.append(f"missing pseudo-syntax negatives (found {len(rej)}, want >=5)")

if fails:
    print("[56] conformance contract FAILED:", file=sys.stderr)
    for f in fails:
        print("    FAIL: " + f, file=sys.stderr)
    sys.exit(1)
print(f"[56] OK: {len(acc)} accepted-construct fixtures translate; {len(rej)} pseudo-syntax blocks "
      "rejected (see docs/language/NEU_LANGUAGE_SPEC.md)")

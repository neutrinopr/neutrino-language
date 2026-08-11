"""[53] domain layout hygiene ( anti-regression guard). Ported verbatim from the retired
run_cpp_tests.sh [53] block ( S5m). Every domain source lives under
examples/domains/<domain>/source/ (none at the examples/ top level); the retired family-major containers
(slot/solidity/postgres/capability/coverage/security) and the root scenarios/ dir must not reappear;
and every domain dir carries its canonical source/<domain>.neu.

Usage: check_layout_hygiene.py <examples-dir>
"""
import glob
import os
import sys

EXAMPLES = sys.argv[1]
REPO = os.path.dirname(os.path.abspath(EXAMPLES))
fails = []

# no top-level examples/*.neu.
if glob.glob(os.path.join(EXAMPLES, "*.neu")):
    fails.append("top-level examples/*.neu found — author domains under examples/domains/<domain>/source/")

# retired family-major containers must not reappear.
for fam in ("slot", "solidity", "postgres", "capability", "coverage", "security"):
    if os.path.isdir(os.path.join(EXAMPLES, fam)):
        fails.append(f"examples/{fam}/ reappeared (retired family-major container)")

# the root scenarios/ dir must not reappear.
if os.path.isdir(os.path.join(REPO, "scenarios")):
    fails.append("top-level scenarios/ reappeared (use examples/domains/<domain>/scenario/)")

# every domain dir carries its canonical source/<domain>.neu.
for sd in sorted(glob.glob(os.path.join(EXAMPLES, "domains", "*") + os.sep)):
    dom = os.path.basename(os.path.dirname(sd))
    if not os.path.isfile(os.path.join(sd, "source", dom + ".neu")):
        fails.append(f"examples/domains/{dom} missing source/{dom}.neu (domain-major requires it)")

if fails:
    print("[53] layout-hygiene contract FAILED:", file=sys.stderr)
    for f in fails:
        print("    FAIL: " + f, file=sys.stderr)
    sys.exit(1)
print("[53] OK: no top-level .neu; retired family-major + scenarios/ containers absent; every domain "
      "has source/<domain>.neu")

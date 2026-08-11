"""[71] M3 samples cookbook (). Ported verbatim from the retired run_cpp_tests.sh [71] block (
S5l). The educational L1/L2/L3 guide (docs/domains/M3_COOKBOOK.md) must cover every current-valid
portfolio sample (so it can't drift as samples are added/renamed) and advertise the real run commands.

Usage: check_cookbook.py <examples-dir>
"""
import json
import os
import sys

EXAMPLES = sys.argv[1]
fails = []

repo = os.path.dirname(os.path.abspath(EXAMPLES))
cookbook = os.path.join(repo, "docs", "domains", "M3_COOKBOOK.md")
try:
    text = open(cookbook).read()
except OSError:
    print("[71] FAIL: cookbook docs/domains/M3_COOKBOOK.md is missing", file=sys.stderr)
    sys.exit(1)

port = json.load(open(os.path.join(EXAMPLES, "m3-sample-portfolio.json")))
missing = [s["id"] for s in port["samples"] if s.get("status") == "current-valid" and s["id"] not in text]
if missing:
    fails.append(f"cookbook does not mention current-valid sample(s): {missing}")

for cmd in ("make test-fast", "make test", "make native-build-gate"):
    if cmd not in text:
        fails.append(f"cookbook omits the {cmd!r} run command")

if fails:
    print("[71] cookbook contract FAILED:", file=sys.stderr)
    for f in fails:
        print("    FAIL: " + f, file=sys.stderr)
    sys.exit(1)
print("[71] OK: cookbook covers every current-valid sample + advertises the real run commands")

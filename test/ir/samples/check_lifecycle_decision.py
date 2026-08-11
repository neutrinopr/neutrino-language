"""[65] M3 L2 lifecycle modeling decision (). Ported verbatim from the retired run_cpp_tests.sh [65]
block ( S5l). The decision that lifecycle/transition semantics map onto the current L2 model
(concepts/actions + guards/invariants/failureModes) with NO lifecycle/transition block is ENFORCED:
lifecycle_states / on_success / on_failure are unknown L2 fields, each rejected fail-closed with
exactly L2-1001. See docs/domains/L2_LIFECYCLE_DECISION.md.

Usage: check_lifecycle_decision.py <validate_l2_domain_semantics.py> <examples-dir>
"""
import json
import os
import subprocess
import sys

VL2, EXAMPLES = sys.argv[1:3]
fails = []
negdir = os.path.join(EXAMPLES, "l2-domain-semantics", "negatives", "lifecycle")

for f in ("lifecycle_states_field.l2.json", "on_success_field.l2.json", "on_failure_field.l2.json"):
    r = subprocess.run([sys.executable, VL2, "--artifact", os.path.join(negdir, f)],
                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        d = json.loads(r.stdout)
        codes = {x["code"] for x in d["diagnostics"]}
        if not (d["ok"] is False and codes == {"L2-1001"}):
            fails.append(f"{f}: codes={sorted(codes)} (want L2-1001 only)")
    except ValueError:
        fails.append(f"{f}: no JSON envelope emitted")

if fails:
    print("[65] lifecycle-decision contract FAILED:", file=sys.stderr)
    for f in fails:
        print("    FAIL: " + f, file=sys.stderr)
    sys.exit(1)
print("[65] OK: lifecycle_states / on_success / on_failure rejected as unknown L2 fields (L2-1001) — "
      "lifecycle maps onto current concepts/actions + guards/invariants/failureModes")

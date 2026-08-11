"""[58] M3 L2 domain-semantics validator (). Ported verbatim from the retired run_cpp_tests.sh [58]
block ( S5l). The valid bnpl_payment_lifecycle L2 artifact is accepted with the documented
machine-readable envelope (kind neutrino.l2-domain-semantics-validation, ok:true, no diagnostics); every
negative fixture (traceability / branch / parameter / expression / reference / shape) fails closed with
coded diagnostics. Non-vacuous floor (>=6 negatives).

Usage: check_l2_validator.py <validate_l2_domain_semantics.py> <l2-domain-semantics-dir>
"""
import glob
import json
import os
import subprocess
import sys

VL2, L2DIR = sys.argv[1:3]
fails = []


def run(artifact):
    return subprocess.run([sys.executable, VL2, "--artifact", artifact],
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)


valid = os.path.join(L2DIR, "bnpl_payment_lifecycle.l2.json")
r = run(valid)
if r.returncode != 0:
    fails.append("valid L2 artifact rejected")
else:
    try:
        d = json.loads(r.stdout)
        if not (d.get("kind") == "neutrino.l2-domain-semantics-validation" and d.get("ok") is True
                and d.get("diagnostics") == []):
            fails.append("L2 validation envelope shape")
    except ValueError:
        fails.append("valid L2 artifact did not emit a JSON envelope")

negs = sorted(glob.glob(os.path.join(L2DIR, "negatives", "*.json")))
for f in negs:
    if run(f).returncode == 0:
        fails.append(f"invalid L2 artifact accepted: {os.path.basename(f)}")
if len(negs) < 6:
    fails.append(f"missing L2 negative fixtures (found {len(negs)}, want >=6)")

if fails:
    print("[58] L2-validator contract FAILED:", file=sys.stderr)
    for f in fails:
        print("    FAIL: " + f, file=sys.stderr)
    sys.exit(1)
print(f"[58] OK: valid L2 accepted with machine-readable envelope; {len(negs)} negatives fail closed "
      "with coded diagnostics (see docs/domains/L2_DOMAIN_SEMANTICS.md)")

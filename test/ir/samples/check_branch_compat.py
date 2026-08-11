"""[64] M3 L2 branch-boundary compatibility (). Ported verbatim from the retired run_cpp_tests.sh
[64] block ( S5l). Two sidecars refining the SAME L1 capability must agree on shared boundary facts
(evidence/outcome/value). The compatible issuer+merchant pair is accepted; each negative is itself a
VALID single sidecar (distinct from single-sidecar errors) but cross-incompatible, so it pins behavior
the single-sidecar validator cannot catch — failing with exactly its targeted L2X code.

Usage: check_branch_compat.py <scripts-dir> <examples-dir>
"""
import json
import os
import subprocess
import sys

SCRIPTS, EXAMPLES = sys.argv[1:3]
fails = []
VBC = os.path.join(SCRIPTS, "domain", "validate_l2_branch_compat.py")
VL2 = os.path.join(SCRIPTS, "domain", "validate_l2_domain_semantics.py")
L2 = os.path.join(EXAMPLES, "l2-domain-semantics")
issuer = os.path.join(L2, "core_installment_fulfillment.l2.json")
merchant = os.path.join(L2, "core_installment_fulfillment.merchant.l2.json")


def compat(*paths):
    args = [sys.executable, VBC]
    for p in paths:
        args += ["--sidecar", p]
    r = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    return r.returncode, (json.loads(r.stdout) if r.stdout.strip() else None)


def single_ok(p):
    r = subprocess.run([sys.executable, VL2, "--artifact", p], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    return r.returncode == 0 and json.loads(r.stdout)["ok"] is True


# positive: the compatible two-branch pair.
rc, d = compat(issuer, merchant)
if not (rc == 0 and d and d["ok"] and d["diagnostics"] == []
        and d["kind"] == "neutrino.l2-branch-compat-validation"):
    fails.append(f"compatible issuer+merchant pair not accepted: rc={rc}")

# negatives: each is a VALID single sidecar but the cross-check fails with exactly its L2X code.
negs = {
    "evidence_schema_mismatch.merchant.l2.json": "L2X-2002",
    "outcome_kind_mismatch.merchant.l2.json": "L2X-2003",
    "value_type_mismatch.merchant.l2.json": "L2X-2004",
    "wrong_capability.merchant.l2.json": "L2X-2001",
}
for fn, code in negs.items():
    p = os.path.join(L2, "branch-compat", "negatives", fn)
    if not single_ok(p):
        fails.append(f"{fn} should be a valid single sidecar (cross-check is the failure)")
    rc, d = compat(issuer, p)
    codes = {x["code"] for x in d["diagnostics"]} if d else set()
    if not (rc == 1 and d and d["ok"] is False and codes == {code}):
        fails.append(f"{fn}: rc={rc} codes={sorted(codes)} (want {code} only)")

if fails:
    print("[64] branch-compat contract FAILED:", file=sys.stderr)
    for f in fails:
        print("    FAIL: " + f, file=sys.stderr)
    sys.exit(1)
print("[64] OK: compatible issuer+merchant pair accepted; mismatched evidence schema / incompatible "
      "outcome / incompatible value type / wrong L1 capability each fail closed with their L2X code; "
      "negatives are valid single sidecars")

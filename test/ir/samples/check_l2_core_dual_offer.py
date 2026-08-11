"""[60] M3 L2 example tied to core_dual_offer (). Ported verbatim from the retired run_cpp_tests.sh
[60] block ( S5l). The committed core_dual_offer L2 sidecar is accepted; each required fail-closed
case rejects with EXACTLY its targeted code (a single mutation, so a regression that lets one class
through is caught by code, not just exit status); and the cross-rail catalog cites the sidecar tied to
the same capability (implements == fixture capabilityId).

Usage: check_l2_core_dual_offer.py <validate_l2_domain_semantics.py> <l2-domain-semantics-dir> <examples-dir>
"""
import json
import os
import subprocess
import sys

VL2, L2DIR, EXAMPLES = sys.argv[1:4]
fails = []


def run(artifact):
    return subprocess.run([sys.executable, VL2, "--artifact", artifact],
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)


# the positive example is accepted.
if run(os.path.join(L2DIR, "core_dual_offer.l2.json")).returncode != 0:
    fails.append("core_dual_offer L2 example rejected")

# each required negative fails closed with EXACTLY its targeted code (single mutation).
negdir = os.path.join(L2DIR, "negatives", "core_dual_offer")
expect = {
    "untraceable_concept.l2.json": "L2-1003",              # L2 concept with no L1 trace
    "missing_required_parameter.l2.json": "L2-1008",       # undeclared parameter reference
    "evidence_bad_shape.l2.json": "L2-1001",               # evidence requirement, unsupported shape
    "branch_boundary_mismatch.l2.json": "L2-1004",         # participant branch boundary mismatch
    "implements_capability_divergence.l2.json": "L2-1002",  # implements != l1.capability (P2)
}
for fn, code in expect.items():
    r = run(os.path.join(negdir, fn))
    try:
        d = json.loads(r.stdout)
        codes = {x["code"] for x in d["diagnostics"]}
        if not (r.returncode == 1 and d["ok"] is False and codes == {code}):
            fails.append(f"{fn}: exit={r.returncode} codes={sorted(codes)} (want {code} only)")
    except ValueError:
        fails.append(f"{fn}: no JSON envelope emitted")

# the cross-rail catalog cites the L2 sidecar, tied to the same capability.
cat = json.load(open(os.path.join(EXAMPLES, "cross-rail-fixtures.json")))
fx = next((f for f in cat["fixtures"] if f["fixtureId"] == "core_dual_offer"), None)
if fx is None or fx.get("l2") != "examples/l2-domain-semantics/core_dual_offer.l2.json":
    fails.append("catalog: core_dual_offer fixture does not cite the L2 sidecar")
else:
    l2 = json.load(open(os.path.join(EXAMPLES, "..", fx["l2"])))
    if l2.get("implements") != fx["capabilityId"]:
        fails.append("catalog: L2 implements != fixture capabilityId")

if fails:
    print("[60] L2-core_dual_offer contract FAILED:", file=sys.stderr)
    for f in fails:
        print("    FAIL: " + f, file=sys.stderr)
    sys.exit(1)
print("[60] OK: core_dual_offer L2 example accepted; no-trace / undeclared-parameter / "
      "bad-evidence-shape / branch-mismatch / implements-divergence each fail closed with their code; "
      "cited from the cross-rail catalog with l1 anchors aligned to the generated artifacts")

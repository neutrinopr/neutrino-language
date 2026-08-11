"""[59] L3 binding-manifest evolution (): schemaVersion-2 L2-parameter bindings + backend profile +
status. Ported verbatim from the retired run_cpp_tests.sh [59] block ( S5l). The L3 Binding Manifest
(schemaVersion 2) binds validated L2 parameters to a backend profile and reports a machine-readable
status. A v1 manifest stays ok=true with NO 'status' key (byte-stable v1 report shape); the L3 positive
validates with status 'complete'; each L3 negative produces its NEU code with status 'invalid'; and a
missing backend-profile catalog fails closed (NEU-3002/invalid) rather than leaving the profile
unvalidated while status reads 'complete'.

Usage: check_l3_evolution.py <validate_binding_manifest.py> <examples-dir>
"""
import json
import os
import subprocess
import sys

VBM, EXAMPLES = sys.argv[1:3]
REPO = os.path.dirname(os.path.abspath(EXAMPLES))
fails = []
BM = os.path.join(EXAMPLES, "binding-manifests")

# : the topology every manifest here is validated against belongs to the
# core-owned core_dual_offer fixture; `1f16e44a` renamed the identity but left this
# constant on the deleted `examples/domains/` prefix, so the validator exited
# usage-2 and all seven L3 negatives reported "exited 2 (want 1)" instead of
# proving their NEU codes.
sys.path.insert(0, os.path.join(REPO, "test", "ir", "pipeline"))
from pipeline_inputs import (PipelineInputError, require_surface,  # noqa: E402
                             resolve_core_fixture)

try:
    BT = str(require_surface(resolve_core_fixture(REPO, "core_dual_offer"),
                             "generated", "slot", "binding-topology.json"))
except PipelineInputError as error:
    print("[59] L3-evolution contract FAILED:", file=sys.stderr)
    print("    FAIL: " + str(error), file=sys.stderr)
    sys.exit(1)
L3 = os.path.join(BM, "core_dual_offer.l3.binding.json")


def validate_json(manifest, *extra):
    r = subprocess.run([sys.executable, VBM, "--manifest", manifest, "--binding-topology", BT, "--json", *extra],
                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    return r.returncode, (json.loads(r.stdout) if r.stdout.strip() else None)


# v1 regression: the existing v1 manifest stays ok=true AND its report carries no 'status' key.
rc, d = validate_json(os.path.join(BM, "core_dual_offer.binding.json"))
if not (d and d["ok"] is True and "status" not in d):
    fails.append("v1 manifest report changed shape (ok!=true or unexpected 'status')")

# L3 positive: validates, status 'complete'.
rc, d = validate_json(L3)
if not (d and d["ok"] is True and d.get("status") == "complete" and d["diagnostics"] == []):
    fails.append("L3 positive manifest did not validate with status 'complete'")

# L3 negatives: each fails closed (exit 1, status 'invalid') with its expected code.
for fx, code in [
    ("param_not_in_l2", "NEU-4001"), ("missing_required_param", "NEU-4002"),
    ("param_type_mismatch", "NEU-4003"), ("unsupported_profile_field", "NEU-3002"),
    ("profile_runtime_mismatch", "NEU-3002"), ("untraceable_semantics", "NEU-4004"),
    ("l2_capability_mismatch", "NEU-4005"),
]:
    rc, d = validate_json(os.path.join(BM, "negatives", f"{fx}.l3.binding.json"))
    if rc != 1:
        fails.append(f"L3 negative '{fx}' exited {rc} (want 1)")
    elif not (d and d["ok"] is False and d.get("status") == "invalid"
              and code in {x["code"] for x in d["diagnostics"]}):
        fails.append(f"L3 negative '{fx}' did not produce {code} with status 'invalid'")

# fail closed when the backend-profile catalog cannot be loaded for a v2 manifest.
rc, d = validate_json(L3, "--backend-catalog", "does/not/exist.json")
if rc != 1:
    fails.append(f"missing backend-profile catalog did not fail closed (exit {rc}, want 1)")
elif not (d and d["ok"] is False and d.get("status") == "invalid"
          and "NEU-3002" in {x["code"] for x in d["diagnostics"]}):
    fails.append("missing backend-profile catalog did not produce NEU-3002/invalid")

if fails:
    print("[59] L3-evolution contract FAILED:", file=sys.stderr)
    for f in fails:
        print("    FAIL: " + f, file=sys.stderr)
    sys.exit(1)
print("[59] OK: v1 report byte-stable; L3 positive status=complete; param NEU-4001/4002/4003 + "
      "profile/runtime NEU-3002 + untraceable NEU-4004 + L2-capability NEU-4005 + missing-catalog "
      "NEU-3002 all fail closed")

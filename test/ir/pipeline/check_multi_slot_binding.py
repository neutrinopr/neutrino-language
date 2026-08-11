"""[49] T1/T2 multi-slot late binding: two to_be_bound slots + binding-manifest completeness. Ported
verbatim from the retired run_cpp_tests.sh [49] block ( S5n). core_dual_offer generates a byte-stable
slot fixture with exactly two to_be_bound slots (Merchant + Sponsor), each fully policied
(allowedRuntimes + minAssurance A2 + authorizedBinder); its binding manifest binds BOTH slots and passes
multi-slot completeness; and a manifest binding only one of the two is rejected (incompleteness).

Usage: check_multi_slot_binding.py <neutrino-gen> <validate_binding_manifest.py> <examples-dir>
"""
import json
import os
import subprocess
import sys
import tempfile

GEN, VBM, EXAMPLES = sys.argv[1:4]
REPO = os.path.dirname(os.path.abspath(EXAMPLES))
fails = []
tmp = tempfile.mkdtemp(prefix="dbd49.")

# : `1f16e44a` externalized the production dual_bound_offer domain and renamed
# the whole core-owned artefact family that binds it to the `core_dual_offer`
# identity (this checker, the v1/L3 manifests, the L2 sidecars, the catalog row in
# docs/backends/CROSS_RAIL_FIXTURES.md) -- but never provided the core-owned L1 those
# artefacts describe, leaving this constant pointing at the deleted
# `examples/domains/` prefix. The fixture now lives in core, next to the
# core_flexible_binding / core_promo_campaign synthetics the sibling trains created.
sys.path.insert(0, os.path.join(REPO, "test", "ir", "pipeline"))
from pipeline_inputs import (PipelineInputError, require_surface,  # noqa: E402
                             resolve_core_fixture)

try:
    DBD_FIXTURE = resolve_core_fixture(REPO, "core_dual_offer")
    DBD_SLOT = require_surface(DBD_FIXTURE, "generated", "slot", directory=True)
except PipelineInputError as error:
    print("[49] FAIL: " + str(error), file=sys.stderr)
    sys.exit(1)
DBM = os.path.join(EXAMPLES, "binding-manifests", "core_dual_offer.binding.json")

slot = os.path.join(tmp, "dbd_slot")
if subprocess.run([GEN, "--target=slot", "--scenario=" + str(DBD_FIXTURE.scenario),
                   str(DBD_FIXTURE.source), "-o", slot],
                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0:
    print("[49] FAIL: slot gen for core_dual_offer", file=sys.stderr)
    sys.exit(1)

# byte-stable slot fixture (manifest.json/diagnostics.json are non-golden run metadata).
for f in ("binding-topology.json", "capability.json", "capability.lock", "compensation.json",
          "envelope.schema.json", "operations.json", "transcript.json"):
    if open(os.path.join(slot, f), "rb").read() != open(os.path.join(DBD_SLOT, f), "rb").read():
        fails.append(f"core_dual_offer slot {f} drifted from committed fixture")

topo = os.path.join(slot, "binding-topology.json")
d = json.load(open(topo))
tbb = [s for o in d["organizations"] for p in o["participants"] for s in p["slots"]
       if s["lateBindingMode"] == "to_be_bound"]
ids = sorted(s["slotId"] for s in tbb)
if not (d["crossOrganization"] is True and len(tbb) == 2
        and ids == ["coordinate.core_dual_offer#Merchant", "coordinate.core_dual_offer#Sponsor"]
        and all(s.get("authorizedBinder") and s.get("allowedRuntimes") and s.get("minAssurance") == "A2" for s in tbb)):
    fails.append("expected two fully-policied to_be_bound slots")


def vbm(manifest):
    return subprocess.run([sys.executable, VBM, "--manifest", manifest, "--binding-topology", topo],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode


# the binding manifest binds BOTH slots and passes multi-slot completeness.
if vbm(DBM) != 0:
    fails.append("core_dual_offer binding manifest did not validate against the topology")
m = json.load(open(DBM))
if not (m["capability"] == "coordinate.core_dual_offer" and len(m["bindings"]) == 2
        and {b["slotId"] for b in m["bindings"]}
        == {"coordinate.core_dual_offer#Sponsor", "coordinate.core_dual_offer#Merchant"}):
    fails.append("binding manifest is not a complete two-binding set")

# fail-closed: a manifest binding only one of the two slots must be rejected.
incomplete = os.path.join(tmp, "dbd_incomplete.json")
mi = json.load(open(DBM))
mi["bindings"] = mi["bindings"][:1]
json.dump(mi, open(incomplete, "w"))
if vbm(incomplete) == 0:
    fails.append("incomplete manifest (1 of 2 slots) was accepted")

if fails:
    print("[49] multi-slot-binding contract FAILED:", file=sys.stderr)
    for f in fails:
        print("    FAIL: " + f, file=sys.stderr)
    sys.exit(1)
print("[49] OK: two to_be_bound slots byte-stable + fully policied; manifest binds both with "
      "completeness; incomplete manifest fails closed")

"""[38] D1b: slot binding-topology. Ported verbatim from the retired run_cpp_tests.sh [38] block (
S5k). Slot gen emits an org->participant->slot binding-topology.json that byte-matches the committed
fixture and validates fail-closed; it is EXCLUDED from the capabilityHash scope (never listed in
capability.lock); a participant-free source emits none (byte-stable, incl. output-dir reuse where a
stale artifact must not survive); and six structural mutations each fail closed.

Usage: check_binding_topology.py <neutrino-gen> <validate_binding_topology.py> <examples-dir>
"""
import json
import os
import subprocess
import sys
import tempfile

GEN, VAL, EXAMPLES = sys.argv[1:4]
REPO = os.path.dirname(os.path.abspath(EXAMPLES))
fails = []
tmp = tempfile.mkdtemp(prefix="bt38.")

# : `be5d2a61` ( train2) externalized flexible_binding_offer /
# merchant_sponsored_installment and created the core-owned synthetics that keep
# this core coverage, but left these two constants pointing at the deleted
# `examples/domains/` prefix. Resolve them through the shared input boundary so a
# missing surface is named here instead of surfacing as a `None` topology and a
# TypeError twenty lines down.
sys.path.insert(0, os.path.join(REPO, "test", "ir", "pipeline"))
from pipeline_inputs import (PipelineInputError, require_surface,  # noqa: E402
                             resolve_core_fixture)

try:
    FBO_FIXTURE = resolve_core_fixture(REPO, "core_flexible_binding")
    MSI_FIXTURE = resolve_core_fixture(REPO, "core_sample_installment")
    FBO_COMMITTED_BT = require_surface(
        FBO_FIXTURE, "generated", "slot", "binding-topology.json")
except PipelineInputError as error:
    print("[38] binding-topology contract FAILED:", file=sys.stderr)
    print("    FAIL: " + str(error), file=sys.stderr)
    sys.exit(1)


def gen_slot(fixture, out):
    return subprocess.run(
        [GEN, "--target=slot", "--scenario=" + str(fixture.scenario),
         str(fixture.source), "-o", out],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode


def validate(path):
    return subprocess.run([sys.executable, VAL, path],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode


slot_bt = os.path.join(tmp, "slot_bt")
if gen_slot(FBO_FIXTURE, slot_bt) != 0:
    fails.append("slot gen (binding-topology) failed")
else:
    bt = os.path.join(slot_bt, "binding-topology.json")
    committed = str(FBO_COMMITTED_BT)
    if open(bt).read() != open(committed).read():
        fails.append("binding-topology.json differs from the committed fixture")
    if validate(bt) != 0:
        fails.append("binding-topology did not validate")
    if "binding-topology.json" in open(os.path.join(slot_bt, "capability.lock")).read():
        fails.append("binding-topology.json leaked into capability.lock (capabilityHash)")
    d = json.load(open(bt))
    orgs = {o["organizationId"] for o in d["organizations"]}
    sids = [s["slotId"] for o in d["organizations"] for p in o["participants"] for s in p["slots"]]
    if not (d["crossOrganization"] is True and orgs == {"sponsorco", "acme"}
            and sids == ["coordinate.core_flexible_binding#Sponsor",
                         "coordinate.core_flexible_binding#Merchant"] and len(set(sids)) == 2):
        fails.append("binding-topology ids/topology not as expected")

# participant-free source stays byte-stable: no binding-topology.json at all.
msi_out = os.path.join(tmp, "slot_bt_msi")
gen_slot(MSI_FIXTURE, msi_out)
if os.path.exists(os.path.join(msi_out, "binding-topology.json")):
    fails.append("participant-free source emitted binding-topology.json")

# output-dir reuse: a participant source then a participant-free source into the SAME dir must end
# with no binding-topology.json (no stale artifact survives).
reuse = os.path.join(tmp, "slot_reuse")
gen_slot(FBO_FIXTURE, reuse)
if not os.path.exists(os.path.join(reuse, "binding-topology.json")):
    fails.append("first gen did not emit binding-topology.json")
gen_slot(MSI_FIXTURE, reuse)
if os.path.exists(os.path.join(reuse, "binding-topology.json")):
    fails.append("stale binding-topology.json survived an output-dir reuse")

# fail-closed mutations. The six probes need a topology to mutate: if generation
# produced none there is nothing to prove, so REPORT that (a named failure) rather
# than crashing on a None subscript and hiding which probes still bite ().
generated_bt = os.path.join(slot_bt, "binding-topology.json")
if not os.path.exists(generated_bt):
    fails.append("no generated binding-topology.json to mutate: the six fail-closed "
                 f"mutation probes could not run (expected {generated_bt})")
    base = None
else:
    base = json.load(open(generated_bt))
for mut in () if base is None else ("unknown", "slotid", "crossorg", "fixedruntimes", "binder", "emptyorgs"):
    d = json.loads(json.dumps(base))
    if mut == "unknown":
        d["surprise"] = 1
    elif mut == "slotid":
        d["organizations"][0]["participants"][0]["slots"][0]["slotId"] = "wrong#id"
    elif mut == "crossorg":
        d["crossOrganization"] = False
    elif mut == "fixedruntimes":
        d["organizations"][1]["participants"][0]["slots"][0]["allowedRuntimes"] = ["evm"]
    elif mut == "binder":
        d["organizations"][0]["participants"][0]["slots"][0]["authorizedBinder"] = "evilco"
    elif mut == "emptyorgs":
        d["organizations"] = []
    neg = os.path.join(tmp, "bt_neg.json")
    json.dump(d, open(neg, "w"))
    if validate(neg) == 0:
        fails.append(f"binding-topology validator accepted a '{mut}' mutation")

if fails:
    print("[38] binding-topology contract FAILED:", file=sys.stderr)
    for f in fails:
        print("    FAIL: " + f, file=sys.stderr)
    sys.exit(1)
print("[38] OK: org->participant->slot emitted + validates; stable ids; excluded from capabilityHash; "
      "participant-free stays byte-stable incl. output-dir reuse; unknown-field / bad-slotId / "
      "wrong-crossOrg / fixed-with-runtimes / binder-outside-org / empty-topology fail closed")

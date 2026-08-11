"""[41] D4: lower-layer translation map (explicit reviewed artifact; lossy mappings visible + test-gated).
Ported verbatim from the retired run_cpp_tests.sh [41] block ( S5k). The reviewed map validates + is
hash-pinned; lower (capability -> pacs.009) and lift (pacs.002 -> evidence) are byte-stable round-trip
fixtures; lossy mappings are visible (the RJCT status lift records the raw status among lossyFields); and
an unknown status code, a tampered map, an unpinned map, a non-array section, a missing-lossiness mapping,
and proposed (un-reviewed) provenance all fail closed.

Usage: check_translation_map.py <validate_translation_map.py> <translate_rail.py> <examples-dir>
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile

VMAP, RAIL, EXAMPLES = sys.argv[1:4]
REPO = os.path.dirname(os.path.abspath(EXAMPLES))
fails = []
tmp = tempfile.mkdtemp(prefix="d4_41.")
MAP = os.path.join(EXAMPLES, "translation-maps", "iso20022_interbank.map.json")
F = os.path.join(EXAMPLES, "translation-maps", "fixtures")

# : `1f16e44a` externalized the sponsored-offer domain to the curated pack
# corpus and renamed this constant to `core_sponsored_offer`, an identity that
# never existed under `examples/domains/`. The capability wire contract this
# lowering consumes is production-domain content, so it is resolved only through
# the receipt-verifying M6 pack resolver at the manifest's pinned coordinates --
# never by assembling a hydrated-cache path here.
sys.path.insert(0, os.path.join(REPO, "test", "ir", "pipeline"))
from pipeline_inputs import (PipelineInputError, require_surface,  # noqa: E402
                             resolve_pipeline_inputs)

try:
    CAP = str(require_surface(resolve_pipeline_inputs(REPO)["sponsored_offer_agreement"],
                              "generated", "slot", "capability.json"))
except PipelineInputError as error:
    print("[41] D4 translation-map contract FAILED:", file=sys.stderr)
    print("    FAIL: " + str(error), file=sys.stderr)
    sys.exit(1)


def ok(cmd):
    return subprocess.run([str(c) for c in cmd],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def vmap(path):
    return ok([sys.executable, VMAP, path])


def rail(*args):
    return ok([sys.executable, RAIL, *args])


def repin(path):
    m = json.load(open(path))
    body = {k: v for k, v in m.items() if k != "translationMapHash"}
    m["translationMapHash"] = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    json.dump(m, open(path, "w"))


def mutate(fn, name):
    p = os.path.join(tmp, name)
    m = json.load(open(MAP))
    fn(m)
    json.dump(m, open(p, "w"))
    return p


# the reviewed map validates + hash-pins.
if not vmap(MAP):
    fails.append("reviewed map did not validate")

# lower + lift are byte-stable round-trip fixtures.
lower = os.path.join(tmp, "d4_lower.json")
if not rail("lower", "--map", MAP, "--capability", CAP, "--out", lower):
    fails.append("lower projection failed")
elif open(lower, "rb").read() != open(os.path.join(F, "pacs009_projection.golden.json"), "rb").read():
    fails.append("lower projection drifted from golden")

lift = os.path.join(tmp, "d4_lift.json")
if not rail("lift", "--map", MAP, "--status", os.path.join(F, "pacs002_status_rejected.json"), "--out", lift):
    fails.append("lift interpretation failed")
elif open(lift, "rb").read() != open(os.path.join(F, "pacs002_evidence.golden.json"), "rb").read():
    fails.append("lift interpretation drifted from golden")
else:
    d = json.load(open(lift))
    if not (d["runtimeState"] == "rejected" and d["correlationId"]
            and "pacs.002/TxInfAndSts/TxSts" in d["lossyFields"]
            and d["extensionData"]["pacs.002/TxInfAndSts/TxSts"] == "RJCT"):
        fails.append("lift did not surface state/correlation/lossiness as expected")

# fail closed: a status code not in the reviewed code-list is rejected.
badcode = os.path.join(tmp, "d4_badcode.json")
s = json.load(open(os.path.join(F, "pacs002_status_rejected.json")))
s["pacs.002"]["TxInfAndSts"]["TxSts"] = "ZZZZ"
json.dump(s, open(badcode, "w"))
if rail("lift", "--map", MAP, "--status", badcode, "--out", os.path.join(tmp, "d4_x.json")):
    fails.append("lift accepted a status code outside the reviewed code-list")

# fail closed: a tampered map (hash mismatch) is refused.
badmap = mutate(lambda m: m.__setitem__("rail", "evil"), "d4_badmap.json")
if rail("lift", "--map", badmap, "--status", os.path.join(F, "pacs002_status_rejected.json"),
        "--out", os.path.join(tmp, "d4_x.json")):
    fails.append("applied a tampered (hash-mismatched) map")

# fail closed: a missing-lossiness mapping (re-pinned so only lossiness is wrong).
noloss = mutate(lambda m: m["lower"][0].pop("lossiness"), "d4_noloss.json")
repin(noloss)
if vmap(noloss):
    fails.append("validator accepted a mapping with no lossiness")

# fail closed: un-reviewed (proposed) provenance.
prop = mutate(lambda m: m["provenance"].__setitem__("status", "proposed"), "d4_prop.json")
repin(prop)
if vmap(prop):
    fails.append("validator accepted proposed (un-reviewed) provenance")

# fail closed: an unpinned (missing-hash) map is rejected by the validator AND not applied.
nohash = mutate(lambda m: m.pop("translationMapHash", None), "d4_nohash.json")
if vmap(nohash):
    fails.append("validator accepted an unpinned (no-hash) map")
if rail("lower", "--map", nohash, "--capability", CAP, "--out", os.path.join(tmp, "d4_x.json")):
    fails.append("translate_rail applied an unpinned (no-hash) map")

# fail closed: a non-array section (e.g. "lower": {}) is rejected, not iterated as empty.
nonarray = mutate(lambda m: m.__setitem__("lower", {}), "d4_nonarray.json")
repin(nonarray)
if vmap(nonarray):
    fails.append("validator accepted a non-array 'lower' section")

if fails:
    print("[41] translation-map contract FAILED:", file=sys.stderr)
    for f in fails:
        print("    FAIL: " + f, file=sys.stderr)
    sys.exit(1)
print("[41] OK: reviewed map validates + is hash-pinned; lower->pacs.009 + lift pacs.002->evidence "
      "byte-stable; lossy mappings visible; unknown status code / tampered map / unpinned map / "
      "non-array section / missing-lossiness / proposed-provenance all fail closed")

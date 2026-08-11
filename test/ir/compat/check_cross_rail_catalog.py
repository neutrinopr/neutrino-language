"""[51] cross-rail fixture catalog (). Ported verbatim from the retired run_cpp_tests.sh [51] block
( S5m). The committed catalog's paths + capability/slot-policy/Binding-Manifest identity match the
generated artifacts, and its top-level compatibility block is pinned to include/Neutrino/VersionInfo.h.
Five negatives each fail closed: a manifest bound under the wrong org/participant; a compatibility
surface drifted from VersionInfo.h; a per-contract schema bump in VersionInfo.h; an L2 sidecar with an
invented l1 anchor; and a capability.json capabilityVersion drifted from the registry. Negatives run
against a copy of examples/ + include/ that is mutated then restored between cases.

Usage: check_cross_rail_catalog.py <validate_cross_rail_catalog.py> <examples-dir>
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

CRC, EXAMPLES = sys.argv[1:3]
REPO = os.path.dirname(os.path.abspath(EXAMPLES))
fails = []


def crc(repo_root=None):
    cmd = [sys.executable, CRC]
    if repo_root:
        cmd += ["--repo-root", repo_root, "--catalog", "examples/cross-rail-fixtures.json"]
    return subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode


# positive: the committed catalog validates (paths + identities + compatibility pin).
if crc(REPO) != 0:
    fails.append("cross-rail fixture catalog is stale or drifted from the committed artifacts")

# Negatives against a mutable copy. The cross-rail catalog consumes translator-owned
# synthetic fixtures from test/ after the production corpus moved to packs, so copy
# every fixture surface the catalog actually cites — derived from the catalog, not a
# hardcoded name, so a fixture the catalog gains is copied automatically.
root = tempfile.mkdtemp(prefix="crc51.")
shutil.copytree(EXAMPLES, os.path.join(root, "examples"))
shutil.copytree(os.path.join(REPO, "include"), os.path.join(root, "include"))
_catalog = json.load(open(os.path.join(EXAMPLES, "cross-rail-fixtures.json")))
_cited_roots = set()
for _fx in _catalog["fixtures"]:
    for _rel in [_fx["source"], _fx["scenario"], _fx["bindingTopology"]] + [
            p for group in _fx["generated"].values() for p in group]:
        if _rel.startswith("test/"):
            # test/ir/<area>/Inputs/<fixture>/...
            _cited_roots.add(os.sep.join(_rel.split("/")[:5]))
for _rel_root in sorted(_cited_roots):
    shutil.copytree(os.path.join(REPO, _rel_root), os.path.join(root, _rel_root))
EX = os.path.join(root, "examples")
INC = os.path.join(root, "include")

# Non-vacuity floor: the UNMUTATED copy must validate. Without this, a fixture the
# catalog cites but the copy omits makes crc(root) fail for the wrong reason and
# every negative below "rejects" vacuously ().
if crc(root) != 0:
    fails.append("the unmutated catalog copy does not validate — every negative below "
                 "would reject vacuously; the copied fixture surface is incomplete")


def restore(rel):
    src = os.path.join(REPO, rel)
    dst = os.path.join(root, rel)
    shutil.copyfile(src, dst)


def mutate_json(path, fn):
    d = json.load(open(path))
    fn(d)
    json.dump(d, open(path, "w"), indent=2)


def edit_text(path, old, new):
    s = open(path).read().replace(old, new)
    open(path, "w").write(s)


def expect_reject(label):
    if crc(root) == 0:
        fails.append(f"catalog validator accepted {label}")


# 1: a Binding Manifest bound under the wrong org/participant.
def _wrong_org(m):
    m["bindings"][0]["organizationId"] = "wrong-org"
    m["bindings"][0]["participantId"] = "WrongParticipant"


mutate_json(os.path.join(EX, "binding-manifests", "core_dual_offer.binding.json"), _wrong_org)
expect_reject("a manifest binding under the wrong org/participant")
restore("examples/binding-manifests/core_dual_offer.binding.json")

# 2: a compatibility surface drifted from VersionInfo.h.
mutate_json(os.path.join(EX, "cross-rail-fixtures.json"),
            lambda c: c["compatibility"].__setitem__("mlirDialectVersion", "9.9.9"))
expect_reject("a compatibility surface drifted from VersionInfo.h")
restore("examples/cross-rail-fixtures.json")

# 3: a per-contract schema bump in VersionInfo.h (catalog unchanged).
edit_text(os.path.join(INC, "Neutrino", "VersionInfo.h"),
          'kSchemaBindingReceipt = "v1"', 'kSchemaBindingReceipt = "v2"')
expect_reject("a per-contract schema bump (bindingReceipt) drifted from VersionInfo.h")
restore("include/Neutrino/VersionInfo.h")

# 4: an L2 sidecar with an invented l1 anchor.
mutate_json(os.path.join(EX, "l2-domain-semantics", "core_dual_offer.l2.json"),
            lambda a: a["l1"]["primitives"].append("FABRICATED_PRIMITIVE"))
expect_reject("an L2 sidecar with an invented l1 anchor (not in generated artifacts)")
restore("examples/l2-domain-semantics/core_dual_offer.l2.json")

# 5: a capability.json capabilityVersion drifted from the registry.
mutate_json(
    os.path.join(
        root, "test", "ir", "samples", "Inputs", "core_dual_offer",
        "generated", "slot", "capability.json"
    ),
            lambda c: c.__setitem__("capabilityVersion", "9.9.9"))
expect_reject("a capability.json capabilityVersion drifted from the registry")

if fails:
    print("[51] cross-rail-catalog contract FAILED:", file=sys.stderr)
    for f in fails:
        print("    FAIL: " + f, file=sys.stderr)
    sys.exit(1)
print("[51] OK: committed paths + capability/slot-policy/manifest identity match the generated "
      "artifacts; compatibility surface pinned to VersionInfo.h; wrong-org manifest / drifted "
      "compatibility / per-contract schema bump / invented l1 anchor / drifted capabilityVersion "
      "all fail closed")

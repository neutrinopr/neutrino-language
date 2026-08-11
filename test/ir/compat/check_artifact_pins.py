"""[52b] M5 R3 (): side-artifact capability-spec version pins. Ported verbatim from the retired
run_cpp_tests.sh [52b] block ( S5m). The emitted capabilitySpecVersion (VersionInfo.h
kCapabilitySpecVersion, read from --version-json) is in lockstep with the capability-spec schema $id;
every committed target profile + production dialect (glob-discovered, so a new side artifact added
without a pin fails closed) declares that same version; and a wrong pin, a missing pin, an unpinnable
kind, and every committed negative fixture each fail closed with their code.

Usage: check_artifact_pins.py <translate> <check_artifact_pins.py> <examples-dir>
"""
import glob
import json
import os
import re
import subprocess
import sys
import tempfile

TRANSLATE, CHK, EXAMPLES = sys.argv[1:4]
REPO = os.path.dirname(os.path.abspath(EXAMPLES))
fails = []

# the emitted capability-spec version (the pin all side artifacts must match).
v = json.loads(subprocess.run([TRANSLATE, "--version-json"], stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL).stdout)
emitted = v["capabilitySpecVersion"]


def chk(*args):
    r = subprocess.run([sys.executable, CHK, *args], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    return r.returncode, (json.loads(r.stdout) if r.stdout.strip() else None)


# 1. VersionInfo.h kCapabilitySpecVersion == capability-spec schema $id vN (lockstep self-check).
rc, _ = chk("--self-check")
if rc != 0:
    fails.append("capability-spec version self-check failed")
sid = json.load(open(os.path.join(REPO, "docs/schemas/capability-spec.schema.json")))["$id"]
if re.search(r"/([^/]+)$", sid).group(1) != emitted:
    fails.append(f"schema $id ({sid}) != emitted ({emitted})")

# 2. every committed target profile + production dialect declares capabilitySpecVersion == emitted.
pinned = sorted(glob.glob(os.path.join(EXAMPLES, "domain-dialects/*.dialect.json")))
pinned += sorted(glob.glob(os.path.join(EXAMPLES, "target-profiles/*.target-profile.json")))
if not pinned:
    fails.append("no committed side artifacts discovered to pin-check")
for p in pinned:
    if json.load(open(p)).get("capabilitySpecVersion") != emitted:
        fails.append(f"stale pin: {os.path.relpath(p, REPO)}")
rc, out = chk(*pinned)
if not (rc == 0 and out and out["ok"]):
    fails.append("committed pins rejected by check_artifact_pins.py")

# 3. fail-closed: a wrong pin, a missing pin, and an unpinnable kind each fail closed with their code.
tmp = tempfile.mkdtemp(prefix="pins52b.")


def run_doc(doc):
    p = os.path.join(tmp, "doc.json")
    json.dump(doc, open(p, "w"))
    rc, out = chk(p)
    return rc, ({d["code"] for d in out["diagnostics"]} if out else set())


for doc, code in [
    ({"kind": "neutrino.target-profile", "capabilitySpecVersion": "v999"}, "compat.capability_spec_mismatch"),
    ({"kind": "neutrino.target-profile"}, "compat.pin_missing"),
    ({"kind": "neutrino.domain-observation-set"}, "compat.unpinnable_kind"),
]:
    rc, codes = run_doc(doc)
    if not (rc == 1 and code in codes):
        fails.append(f"{doc.get('kind')} did not fail closed with {code} (rc={rc}, codes={sorted(codes)})")

# committed negative fixtures fail closed too.
negdir = os.path.join(EXAMPLES, "artifact-pins", "negatives")
for fn in sorted(os.listdir(negdir)):
    rc, _ = chk(os.path.join(negdir, fn))
    if rc != 1:
        fails.append(f"committed negative did not fail closed: {fn}")

if fails:
    print("[52b] artifact-pins contract FAILED:", file=sys.stderr)
    for f in fails:
        print("    FAIL: " + f, file=sys.stderr)
    sys.exit(1)
print("[52b] OK: emitted kCapabilitySpecVersion in lockstep with the capability-spec schema $id; "
      "committed target profiles + dialect pin the emitted version; wrong/missing pin, unpinnable kind, "
      "and every committed negative fail closed")

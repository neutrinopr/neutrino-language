"""[50] M2 promotion: core_scheme_settlement (participant/org/allow/leg-participant). Ported verbatim
from the retired run_cpp_tests.sh [50] block ( S5l). The upgraded scheme source translates; its
slot / security / postgres artifacts are byte-stable against the committed goldens; exactly one slot is
to_be_bound (SettlementBank); security is ok=true (the A2 binding is a trustBoundary advisory, not a
hard violation); and the binding manifest validates against the generated topology.

Usage: check_m2_promotion.py <neutrino-translate> <neutrino-gen> <validate_binding_manifest.py> <examples-dir>
"""
import json
import os
import subprocess
import sys
import tempfile

TRANSLATE, GEN, VBM, EXAMPLES = sys.argv[1:5]
fails = []
tmp = tempfile.mkdtemp(prefix="m2_50.")
HERE = os.path.dirname(os.path.abspath(__file__))
SND = os.path.join(HERE, "..", "pipeline", "Inputs", "core_scheme_settlement")
SRC = os.path.join(SND, "source", "core_scheme_settlement.neu")
SCEN = os.path.join(SND, "scenario", "core_scheme_settlement_happy_path.json")
MANIFEST = os.path.join(EXAMPLES, "binding-manifests", "core_scheme_settlement.binding.json")


def run(cmd):
    return subprocess.run([str(c) for c in cmd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def byte_match(a, b):
    return open(a, "rb").read() == open(b, "rb").read()


if run([TRANSLATE, SRC, "-o", os.path.join(tmp, "sn.mlir")]).returncode != 0:
    fails.append("upgraded scheme source did not translate")

# slot: byte-stable golden.
slot = os.path.join(tmp, "sn_slot")
if run([GEN, "--target=slot", "--scenario=" + SCEN, SRC, "-o", slot]).returncode != 0:
    fails.append("scheme slot gen failed")
else:
    for f in ("binding-topology.json", "capability.json", "capability.lock", "compensation.json",
              "envelope.schema.json", "operations.json", "transcript.json"):
        if not byte_match(os.path.join(slot, f), os.path.join(SND, "generated", "slot", f)):
            fails.append(f"scheme slot {f} drifted from committed fixture")
    d = json.load(open(os.path.join(slot, "binding-topology.json")))
    tbb = [s["slotId"] for o in d["organizations"] for p in o["participants"]
           for s in p["slots"] if s["lateBindingMode"] == "to_be_bound"]
    if not (d["crossOrganization"] is True and tbb == ["coordinate.core_scheme_settlement#SettlementBank"]):
        fails.append("expected exactly one to_be_bound slot (SettlementBank)")

# security: ok=true (A2 binding is a trustBoundary advisory) + byte-stable.
sec = os.path.join(tmp, "sn_sec")
if run([GEN, "--target=security", "--scenario=" + SCEN, SRC, "-o", sec]).returncode != 0:
    fails.append("scheme security gen exited non-zero (unexpected hard violation)")
else:
    if '"ok": true' not in open(os.path.join(sec, "security.json")).read():
        fails.append("scheme security is not ok=true")
    if not byte_match(os.path.join(sec, "security.json"), os.path.join(SND, "generated", "security", "security.json")):
        fails.append("scheme security.json drifted from committed fixture")

# postgres: generates + byte-stable.
pg = os.path.join(tmp, "sn_pg")
if run([GEN, "--target=postgres", "--scenario=" + SCEN, SRC, "-o", pg]).returncode != 0:
    fails.append("scheme postgres gen failed")
else:
    for f in ("schema.sql", "procedure.sql", "reconciliation.sql", "run_db_test.sh"):
        if not byte_match(os.path.join(pg, f), os.path.join(SND, "generated", "postgres", f)):
            fails.append(f"scheme postgres {f} drifted from committed fixture")

# binding manifest validates against the generated topology (single-slot completeness).
if run([sys.executable, VBM, "--manifest", MANIFEST,
        "--binding-topology", os.path.join(slot, "binding-topology.json")]).returncode != 0:
    fails.append("scheme binding manifest did not validate")

if fails:
    print("[50] M2-promotion contract FAILED:", file=sys.stderr)
    for f in fails:
        print("    FAIL: " + f, file=sys.stderr)
    sys.exit(1)
print("[50] OK: translates; slot/security/postgres byte-stable; one to_be_bound slot; security ok=true; "
      "manifest validates")

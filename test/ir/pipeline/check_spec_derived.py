"""[16b]/[22b] spec-derivation invariance ( coverage /  security; M5  B2/B3). Ported verbatim
from the retired run_cpp_tests.sh [16b]/[22b] blocks ( S5n). The coverage / security report is derived
from the frozen, scenario-free capability-spec () — Gen{Coverage,Security}Spec reads the spec JSON,
not a ProcedureView. Prove it is a pure function of that spec by mutating SCENARIO-ONLY data
(expect.events, which the report never consumes) and asserting the report is byte-identical; a
view+scenario reconstruction would let scenario data leak in, spec-derivation cannot.

Usage: check_spec_derived.py <neutrino-gen> <target> <artifact.json> <src.neu> <scenario.json>
"""
import json
import os
import subprocess
import sys
import tempfile

GEN, TARGET, ARTIFACT, SRC, SCEN = sys.argv[1:6]
tmp = tempfile.mkdtemp(prefix="specderiv.")


def gen(scenario, sub):
    out = os.path.join(tmp, sub)
    rc = subprocess.run([GEN, "--target=" + TARGET, "--scenario=" + scenario, SRC, "-o", out],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode
    return rc, out


rc, base = gen(SCEN, "base")
if rc != 0:
    print(f"[{TARGET}] FAIL: {TARGET} gen", file=sys.stderr)
    sys.exit(1)

# mutate SCENARIO-ONLY data the report never consumes.
alt_scen = os.path.join(tmp, "alt_scenario.json")
s = json.load(open(SCEN))
s["expect"] = s.get("expect", {})
s["expect"]["events"] = ["ZzzScenarioOnlyProbe"]
json.dump(s, open(alt_scen, "w"))
rc, alt = gen(alt_scen, "alt")
if rc != 0:
    print(f"[{TARGET}] FAIL: {TARGET} gen (alt scenario)", file=sys.stderr)
    sys.exit(1)

if open(os.path.join(base, ARTIFACT), "rb").read() != open(os.path.join(alt, ARTIFACT), "rb").read():
    print(f"[{TARGET}] FAIL: {ARTIFACT} changed with scenario-only data — not purely spec-derived",
          file=sys.stderr)
    sys.exit(1)
print(f"[{TARGET}] OK: {ARTIFACT} byte-identical under a mutated scenario — derived from the "
      "scenario-free capability-spec, not reconstructed from view+scenario")

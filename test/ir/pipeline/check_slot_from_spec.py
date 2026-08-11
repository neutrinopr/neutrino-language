"""[80] M5 WP3 (): slot renders from the spec lifecycle — scenario-free + mechanical drift guard.
Ported verbatim from the retired run_cpp_tests.sh [80] block ( S5n). Slot needs NO --scenario (it
emits from the canonical machine); it is scenario-INDEPENDENT (byte-identical with vs without a
scenario); and its lifecycle vocabulary (capability.operations / operations.json / compensation
compensable+nonCompensable / envelope operation enum) all PROJECT from the spec's canonical machine — a
slot can never advertise/compensate an operation the spec's lifecycle does not define.

Usage: check_slot_from_spec.py <neutrino-gen> <examples-dir>
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from pipeline_inputs import PipelineInputError, resolve_pipeline_inputs

GEN, EXAMPLES = sys.argv[1:3]
fails = []
tmp = tempfile.mkdtemp(prefix="slot80.")
try:
    MSI_FIXTURE = resolve_pipeline_inputs(Path(EXAMPLES).resolve().parent)[
        "merchant_sponsored_installment"
    ]
except PipelineInputError as error:
    print(f"[80] slot-from-spec contract FAILED:\n    FAIL: {error}", file=sys.stderr)
    raise SystemExit(1)
SRC = str(MSI_FIXTURE.source)
SCEN = str(MSI_FIXTURE.scenario)


def gen(args, sub):
    out = os.path.join(tmp, sub)
    rc = subprocess.run([GEN] + args + [SRC, "-o", out],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode
    return rc, out


# 1. slot needs NO --scenario.
rc, sl_ns = gen(["--target=slot"], "sl_ns")
if rc != 0:
    fails.append("slot required a scenario")

# 2. scenario-INDEPENDENT: byte-identical with vs without a scenario.
rc, sl_sc = gen(["--target=slot", "--scenario=" + SCEN], "sl_sc")
for f in ("capability.json", "operations.json", "compensation.json", "transcript.json",
          "envelope.schema.json", "capability.lock"):
    if open(os.path.join(sl_ns, f), "rb").read() != open(os.path.join(sl_sc, f), "rb").read():
        fails.append(f"slot {f} differs with vs without a scenario (scenario dependency leaked)")

# 3. mechanical drift guard: the slot lifecycle vocabulary projects from the spec's canonical machine.
rc, sl_spec = gen(["--target=capability-spec"], "sl_spec")
spec = json.load(open(os.path.join(sl_spec, "capability-spec.json")))
trans = spec["lifecycle"]["transitions"]
ops, seen = [], set()
for t in trans:
    if t["name"] not in seen:
        ops.append(t["name"])
        seen.add(t["name"])
post = [t["name"] for t in trans if "post" in t["effects"]]
comp = [t["name"] for t in trans if "compensate" in t["effects"]]
noncomp = [o for o in ops if o not in post and o not in comp]
try:
    cap = json.load(open(os.path.join(sl_ns, "capability.json")))
    assert cap["operations"] == ops, ("capability.operations", cap["operations"], ops)
    opsj = json.load(open(os.path.join(sl_ns, "operations.json")))
    assert [o["operation"] for o in opsj["operations"]] == ops, "operations.json op set != spec"
    cmp = json.load(open(os.path.join(sl_ns, "compensation.json")))
    assert list(cmp["compensable"]) == post, ("compensable", list(cmp["compensable"]), post)
    assert cmp["nonCompensable"] == noncomp, ("nonCompensable", cmp["nonCompensable"], noncomp)
    env = json.load(open(os.path.join(sl_ns, "envelope.schema.json")))
    assert env["properties"]["operation"]["enum"] == ops, "envelope op enum != spec vocabulary"
except AssertionError as ex:
    fails.append(f"slot lifecycle drifted from the spec's canonical machine: {ex}")

if fails:
    print("[80] slot-from-spec contract FAILED:", file=sys.stderr)
    for f in fails:
        print("    FAIL: " + f, file=sys.stderr)
    sys.exit(1)
print("[80] OK: slot emits with no --scenario; byte-identical with/without a scenario; capability/"
      "operations/compensation/envelope lifecycle vocabulary all project from the spec's canonical "
      "machine — a slot can't drift from the spec lifecycle")

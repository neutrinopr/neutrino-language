"""[42] T0/T2: binding-manifest validated against the D1b slot binding-topology ( diagnostic
taxonomy). Ported verbatim from the retired run_cpp_tests.sh [42] block ( S5k). The reviewed realized
manifest validates (exit 0 + ok=true JSON report); every diagnostic family (NEU-1001..1004 / 2001..2003
/ 3000..3001) is produced with BOTH its expected code AND category (so a code-category remap is caught),
exiting 1; and malformed/null topology containers report NEU-1001, never a traceback.

Usage: check_binding_manifest.py <validate_binding_manifest.py> <examples-dir>
"""
import json
import os
import subprocess
import sys
import tempfile

VBM, EXAMPLES = sys.argv[1:3]
REPO = os.path.dirname(os.path.abspath(EXAMPLES))
fails = []
tmp = tempfile.mkdtemp(prefix="bm42.")

# : the D1b topology this manifest is validated against moved to the
# core-owned synthetic when `be5d2a61` externalized flexible_binding_offer; the
# constant kept the deleted `examples/domains/` prefix, so every one of the 12
# diagnostic-family probes below degenerated into a usage-2 exit. Resolve it at
# the input boundary so the next absence names itself.
sys.path.insert(0, os.path.join(REPO, "test", "ir", "pipeline"))
from pipeline_inputs import (PipelineInputError, require_surface,  # noqa: E402
                             resolve_core_fixture)

try:
    FBO_FIXTURE = resolve_core_fixture(REPO, "core_flexible_binding")
    BT = str(require_surface(FBO_FIXTURE, "generated", "slot", "binding-topology.json"))
except PipelineInputError as error:
    print("[42] binding-manifest contract FAILED:", file=sys.stderr)
    print("    FAIL: " + str(error), file=sys.stderr)
    sys.exit(1)
M = os.path.join(EXAMPLES, "binding-manifests", "core_flexible_binding.binding.json")


def validate_json(manifest, topology):
    """Return (rc, report_dict_or_None)."""
    r = subprocess.run([sys.executable, VBM, "--manifest", manifest, "--binding-topology", topology, "--json"],
                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    return r.returncode, (json.loads(r.stdout) if r.stdout.strip() else None)


# the reviewed manifest validates (text exit 0) and the JSON report is ok=true.
if subprocess.run([sys.executable, VBM, "--manifest", M, "--binding-topology", BT],
                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0:
    fails.append("reviewed binding manifest did not validate")
rc, rep = validate_json(M, BT)
if not (rep and rep["ok"] is True and rep["diagnostics"] == []
        and rep["capability"] == "coordinate.core_flexible_binding"):
    fails.append("JSON report for the reviewed manifest is not ok=true")


def apply_mut(mut):
    m = json.load(open(M))
    b = m["bindings"][0]
    if mut == "runtime":
        b["runtime"] = "btc"
    elif mut == "assurance":
        b["assurance"] = "A1"
    elif mut == "badassurance":
        b["assurance"] = "A9"
    elif mut == "binder":
        b["binder"] = "evilco"
    elif mut == "wrongorg":
        b["organizationId"] = "otherco"
    elif mut == "fixedslot":
        m["bindings"] = [{"organizationId": "acme", "participantId": "Merchant",
                          "slotId": "coordinate.core_flexible_binding#Merchant",
                          "runtime": "evm", "assurance": "A2", "binder": "acme"}]
    elif mut == "unknownslot":
        b["slotId"] = "coordinate.core_flexible_binding#Ghost"
    elif mut == "dup":
        m["bindings"] = [b, dict(b)]
    elif mut == "incomplete":
        m["bindings"] = []
    elif mut == "nocapability":
        del m["capability"]
    elif mut == "unknowntop":
        m["surprise"] = 1
    elif mut == "unknownbinding":
        b["extra"] = "x"
    return m


# each diagnostic family produces its expected NEU code AND category, exiting 1.
for mut, code, cat in [
    ("runtime", "NEU-3000", "runtime"), ("assurance", "NEU-2001", "security"),
    ("binder", "NEU-2002", "security"), ("badassurance", "NEU-2003", "security"),
    ("wrongorg", "NEU-1003", "topology"), ("unknownslot", "NEU-1003", "topology"),
    ("dup", "NEU-1004", "topology"), ("incomplete", "NEU-1004", "topology"),
    ("fixedslot", "NEU-3001", "runtime"), ("nocapability", "NEU-1002", "topology"),
    ("unknowntop", "NEU-1001", "topology"), ("unknownbinding", "NEU-1001", "topology"),
]:
    neg = os.path.join(tmp, "bm_neg.json")
    json.dump(apply_mut(mut), open(neg, "w"))
    rc, rep = validate_json(neg, BT)
    if rc != 1:
        fails.append(f"'{mut}' mutation exited {rc} (want 1)")
    elif not (rep and rep["ok"] is False
              and (code, cat) in {(x["code"], x["category"]) for x in rep["diagnostics"]}):
        fails.append(f"'{mut}' mutation did not produce {code}/{cat}")

# malformed topology containers (non-list / null organizations|participants|slots) must produce a coded
# NEU-1001 JSON report, never a traceback.
for topbad in ('{"organizations":null}',
               '{"organizations":[{"organizationId":"o","participants":null}]}',
               '{"organizations":[{"organizationId":"o","participants":[{"participantId":"p","slots":null}]}]}'):
    t = json.loads(topbad)
    t["kind"] = "neutrino.slot-binding-topology"
    t["capability"] = "coordinate.core_flexible_binding"
    btbad = os.path.join(tmp, "bt_bad.json")
    json.dump(t, open(btbad, "w"))
    rc, rep = validate_json(M, btbad)
    if rc != 1:
        fails.append(f"malformed topology exited {rc} (want 1; likely a traceback)")
    elif not (rep and rep["ok"] is False
              and ("NEU-1001", "topology") in {(x["code"], x["category"]) for x in rep["diagnostics"]}):
        fails.append("malformed topology did not produce NEU-1001/topology")

if fails:
    print("[42] binding-manifest contract FAILED:", file=sys.stderr)
    for f in fails:
        print("    FAIL: " + f, file=sys.stderr)
    sys.exit(1)
print("[42] OK: reviewed manifest validates with ok=true JSON report; every diagnostic family "
      "(NEU-1001..1004 / 2001..2003 / 3000..3001) produces its code+category and exits 1; "
      "malformed/null topology containers report NEU-1001, never traceback")

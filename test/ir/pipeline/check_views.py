"""[33] generate.views: per-participant narrowed views (no obligation leakage). Ported verbatim from the
retired run_cpp_tests.sh [33] block ( S5n). Each per-participant view carries only its own leg +
inputs + (for a flexible participant) its binding policy — no view leaks another participant's leg or a
counterparty-only input. A no-participant source emits no view files (additive); views is a gated
coordination artifact (an insecure capability is refused exit 5 unless --allow-insecure); and
requiredInputs resolves compute dependencies transitively.

Usage: check_views.py <neutrino-gen> <examples-dir> <src.neu> <scenario.json>
"""
import json
import os
import subprocess
import sys
import tempfile

GEN, EXAMPLES, SRC, SCEN = sys.argv[1:5]
REPO = os.path.dirname(os.path.abspath(EXAMPLES))
fails = []
tmp = tempfile.mkdtemp(prefix="views33.")

# : `be5d2a61` renamed this constant to the core-owned synthetic identity but
# kept the `examples/domains/` prefix the same commit deleted, so the first gen()
# failed and the narrowing assertions never ran. The no-participant source (SRC /
# SCEN) is already passed as a %test/ir/.../Inputs path by the .test driver.
sys.path.insert(0, os.path.join(REPO, "test", "ir", "pipeline"))
from pipeline_inputs import PipelineInputError, resolve_core_fixture  # noqa: E402

try:
    FBO_FIXTURE = resolve_core_fixture(REPO, "core_flexible_binding")
except PipelineInputError as error:
    print("[33] views contract FAILED:", file=sys.stderr)
    print("    FAIL: " + str(error), file=sys.stderr)
    sys.exit(1)


def gen(scenario, src, sub, allow_insecure=False):
    out = os.path.join(tmp, sub)
    cmd = [GEN, "--target=views", "--scenario=" + scenario, src, "-o", out]
    if allow_insecure:
        cmd.insert(2, "--allow-insecure")
    rc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode
    return rc, out


# core_flexible_binding: narrowed per-participant views.
rc, out = gen(str(FBO_FIXTURE.scenario), str(FBO_FIXTURE.source), "views")
if rc != 0:
    fails.append("views gen")
elif not (os.path.isfile(os.path.join(out, "Sponsor.json")) and os.path.isfile(os.path.join(out, "Merchant.json"))):
    fails.append("a per-participant view file is missing")
else:
    s = json.load(open(os.path.join(out, "Sponsor.json")))
    m = json.load(open(os.path.join(out, "Merchant.json")))
    narrowed = ([o["leg"] for o in s["evidenceObligations"]] == ["sponsor_commitment"]
                and [o["leg"] for o in m["evidenceObligations"]] == ["merchant_expected_contribution"]
                and s.get("binding", {}).get("mode") == "to_be_bound" and "binding" not in m
                and s["permittedCounterparties"] == [{"org": "acme", "role": "merchant"}]
                and m["permittedCounterparties"] == [{"org": "sponsorco", "role": "sponsor"}]
                and "merchant_id" not in [i["name"] for i in s["requiredInputs"]]
                and "sponsor_id" not in [i["name"] for i in m["requiredInputs"]])
    if not narrowed:
        fails.append("views not correctly narrowed / leaked an obligation")
    if "merchant_expected_contribution" in open(os.path.join(out, "Sponsor.json")).read():
        fails.append("Sponsor view leaked the Merchant's leg")

# a no-participant source emits no view files (additive).
rc, out = gen(SCEN, SRC, "views_np")
extra = [f for f in os.listdir(out) if f.endswith(".json") and f not in ("manifest.json", "diagnostics.json")]
if extra:
    fails.append(f"no-participant source emitted view files: {extra}")

# views is gated like slot: an insecure role-constrained topology is refused.
insview = os.path.join(tmp, "insview.neu")
open(insview, "w").write("""procedure ins {
    trigger t
    participant P {
        role = "r"
        org  = "o"
    }
    participant Q {
        role = "q"
        org  = "q"
    }
    allow "o" with "q" {
        "o" as "wrong"
        "q" as "q"
    }
    input amt : money
    input acct : party
    input cur : currency
    input k : string
    debit d1 {
        ledger          = "a"
        owner           = "o"
        participant     = "P"
        party           = %acct
        amount          = %amt
        currency        = %cur
        idempotency_key = %k
    }
    credit c1 {
        ledger          = "b"
        owner           = "o"
        participant     = "Q"
        party           = %acct
        amount          = %amt
        currency        = %cur
        idempotency_key = %k
    }
    assert balanced
}
""")
insview_json = os.path.join(tmp, "insview.json")
open(insview_json, "w").write('{ "scenario":"i","procedure":"ins","inputs":{"amt":100,"acct":"p","cur":"EUR","k":"w"} }\n')
rc, _ = gen(insview_json, insview, "insview_out")
if rc != 5:
    fails.append(f"views not gated on an insecure capability (exit={rc}, want 5)")
rc, _ = gen(insview_json, insview, "insview_ok", allow_insecure=True)
if rc != 0:
    fails.append("--allow-insecure did not override the views gate")

# requiredInputs resolves compute deps transitively.
cmpview = os.path.join(tmp, "cmpview.neu")
open(cmpview, "w").write("""procedure cmpview {
    trigger t
    participant Seller {
        role = "seller"
        org  = "acme"
    }
    input principal   : money
    input subsidy_pct : number
    input acct        : party
    input cur         : currency
    input k           : string
    compute subsidy = principal * subsidy_pct / 100
    debit d1 {
        ledger          = "a.out"
        owner           = "acme"
        participant     = "Seller"
        party           = %acct
        amount          = %subsidy
        currency        = %cur
        idempotency_key = %k
    }
    credit c1 {
        ledger          = "b.in"
        owner           = "acme"
        participant     = "Seller"
        party           = %acct
        amount          = %subsidy
        currency        = %cur
        idempotency_key = %k
    }
    assert balanced
}
""")
cmpview_json = os.path.join(tmp, "cmpview.json")
open(cmpview_json, "w").write('{ "scenario":"cv","procedure":"cmpview","inputs":'
                              '{"principal":1000,"subsidy_pct":10,"acct":"p","cur":"EUR","k":"w"} }\n')
rc, out = gen(cmpview_json, cmpview, "cmpview_out")
if rc != 0:
    fails.append("views gen on compute-referencing leg")
else:
    n = [i["name"] for i in json.load(open(os.path.join(out, "Seller.json")))["requiredInputs"]]
    if not ("principal" in n and "subsidy_pct" in n):
        fails.append("requiredInputs did not resolve compute deps (principal/subsidy_pct missing)")

if fails:
    print("[33] views contract FAILED:", file=sys.stderr)
    for f in fails:
        print("    FAIL: " + f, file=sys.stderr)
    sys.exit(1)
print("[33] OK: per-participant views; narrowed + no leakage; legacy empty; security-gated; compute deps "
      "resolved transitively")

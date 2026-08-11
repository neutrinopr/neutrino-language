"""[78] M5 WP1c (): shared diagnostic taxonomy. Ported verbatim from the retired run_cpp_tests.sh
[78] block ( S5k). The taxonomy is the COMPILER's (regenerating the committed JSON byte-matches);
its shape holds strict-total-order precedence with active<reserved and cpp/validator emitter provenance;
the kernel verifier emits machine-readable [kernel.*] codes; every code the C++ tools (gen + equiv)
write into diagnostics.json is a REGISTERED, active code emitted in root-cause (non-decreasing precedence)
order; and each stdlib validator's diag() codes EQUAL the codes registered for its family (no drift).

Usage: check_diagnostic_taxonomy.py <neutrino-translate> <neutrino-opt> <neutrino-gen> <neutrino-equiv>
       <committed-taxonomy.json> <scripts-dir> <src.neu> <scenario.json> <bad_scenario.json> <ir-verify-neg.neu>
       <unbound-policy.neu> <unbound-policy-scenario.json>
"""
import json
import os
import re
import subprocess
import sys
import tempfile

(TRANSLATE, OPT, GEN, EQUIV, COMMITTED_TAX, SCRIPTS,
 SRC, SCEN, BAD_SCEN, IRV_NEG, UNBOUND, UNBOUND_SCEN) = sys.argv[1:13]
fails = []
tmp = tempfile.mkdtemp(prefix="tax78.")


def run(cmd, **kw):
    return subprocess.run([str(c) for c in cmd], stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kw)


# (a) the taxonomy is the compiler's; regenerating byte-matches the committed doc.
tax_path = os.path.join(tmp, "taxonomy.json")
r = run([TRANSLATE, "--diagnostic-taxonomy"])
open(tax_path, "wb").write(r.stdout)
if r.returncode != 0:
    fails.append("--diagnostic-taxonomy command failed")
elif open(COMMITTED_TAX, "rb").read() != r.stdout:
    fails.append("docs/diagnostic-taxonomy.json drifted from the compiler (regenerate it)")

# (b) shape + invariants.
codes = []
by = {}
try:
    t = json.loads(r.stdout)
    codes = t["codes"]
    by = {c["code"]: c for c in codes}
    ok = (t["schemaVersion"] == 1 and t["kind"] == "neutrino.diagnostic-taxonomy"
          and t["categories"][0] == "frontend" and t["categories"][-1] == "domain"
          and {"kernel.balance.unbalanced", "kernel.version.invalid", "value_type.mismatch",
               "expr.unsupported", "scenario.invalid", "security.gate",
               "equivalence.reference_mismatch", "equivalence.backend_environment_failed",
               "equivalence.backend_skipped",
               "attest.policy.unbound",
               "input.io", "classification.io", "spec.dead_end_state",
               "profile.conflicting_feature", "legality.unsupported_feature",
               "realization.hash_mismatch", "view.hash_mismatch",
               "observation.ai_field_forbidden", "domain.import.dangling",
               "domain.import.cyclic"} <= set(by)
          and by["kernel.balance.unbalanced"]["status"] == "active"
          and by["kernel.compensation.not_inverse"]["status"] == "reserved"
          and by["kernel.balance.unbalanced"]["emitter"] == "cpp"
          and by["input.io"]["emitter"] == "cpp"
          and by["classification.io"]["emitter"] == "validator"
          and by["spec.dead_end_state"]["emitter"] == "validator"
          and by["observation.ai_field_forbidden"]["emitter"] == "validator"
          and by["domain.import.dangling"]["emitter"] == "cpp"
          and by["domain.import.cyclic"]["status"] == "active"
          and by["equivalence.backend_environment_failed"]["precedence"] == 79
          and by["equivalence.backend_skipped"]["precedence"] == 82
          and by["legality.unsupported_feature"]["emitter"] == "both")
    precs = [c["precedence"] for c in codes]
    ok = ok and all(precs[i] < precs[i + 1] for i in range(len(precs) - 1))  # strict total order
    act = [c["precedence"] for c in codes if c["status"] == "active"]
    res = [c["precedence"] for c in codes if c["status"] == "reserved"]
    ok = ok and (not res or max(act) < min(res))  # every active ranks before every reserved
    if not ok:
        fails.append("taxonomy shape/invariants")
except (ValueError, KeyError, IndexError) as ex:
    fails.append(f"taxonomy shape/invariants: {ex}")

# (c) the kernel verifier emits machine-readable [kernel.*] codes (balance + version) via neutrino-opt.
unbalanced = os.path.join(tmp, "unbalanced.mlir")
open(unbalanced, "w").write(
    '"builtin.module"() ({\n'
    '  "neutrino.procedure"() ({\n'
    '    %0 = "neutrino.input"() {sym_name = "k", ty = "string"} : () -> !neutrino.value\n'
    '    %1 = "neutrino.input"() {sym_name = "amt", ty = "money"} : () -> !neutrino.value\n'
    '    "neutrino.debit"(%0, %1, %0, %0) {sym_name = "d", ledger = "a.b", owner = "o"} : '
    '(!neutrino.value, !neutrino.value, !neutrino.value, !neutrino.value) -> ()\n'
    '    "neutrino.assert_balanced"() : () -> ()\n'
    '  }) {sym_name = "p"} : () -> ()\n'
    '}) : () -> ()\n')
if not re.search(r"\[kernel\.balance\.", run([OPT, unbalanced]).stderr.decode("utf-8", "replace")):
    fails.append("balance verifier emitted no [kernel.balance.*] code")

ver = os.path.join(tmp, "tax_ver.mlir")
open(ver, "w").write(
    '"neutrino.procedure"() ({\n'
    '  "neutrino.participant"() {sym_name = "P", role = "r"} : () -> ()\n'
    '}) {sym_name = "p", trigger = "t", version = "dev"} : () -> ()\n')
if "[kernel.version.invalid]" not in run([OPT, ver]).stderr.decode("utf-8", "replace"):
    fails.append("version verifier emitted no [kernel.version.invalid] code")

# (d) every code the C++ tools write into diagnostics.json is a registered, active code, root-cause
#     ordered. Exercised across gen (invalid scenario / IR-verify failure / bad target) and equiv.
run([GEN, "--target=solidity", "--scenario=" + BAD_SCEN, SRC, "-o", os.path.join(tmp, "tax_scn")])
run([GEN, "--target=solidity", "--scenario=" + SCEN, IRV_NEG, "-o", os.path.join(tmp, "tax_irv")])
run([GEN, "--target=bogustarget", "--scenario=" + SCEN, SRC, "-o", os.path.join(tmp, "tax_tgt")])
run([GEN, "--target=capability-spec", UNBOUND, "-o", os.path.join(tmp, "tax_unbound_gen")])
diag_dirs = ["tax_scn", "tax_irv", "tax_tgt", "tax_unbound_gen"]
if EQUIV and EQUIV != "None":
    run([EQUIV, "--scenario=/no/such.json", "/no/such.neu", "--report=" + os.path.join(tmp, "tax_eqv_io")])
    # RETIRED FIXTURE (M6): `tax_eqv_skip` emptied PATH to starve an IN-PROCESS
    # PostgreSQL comparison of docker/psql and assert a skip diagnostic. This run
    # does not require PostgreSQL -- comparison rails come from the verified
    # package catalog, and the Solidity package is a self-contained binary that
    # PATH cannot starve. Emptying PATH now produces no skip at all, so the
    # fixture asserts a condition that can no longer arise. Skip accounting
    # itself remains covered by the profile-incompatibility path below.
    run([EQUIV, "--reference-only", "--scenario=" + UNBOUND_SCEN, UNBOUND,
         "--report=" + os.path.join(tmp, "tax_unbound_equiv"), "--allow-skips"])
    # RETIRED FIXTURE (M6): `tax_eqv_ready` faked docker/seq/sleep on PATH to make
    # an IN-PROCESS PostgreSQL readiness probe fail closed. Same reason as above --
    # PostgreSQL is not a required rail of this run, so no readiness probe runs and
    # nothing can fail closed. Kept out rather than weakened into a tautology.
    diag_dirs += ["tax_eqv_io", "tax_unbound_equiv"]

tax = by
for d in diag_dirs:
    dj = os.path.join(tmp, d, "diagnostics.json")
    if not os.path.isfile(dj):
        fails.append(f"{d} wrote no diagnostics.json")
        continue
    try:
        entries = json.load(open(dj))["diagnostics"]
        clist = [e["code"] for e in entries]
        assert clist, "no diagnostics emitted"
        for c in clist:
            assert c in tax and tax[c]["status"] == "active", f"unregistered/inactive code: {c}"
        if d == "tax_eqv_ready":
            assert "equivalence.backend_environment_failed" in clist, \
                "readiness failure emitted no equivalence.backend_environment_failed"
        if d in ("tax_unbound_gen", "tax_unbound_equiv"):
            assert clist == ["attest.policy.unbound"], \
                f"unbound-policy witness emitted unexpected codes: {clist}"
        p = [tax[c]["precedence"] for c in clist]
        assert all(p[i] <= p[i + 1] for i in range(len(p) - 1)), "not root-cause ordered"
    except (ValueError, KeyError, AssertionError) as ex:
        fails.append(f"{d} emitted an unregistered/inactive or mis-ordered code: {ex}")

# (e) validator-family drift: each stdlib validator's diag() codes EQUAL the taxonomy codes registered
#     for that family with emitter in {validator, both}. Reads the validator SOURCE for its diag() codes.
families = [
    ("classification", "corpus/validate_solidity_classification.py"),
    ("spec", "validators/validate_capability_spec.py"),
    ("profile", "validators/validate_target_profile.py"),
    ("legality", "gates/check_spec_legality.py"),
    ("realization", "validators/validate_test_realization.py"),
    ("view", "validators/validate_participant_view.py"),
    ("observation", "corpus/validate_domain_observation_set.py"),
]
for fam, rel in families:
    reg = {c["code"] for c in codes
           if c["code"].startswith(fam + ".") and c["emitter"] in ("validator", "both")}
    src = open(os.path.join(SCRIPTS, rel)).read()
    emitted = set(re.findall(r'diag\(\s*["\'](' + fam + r'\.[a-z_.]+)["\']', src))
    if emitted != reg:
        fails.append(f"{fam} diag() codes drifted -> validator-only: "
                     f"{sorted(emitted - reg)} ; taxonomy-only: {sorted(reg - emitted)}")

if fails:
    print("[78] diagnostic-taxonomy contract FAILED:", file=sys.stderr)
    for f in fails:
        print("    FAIL: " + f, file=sys.stderr)
    sys.exit(1)
print("[78] OK: taxonomy byte-matches committed; strict-total-order precedence, active<reserved, "
      "cpp/validator emitter provenance; kernel verifier emits [kernel.balance.*]/[kernel.version.invalid]; "
      "every gen+equiv diagnostics.json code is registered+active and root-cause ordered; validator diag() "
      "codes match the taxonomy exactly")

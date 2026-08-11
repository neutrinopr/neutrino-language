""" R1b: the crafted-external-spec fail-closed matrix at the planFromSpec /
assemblePlan trust boundary (architect F2). Every required-field deletion or
reference mismatch on an obligation-bearing capability-spec MUST be rejected —
the MLIR op verifier cannot defend this second boundary, so each is re-checked on
ingestion. One-line mutations of the valid spec, each asserting its stable
diagnostic. Complements the inline ghost-effect / version / order / non-array
groups in obligation_plan.mlir.

Usage: check_obligation_failclosed_matrix.py <neutrino-gen> <valid-spec.json>
"""
import copy
import json
import os
import subprocess
import sys
import tempfile

GEN, SPEC = sys.argv[1:3]
base = json.load(open(SPEC))
tmp = tempfile.mkdtemp(prefix="oblfc811.")


def O(s):
    return s["obligations"][0]


def expect_reject(desc, mutate, needle):
    s = copy.deepcopy(base)
    mutate(s)
    p = os.path.join(tmp, desc + ".json")
    json.dump(s, open(p, "w"))
    out = os.path.join(tmp, desc + ".out")
    r = subprocess.run([GEN, "--target=coordination-plan", "--from-spec", p, "-o", out],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    err = (r.stdout + r.stderr).decode("utf-8", "replace")
    if r.returncode == 0:
        sys.exit("FAIL[%s]: expected rejection, but --from-spec succeeded" % desc)
    if needle not in err:
        sys.exit("FAIL[%s]: expected %r, got:\n%s" % (desc, needle, err))
    print("OK[%s]: %s" % (desc, needle))


def _dup_first_effect(s):
    O(s)["effects"] = [O(s)["effects"][0], O(s)["effects"][0]]


def _mismatch(s):
    # Flip the obligation predicate's operator so its guardKey diverges from the
    # effects it authorizes (which keep `amount >= agreed`).
    O(s)["when"]["ast"]["op"] = "<"
    O(s)["when"]["expr"] = "amount < agreed"


expect_reject("undeclared_obligor", lambda s: O(s).__setitem__("obligor", "Ghost"),
              "[kernel.obligation.obligor]")
expect_reject("undeclared_beneficiary", lambda s: O(s).__setitem__("beneficiary", "Ghost"),
              "[kernel.obligation.scope]")
expect_reject("undeclared_authority", lambda s: O(s).__setitem__("authority", "Ghost"),
              "[kernel.obligation.scope]")
expect_reject("missing_predicate_ast", lambda s: O(s)["when"].pop("ast"),
              "[kernel.obligation.predicate]")
expect_reject("duplicate_effect", _dup_first_effect,
              "[kernel.obligation.duplicate_effect]")
expect_reject("empty_effects", lambda s: O(s).__setitem__("effects", []),
              "[kernel.obligation.effects_empty]")
expect_reject("predicate_guard_mismatch", _mismatch,
              "does not match the guard")
print("OK: obligation crafted-spec fail-closed matrix complete (7 rejections)")

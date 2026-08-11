"""[94] M5 release-review (): negative money compute REFUSES before rendering (evaluated, not the
declared echo). Ported verbatim from the retired run_cpp_tests.sh [94] block ( S5n). core_scheme_settlement's committed negative fixture drives `net = gross_position - fee` below zero; it must fail
closed at scenario validation (exit 3 + scenario.invalid, naming the evaluated negative money compute)
before any backend, on BOTH Solidity and Postgres with NO artifact. The check is on the EVALUATED value:
a scenario that LIES (declares a non-negative net) or OMITS expect.computed.net is still refused; a
negative money INPUT is refused too; and the valid (non-negative) scenario still renders — the guard is
targeted, not blanket, so signed ledger NET deltas are untouched.

Usage: check_money_refuse.py <neutrino-gen> <examples-dir>
"""
import json
import os
import subprocess
import sys
import tempfile

GEN, EXAMPLES = sys.argv[1:3]
fails = []
tmp = tempfile.mkdtemp(prefix="money94.")
# Test-only synthetic (domain externalized under  train3).
SNS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Inputs", "core_scheme_settlement")
SRC = os.path.join(SNS, "source", "core_scheme_settlement.neu")
NEG = os.path.join(SNS, "scenario", "core_scheme_settlement_negative_net.json")
POS = os.path.join(SNS, "scenario", "core_scheme_settlement_happy_path.json")


def gen(target, scenario, sub):
    out = os.path.join(tmp, sub)
    rc = subprocess.run([GEN, "--target=" + target, "--scenario=" + scenario, SRC, "-o", out],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode
    dj = os.path.join(out, "diagnostics.json")
    return rc, out, (open(dj).read() if os.path.isfile(dj) else "")


# the committed negative fixture fails closed at scenario validation (Solidity), naming the evaluated compute.
rc, out, diag = gen("solidity", NEG, "d298neg")
if rc != 3:
    fails.append(f"negative-net solidity exit={rc} (want 3)")
if '"scenario.invalid"' not in diag:
    fails.append("negative-net missing scenario.invalid")
if "computed money value 'net' evaluates to -500000" not in diag:
    fails.append("negative-net diagnostic did not name the evaluated negative money compute")
if os.path.isdir(os.path.join(out, "src")):
    fails.append("emitted Solidity src despite negative money compute")

# the Postgres path fails closed too (the signed-money-inversion hazard).
rc, out, _ = gen("postgres", NEG, "d298negpg")
if rc != 3:
    fails.append(f"negative-net postgres exit={rc} (want 3)")
if os.path.isfile(os.path.join(out, "procedure.sql")):
    fails.append("emitted procedure.sql despite negative money compute")


def variant(sub, mutate, base=NEG):
    p = os.path.join(tmp, sub + ".json")
    d = json.load(open(base))
    mutate(d)
    json.dump(d, open(p, "w"))
    return p


# a scenario that LIES (declares net=999) with the same negative-driving inputs is still refused.
lie = variant("d298lie", lambda d: d["expect"].__setitem__("computed", {"fee": 1500000, "net": 999}))
rc, out, _ = gen("solidity", lie, "d298lie")
if rc != 3:
    fails.append(f"lying (net=999) negative scenario exit={rc} (want 3)")
if os.path.isdir(os.path.join(out, "src")):
    fails.append("emitted src for a lying negative scenario")

# a scenario that OMITS expect.computed.net is refused too (guard doesn't depend on the echo).
omit = variant("d298omit", lambda d: d["expect"].__setitem__("computed", {}))
rc, out, _ = gen("solidity", omit, "d298omit")
if rc != 3:
    fails.append(f"omitted-expect negative scenario exit={rc} (want 3)")
if os.path.isdir(os.path.join(out, "src")):
    fails.append("emitted src for an omitted-expect negative scenario")

# a negative money INPUT (not just a computed result) is refused too.
negin = variant("d298negin", lambda d: (d["inputs"].__setitem__("gross_position", -5),
                                        d["expect"].__setitem__("computed", {})), base=POS)
rc, out, diag = gen("solidity", negin, "d298negin")
if rc != 3:
    fails.append(f"negative money input exit={rc} (want 3)")
if "money input 'gross_position' is negative" not in diag:
    fails.append("negative money input not named in diagnostics")

# the valid (non-negative) scenario still renders — signed ledger NET deltas must NOT trip the guard.
rc, out, _ = gen("solidity", POS, "d298pos")
if rc != 0:
    fails.append("valid core_scheme_settlement scenario no longer renders")
if not os.path.isdir(os.path.join(out, "src")):
    fails.append("valid scenario did not emit Solidity src")

if fails:
    print("[94] money-refuse contract FAILED:", file=sys.stderr)
    for f in fails:
        print("    FAIL: " + f, file=sys.stderr)
    sys.exit(1)
print("[94] OK: negative money compute refused on the EVALUATED value — committed fixture + lying + "
      "omitted expect all fail closed on Solidity/SQL with no artifact; negative money input refused; "
      "signed ledger deltas untouched so the valid scenario still renders")

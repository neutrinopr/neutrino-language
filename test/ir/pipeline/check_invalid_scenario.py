"""[6] invalid scenario: exit 3 + machine-readable diagnostics. Ported verbatim from the retired
run_cpp_tests.sh [6] block ( S5n). A bad scenario -> exit 3 + scenario.invalid; a non-string
expect.invariants entry is a schema error caught at load (exit 3, scenario.schema), not silently dropped;
a money-typed idempotency_key -> exit 3 + an idempotency_key diagnostic and NO artifacts (it would emit
uncompilable Solidity); and divergent per-leg idempotency_keys -> exit 3 + a "share one workflow"
diagnostic and NO artifacts (backends would silently collapse them to the first).

Usage: check_invalid_scenario.py <neutrino-gen> <src.neu> <scenario.json> <bad_scenario.json>
"""
import json
import os
import subprocess
import sys
import tempfile

GEN, SRC, SCEN, BAD = sys.argv[1:5]
fails = []
tmp = tempfile.mkdtemp(prefix="scn6.")


def gen(scenario, src, sub):
    out = os.path.join(tmp, sub)
    rc = subprocess.run([GEN, "--target=solidity", "--scenario=" + scenario, src, "-o", out],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode
    diag = ""
    dj = os.path.join(out, "diagnostics.json")
    if os.path.isfile(dj):
        diag = open(dj).read()
    return rc, diag, out


# a bad scenario -> exit 3 + scenario.invalid.
rc, diag, _ = gen(BAD, SRC, "bad")
if rc != 3:
    fails.append(f"bad scenario exit={rc} (want 3)")
if '"scenario.invalid"' not in diag:
    fails.append("diagnostics code scenario.invalid missing")

# a non-string expect.invariants entry -> exit 3 + scenario.schema (caught at load).
badinv = os.path.join(tmp, "badinv.json")
s = json.load(open(SCEN))
s.setdefault("expect", {})["invariants"] = ["balanced", 123]
json.dump(s, open(badinv, "w"))
rc, diag, _ = gen(badinv, SRC, "badinv")
if rc != 3:
    fails.append(f"non-string invariant exit={rc} (want 3)")
if '"scenario.schema"' not in diag:
    fails.append("non-string invariant not scenario.schema")

# a money-typed idempotency_key -> exit 3 + idempotency_key diagnostic + NO artifacts.
keymoney_json = os.path.join(tmp, "keymoney.json")
s = json.load(open(SCEN))
s["inputs"]["transaction_id"] = 1
json.dump(s, open(keymoney_json, "w"))
keymoney_neu = os.path.join(tmp, "keymoney.neu")
open(keymoney_neu, "w").write(open(SRC).read().replace("transaction_id : string", "transaction_id : money"))
rc, diag, out = gen(keymoney_json, keymoney_neu, "keymoney")
if rc != 3:
    fails.append(f"money idempotency_key exit={rc} (want 3)")
if "idempotency_key" not in diag:
    fails.append("idempotency_key diagnostic missing")
if os.path.isdir(os.path.join(out, "src")):
    fails.append("emitted Solidity despite invalid idempotency_key")

# divergent per-leg idempotency_key -> exit 3 + "share one workflow" + NO artifacts.
divkey_neu = os.path.join(tmp, "divkey.neu")
src = open(SRC).read()
src = src.replace("input transaction_id : string",
                  "input transaction_id : string\n    input other_key : string", 1)
i = src.rfind("idempotency_key = %transaction_id")
src = src[:i] + "idempotency_key = %other_key" + src[i + len("idempotency_key = %transaction_id"):]
open(divkey_neu, "w").write(src)
divkey_json = os.path.join(tmp, "divkey.json")
s = json.load(open(SCEN))
s["inputs"]["other_key"] = "o-1"
json.dump(s, open(divkey_json, "w"))
rc, diag, out = gen(divkey_json, divkey_neu, "divkey")
if rc != 3:
    fails.append(f"divergent per-leg idempotency_key exit={rc} (want 3)")
if "share one workflow" not in diag:
    fails.append("divergent-key diagnostic missing")
if os.path.isdir(os.path.join(out, "src")):
    fails.append("emitted Solidity despite divergent keys")

if fails:
    print("[6] invalid-scenario contract FAILED:", file=sys.stderr)
    for f in fails:
        print("    FAIL: " + f, file=sys.stderr)
    sys.exit(1)
print("[6] OK: exit 3 + scenario.invalid; non-string invariant -> scenario.schema; numeric + divergent "
      "idempotency_key -> exit 3, no artifacts")

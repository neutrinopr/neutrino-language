"""[92] M5 WP7 (): conditional guards — end-to-end (spec `when` + SQL IF + Solidity if + guard-aware
count) and predicate-ONLY-in-guard fail-closed. Ported verbatim from the retired run_cpp_tests.sh [92]
block ( S5n). core_document_escrow's spec carries a `when` comparison guard on the release legs + the
guard:conditional feature; the guard lowers to SQL `IF ... THEN` and Solidity `if (...)`; the harness
posting count is guard-aware; a predicate used anywhere but a guard (comparison-in-compute /
non-comparison / non-numeric / ill-typed ingested / undeclared var) fails closed with no SQL; the events
+ count are scenario-aware on BOTH branches; and a guarded spec is schemaVersion 2 (unguarded stays 1).

Usage: check_conditional_guards.py <neutrino-gen> <examples-dir>
"""
import json
import os
import subprocess
import sys
import tempfile

GEN, EXAMPLES = sys.argv[1:3]
REPO = os.path.dirname(os.path.abspath(EXAMPLES))
fails = []
tmp = tempfile.mkdtemp(prefix="guard92.")
# Test-only synthetic (domain externalized under ).
CE = os.path.join(REPO, "test", "ir", "samples", "Inputs", "core_document_escrow")
CE_SRC = os.path.join(CE, "source", "core_document_escrow.neu")
GEN_DIR = os.path.join(CE, "generated")


def gen(args, sub):
    out = os.path.join(tmp, sub)
    r = subprocess.run([GEN] + args + ["-o", out], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    dj = os.path.join(out, "diagnostics.json")
    return r.returncode, out, (open(dj).read() if os.path.isfile(dj) else "")


def has(path, needle):
    return os.path.isfile(path) and needle in open(path).read()


# (a) the spec carries a `when` comparison guard on the release legs + guard:conditional feature.
d = json.load(open(os.path.join(GEN_DIR, "capability-spec", "capability-spec.json")))
g = [e["name"] for e in d["effects"] if "when" in e]
feats = {r["feature"] for r in d["targetRequirements"]["requirements"]}
if not ("escrow_release" in g and "guard:conditional" in feats):
    fails.append("core_document_escrow spec missing the when guard / guard:conditional feature")

# (b) the guard lowers to SQL IF...THEN and Solidity if(...).
if not has(os.path.join(GEN_DIR, "postgres", "procedure.sql"), "IF p_amount >= p_agreed_amount THEN"):
    fails.append("postgres did not lower the guard to IF ... THEN")
sol_dir = os.path.join(GEN_DIR, "solidity", "src")
if not any(has(os.path.join(sol_dir, f), "if (u_amount >= u_agreed_amount)") for f in os.listdir(sol_dir)):
    fails.append("Solidity did not lower the guard to if(...)")

# (c) the harness posting count is guard-aware: base 2 + fired release pair = 4.
if not has(os.path.join(GEN_DIR, "postgres", "run_db_test.sh"), '[ "$N" = "4" ]'):
    fails.append("harness posting count is not guard-aware (expected 4 fired legs)")

# (d) NEGATIVE — a comparison in a compute VALUE is not value grammar -> rejected.
cic = os.path.join(tmp, "cic.neu")
open(cic, "w").write("""procedure p { trigger t version "1.0.0"
    input a : money
    input b : money
    compute bad = a >= b
    input k : string
    input acct : party
    input cur : currency
    debit d {
        ledger = "l"
        owner = "o"
        party = %acct
        amount = %a
        currency = %cur
        idempotency_key = %k
    }
    assert balanced
}
""")
if gen(["--target=capability-spec", cic], "o1")[0] == 0:
    fails.append("a comparison used as a compute value was accepted")

# (e) NEGATIVE — a non-comparison `when` guard is rejected.
noncmp = os.path.join(tmp, "noncmp.neu")
open(noncmp, "w").write(open(CE_SRC).read().replace("= amount >= agreed_amount", "= amount"))
if gen(["--target=capability-spec", noncmp], "o2")[0] == 0:
    fails.append("a non-comparison when guard was accepted")

# (f) NEGATIVE — a non-numeric (party) guard operand -> expr.type.
nonnum = os.path.join(tmp, "nonnum.neu")
open(nonnum, "w").write(open(CE_SRC).read().replace("= amount >= agreed_amount", "= buyer_id >= agreed_amount"))
rc, _, diag = gen(["--target=capability-spec", nonnum], "o3")
if rc == 0 or "expr.type" not in diag:
    fails.append("a non-numeric guard operand should be rejected with expr.type")

# spec used as the ingestion base for (g)/(h).
_, gcs, _ = gen(["--target=capability-spec", CE_SRC], "capability-spec")
base_spec = json.load(open(os.path.join(gcs, "capability-spec.json")))


def ingest_reject(mutate, sub, label):
    spec = json.loads(json.dumps(base_spec))
    for e in spec["effects"]:
        if "when" in e:
            mutate(e)
    p = os.path.join(tmp, sub + ".json")
    json.dump(spec, open(p, "w"))
    rc, out, diag = gen(["--target=postgres", "--from-spec", p], sub)
    if rc != 4:
        fails.append(f"{label}: not rejected with EXIT_IR(4) (got {rc})")
    if os.path.isfile(os.path.join(out, "procedure.sql")):
        fails.append(f"{label}: SQL emitted despite the ill-typed/undeclared guard")
    if "expr.type" not in diag:
        fails.append(f"{label}: should be expr.type")
    return p


# (g) ill-typed ingested guard (money >= string) -> expr.type, no SQL.
def _illtype(e):
    e["when"]["ast"]["lhs"] = {"kind": "var", "name": "amount", "dtype": "money"}
    e["when"]["ast"]["rhs"] = {"kind": "var", "name": "currency", "dtype": "string"}


ingest_reject(_illtype, "ill", "ill-typed ingested guard")

# (h) undeclared guard var -> expr.type, no SQL; and the spec validator rejects it too.
ghost = ingest_reject(lambda e: e["when"]["ast"].__setitem__("lhs", {"kind": "var", "name": "ghost", "dtype": "money"}),
                      "gh", "undeclared guard var")
if subprocess.run([sys.executable, os.path.join(REPO, "scripts", "validators", "validate_capability_spec.py"), ghost],
                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
    fails.append("spec validator accepted an undeclared guard var")

# (i) scenario-aware events + conditional versioning. TRUE branch (committed): fired release event
# present; guarded spec is schemaVersion 2.
if not has(os.path.join(GEN_DIR, "test-realization", "test-realization.json"), "EscrowReleaseDebited"):
    fails.append("true-branch realization is missing the fired release event")
if d["schemaVersion"] != 2:
    fails.append("a guarded spec must be schemaVersion 2 (conditional versioning)")

# FALSE branch (amount < agreed): the release is suppressed — no release events; only 2 base legs post.
nr = os.path.join(tmp, "nr.json")
open(nr, "w").write(json.dumps({
    "scenario": "ce_norelease", "procedure": "core_document_escrow",
    "inputs": {"escrow_id": "esc-002", "buyer_id": "buyer-001", "agent_id": "agent-001",
               "seller_id": "seller-001", "amount": 5000, "agreed_amount": 6000, "currency": "EUR"},
    "expect": {"computed": {}, "ledger": {"buyer.escrow": -5000, "escrow.holding": 5000},
               "invariants": ["replay_safe", "balanced"]}}))
rc, nrout, _ = gen(["--target=test-realization", "--scenario=" + nr, CE_SRC], "nr")
if rc != 0:
    fails.append("false-branch test-realization emit failed")
elif has(os.path.join(nrout, "test-realization.json"), "EscrowReleaseDebited"):
    fails.append("false branch still emits the suppressed release event")
_, nrpg, _ = gen(["--target=postgres", "--scenario=" + nr, CE_SRC], "nrpg")
if not has(os.path.join(nrpg, "run_db_test.sh"), '[ "$N" = "2" ]'):
    fails.append("false-branch harness count should be 2 (release suppressed)")

if fails:
    print("[92] conditional-guards contract FAILED:", file=sys.stderr)
    for f in fails:
        print("    FAIL: " + f, file=sys.stderr)
    sys.exit(1)
print("[92] OK: guard lowers to SQL IF + Solidity if with a guard-aware harness count; predicate ONLY in "
      "a guard — comparison-in-compute / non-comparison / non-numeric / ill-typed / undeclared-var all "
      "fail closed with no SQL; scenario-aware events + guard-aware count on BOTH branches; guarded spec "
      "is schemaVersion 2")

"""[21] participants: declared participants flow source -> IR -> capability; coverage L3 -> full. Ported
verbatim from the retired run_cpp_tests.sh [21] block ( S5n). Declared participants reach the IR
(neutrino.participant) and the slot capability (declaredParticipants + role); coverage L3 is full and, with
org boundaries, the topology is cross-organization with L8 partial; an unknown participant field and a
duplicate explicit participant are rejected; a to_be_bound binding policy is emitted into the capability
(and stays off fixed participants) with a bind_min_assurance>A1 trustBoundary ADVISORY (ok stays true);
and malformed binding policies (bind_* without to_be_bound / to_be_bound without runtimes / no org /
empty runtime) are rejected at the frontend AND at the IR verifier (which the parser can be bypassed to).

Usage: check_participants.py <neutrino-gen> <neutrino-translate> <neutrino-opt> <src.neu> <scenario.json>
"""
import json
import os
import re
import subprocess
import sys
import tempfile

GEN, TRANSLATE, OPT, SRC, SCEN = sys.argv[1:6]
fails = []
tmp = tempfile.mkdtemp(prefix="part21.")


def write(name, content):
    p = os.path.join(tmp, name)
    open(p, "w").write(content)
    return p


def rejects(cmd):
    return subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0


def gen(target, src, sub, scenario=SCEN):
    out = os.path.join(tmp, sub)
    rc = subprocess.run([GEN, "--target=" + target, "--scenario=" + scenario, src, "-o", out],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode
    return rc, out


# synthesize a participant source: two participant blocks after the trigger, and bind the first two legs.
src = open(SRC).read()
parts = ('    participant Merchant {\n        role = "seller"\n'
         '        capabilities = ["accept_funds"]\n        org = "acme"\n    }\n'
         '    participant Issuer {\n        role = "financier"\n        org = "bankco"\n    }\n')
src = re.sub(r'(\n[ \t]*trigger[^\n]*\n)', r'\1' + parts, src, count=1)
n = [0]


def bind(m):
    n[0] += 1
    return m.group(0) + '        participant     = "%s"\n' % ("Merchant" if n[0] == 1 else "Issuer")


src = re.sub(r'[ \t]*owner[ \t]*=[^\n]*\n', bind, src, count=2)
p_neu = write("p.neu", src)

p_mlir = os.path.join(tmp, "p.mlir")
if rejects([TRANSLATE, p_neu, "-o", p_mlir]):
    fails.append("participant source did not translate")
elif "neutrino.participant" not in open(p_mlir).read():
    fails.append("participant op missing from IR")

rc, pslot = gen("slot", p_neu, "pslot")
cap = open(os.path.join(pslot, "capability.json")).read() if rc == 0 else ""
if rc != 0:
    fails.append("slot gen on participant source")
else:
    if '"declaredParticipants"' not in cap:
        fails.append("declaredParticipants missing from slot capability")
    if '"role": "seller"' not in cap:
        fails.append("participant role missing")
    if '"crossOrganization": true' not in cap:
        fails.append("cross-organization topology not declared")

rc, pcov = gen("coverage", p_neu, "pcov")
covtext = open(os.path.join(pcov, "coverage.json")).read() if rc == 0 else ""
if rc != 0:
    fails.append("coverage gen on participant source")
else:
    # L3 present:true and L8 present:"partial" (crude adjacency check, as the shell's grep -A2 did).
    if not re.search(r'"level": "L3".{0,80}?"present": true', covtext, re.S):
        fails.append("L3 not full when participants declared")
    if not re.search(r'"level": "L8".{0,80}?"present": "partial"', covtext, re.S):
        fails.append("L8 abstract topology not partial across orgs")

# unknown participant field rejected.
if not rejects([TRANSLATE, write("pneg.neu", 'procedure p {\n    participant X {\n        bogus = "y"\n    }\n}\n'),
                "-o", os.devnull]):
    fails.append("unknown participant field was accepted")

# duplicate explicit participant rejected.
pdup = 'procedure p {\n    trigger t\n    participant A {\n        role = "r"\n    }\n    participant A {\n        role = "q"\n    }\n}\n'
if not rejects([TRANSLATE, write("pdup.neu", pdup), "-o", os.devnull]):
    fails.append("duplicate explicit participant was accepted")

# late-binding policy: emitted into capability, off fixed participants; advisory when assurance>A1.
flexbind = write("flexbind.neu", """procedure flexbind {
    trigger t
    participant Sponsor {
        role          = "sponsor"
        org           = "sponsorco"
        binding       = "to_be_bound"
        bind_runtimes = ["evm", "jvm"]
        bind_min_assurance = "A2"
    }
    participant Merchant {
        role = "merchant"
        org  = "acme"
    }
    input wkey : string
    input p1 : party
    input amt : money
    input cur : currency
    debit d1 {
        ledger          = "a.out"
        owner           = "acme"
        participant     = "Merchant"
        party           = %p1
        amount          = %amt
        currency        = %cur
        idempotency_key = %wkey
    }
    credit c1 {
        ledger          = "b.in"
        owner           = "sponsorco"
        participant     = "Sponsor"
        party           = %p1
        amount          = %amt
        currency        = %cur
        idempotency_key = %wkey
    }
    assert balanced
}
""")
flexbind_json = write("flexbind.json",
                      '{ "scenario": "fb", "procedure": "flexbind", "inputs": '
                      '{ "wkey": "w-1", "p1": "p-1", "amt": 100, "cur": "EUR" } }\n')
rc, flexslot = gen("slot", flexbind, "flexslot", scenario=flexbind_json)
if rc != 0:
    fails.append("flexible-binding source did not generate")
else:
    d = json.load(open(os.path.join(flexslot, "capability.json")))
    s = [p for p in d["declaredParticipants"] if p["name"] == "Sponsor"][0]
    m = [p for p in d["declaredParticipants"] if p["name"] == "Merchant"][0]
    if not (s.get("binding", {}).get("mode") == "to_be_bound" and s["binding"]["runtimes"] == ["evm", "jvm"]
            and s["binding"]["minAssurance"] == "A2" and s["binding"].get("authorizedBinder") == "sponsorco"
            and "binding" not in m):
        fails.append("binding policy not emitted correctly (or leaked onto a fixed participant)")

rc, flexsec = gen("security", flexbind, "flexsec", scenario=flexbind_json)
if rc != 0:
    fails.append("security gen on flexible binding exited non-zero")
else:
    d = json.load(open(os.path.join(flexsec, "security.json")))
    tb = [c for c in d["categories"] if c["category"] == "trustBoundary"][0]
    adv = [f for f in tb["findings"] if "requires assurance A2" in f]
    if not (d["ok"] is True and tb["status"] == "advisory" and adv):
        fails.append("bind_min_assurance>A1 did not produce a trustBoundary advisory (ok must stay true)")

# malformed binding policies rejected at the frontend.
for name, body in [
    ("flexbad1", 'procedure t {\n  trigger x\n  participant P {\n    role = "r"\n    bind_min_assurance = "A2"\n  }\n}\n'),
    ("flexbad2", 'procedure t {\n  trigger x\n  participant P {\n    role = "r"\n    binding = "to_be_bound"\n  }\n}\n'),
    ("flexbad3", 'procedure t {\n  trigger x\n  participant P {\n    role = "r"\n    binding = "to_be_bound"\n    bind_runtimes = ["evm"]\n  }\n}\n'),
    ("flexbad4", 'procedure t {\n  trigger x\n  participant P {\n    role = "r"\n    org = "o"\n    binding = "to_be_bound"\n    bind_runtimes = ["evm", ""]\n  }\n}\n'),
]:
    if not rejects([TRANSLATE, write(name + ".neu", body), "-o", os.devnull]):
        fails.append(f"{name}: malformed binding policy accepted at the frontend")

# the IR verifier enforces the same invariants for direct .mlir input (parser is bypassable).
bypass_noorg = write("bypass_noorg.mlir",
                     '"neutrino.procedure"() ({\n  "neutrino.participant"() {sym_name = "S", role = "s", '
                     'binding = "to_be_bound", bind_runtimes = ["evm"]} : () -> ()\n}) '
                     '{sym_name = "p", trigger = "t"} : () -> ()\n')
if not rejects([OPT, bypass_noorg]):
    fails.append("IR verifier passed a to_be_bound participant with no org")
bypass_empty = write("bypass_empty.mlir",
                     '"neutrino.procedure"() ({\n  "neutrino.participant"() {sym_name = "S", role = "s", '
                     'org = "o", binding = "to_be_bound", bind_runtimes = [""]} : () -> ()\n}) '
                     '{sym_name = "p", trigger = "t"} : () -> ()\n')
if not rejects([OPT, bypass_empty]):
    fails.append("IR verifier passed an empty bind_runtimes entry")

if fails:
    print("[21] participants contract FAILED:", file=sys.stderr)
    for f in fails:
        print("    FAIL: " + f, file=sys.stderr)
    sys.exit(1)
print("[21] OK: participants -> IR/capability; L3 full; org boundaries -> cross-org topology + L8 partial; "
      "bad field + duplicate participant rejected; binding policy emitted + validated; unconstrained "
      "binder + empty runtime rejected at frontend AND IR verifier")

"""[39] D2: sponsored-finance dialect expansion (Upper-Layer path; no parser syntax). Ported verbatim
from the retired run_cpp_tests.sh [39] block ( S5k). Expanding the reviewed dialect template yields
a byte-stable .neu (accepted by the existing translator + verifier — no new syntax) and an expansion
manifest that pins dialect+source hashes and traces every construct to a real mapping edge; the declared
participants flow through to a D1b binding-topology whose org->participant->slot grouping matches the
manifest's prediction; and a tampered dialect, a hash-valid source-injecting dialect, and a
non-identifier --trigger are all refused (the grammar gate is independent of the hash pin).

Usage: check_dialect_expansion.py <expand_dialect.py> <neutrino-translate> <neutrino-opt> <neutrino-gen> <examples-dir>
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile

EXP, TRANSLATE, OPT, GEN, EXAMPLES = sys.argv[1:6]
fails = []
tmp = tempfile.mkdtemp(prefix="exp39.")
DIALECT = os.path.join(EXAMPLES, "domain-dialects", "sponsored_finance.dialect.json")
GOLD = os.path.join(EXAMPLES, "domain-dialects", "expansions")
SOA_SCEN = os.path.join(EXAMPLES, "domains", "core_sponsored_offer", "scenario",
                        "core_sponsored_offer_happy_path.json")


def run(cmd):
    return subprocess.run([str(c) for c in cmd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def expand(dialect, trigger, out_neu, out_manifest):
    return run([sys.executable, EXP, "--dialect", dialect, "--template", "core_sponsored_offer",
                "--trigger", trigger, "--out-neu", out_neu, "--out-manifest", out_manifest]).returncode


neu = os.path.join(tmp, "core_sponsored_offer.neu")
man = os.path.join(tmp, "core_sponsored_offer.expansion.json")
if expand(DIALECT, "sponsored_offer_proposed", neu, man) != 0:
    fails.append("expansion command failed")
else:
    if open(neu, "rb").read() != open(os.path.join(GOLD, "core_sponsored_offer.neu"), "rb").read():
        fails.append("generated .neu drifted from golden")
    if open(man, "rb").read() != open(os.path.join(GOLD, "core_sponsored_offer.expansion.json"), "rb").read():
        fails.append("expansion manifest drifted from golden")
    if run([TRANSLATE, neu, "-o", os.path.join(tmp, "exp.mlir")]).returncode != 0:
        fails.append("generated .neu not accepted by neutrino-translate")
    elif run([OPT, os.path.join(tmp, "exp.mlir")]).returncode != 0:
        fails.append("generated IR did not verify (balanced)")

    # manifest traceability + pinning invariants (every construct -> >=1 real edge).
    m = json.load(open(man))
    d = json.load(open(DIALECT))
    edge_ids = {e["id"] for e in d["mappingGraph"]["edges"]}
    inv = (m["kind"] == "neutrino.dialect-expansion-manifest" and m["schemaVersion"] == 1
           and m["dialect"]["domainDialectHash"] == d["domainDialectHash"]
           and m["generated"]["sourceHash"] == hashlib.sha256(open(neu, "rb").read()).hexdigest()
           and set(m["edgesUsed"]) <= edge_ids
           and all(c["edges"] and set(c["edges"]) <= set(m["edgesUsed"]) for c in m["constructs"])
           and all(lp["edge"] in edge_ids for lp in m["lowerProvenance"])
           and m["grouping"]
           and all(g["termEdges"] and set(g["termEdges"]) <= set(m["edgesUsed"]) for g in m["grouping"]))
    if not inv:
        fails.append("expansion manifest invariants")

    # D2 -> D1b tie: the generated participants flow through to a binding-topology whose grouping
    # matches the manifest's predicted org->participant->slot grouping.
    exp_slot = os.path.join(tmp, "exp_slot")
    if run([GEN, "--target=slot", "--scenario=" + SOA_SCEN, neu, "-o", exp_slot]).returncode != 0:
        fails.append("gen slot on the generated .neu failed")
    elif not os.path.exists(os.path.join(exp_slot, "binding-topology.json")):
        fails.append("generated .neu did not produce binding-topology.json")
    else:
        bt = json.load(open(os.path.join(exp_slot, "binding-topology.json")))
        mg = {(g["organizationId"], g["participantId"], g["slotId"]) for g in m["grouping"]}
        btg = {(o["organizationId"], p["participantId"], s["slotId"])
               for o in bt["organizations"] for p in o["participants"] for s in p["slots"]}
        if not (mg and mg == btg):
            fails.append("manifest grouping != compiler binding-topology")

# fail closed: a tampered dialect (hash no longer matches) must not expand.
bad = os.path.join(tmp, "bad_dialect.json")
d = json.load(open(DIALECT))
d["domain"] = "evil"
json.dump(d, open(bad, "w"))
if expand(bad, "t", os.path.join(tmp, "x.neu"), os.path.join(tmp, "x.json")) == 0:
    fails.append("expander accepted a tampered (hash-mismatched) dialect")

# anti-injection: a hash-VALID dialect with a newline in an input name must STILL be refused (the
# grammar gate is independent of the hash pin).
inj = os.path.join(tmp, "inject_dialect.json")
d = json.load(open(DIALECT))
d["templates"]["core_sponsored_offer"]["requiredInputs"]["evil\n    input injected : party"] = "party"
body = {k: v for k, v in d.items() if k != "domainDialectHash"}
d["domainDialectHash"] = hashlib.sha256(
    json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
json.dump(d, open(inj, "w"))
if expand(inj, "sponsored_offer_proposed", os.path.join(tmp, "inj.neu"), os.path.join(tmp, "inj.json")) == 0:
    fails.append("expander emitted source for an injected (hash-valid) dialect")

# a CLI --trigger that is not a bare identifier is refused.
if expand(DIALECT, "t input evil", os.path.join(tmp, "c.neu"), os.path.join(tmp, "c.json")) == 0:
    fails.append("expander accepted a non-identifier --trigger")

if fails:
    print("[39] dialect-expansion contract FAILED:", file=sys.stderr)
    for f in fails:
        print("    FAIL: " + f, file=sys.stderr)
    sys.exit(1)
print("[39] OK: template -> byte-stable .neu accepted by the translator + verifier; declares "
      "participants that flow through to a D1b binding-topology with the manifest's predicted grouping; "
      "manifest pins dialect+source hashes and traces every construct to a real edge; tampered dialect / "
      "hash-valid injection / non-identifier trigger all refused")

"""[40] D3: domain-origin diagnostics. Ported verbatim from the retired run_cpp_tests.sh [40] block
( S5k). Each construct's sourceSpan actually begins that construct in the generated .neu; a
stale/mismatched sidecar (generated.sourceHash no longer matching) does NOT attach a domain origin,
while a genuinely matching manifest maps a core .neu error back to its domain term/template/dialect-hash;
a valid source invents no diagnostics; and the capabilityHash is presentation-independent (stripping the
.neu header comments does not change it — trust stays on core semantics, not labels).

Usage: check_domain_origin.py <domain_diagnostics.py> <neutrino-translate> <neutrino-gen> <examples-dir>
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile

DD, TRANSLATE, GEN, EXAMPLES = sys.argv[1:5]
fails = []
tmp = tempfile.mkdtemp(prefix="d3_40.")
G = os.path.join(EXAMPLES, "domain-dialects", "expansions")
NEU = os.path.join(G, "core_sponsored_offer.neu")
MAN = os.path.join(G, "core_sponsored_offer.expansion.json")
SOA_SCEN = os.path.join(EXAMPLES, "domains", "core_sponsored_offer", "scenario",
                        "core_sponsored_offer_happy_path.json")


def diag(neu, manifest, out):
    with open(out, "w") as f:
        subprocess.run([sys.executable, DD, "--neu", neu, "--manifest", manifest, "--translate", TRANSLATE],
                       stdout=f, stderr=subprocess.DEVNULL)
    return json.load(open(out))


# 1. each construct's sourceSpan actually begins that construct in the generated .neu.
neu_lines = open(NEU).read().splitlines()
m = json.load(open(MAN))
if not all("sourceSpan" in c
           and 1 <= c["sourceSpan"]["startLine"] <= c["sourceSpan"]["endLine"] <= len(neu_lines)
           and neu_lines[c["sourceSpan"]["startLine"] - 1].strip().startswith(c["construct"].split()[0])
           for c in m["constructs"]):
    fails.append("sourceSpan does not match the generated .neu")

# break the sponsor leg (drop its idempotency_key -> missing-field at the leg).
broken = os.path.join(tmp, "d3_broken.neu")
out, dropped = [], False
for line in neu_lines:
    if not dropped and line.strip().startswith("idempotency_key"):
        dropped = True
        continue
    out.append(line)
open(broken, "w").write("\n".join(out) + "\n")

# 2a. a stale/mismatched sidecar (broken .neu vs the ORIGINAL manifest) must NOT attach a domain origin.
d = diag(broken, MAN, os.path.join(tmp, "d3_stale.json"))
if not (d["sourceMatches"] is False and d["mappedCount"] == 0
        and all("domainOrigin" not in g for g in d["diagnostics"])):
    fails.append("mismatched manifest still attached a domain origin")

# 2b. a manifest that genuinely describes the source maps the same core error to its domain origin.
man_match = os.path.join(tmp, "d3_man_match.json")
mm = json.load(open(MAN))
mm["generated"]["sourceHash"] = hashlib.sha256(open(broken, "rb").read()).hexdigest()
json.dump(mm, open(man_match, "w"))
d = diag(broken, man_match, os.path.join(tmp, "d3_diag.json"))
g = d["diagnostics"][0]
o = g.get("domainOrigin", {})
if not (d["kind"] == "neutrino.domain-diagnostics" and d["ok"] is False and d["sourceMatches"] is True
        and d["mappedCount"] >= 1 and o.get("construct") == "debit sponsor_commitment"
        and o.get("participantTerm") == "sponsor"
        and o["dialect"]["domainDialectHash"] == d["dialect"]["domainDialectHash"]
        and "edge:sponsor-term-001" in o.get("edges", [])):
    fails.append("matching manifest did not annotate the diagnostic with its domain origin")

# 3. a valid generated .neu -> ok, no diagnostics, nothing mapped (no invented errors).
d = diag(NEU, MAN, os.path.join(tmp, "d3_ok.json"))
if not (d["ok"] and d["diagnostics"] == [] and d["mappedCount"] == 0):
    fails.append("valid .neu produced diagnostics")

# 4. capabilityHash is presentation-independent: stripping the .neu header comments must not change it.
s1 = os.path.join(tmp, "d3_s1")
if subprocess.run([GEN, "--target=slot", "--scenario=" + SOA_SCEN, NEU, "-o", s1],
                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0:
    fails.append("gen slot on generated .neu failed")
nocomment = os.path.join(tmp, "d3_nocomment.neu")
open(nocomment, "w").write("\n".join(neu_lines[3:]) + "\n")
s2 = os.path.join(tmp, "d3_s2")
if subprocess.run([GEN, "--target=slot", "--scenario=" + SOA_SCEN, nocomment, "-o", s2],
                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0:
    fails.append("gen slot on comment-stripped .neu failed")
try:
    h1 = json.load(open(os.path.join(s1, "capability.lock")))["capabilityHash"]
    h2 = json.load(open(os.path.join(s2, "capability.lock")))["capabilityHash"]
    if h1 != h2:
        fails.append(f"capabilityHash changed when .neu comments changed ({h1} != {h2})")
except (OSError, KeyError):
    fails.append("could not read capability.lock for the presentation-independence check")

if fails:
    print("[40] domain-origin contract FAILED:", file=sys.stderr)
    for f in fails:
        print("    FAIL: " + f, file=sys.stderr)
    sys.exit(1)
print("[40] OK: sourceSpan matches the .neu; a stale/mismatched manifest is fail-closed via "
      "generated.sourceHash (no origin attached); a matching manifest annotates the leg error with its "
      "domain term/template/dialect-hash; valid source invents no diagnostics; capabilityHash is "
      "independent of .neu presentation comments")

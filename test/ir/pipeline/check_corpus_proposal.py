"""[75c] M5 S2 (): corpus-to-proposal generator — deterministic vocabulary-proposal from the S1
observation-set. Ported verbatim from the retired run_cpp_tests.sh [75c] block ( S5n). The generated
form is a PROPOSAL (untrusted, status/reviewStatus 'proposed'), validated by validate_domain_proposal.py
--corpus, not an accepted domain-dialect; the committed proposal regenerates byte-identically, validates,
and re-verifies the committed corpus binding by default (--check); the fail-closed teeth are pinned by the
generator self-test; and confidence is graded by the S1 code-vs-editorial split (high=code/derived,
medium=editorial), asserted directly.

Usage: check_corpus_proposal.py <examples-dir>
"""
import json
import os
import subprocess
import sys

EXAMPLES = sys.argv[1]
REPO = os.path.dirname(os.path.abspath(EXAMPLES))
fails = []
CORPUS = os.path.join(REPO, "scripts", "corpus")


def run(*args):
    return subprocess.run([sys.executable, *args], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode


# the committed proposal regenerates byte-identically, validates as Stage-3, re-verifies its corpus.
if run(os.path.join(CORPUS, "generate_proposal_from_observations.py"),
       "--observations", os.path.join(EXAMPLES, "domain-proposals", "solidity_samples.observation-set.json"),
       "--corpus", os.path.join(EXAMPLES, "domain-proposals", "solidity_samples.corpus.json"), "--check") != 0:
    fails.append("committed proposal stale or does not validate as Stage-3")

# the generator's fail-closed teeth (invalid observations / unknown dimension / corpus mismatch /
# non-authority source / anti-rebind content-hash).
if run(os.path.join(CORPUS, "generate_proposal_selftest.py")) != 0:
    fails.append("proposal generator fail-closed self-test")

# confidence wired from the code-vs-editorial split.
p = json.load(open(os.path.join(EXAMPLES, "domain-proposals", "solidity_samples.proposal.json")))
CODE = {"timeBound", "orderingModel", "oracleDependency", "evidenceStyle", "expressibility"}
EDIT = {"partyModel", "accessControl", "identityBinding", "characteristics"}
try:
    assert p["kind"] == "neutrino.domain-vocabulary-proposal" and p["status"] == "proposed", "must be a proposed proposal"
    for t in p["candidateTerms"]:
        dim = t["term"].split(":", 1)[0]
        assert t["reviewStatus"] == "proposed", ("term not proposed", t["term"])
        want = "high" if dim in CODE else "medium" if dim in EDIT else None
        assert want is not None, ("unclassified dimension leaked into a term", dim)
        assert t["confidence"] == want, (t["term"], t["confidence"], "expected", want)
    for e in p.get("candidateEdges", []):
        assert e["provenance"]["status"] == "proposed", ("edge not proposed", e["id"])
except AssertionError as ex:
    fails.append(f"proposal confidence not wired to the code-vs-editorial split: {ex}")

if fails:
    print("[75c] corpus-proposal contract FAILED:", file=sys.stderr)
    for f in fails:
        print("    FAIL: " + f, file=sys.stderr)
    sys.exit(1)
print("[75c] OK: deterministic proposer's output validates as a Stage-3 vocabulary-proposal via its "
      "owning validator + corpus; confidence high=code/derived, medium=editorial; status/reviewStatus/"
      "edge-status all proposed; fail-closed teeth pinned by the self-test")

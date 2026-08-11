"""[36] D1a: proposal-only dataset-analysis artifacts validate fail-closed. Ported verbatim from the
retired run_cpp_tests.sh [36] block ( S5k). The three ISO 20022 interbank artifacts (corpus / run /
proposal) validate, with the proposal cross-checked against its corpus authority; citation authority is
fail-closed (no --corpus -> unverifiable), the supplied corpus must be the proposal's own, and eight
schema/authority negatives each fail closed with their specific code.

Usage: check_domain_proposal.py <validate_domain_proposal.py> <domain-proposals-dir>
"""
import os
import subprocess
import sys
import tempfile

DP, DPEX = sys.argv[1:3]
fails = []
tmp = tempfile.mkdtemp(prefix="dp36.")
NEG = os.path.join(DPEX, "negatives")


def validate(artifact, out, corpus=None):
    cmd = [sys.executable, DP, "--artifact", artifact]
    if corpus:
        cmd += ["--corpus", corpus]
    cmd += ["--out", out]
    r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return r.returncode


def diags(out):
    return open(os.path.join(out, "diagnostics.json")).read()


# positives: corpus, analysis-run, and the proposal (cross-checked vs corpus) validate.
if validate(os.path.join(DPEX, "iso20022_interbank.corpus.json"), os.path.join(tmp, "dp_corpus")) != 0:
    fails.append("corpus manifest did not validate")
if validate(os.path.join(DPEX, "iso20022_interbank.run.json"), os.path.join(tmp, "dp_run")) != 0:
    fails.append("analysis-run manifest did not validate")
if validate(os.path.join(DPEX, "iso20022_interbank.proposal.json"), os.path.join(tmp, "dp_prop"),
            corpus=os.path.join(DPEX, "iso20022_interbank.corpus.json")) != 0:
    fails.append("vocabulary proposal did not validate")

# authority is fail-closed: the SAME proposal WITHOUT --corpus must NOT pass.
nocorp = os.path.join(tmp, "dp_nocorp")
rc = validate(os.path.join(DPEX, "iso20022_interbank.proposal.json"), nocorp)
if rc != 1:
    fails.append(f"proposal validated (exit={rc}) with no --corpus (authority fail-open)")
elif '"proposal.authority_unverifiable"' not in diags(nocorp):
    fails.append("missing proposal.authority_unverifiable when --corpus omitted")

# the supplied corpus must be the proposal's own.
mism = os.path.join(tmp, "dp_mism")
rc = validate(os.path.join(DPEX, "iso20022_interbank.proposal.json"), mism,
              corpus=os.path.join(NEG, "reference_only.corpus.json"))
if rc != 1:
    fails.append(f"mismatched corpus accepted (exit={rc})")
elif '"proposal.corpus_mismatch"' not in diags(mism):
    fails.append("mismatched corpus did not raise proposal.corpus_mismatch")

# negatives: each fails closed (exit 1) with its specific diagnostic code.
for artifact, code, corpus in [
    ("unknown_field.proposal.json", "proposal.schema", None),
    ("claims_accepted.proposal.json", "proposal.schema", None),
    ("uncited_term.proposal.json", "proposal.schema", None),
    ("decompiled_unreviewed.corpus.json", "corpus.decompiled_unreviewed", None),
    ("authority_not_permitted.corpus.json", "corpus.authority_not_permitted", None),
    ("cites_nonauthority.proposal.json", "proposal.source_authority", "reference_only.corpus.json"),
    ("unknown_source.proposal.json", "proposal.unknown_source", "reference_only.corpus.json"),
    ("edge_nonauthority.proposal.json", "proposal.unknown_source", "edge_authority.corpus.json"),
]:
    out = os.path.join(tmp, "dp_neg")
    c = os.path.join(NEG, corpus) if corpus else None
    rc = validate(os.path.join(NEG, artifact), out, corpus=c)
    if rc != 1:
        fails.append(f"{artifact} exit={rc} (want 1)")
    elif ('"' + code + '"') not in diags(out):
        fails.append(f"{artifact} missing diagnostic {code}")

if fails:
    print("[36] domain-proposal contract FAILED:", file=sys.stderr)
    for f in fails:
        print("    FAIL: " + f, file=sys.stderr)
    sys.exit(1)
print("[36] OK: corpus/run/proposal validate; missing-corpus / corpus-mismatch / unknown-field / "
      "claims-accepted / uncited / decompiled-unreviewed / non-public-authority / term+edge "
      "unknown-source / non-authority all fail closed")

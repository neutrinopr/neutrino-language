#!/usr/bin/env python3
"""M5 S2 () — deterministic corpus-to-proposal generator.

Consumes an S1 `neutrino.domain-observation-set` (the frozen S0 contract, ) and emits a
`neutrino.domain-vocabulary-proposal` ( Stage 3): the **reviewable, untrusted** scaffold
toward a domain dialect. In the frozen four-stage model (docs/domains/DOMAIN_DATASET_EXTRACTION.md) the
*generated* form is a PROPOSAL — `status`/`reviewStatus`/edge-status all `proposed` — which a human
reviews and PROMOTES into an accepted `neutrino.domain-dialect` (Stage 4). It is therefore validated
by `scripts/corpus/validate_domain_proposal.py`, NOT `validate_domain_dialect.py`: emitting an accepted
dialect for machine-derived, unreviewed vocabulary would violate the trust boundary. See the
"Promotion path" section of docs/domains/DOMAIN_DATASET_EXTRACTION.md.

The translator never calls an LLM; this is a DETERMINISTIC proposer. `confidence` is wired from S1's
code-signal-vs-editorial split, not a model score:

  - `high`   — dimensions independently DETECTED from source (`timeBound`, `orderingModel`,
               `oracleDependency`, `evidenceStyle`) and the `expressibility` derived from them;
  - `medium` — coordination-semantic dimensions RE-PROJECTED from the reviewed classification.json
               labels (`partyModel`, `accessControl`, `identityBinding`, `characteristics`), which
               rest on the human labels' correctness rather than independent code verification.

Fail-closed: an observation-set that is not S0-valid, an unknown/unclassifiable dimension, a
corpusRef mismatch against the governing corpus manifest, a cited source that is not a
domain-authority corpus source, or (with `--corpus-dir`) an anti-rebind content-hash mismatch all
fail closed. The emitted proposal is not auto-wired into the compiler build.

  generate_proposal_from_observations.py --observations FILE --corpus FILE [--corpus-dir DIR]
                                         [--out FILE] [--emit] [--check]

Exit 0 ok / 1 violations / 2 usage.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys

# moved to scripts/corpus/ (): repo root is three dirs up (corpus -> scripts -> repo)
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # corpus/ siblings
import validate_domain_observation_set as VOBS  # noqa: E402  (repo-local stdlib validator)

DEFAULT_OUT = os.path.join(REPO, "examples", "domain-proposals", "solidity_samples.proposal.json")
PROPOSAL_VALIDATOR = os.path.join(REPO, "scripts", "corpus", "validate_domain_proposal.py")
# The committed corpus snapshot the emit/check path re-verifies against BY DEFAULT — so the
# anti-rebind binding is enforced at the point of use, not a flag away from being skipped (
# review). Overridable with --corpus-dir; skippable only via the explicit --allow-unverified opt-out
# that CI never passes.
DEFAULT_CORPUS_DIR = os.path.join(REPO, "examples", "domain-proposals", "solidity-samples-corpus")

DOMAIN = "solidity_coordination"
PROPOSAL_VERSION = "0.1.0"

# S1's code-signal-vs-editorial split -> proposal confidence (deterministic, not a model score).
CODE_DIMENSIONS = {"timeBound", "orderingModel", "oracleDependency", "evidenceStyle"}
DERIVED_DIMENSIONS = {"expressibility"}          # derived from the detected dimensions -> high
EDITORIAL_DIMENSIONS = {"partyModel", "accessControl", "identityBinding", "characteristics"}
KNOWN_DIMENSIONS = CODE_DIMENSIONS | DERIVED_DIMENSIONS | EDITORIAL_DIMENSIONS


def diag(code: str, message: str, severity: str = "error") -> dict:
    return {"code": code, "severity": severity, "message": message}


def _confidence(dimension: str) -> str:
    return "high" if dimension in (CODE_DIMENSIONS | DERIVED_DIMENSIONS) else "medium"


def corpus_content_hash(corpus_dir: str) -> str:
    """Recompute the S1 aggregate corpus content hash (same algorithm as the extractor): sha256 over
    the sorted (repo-relative 'src/<file>', bytes) of every .sol, null-delimited. Raises
    FileNotFoundError if the corpus dir has no src/ (surfaced as a fatal proposal.corpus_unavailable)."""
    src_dir = os.path.join(corpus_dir, "src")
    if not os.path.isdir(src_dir):
        raise FileNotFoundError(src_dir)
    files = sorted(f for f in os.listdir(src_dir) if f.endswith(".sol"))
    h = hashlib.sha256()
    for f in files:
        rel = f"src/{f}"
        h.update(rel.encode("utf-8") + b"\0")
        with open(os.path.join(src_dir, f), "rb") as fh:
            h.update(fh.read())
        h.update(b"\0")
    return "sha256:" + h.hexdigest()


def build(observations: dict, corpus: dict, corpus_dir: str | None):
    """Return (proposal, diagnostics). Fails closed on invalid observations, an unknown dimension,
    a corpusRef mismatch, or an anti-rebind hash mismatch (when the corpus is provided)."""
    out: list = []

    # 1. the input must be a valid S0 observation-set (verify, don't trust the upstream stage).
    obs_errors = [d for d in VOBS.validate(observations) if d.get("severity") == "error"]
    if obs_errors:
        out.append(diag("proposal.invalid_observations",
                        f"input observation-set is not S0-valid ({len(obs_errors)} error(s)); refusing to generate"))
        return None, out

    corpus_id = observations.get("corpusRef", {}).get("corpusId")
    corpus_hash = observations.get("corpusRef", {}).get("contentHash")

    # 2. corpusRef must match the governing corpus manifest (the proposal binds to that corpus).
    if corpus_id != corpus.get("corpusId"):
        out.append(diag("proposal.corpus_mismatch",
                        f"observation corpusId {corpus_id!r} != corpus-manifest corpusId {corpus.get('corpusId')!r}"))
    authority = {s["id"] for s in corpus.get("sources", []) if s.get("allowedUse") == "domain-authority"}

    # 3. anti-rebind re-verify (/ obligation): recompute the corpus content hash and FAIL
    #    CLOSED on mismatch. This is REQUIRED on the emit/check path — the caller defaults corpus_dir
    #    to the committed corpus snapshot, so the binding is enforced at the point of use, not
    #    skippable by omitting a flag ( review). corpus_dir is None only under the explicit
    #    --allow-unverified opt-out (which CI never uses), and is then a visible warning.
    if corpus_dir:
        try:
            recomputed = corpus_content_hash(corpus_dir)
        except (OSError, ValueError) as exc:
            out.append(diag("proposal.corpus_unavailable",
                            f"cannot re-verify corpusRef.contentHash: corpus dir {corpus_dir} unreadable ({exc}); "
                            f"refusing to generate without discharging the anti-rebind obligation"))
            return None, out
        if recomputed != corpus_hash:
            out.append(diag("proposal.corpus_rebind",
                            f"observation corpusRef.contentHash {corpus_hash} != recomputed {recomputed} over "
                            f"{corpus_dir} (anti-rebind: the set no longer matches the corpus it claims)"))
    else:
        out.append(diag("proposal.hash_unverified",
                        "corpusRef.contentHash NOT re-verified (--allow-unverified) — the anti-rebind binding is "
                        "not enforced; do not use this mode at a real point of use", severity="warning"))

    # 4. group observations by (dimension, value); fail closed on an unclassifiable dimension.
    by_dim_value: dict = {}
    for o in observations.get("observations", []):
        dim, val = o["dimension"], o["value"]
        if dim not in KNOWN_DIMENSIONS:
            out.append(diag("proposal.unknown_dimension",
                            f"dimension '{dim}' is not classifiable by this generator (fail closed)"))
            continue
        src = o["provenance"]["source"]
        by_dim_value.setdefault((dim, val), set()).add(src)
        if src not in authority:
            out.append(diag("proposal.non_authority_source",
                            f"observation source '{src}' ({dim}={val}) is not a domain-authority corpus source"))

    if [d for d in out if d["severity"] == "error"]:
        return None, out

    # 5. candidate terms — one per observed (dimension, value); confidence from the code/editorial
    #    split; cited to the source constructs; proposed (never accepted).
    candidate_terms = []
    m6_features = {}  # frontier feature note per m6-frontier contract, for extensionDataCandidates
    for (dim, val), srcs in sorted(by_dim_value.items()):
        term = {
            "term": f"{dim}:{val}",
            "layer": "L2",
            "confidence": _confidence(dim),
            "reviewStatus": "proposed",
            "citations": [{"source": s} for s in sorted(srcs)],
        }
        notes = []
        if dim in EDITORIAL_DIMENSIONS:
            notes.append("editorial label re-projected from classification.json — re-verify against "
                         "source before promotion")
        if dim == "expressibility" and val == "m5-expressible":
            term["mapsToCore"] = ["procedure"]
        if dim == "expressibility" and val == "m6-frontier":
            notes.append("M6 frontier — not expressible in the M5 kernel; do not promote to an "
                         "expandsTo template")
        if notes:
            term["unresolvedQuestions"] = notes
        candidate_terms.append(term)

    # 6. candidate edges — propose an expandsTo for each M5-expressible contract (evidence anchoring
    #    lowers to a core procedure). Derived from the detected expressibility; proposed only.
    candidate_edges = []
    for o in observations.get("observations", []):
        if o["dimension"] == "expressibility" and o["value"] == "m5-expressible":
            contract = o["provenance"]["construct"]
            src = o["provenance"]["source"]
            candidate_edges.append({
                "id": f"edge:m5-expand:{contract.lower()}",
                "type": "expandsTo",
                "from": f"concept:shape:{contract}",
                "to": "core:construct:procedure",
                "direction": "expand",
                "lossiness": "lossless",
                "provenance": {"source": src, "status": "proposed"},
            })
        elif o["dimension"] == "expressibility" and o["value"] == "m6-frontier":
            m6_features[o["provenance"]["construct"]] = o.get("note", "M6 frontier")

    # 7. extensionData candidates — name each M6-frontier shape's deferred semantics (scorecard input).
    extension_candidates = [
        {"field": f"m6_frontier:{c}", "reason": note}
        for c, note in sorted(m6_features.items())
    ]

    proposal = {
        "kind": "neutrino.domain-vocabulary-proposal",
        "domain": DOMAIN,
        "proposalVersion": PROPOSAL_VERSION,
        "status": "proposed",
        "corpusRef": corpus_id,
        "candidateTerms": sorted(candidate_terms, key=lambda t: t["term"]),
        "candidateEdges": sorted(candidate_edges, key=lambda e: e["id"]),
        "extensionDataCandidates": extension_candidates,
    }
    return proposal, out


def _dump(obj) -> str:
    return json.dumps(obj, indent=2, sort_keys=True) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate a neutrino.domain-vocabulary-proposal from an S1 observation-set")
    ap.add_argument("--observations", required=True, help="S1 neutrino.domain-observation-set JSON")
    ap.add_argument("--corpus", required=True, help="governing neutrino.domain-corpus-manifest JSON")
    ap.add_argument("--corpus-dir", help="corpus source dir (with src/*.sol) to re-verify the "
                    "content-hash binding against; defaults to the committed corpus snapshot")
    ap.add_argument("--allow-unverified", action="store_true",
                    help="opt out of the anti-rebind re-verify (NOT used by CI; leaves the binding unenforced)")
    ap.add_argument("--out", default=DEFAULT_OUT, help="output proposal path")
    ap.add_argument("--emit", action="store_true", help="write the proposal")
    ap.add_argument("--check", action="store_true", help="regenerate + assert committed proposal current + validate it")
    args = ap.parse_args()
    if not (args.emit or args.check):
        args.check = True
    # Enforced by default: re-verify against the committed corpus snapshot unless explicitly opted out.
    corpus_dir = None if args.allow_unverified else (args.corpus_dir or DEFAULT_CORPUS_DIR)

    try:
        observations = json.load(open(args.observations, encoding="utf-8"))
        corpus = json.load(open(args.corpus, encoding="utf-8"))
    except (OSError, ValueError) as exc:
        json.dump({"ok": False, "diagnostics": [diag("proposal.io", f"cannot read input: {exc}")]},
                  sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 1

    proposal, diagnostics = build(observations, corpus, corpus_dir)
    errors = [d for d in diagnostics if d["severity"] == "error"]
    rendered = _dump(proposal) if proposal is not None else None

    if args.emit and not errors and rendered is not None:
        os.makedirs(os.path.dirname(args.out), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(rendered)

    if args.check and not errors and rendered is not None:
        if not os.path.isfile(args.out):
            diagnostics.append(diag("proposal.not_committed",
                                    f"{os.path.relpath(args.out, REPO)} is missing — run --emit and commit it"))
        elif open(args.out, encoding="utf-8").read() != rendered:
            diagnostics.append(diag("proposal.drift",
                                    f"{os.path.relpath(args.out, REPO)} is stale — re-run --emit and commit"))
        else:
            # Verify, don't trust: the emitted proposal must pass its OWNING validator with the corpus.
            import tempfile
            with tempfile.TemporaryDirectory() as td:
                r = subprocess.run([sys.executable, PROPOSAL_VALIDATOR, "--artifact", args.out,
                                    "--corpus", args.corpus, "--out", td], capture_output=True, text=True)
                if r.returncode != 0:
                    diagnostics.append(diag("proposal.validation_failed",
                                            f"emitted proposal failed validate_domain_proposal.py (exit {r.returncode})"))

    errors = [d for d in diagnostics if d["severity"] == "error"]
    ok = not errors
    json.dump({"ok": ok,
               "candidateTerms": len(proposal["candidateTerms"]) if proposal else 0,
               "candidateEdges": len(proposal["candidateEdges"]) if proposal else 0,
               "diagnostics": sorted(diagnostics, key=lambda d: (d["code"], d["message"]))},
              sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

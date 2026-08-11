#!/usr/bin/env python3
"""M5 S2 () — fail-closed self-test for the corpus-to-proposal generator.

Proves the generator's teeth in-memory (no external corpus needed): the honest positive generates a
valid proposal, and every fail-closed path fires its specific `proposal.*` code — invalid input
observations, an unclassifiable dimension, a corpusRef mismatch, a non-authority citation source,
and (the / anti-rebind obligation) a content-hash that no longer matches the corpus it
claims. Wired into `make proposal-selftest` and the fast tier. Exit 0 on pass, 1 on failure.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))  # corpus -> scripts -> repo ()
OBS = os.path.join(REPO, "examples", "domain-proposals", "solidity_samples.observation-set.json")
CORPUS = os.path.join(REPO, "examples", "domain-proposals", "solidity_samples.corpus.json")


def _load_gen():
    spec = importlib.util.spec_from_file_location("gen", os.path.join(HERE, "generate_proposal_from_observations.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _codes(diags, severity="error"):
    return {d["code"] for d in diags if d["severity"] == severity}


def main() -> int:
    m = _load_gen()
    observations = json.load(open(OBS, encoding="utf-8"))
    corpus = json.load(open(CORPUS, encoding="utf-8"))
    cases = []

    # 0a. the REAL committed binding is enforced: build against the committed corpus snapshot
    #     (the default point-of-use path) re-verifies the aggregate hash and passes with NO warning.
    prop, diags = m.build(observations, corpus, m.DEFAULT_CORPUS_DIR)
    cases.append(("committed observation-set re-verifies against the committed corpus (no warning)",
                  prop is not None and not _codes(diags) and not _codes(diags, "warning"), diags))

    # 0b.  High: a rebound/stale committed observation-set (tampered contentHash) fails CLOSED
    #     against the committed corpus — the default path no longer fails open.
    rebound_committed = copy.deepcopy(observations)
    rebound_committed["corpusRef"]["contentHash"] = "sha256:" + "f" * 64
    _, diags = m.build(rebound_committed, corpus, m.DEFAULT_CORPUS_DIR)
    cases.append(("tampered committed contentHash -> corpus_rebind (real binding enforced)",
                  "proposal.corpus_rebind" in _codes(diags), diags))

    # 0c. an unreadable corpus dir is fatal, not a skip (can't silently fail open).
    _, diags = m.build(observations, corpus, "/no/such/corpus")
    cases.append(("unreadable corpus dir -> corpus_unavailable (fatal)",
                  "proposal.corpus_unavailable" in _codes(diags), diags))

    # 0d. the explicit --allow-unverified opt-out (corpus_dir None) warns but does not error.
    prop, diags = m.build(observations, corpus, None)
    ok = prop is not None and not _codes(diags) and "proposal.hash_unverified" in _codes(diags, "warning")
    cases.append(("--allow-unverified opt-out warns (never used by CI)", ok, diags))

    # 1. invalid input observations (drop provenance -> not S0-valid) fails closed.
    bad_obs = copy.deepcopy(observations)
    bad_obs["observations"][0].pop("provenance", None)
    _, diags = m.build(bad_obs, corpus, None)
    cases.append(("invalid observations -> invalid_observations",
                  "proposal.invalid_observations" in _codes(diags), diags))

    # 2. an unclassifiable dimension fails closed (declared in the set, unknown to the generator).
    dim_obs = copy.deepcopy(observations)
    dim_obs["dimensions"]["riskLevel"] = ["high", "low"]
    inject = copy.deepcopy(dim_obs["observations"][0])
    inject.update({"id": "inject-risklevel", "dimension": "riskLevel", "value": "high"})
    dim_obs["observations"].append(inject)
    _, diags = m.build(dim_obs, corpus, None)
    cases.append(("unknown dimension -> unknown_dimension",
                  "proposal.unknown_dimension" in _codes(diags), diags))

    # 3. a corpusRef mismatch against the governing manifest fails closed.
    mm = copy.deepcopy(observations)
    mm["corpusRef"]["corpusId"] = "some-other-corpus"
    _, diags = m.build(mm, corpus, None)
    cases.append(("corpusRef mismatch -> corpus_mismatch",
                  "proposal.corpus_mismatch" in _codes(diags), diags))

    # 4. a citation source that is not domain-authority fails closed.
    ref_corpus = copy.deepcopy(corpus)
    ref_corpus["sources"][0]["allowedUse"] = "reference-only"
    _, diags = m.build(observations, ref_corpus, None)
    cases.append(("non-authority citation source -> non_authority_source",
                  "proposal.non_authority_source" in _codes(diags), diags))

    # 5. anti-rebind (/): build a TINY self-contained corpus, compute its true aggregate
    #    hash, and prove a matching hash passes while a tampered hash fails closed — the re-verify
    #    teeth, exercised without the real .sol corpus.
    with tempfile.TemporaryDirectory() as td:
        srcdir = os.path.join(td, "src")
        os.makedirs(srcdir)
        open(os.path.join(srcdir, "A.sol"), "w").write("contract A {}\n")
        open(os.path.join(srcdir, "B.sol"), "w").write("contract B {}\n")
        true_hash = m.corpus_content_hash(td)
        tiny_obs = {
            "kind": "neutrino.domain-observation-set", "schemaVersion": 1,
            "corpusRef": {"corpusId": "tiny", "contentHash": true_hash},
            "extractor": {"tool": "t", "version": "0"},
            "dimensions": {"evidenceStyle": ["single_hash"]},
            "observations": [{
                "id": "a-ev", "dimension": "evidenceStyle", "value": "single_hash",
                "provenance": {"source": "src/A.sol", "construct": "A"},
            }],
        }
        tiny_corpus = {"kind": "neutrino.domain-corpus-manifest", "corpusId": "tiny", "sources": [
            {"id": "src/A.sol", "owner": "o", "sensitivity": "public", "allowedUse": "domain-authority",
             "contentHash": "sha256:" + "0" * 64, "sourceType": "official-public-repository"}]}
        _, diags = m.build(tiny_obs, tiny_corpus, td)
        cases.append(("anti-rebind match passes (corpus_dir, true hash)",
                      not _codes(diags), diags))
        rebound = copy.deepcopy(tiny_obs)
        rebound["corpusRef"]["contentHash"] = "sha256:" + "f" * 64
        _, diags = m.build(rebound, tiny_corpus, td)
        cases.append(("anti-rebind tampered hash -> corpus_rebind",
                      "proposal.corpus_rebind" in _codes(diags), diags))

    ok_all = True
    for name, passed, diags in cases:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        if not passed:
            ok_all = False
            print("        errors:", sorted(_codes(diags)), "warnings:", sorted(_codes(diags, "warning")))
    print("PROPOSAL GENERATOR SELF-TEST", "PASSED" if ok_all else "FAILED")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())

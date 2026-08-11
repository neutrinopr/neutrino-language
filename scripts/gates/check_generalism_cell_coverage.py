#!/usr/bin/env python3
"""Backend-generalism cell coverage completeness gate (translator , S1a).

The generalism matrix cells are DERIVED from the capability-spec JSON schema + the Solidity
`classification.json` (scripts/generators/gen_generalism_cells.py). This gate makes the derivation
fail-closed against feature drift — the same structural pattern as the repo's `check_*` completeness
ratchets (check_cpp_policy):

  - FRESH        : the committed manifest matches a fresh regeneration (a new schema enum / classification
                   value / seed / generator change forces a reviewed regeneration — it cannot land silently).
  - CLASSIFIED   : every schema enum coordinate is classified (behavior or excluded); a NEW behavior enum at
                   an unknown coordinate is UNCLASSIFIED -> hard RED (it cannot be banked in the baseline).
  - WITNESS      : every cell declares a witness in {ledger, refusal, render}. Only ledger/refusal cells
                   count toward coverage — and are MECHANICALLY PROVEN by the build-tier `--prove-witness`
                   pass (this gate is stdlib-only; the proof runs neutrino-gen in the build tier). `render`
                   cells are carried fixtures, NOT counted (deferred to the render-witness child of ).
  - RATCHET      : the manifest's uncovered set equals the committed baseline exactly, AND is a SUBSET of the
                   PR BASE REVISION's baseline (mechanical monotonicity — uncovered can only shrink, never
                   grow: a new uncovered feature not banked, or one that regressed out of coverage, is RED).
  - NON-VACUOUS  : floors on feature/cell/seed/witnessed counts so an emptied schema/seed set fails closed.

No expected-value table anywhere (grep-checkable): cells carry inputs + a materialized scenario + coverage
+ a witness descriptor only; dispositions are the neutral test-realization's job (/). This is
PARTIAL coverage at S1a (12/101) — NOT  completion; see coverage-baseline.json + the  children.
`--selftest` runs it against the committed artifacts.
"""
import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
GEN = os.path.join(REPO, "scripts", "generators", "gen_generalism_cells.py")

# Reuse the generator's pure structural-control-delta check (held-fixed coordinates), so the fast tier
# rejects a confounded control without a build (the build tier re-checks it under --prove-witness).
import importlib.util as _ilu
_spec = _ilu.spec_from_file_location("gen_generalism_cells", GEN)
_gen = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_gen)
MANIFEST = os.path.join(REPO, "test", "generalism", "generalism-cells.manifest.json")
BASELINE = os.path.join(REPO, "test", "generalism", "coverage-baseline.json")
BASELINE_REL = "test/generalism/coverage-baseline.json"

# Non-vacuous floors: below these, a wrong path / emptied schema / eroded seed set fails closed.
MIN_FEATURES = 60
MIN_CELLS = 15
MIN_SEEDS = 16
MIN_WITNESSED = 5    # single-feature controlled-experiment cells that credit coverage
WITNESSES = ("ledger", "refusal", "render", "spec_refusal", "binding_consume")


def fail(reasons, msg):
    reasons.append(msg)


def _ref_exists(ref):
    return subprocess.run(["git", "-C", REPO, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
                          capture_output=True, text=True).returncode == 0


def _resolve_baseline_at(ref):
    """Return the uncovered set committed at `ref` (the ref is assumed present), or None if the baseline
    file does not exist at that ref (the bootstrapping case)."""
    r = subprocess.run(["git", "-C", REPO, "show", f"{ref}:{BASELINE_REL}"], capture_output=True, text=True)
    if r.returncode != 0:
        return None
    return {tuple(x) for x in json.loads(r.stdout).get("uncovered", [])}


def _base_uncovered(reasons):
    """The PR BASE REVISION's uncovered set, for mechanical monotonicity (uncovered can only shrink).

    CI passes the concrete base via $GENERALISM_BASE_REF (e.g. `origin/main` or the PR base SHA). When it
    is set, the base ref MUST be PRESENT — a missing ref (a shallow checkout that never fetched the base)
    is a HARD FAILURE, never a fail-open skip ( P1.2). A ref that IS present but does not yet carry the
    baseline is the genuine bootstrap and yields a skip. Only when no base ref is supplied (local dev) do we
    fall back to origin/main -> main. Returns (ref, set), (None, 'skip'), or (None, None) on hard failure."""
    explicit = os.environ.get("GENERALISM_BASE_REF")
    if explicit:
        if not _ref_exists(explicit):
            fail(reasons, f"GENERALISM_BASE_REF={explicit} is set but that ref/commit is NOT present in the "
                          "checkout (a shallow clone that never fetched the PR base) — deepen the checkout "
                          "(fetch-depth: 0) or fetch the base ref. The monotonicity ratchet must NOT run "
                          "fail-open in CI.")
            return None, None
        try:
            base = _resolve_baseline_at(explicit)
        except (ValueError, KeyError):
            fail(reasons, f"base revision {explicit} has an unparseable {BASELINE_REL}")
            return None, None
        if base is None:
            return None, "skip"   # ref present, baseline not yet on the base -> genuine bootstrap
        return explicit, base
    # Local dev fallback: no explicit base supplied.
    for ref in ("origin/main", "main"):
        if not _ref_exists(ref):
            continue
        try:
            base = _resolve_baseline_at(ref)
        except (ValueError, KeyError):
            fail(reasons, f"base revision {ref} has an unparseable {BASELINE_REL}")
            return None, None
        if base is not None:
            return ref, base
    return None, "skip"


def check(reasons, notes):
    if not os.path.isfile(MANIFEST):
        fail(reasons, f"{os.path.relpath(MANIFEST, REPO)} is missing — run the generator")
        return
    manifest = json.load(open(MANIFEST, encoding="utf-8"))

    # FRESH: regenerate to a temp and compare (the generator is pure-Python: schema + classification +
    # seeds, no build). A drift (new enum, changed seed) makes the committed manifest stale -> RED.
    import tempfile
    tf = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    tf.close()
    r = subprocess.run([sys.executable, GEN, "--out", tf.name], capture_output=True, text=True)
    if r.returncode != 0:
        fail(reasons, "generator failed: " + (r.stderr.strip() or "unknown"))
    else:
        fresh = open(tf.name, encoding="utf-8").read()
        if fresh != open(MANIFEST, encoding="utf-8").read():
            fail(reasons, f"{os.path.relpath(MANIFEST, REPO)} is STALE vs the schema/classification/seeds "
                          "— regenerate it (a new feature or seed landed unreviewed)")
    os.unlink(tf.name)

    # NON-VACUOUS floors.
    if manifest.get("featureCount", 0) < MIN_FEATURES:
        fail(reasons, f"only {manifest.get('featureCount')} derived features (< floor {MIN_FEATURES}) — "
                      "the schema/classification derivation eroded?")
    if manifest.get("cellCount", 0) < MIN_CELLS:
        fail(reasons, f"only {manifest.get('cellCount')} cells (< floor {MIN_CELLS})")
    if manifest.get("witnessedCellCount", 0) < MIN_WITNESSED:
        fail(reasons, f"only {manifest.get('witnessedCellCount')} witnessed (ledger/refusal) cells "
                      f"(< floor {MIN_WITNESSED}) — the witnessable coverage eroded?")
    if manifest.get("seedCount", 0) < MIN_SEEDS:
        fail(reasons, f"only {manifest.get('seedCount')} seed cells (< floor {MIN_SEEDS}: the 16  "
                      "hand-run regression cells)")

    # CLASSIFIED: every schema enum coordinate classified; a NEW behavior enum at an unknown coordinate is
    # UNCLASSIFIED -> hard RED (it cannot be banked in the coverage baseline; classify it in the generator).
    unclassified = manifest.get("unclassifiedCoordinates") or []
    if unclassified:
        fail(reasons, f"UNCLASSIFIED schema enum coordinate(s) {unclassified} — a new behavior enum landed "
                      "without classification; add it to BEHAVIOR_ENUM_PATHS (with a witnessed cell) or "
                      "EXCLUDED_ENUM_PATHS (with a documented reason) in gen_generalism_cells.py")

    # WITNESS: every cell's witness in {ledger, refusal, render, spec_refusal, binding_consume}. The MECHANICAL proof that a ledger/refusal
    # witness actually holds is the build-tier `--prove-witness` pass (needs neutrino-gen); here we only
    # enforce the field is present + valid (this gate is stdlib-only, runs in the fast tier).
    bad_witness = sorted(c["id"] for c in manifest.get("cells", []) if c.get("witness") not in WITNESSES)
    if bad_witness:
        fail(reasons, f"cell(s) {bad_witness} have no valid witness (must be one of {WITNESSES})")
    # A CREDITING cell must be a controlled experiment. A `.neu` cell (kind=generated) carries a `control`
    # (so --prove-witness proves the feature CAUSES the difference); a binding cell (kind=binding,  S1c)
    # carries a closed `consumeProof` consumed by its authoritative first consumer. Coverage may never rest
    # on a cell without a causal proof handle (/ P1).
    no_handle = sorted(c["id"] for c in manifest.get("cells", [])
                       if c.get("credits")
                       and not (c.get("control") or {})
                       and not (c.get("kind") == "binding" and c.get("consumeProof")))
    if no_handle:
        fail(reasons, f"crediting cell(s) {no_handle} carry no causal proof handle (a `control`, or a "
                      "binding `consumeProof`) — a feature may not be credited without a controlled "
                      "experiment")
    no_code = sorted(c["id"] for c in manifest.get("cells", [])
                     if c.get("credits") and c.get("witness") in ("refusal", "spec_refusal")
                     and not c.get("refusalCode"))
    if no_code:
        fail(reasons, f"crediting refusal cell(s) {no_code} carry no `refusalCode` to prove the coded refusal")
    # COVERS<->LOCUS BINDING (+ RECONSTRUCTION for .neu cells): every crediting cell's perturbation must be
    # the CANONICAL locus of the feature it credits, so causal credit cannot be RELABELED. `.neu` cells also
    # require the control to equal apply(mutation, cell) EXACTLY (nothing outside the locus differs). The
    # build tier re-checks .neu cells in --prove-witness and binding cells in --prove-binding (/ P1).
    for c in manifest.get("cells", []):
        if not c.get("credits"):
            continue
        if c.get("kind") == "binding":
            viol = _gen.binding_consume_proof_violations(c)
        else:
            viol = _gen.feature_locus_violations(c) or _gen.control_reconstruction_violations(c)
        if viol:
            fail(reasons, f"crediting cell {c['id']}: {viol[0]}")
    # S1c BINDING PROOF (): the capability-spec validator is pure-Python, so we PROVE the validator-
    # contract binding cells here in the fast tier (no build) — the committed spec validates clean and
    # invalidating the one located field refuses with the field-specific code. The valid_carry_and_consume
    # rows are proven in CTest through the native participant slot producer and/or the observation-binding
    # consumer.
    if not any("STALE" in r for r in reasons):
        for b in _gen.prove_binding(manifest, os.path.join(REPO, "scripts", "validators",
                                                           "validate_capability_spec.py")):
            fail(reasons, f"binding proof: {b}")
        for b in _gen.binding_lifecycle_disposition_violations(manifest):
            fail(reasons, f"binding/lifecycle disposition: {b}")
    # A seed fixture must NOT credit coverage (coverage rests only on controlled experiments).
    crediting_seed = sorted(c["id"] for c in manifest.get("cells", [])
                            if c.get("kind") == "seed" and c.get("credits"))
    if crediting_seed:
        fail(reasons, f"seed fixture(s) {crediting_seed} credit coverage — seeds are regression fixtures "
                      "only; coverage must come from controlled-experiment cells")

    # RATCHET (a): uncovered == committed baseline exactly.
    baseline = None
    if os.path.isfile(BASELINE):
        baseline = {tuple(x) for x in json.load(open(BASELINE, encoding="utf-8")).get("uncovered", [])}
    else:
        fail(reasons, f"{BASELINE_REL} is missing (the sanctioned coverage-debt ledger)")
    uncovered = {tuple(x) for x in manifest.get("uncoveredFeatures", [])}
    if baseline is not None:
        new_uncovered = sorted(uncovered - baseline)
        if new_uncovered:
            fail(reasons, "NEW uncovered feature(s) with no covering cell and not in the coverage baseline "
                          f"(completeness failure): {[list(x) for x in new_uncovered]} — add a WITNESSED "
                          "covering cell, or (if genuinely frontier/binding/lifecycle) bank it in "
                          f"{BASELINE_REL} with review")
        stale_baseline = sorted(baseline - uncovered)
        if stale_baseline:
            fail(reasons, "coverage baseline lists feature(s) that are now COVERED "
                          f"{[list(x) for x in stale_baseline]} — shrink {BASELINE_REL} to bank the gain")

    # RATCHET (b): MECHANICAL MONOTONICITY vs the PR base revision — uncovered must be a SUBSET of the base
    # revision's uncovered set. This defeats the "add an enum value AND bank the same tuple in one diff"
    # loophole: the base revision's baseline is immutable to this PR, so a grown uncovered set is RED.
    base_ref, base_unc = _base_uncovered(reasons)
    if base_unc == "skip":
        notes.append(f"monotonicity-vs-base skipped: no {BASELINE_REL} on the base revision yet (this is the "
                     "bootstrapping PR that introduces it) and no GENERALISM_BASE_REF was supplied; the "
                     "committed exact-match ratchet still applies, and the subset check activates for every "
                     "subsequent PR (CI supplies GENERALISM_BASE_REF, which fails closed if unresolvable)")
    elif base_unc is not None:
        grew = sorted(uncovered - base_unc)
        if grew:
            fail(reasons, f"uncovered set GREW vs base revision {base_ref} (monotonicity violation): "
                          f"{[list(x) for x in grew]} — the uncovered debt may only SHRINK; a feature that "
                          "regressed out of coverage, or a new feature added without a witnessed cell, is "
                          "not admissible even if also added to the baseline in this PR")
    # (base_unc is None -> a hard failure was already recorded in reasons by _base_uncovered)


def main():
    ap = argparse.ArgumentParser(description="generalism cell coverage completeness gate ( S1a)")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    reasons, notes = [], []
    check(reasons, notes)
    if reasons:
        print("generalism cell coverage gate FAILED:", file=sys.stderr)
        for r in reasons:
            print(f"    {r}", file=sys.stderr)
        return 1
    m = json.load(open(MANIFEST, encoding="utf-8"))
    covered = m["coveredCount"]
    for n in notes:
        print(f"note: {n}")
    print(f"generalism cell coverage gate OK (PARTIAL coverage — NOT  completion): {m['cellCount']} "
          f"cells ({m['seedCount']} seeds, {m['witnessedCellCount']} witnessed) derived from the "
          f"capability-spec schema + classification; {covered}/{m['featureCount']} features witnessed "
          f"({round(100.0*covered/m['featureCount'],1)}%); {len(m.get('uncoveredFeatures', []))} "
          f"frontier/binding/render features are pinned DEBT in {BASELINE_REL}, deferred to the  "
          "children; every schema enum coordinate classified; manifest fresh; uncovered ⊆ base revision")
    return 0


if __name__ == "__main__":
    sys.exit(main())

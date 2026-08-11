"""[] normalized trace-equivalence + non-vacuous tamper gate.

Drives neutrino-equiv's core-owned trace-equivalence check (the reference
evaluator's  observation trace vs the independent normalized realization)
and enforces it
is NON-VACUOUS and fails closed:

  1. Every committed sample is trace-equivalent (observable agreement) with the
     reference evaluator, executedCases>=1 — floor >=5 samples (a zero/empty run
     fails closed, not passes).
  2. Every tamper class (dropped effect, altered amount, reordered observations,
     wrong terminal, replay omission, partial commit, altered derived value,
     changed outcome) is DETECTED as a failing equivalence result with
     divergence coordinates — one per compared field, all or the gate fails.

The trace comparison is target-blind and always executes. Package profile
compatibility and execution are covered by the integration-only catalog test.
Exit 0 ok / 1 violations / 2 usage.

Usage: check_trace_equivalence.py <neutrino-equiv> <repo-root>
"""
import glob
import json
import os
import subprocess
import sys
import tempfile

if len(sys.argv) != 3:
    print(__doc__, file=sys.stderr)
    sys.exit(2)
EQ, REPO = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
fails = []
TAMPERS = ["drop_effect", "alter_amount", "reorder_obs", "wrong_terminal",
           "replay_omission", "partial_commit", "alter_computed",
           "alter_outcome"]

sys.path.insert(0, os.path.join(REPO, "test", "ir", "pipeline"))
from pipeline_inputs import (PipelineInputError, resolve_core_fixture,  # noqa: E402
                             resolve_core_fixtures, resolve_pipeline_inputs)

try:
    INPUTS = resolve_pipeline_inputs(REPO)
    CORE_INPUTS = resolve_core_fixtures(REPO)
    # The tamper corpus is one concrete sample; naming it here means a missing
    # fixture is reported as a resolution failure instead of eight indistinguishable
    # "tamper ... was NOT detected (the gate is vacuous)" lines ().
    TAMPER_FIXTURE = resolve_core_fixture(REPO, "core_sample_installment")
    if TAMPER_FIXTURE.scenario is None:
        raise PipelineInputError(
            "required tamper input missing: core_sample_installment.scenario "
            f"(no single scenario under {TAMPER_FIXTURE.root / 'scenario'})")
except PipelineInputError as error:
    print("[] trace-equivalence gate FAILED:", file=sys.stderr)
    print("    FAIL: " + str(error), file=sys.stderr)
    sys.exit(1)


def run_equiv(src, scn, extra=None):
    rd = tempfile.mkdtemp(prefix="te522.")
    r = subprocess.run([EQ, "--reference-only", "--scenario=" + scn, src,
                        "--report=" + rd] + (extra or []),
                       cwd=rd, capture_output=True)
    try:
        rep = json.load(open(os.path.join(rd, "equivalence.json")))
    except (OSError, ValueError):
        rep = None
    return r.returncode, rep


def samples():
    """The (source, scenario) corpus the equivalence floor is measured over.

    : this used to glob `examples/domains/*/scenario/*.json`. Every production
    domain moved to a published pack, so the glob returned [] and the >=5 floor
    correctly failed closed on an empty corpus. The gate was never broken -- the
    corpus was. Rebuild it from the receipt-verified packs at their pinned
    coordinates plus the core-owned synthetics, so a sample can only enter the
    corpus through a verified surface.

    This supersedes 's manifest path-assembly (`corpus["packs"][m]["packPath"]`):
    same pack membership, but resolved THROUGH the receipt-verifying resolver instead
    of joining a declared path, so an unverified surface cannot enter the corpus.
    """
    out = []
    for fixture in sorted(INPUTS.values(), key=lambda f: f.name):
        if fixture.scenario is not None:
            out.append((str(fixture.source), str(fixture.scenario)))
    for fixture in sorted(CORE_INPUTS.values(), key=lambda f: f.name):
        if fixture.scenario is not None:
            out.append((str(fixture.source), str(fixture.scenario)))
    # one scenario per domain is enough — dedupe by source.
    seen, uniq = set(), []
    for src, scn in out:
        if src not in seen:
            seen.add(src)
            uniq.append((src, scn))
    return uniq


# 1. committed samples are trace-equivalent, non-vacuously.
n_ok = 0
CORPUS = samples()
if not CORPUS:
    fails.append("trace-equivalence corpus is empty: no resolved pack or core fixture "
                 "carries a (source, scenario) pair — the >=5 floor below cannot be "
                 "satisfied and this is an input failure, not a gate failure")
for src, scn in CORPUS:
    rc, rep = run_equiv(src, scn)
    if rep is None or "traceEquivalence" not in rep:
        fails.append(f"no traceEquivalence report for {os.path.basename(src)}")
        continue
    te = rep["traceEquivalence"]
    if not te.get("ok") or te.get("executedCases", 0) < 1:
        fails.append(f"{os.path.basename(src)}: not trace-equivalent "
                     f"(ok={te.get('ok')}, executed={te.get('executedCases')})")
    else:
        n_ok += 1
if n_ok < 5:
    fails.append(f"non-vacuous floor: only {n_ok} of {len(CORPUS)} corpus samples "
                 "trace-equivalent (need >=5) — a zero/empty run must fail closed")

# 2. every tamper class is detected as a failing equivalence result.
# The tamper corpus is ONE named fixture, resolved () rather than path-assembled:
# a missing input then reports as a resolution failure instead of eight
# indistinguishable "tamper ... was NOT detected (the gate is vacuous)" lines.
# The profile/refusal block that used to sit here was removed by  when the
# comparison became target-blind; it is deliberately NOT reinstated.
smp_src = str(TAMPER_FIXTURE.source)
smp_scn = str(TAMPER_FIXTURE.scenario)
n_tamper = 0
for t in TAMPERS:
    rc, rep = run_equiv(smp_src, smp_scn, ["--tamper=" + t])
    te = rep.get("traceEquivalence", {}) if rep else {}
    if rc == 0 or te.get("ok", True):
        fails.append(f"tamper '{t}' was NOT detected (the gate is vacuous)")
    elif "divergence" not in te:
        fails.append(f"tamper '{t}' detected but carries no divergence coordinates")
    else:
        n_tamper += 1
if n_tamper < len(TAMPERS):
    fails.append(f"non-vacuous floor: only {n_tamper}/{len(TAMPERS)} tampers detected")

# 4. evidence-only (): the comparator handles the effectless evidence-shaped
# trace WITHOUT false-failing (its observable shape is outcome=committed, one
# acceptance event, success terminal, a posted instance key, and NO ledger), and
# its tamper self-test is non-vacuous on that shape — dropping the acceptance
# event, the posted instance key, the terminal, or the outcome each diverges on
# a DISTINCT field. This is a COMPARATOR + reference-evaluator self-test on the
# evidence trace shape, NOT a proof the rails agree: an effectless coordination
# has no ledger arithmetic to recompute independently, so evidence rail agreement
# is proven by the byte goldens + forge/docker behavioral tests + the
# spec-vs-artifact structural check, not here.
ev_src = os.path.join(REPO, "test", "ir", "evidence", "shipment_evidence_anchor.neu")
ev_scn = os.path.join(REPO, "test", "ir", "evidence",
                      "shipment_evidence_anchor.scn.json")
rc, rep = run_equiv(ev_src, ev_scn)
ev_te = rep.get("traceEquivalence", {}) if rep else {}
if not ev_te.get("ok") or ev_te.get("executedCases", 0) < 1:
    fails.append(f"evidence-only: comparator false-failed on the evidence shape "
                 f"(ok={ev_te.get('ok')}, executed={ev_te.get('executedCases')})")
# field -> tamper that breaks it: acceptance event, instance key, terminal, outcome
EVIDENCE_TAMPERS = {"events": "drop_effect", "postedKeys": "replay_omission",
                    "terminal": "wrong_terminal", "outcome": "alter_outcome"}
n_ev_tamper = 0
for field, t in sorted(EVIDENCE_TAMPERS.items()):
    rc, rep = run_equiv(ev_src, ev_scn, ["--tamper=" + t])
    te = rep.get("traceEquivalence", {}) if rep else {}
    if rc == 0 or te.get("ok", True):
        fails.append(f"evidence-only tamper '{t}' ({field}) was NOT detected (vacuous)")
    elif te.get("divergence", {}).get("field") != field:
        fails.append(f"evidence-only tamper '{t}' diverged on "
                     f"'{te.get('divergence', {}).get('field')}', expected '{field}'")
    else:
        n_ev_tamper += 1
if n_ev_tamper < len(EVIDENCE_TAMPERS):
    fails.append(f"evidence-only non-vacuous floor: only {n_ev_tamper}/"
                 f"{len(EVIDENCE_TAMPERS)} field tampers detected")

if fails:
    print("[] trace-equivalence gate FAILED:", file=sys.stderr)
    for f in fails:
        print("    FAIL: " + f, file=sys.stderr)
    sys.exit(1)
print(f"[] OK: {n_ok} samples trace-equivalent vs the reference evaluator; "
      f"all {n_tamper} tamper "
      f"classes detected with divergence coordinates; the comparator handles the evidence-only "
      f"trace shape + {n_ev_tamper} field tampers self-tested (rail agreement proven by "
      f"goldens/behavioral/structural) — non-vacuous, fail-closed")

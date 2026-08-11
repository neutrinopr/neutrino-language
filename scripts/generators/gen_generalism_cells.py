#!/usr/bin/env python3
"""Backend-generalism matrix runner — S1a schema-derived cell generator (translator ).

Emits a machine-readable CELL MANIFEST for the backend-generalism conformance matrix. Each cell pairs a
minimal capability-spec INPUT (a `.neu` source domain) with a MATERIALIZED scenario (the real
`--target=capability --scenario=<json>` contract), and declares which capability-spec schema /
Solidity-classification FEATURES it covers plus a MECHANICALLY-PROVEN behavioral witness. Later slices
render + execute the cells () and classify FAITHFUL/REFUSED/SILENT/BROKEN against the neutral
test-realization (), gating CI on a non-empty SILENT∪BROKEN set ().

Non-negotiable contracts this generator upholds ():
  1. Rows are DERIVED from the capability-spec JSON schema + solidity `classification.json` — never a
     hardcoded feature list. `derive_features()` traverses EVERY schema enum coordinate and classifies it
     (behavior/excluded); an UNCLASSIFIED coordinate is reported so the gate fails closed.
  2. NO hand-maintained expected-value table: cells carry INPUTS + a materialized scenario + feature
     coverage + a witness descriptor only. Expected behaviour is the test-realization (), not this file.
  3. Coverage requires a MECHANICALLY-PROVEN witness, not a trusted label (P1,  re-review):
       - `ledger`  : the feature is structurally present in the realized capability model; the cell
                     realizes (exit 0) AND a mechanically-derived feature-REMOVAL mutant changes the
                     normalized observation (exit code + solidity/postgres model sha). Proven by
                     `--prove-witness`, which runs neutrino-gen on the cell and its mutant.
       - `refusal` : the cell (or its adversarial scenario) triggers the INTENDED coded refusal — exit in
                     {3,4,6} AND the declared `refusalCode` appears in the diagnostics. Proven likewise.
       - `render`  : the feature survives ONLY into the emitted backend code (guards/`when`,
                     canonicalization, fallback, evidence-gating): the S1 capability model drops it
                     (guard-present and guard-removed emit byte-identical models). NOT observable at S1 —
                     carried as a fixture but NOT counted; deferred to the render-witness child of .
     Coverage is therefore PARTIAL at S1a; the uncovered set is pinned in coverage-baseline.json and
     ratcheted monotonically (subset vs the PR base revision) by check_generalism_cell_coverage.py.
  4. Adversarial-input discipline: a `refusal` cell's scenario is the divergence-exposing input (negative
     money, cross-currency, missing leg), never a happy value.

The 16 hand-run cells from  are seeded from committed fixtures (test/generalism/seed-cells.json)
so the runner reproduces the known verdicts ( guard blindness,  money-sign) as regression, while the
ROWS stay schema-derived. The guard seeds are `render`-witnessed (finding  is a silent EMITTED-code
divergence — exactly what the render witness catches — not a capability-model delta).

Usage:
    gen_generalism_cells.py [--schema F] [--classification F] [--seeds F] [--out F]
                            [--check | --prove-witness NEUTRINO_GEN]
                            [--prove-binding-consume SLOT_SPEC_SMOKE]
--check regenerates in-memory and compares to --out (exit 1 if stale).
--prove-witness realizes every ledger/refusal cell (and each ledger cell's mutant) with the given
neutrino-gen and asserts the witness actually holds.
"""
import argparse
import copy
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
SCHEMA = os.path.join(REPO, "docs", "schemas", "capability-spec.schema.json")
CLASSIFICATION = os.path.join(REPO, "examples", "solidity-classification", "classification.json")
SEEDS = os.path.join(REPO, "test", "generalism", "seed-cells.json")

# Every enum coordinate in the live schema is CLASSIFIED — behavior-bearing (mapped to a feature family)
# or explicitly excluded — and an UNCLASSIFIED coordinate fails the gate (a new behavior enum at a NEW
# schema coordinate must never land invisibly). A derivation RULE over the schema, not a per-value list:
# every VALUE under a behavior path is enumerated from the live schema.
BEHAVIOR_ENUM_PATHS = {
    "/effects/kind": "effect_kind",
    "/invariants/kind": "invariant",
    "/valueCategory": "value_category",
    "/exprNode/kind": "expr_kind",
    "/exprNode/op": "expr_op",
    "/state/terminalKind": "terminal_kind",
    "/transition/idempotency": "idempotency",
    "/transition/effects": "transition_effect",
    "/transition/guards/kind": "transition_guard",
    "/participants/binding": "participant_binding",
    "/participants/bindMinAssurance": "bind_min_assurance",
    "/attestationPolicy/observerSet/assurance": "assurance",
    "/attestationPolicy/observerSet/independence": "independence",
    "/attestationPolicy/canonicalization/mode": "canonicalization",
    "/attestationPolicy/fallback": "fallback",
    "/transition/evidence/oneOf1/style": "evidence_style",
}

# Enum coordinates that carry NO backend-observable rendering behavior (compiler/protocol metadata), so
# they are not generalism features. Each is a reviewed, documented exclusion — NOT a silent skip.
EXCLUDED_ENUM_PATHS = {
    "/schemaVersion": "capability-spec schema version (protocol metadata, not a rendered behavior)",
    "/targetRequirement/requirement": "required/optional requirement strength (planning metadata)",
    "/operand/kind": "ref/literal operand kind (a syntactic operand shape, subsumed by expr_kind)",
    "/targetRequirements/evidenceStyle": "the derived evidence-style summary mirror of transition.evidence.style",
}


def _all_enum_coordinates(node, path, out):
    """Collect EVERY (path -> enum values) coordinate in the schema, exhaustively — so classification
    (behavior vs excluded vs UNCLASSIFIED) is total and a new coordinate cannot be silently ignored."""
    if isinstance(node, dict):
        if "enum" in node:
            out.setdefault(path, [str(v) for v in node["enum"]])
        for k, v in node.items():
            if k in ("properties", "definitions", "$defs", "patternProperties") and isinstance(v, dict):
                for kk, vv in v.items():
                    _all_enum_coordinates(vv, path + "/" + kk, out)
            elif k == "items":
                _all_enum_coordinates(v, path, out)
            elif k in ("oneOf", "anyOf", "allOf") and isinstance(v, list):
                for i, vv in enumerate(v):
                    _all_enum_coordinates(vv, path + "/" + k + str(i), out)


# Structural feature families the scope names explicitly that are NOT single schema enums — backend
# shapes the matrix must exercise. Enumerated as (family, value) rows; witnessability is decided per-cell.
STRUCTURAL_FEATURES = {
    "when_guard": ["present", "guard_false"],
    "compute": ["present"],
    "participant_scoping": ["single", "multi"],
    "currency_dimension": ["single", "cross"],
    "degenerate": ["empty_effects", "missing_leg", "negative_amount", "zero_amount", "boundary"],
}


def derive_features(schema, classification):
    """The DERIVED feature set: (family, value, source, coordinate) + the UNCLASSIFIED schema enum
    coordinates. Rows come from the live schema + classification, never a hardcoded list."""
    coords = {}
    _all_enum_coordinates(schema, "", coords)
    feats = []
    unclassified = []
    for path in sorted(coords):
        if path in BEHAVIOR_ENUM_PATHS:
            for v in coords[path]:
                feats.append((BEHAVIOR_ENUM_PATHS[path], v, "schema", path))
        elif path in EXCLUDED_ENUM_PATHS:
            continue
        else:
            unclassified.append(path)
    for family, values in STRUCTURAL_FEATURES.items():
        for v in values:
            feats.append((family, v, "structural", family))
    for dim, values in (classification.get("dimensions") or {}).items():
        for v in values:
            feats.append(("classification:" + dim, str(v), "classification", "dimensions/" + dim))
    seen, ordered = set(), []
    for f in feats:
        key = (f[0], f[1])
        if key not in seen:
            seen.add(key)
            ordered.append(f)
    ordered.sort(key=lambda f: (f[0], f[1]))
    return ordered, sorted(unclassified)


def _live_schema_values(family, schema=None, classification=None):
    """Return a family's identities through the live matrix derivation.

    Guard rows must not acquire a second expected-value table: this deliberately
    reads the same schema/classification inputs and rules as derive_features().
    """
    if schema is None:
        with open(SCHEMA, encoding="utf-8") as f:
            schema = json.load(f)
    if classification is None:
        with open(CLASSIFICATION, encoding="utf-8") as f:
            classification = json.load(f)
    values = [value for fam, value, source, _coord in derive_features(schema, classification)[0]
              if fam == family and source == "schema"]
    if not values:
        raise RuntimeError(f"live schema derives no values for {family!r}")
    return values


# ---- minimal .neu domain construction (the cell INPUT) --------------------------------------------
#
# A compact balanced two-party settlement is the base; feature builders mutate it. The .neu grammar
# requires each block field on its own line and the header to end with `{`.

def _base(name, extra_inputs="", pre_effects="", tail="assert balanced",
          credit_currency="%currency", amount_ref="%amount"):
    return f"""procedure {name} {{
    trigger settlement
    version "1.0.0"
    participant Payer {{
        role = "payer"
        org  = "a"
    }}
    participant Payee {{
        role = "payee"
        org  = "b"
    }}
    allow "a" with "b" {{
        "a" as "payer"
        "b" as "payee"
    }}
    input amount   : money
    input currency : currency
    input pid      : party
    input qid      : party
    input key      : string{extra_inputs}
{pre_effects}    debit d {{
        ledger          = "l.payer"
        owner           = "payer"
        participant     = "Payer"
        party           = %pid
        amount          = {amount_ref}
        currency        = %currency
        idempotency_key  = %key
    }}
    credit c {{
        ledger          = "l.payee"
        owner           = "payee"
        participant     = "Payee"
        party           = %qid
        amount          = {amount_ref}
        currency        = {credit_currency}
        idempotency_key  = %key
    }}
    {tail}
}}
"""


def _remove_block(neu, header_prefix):
    """Drop a whole `debit`/`credit`/`assert` block: from the header line to its closing `}` line."""
    out, skip = [], False
    for line in neu.splitlines():
        if line.strip().startswith(header_prefix):
            skip = line.strip().endswith("{")   # multi-line block -> skip to closing brace
            if not skip:
                continue                          # single-line statement (e.g. `assert balanced`) -> drop
            continue
        if skip:
            if line.strip() == "}":
                skip = False
            continue
        out.append(line)
    return "\n".join(out) + "\n"


TYPE_DEFAULTS = {"money": 100, "decimal": 2, "party": "party-1", "currency": "EUR",
                 "string": "sha256:aa", "evidence": "sha256:aa",
                 "timestamp": "2026-01-01T00:00:00Z"}


def _proc_name(neu):
    m = re.search(r"procedure\s+(\S+)", neu)
    return m.group(1) if m else "cell"


def _synth_scenario(neu, overrides=None):
    """Materialize a real `--scenario` JSON from a cell's OWN declared inputs (parsed from the `.neu`),
    filling type-appropriate defaults; `overrides` supplies the adversarial value(s). Each cell/mutant
    gets a scenario derived from its own inputs, so a mutant with fewer inputs still validates."""
    proc = _proc_name(neu)
    inputs = {}
    for name, typ in re.findall(r"^\s*input\s+(\w+)\s*:\s*(\w+)", neu, re.M):
        inputs[name] = TYPE_DEFAULTS.get(typ, "x")
    for k, v in (overrides or {}).items():
        inputs[k] = v
    return {"scenario": proc, "procedure": proc, "inputs": inputs}


# ---- controlled-experiment cell builders ----------------------------------------------------------
#
# Every COUNTED cell is a CONTROLLED EXPERIMENT: it carries a `control` that differs from the cell in
# EXACTLY the covered feature coordinate (a single leg block, the `assert`, the credit currency variable,
# one operator token, or one scenario scalar) and holds all else fixed. The witness is credited only when
# the cell's realized observation differs from the control's — so the observed change is CAUSED by the
# feature, not by an incidental coordinate (the  P1: prove causation, not just "something changed").
#
#   ledger  : the cell realizes (exit 0); the control (feature removed) yields a DIFFERENT observation.
#   refusal : the cell emits its coded `refusalCode`; the control (feature normalized) does NOT emit that
#             code (the refusal disappears) — proving the refusal is caused by the feature.
#
# `control` is `{"neu": <control source>}` (a structural single-coordinate edit) or `{"adversarial":
# {...}}` (the cell's own source, one scenario scalar flipped). A feature with no clean single-coordinate
# control is honestly UNCOVERED (deferred to a  child) — never credited by a confounded diff.

# ---- mechanically-derived typed mutations ---------------------------------------------------------
#
# The control is not authored — it is DERIVED from the cell by applying ONE typed mutation, so nothing
# outside the mutation locus (version, `allow`, `compute`, any line) can differ ( P1: the old
# held-fixed check was a partial allowlist that let a `version 1.0.0 -> 9.9.9` control through). Each
# mutation is exact-match-count checked. The gate re-derives the control and requires it to EQUAL the
# committed control byte-for-byte (reconstruction), so a tampered control that adds an unrelated change
# fails closed.

class MutationError(Exception):
    pass


def apply_mutation(neu, mut):
    """Apply ONE typed mutation to `neu`, returning the control source (or None for a scenario-only
    mutation, whose control shares the cell's source and varies only a scenario scalar). Exact-match-count:
    the target must occur exactly the declared number of times, so a mutation can neither miss nor
    over-reach."""
    op = mut.get("op")
    if op == "scenario":
        return None
    if op == "retoken":
        old, new, cnt = mut["old"], mut["new"], mut.get("count", 1)
        found = neu.count(old)
        if found != cnt:
            raise MutationError(f"retoken {old!r}: expected {cnt} occurrence(s), found {found}")
        return neu.replace(old, new)
    if op == "remove_block":
        header = mut["header"]
        hits = sum(1 for line in neu.splitlines() if line.strip().startswith(header))
        if hits != 1:
            raise MutationError(f"remove_block {header!r}: expected 1 matching block, found {hits}")
        return _remove_block(neu, header)
    raise MutationError(f"unknown mutation op {op!r}")


def _cell(family, value, witness, neu, mutation, note, refusal_code=None, adversarial=None,
          adv_kind="boundary"):
    """A crediting controlled-experiment cell. The control is DERIVED by applying `mutation` to `neu`."""
    control_neu = apply_mutation(neu, mutation)   # raises on a bad/ambiguous mutation
    control = {"adversarial": mutation["override"]} if mutation["op"] == "scenario" else {"neu": control_neu}
    c = {"witness": witness, "adversarialKind": adv_kind, "input": {"neu": neu},
         "scenario": _synth_scenario(neu, adversarial), "adversarial": adversarial or {},
         "mutation": mutation, "control": control, "covers": [[family, value]], "note": note}
    if refusal_code:
        c["refusalCode"] = refusal_code
    return c


# The CLOSED feature-locus binding: the ONE canonical mutation that IS each credited feature's locus.
# `covers` and `mutation` are NOT independently authored — both a cell's coverage and its control come from
# this single table, so the mutation cannot be relabeled to a different feature ( P1). The gate + proof
# re-validate `cell.mutation == FEATURE_LOCUS[cell.covers]`, so a manifest that swaps one for the other is
# RED. Removing the debit node witnesses effect_kind/debit; removing the assert witnesses invariant/balanced;
# retokening the credit currency witnesses currency_dimension/cross; etc.
FEATURE_LOCUS = {
    ("effect_kind", "debit"): {"op": "remove_block", "header": "debit d"},
    ("effect_kind", "credit"): {"op": "remove_block", "header": "credit c"},
    ("invariant", "balanced"): {"op": "remove_block", "header": "assert balanced"},
    ("currency_dimension", "cross"): {"op": "retoken", "old": "currency        = %currency2",
                                      "new": "currency        = %currency", "count": 1},
    ("degenerate", "negative_amount"): {"op": "scenario", "override": {"amount": 100}},
    ("expr_op", "-"): {"op": "retoken", "old": "amount - other", "new": "amount + other", "count": 1},
}


def build_controlled_cells():
    """The single-feature CONTROLLED-EXPERIMENT cells that are causally witnessable at S1a. The control is a
    mechanically-DERIVED typed mutation taken from the closed FEATURE_LOCUS binding (so the mutation IS the
    credited feature's locus, not an independently-authored one), and by construction only that locus
    differs — `--prove-witness` then proves the feature causes the observation difference."""
    def mut(fam, val):
        return FEATURE_LOCUS[(fam, val)]
    out = []
    # 1,2 — effect kinds: remove ONLY one leg block (-> not_balanceable).
    for leg in ("debit", "credit"):
        nm = f"gen_effect_kind_{leg}"
        out.append(_cell("effect_kind", leg, "ledger", _base(nm), mut("effect_kind", leg),
                         f"balanced pair; control removes ONLY the {leg} leg -> not_balanceable"))
    # 3 — balanced invariant: remove ONLY `assert balanced` (-> assert_missing).
    out.append(_cell("invariant", "balanced", "ledger", _base("gen_invariant_balanced"),
                     mut("invariant", "balanced"),
                     "balanced pair; control removes ONLY `assert balanced` -> assert_missing"))
    # 4 — currency cross: retoken ONLY the credit currency reference; the currency2 input line is untouched
    #     (it has no `%`), so the input set is held fixed by construction.
    out.append(_cell("currency_dimension", "cross", "refusal",
                     _base("gen_currency_dimension_cross", extra_inputs="\n    input currency2 : currency",
                           credit_currency="%currency2"),
                     mut("currency_dimension", "cross"),
                     "credit in a 2nd currency -> unbalanced; retoken the credit currency ref -> single -> ok",
                     refusal_code="kernel.balance.unbalanced"))
    # 5 — negative money: scenario mutation flips ONLY the amount scalar's sign (same source).
    out.append(_cell("degenerate", "negative_amount", "refusal", _base("gen_degenerate_negative_amount"),
                     mut("degenerate", "negative_amount"),
                     "negative money amount refused (); positive-amount control (same source) -> ok",
                     refusal_code="negative", adversarial={"amount": -500}, adv_kind="negative"))
    # 6 — subtraction: retoken ONLY the operator token (- -> +), same source shape + same scenario.
    out.append(_cell("expr_op", "-", "refusal",
                     _base("gen_expr_op_minus", extra_inputs="\n    input other : money",
                           pre_effects="    compute r = amount - other\n", amount_ref="%r"),
                     mut("expr_op", "-"),
                     "subtraction driven <0 refused (); the `+` control on the same scenario -> ok",
                     refusal_code="negative", adversarial={"other": 999}, adv_kind="negative"))
    return out


def feature_locus_violations(cell):
    """Bind `covers` to `mutation`: the cell's mutation must be the CANONICAL locus of the feature it
    credits (FEATURE_LOCUS). This defeats a RELABELED experiment — e.g. crediting effect_kind/debit while
    the mutation actually removes the assert (which witnesses invariant/balanced). Empty == correctly bound."""
    covers = cell.get("covers") or []
    if len(covers) != 1:
        return ["a crediting cell must credit exactly one feature"]
    key = tuple(covers[0])
    if key not in FEATURE_LOCUS:
        return [f"feature {list(key)} has no canonical locus in FEATURE_LOCUS (cannot be credited at S1a)"]
    if cell.get("mutation") != FEATURE_LOCUS[key]:
        return [f"mutation is not the canonical locus for {list(key)} — the experiment credits a feature it "
                "does not actually perturb (relabeled)"]
    return []


def control_reconstruction_violations(cell):
    """The gate's pure structural proof: re-DERIVE the control from the committed cell + mutation and
    require it to match the committed control EXACTLY. Any control that changed something outside the
    mutation locus (a version bump, an extra `allow`/`compute` edit) will not reconstruct -> flagged. Empty
    list == a faithfully-derived single-locus control."""
    mut = cell.get("mutation")
    if not mut:
        return ["crediting cell carries no typed mutation"]
    control = cell.get("control") or {}
    try:
        derived = apply_mutation(cell["input"]["neu"], mut)
    except MutationError as e:
        return [str(e)]
    if mut.get("op") == "scenario":
        if control.get("neu"):
            return ["scenario mutation must not carry a control .neu"]
        if control.get("adversarial") != mut.get("override"):
            return ["control scenario override does not match the declared mutation override"]
        return []
    if control.get("neu") != derived:
        return ["committed control does not equal apply(mutation, cell) — the control changed a coordinate "
                "outside the declared mutation locus (confounded)"]
    return []


# ---- S1c: binding/lifecycle controlled experiments on the canonical capability-spec artifact ------
#
# The binding- and lifecycle-level features () are NOT observable from a settlement `.neu` capability
# model: attestation observer assurance/independence, participant binding/bindMinAssurance are set at
# observation-binding time, and terminalKind/idempotency/transition-effects/transition-guards are synthesized by a FIXED
# lifecycle machine (no `.neu` grammar). They ARE carried in the CANONICAL capability-spec JSON, and
# `scripts/validators/validate_capability_spec.py` (the frozen spec contract's validator) ENFORCES each —
# emitting a FIELD-SPECIFIC coded diagnostic when the value is invalid. So the controlled experiment is:
#   cell    = a committed canonical capability-spec artifact that carries the value at a located field
#             (validates clean, exit 0);
#   mutation= either set THAT ONE located field to an invalid sentinel for a non-crediting validator
#             contract, or derive a second schema-valid spec and prove the first authoritative consumer
#             observes the value delta;
#   control = the mutated/derived artifact;
#   witness = non-crediting validator-contract rows refuse with a field-specific code, while crediting
#             rows carry a schema-valid value through a real consumer path. The value is carried at the
#             located locus in both cases.
# Validator-contract rows witness only values that appear in a committed spec. Valid carry-and-consume
# rows may derive canonical schema-valid variants from that committed source, but must rebuild identity
# and prove a valid<->valid consumer delta. The locus is content-located, robust to array-index drift.
# BINDING_LOCUS is the closed covers<->locus binding (the S1c analogue of FEATURE_LOCUS): the credited
# feature IS the located/enforced field, so credit cannot be relabeled.

_CBEC = "test/generalism/Inputs/export_clearance_fixture/capability-spec.json"
_CBEC_BINDING = "test/generalism/Inputs/export_clearance_fixture/binding.json"
_CE = "test/ir/samples/Inputs/core_document_escrow/generated/capability-spec/capability-spec.json"
_MPRP = "test/ir/security/Inputs/core_multi_pair_role/generated/capability-spec/capability-spec.json"
_TK = "test/generalism/fixtures/terminal_kind.capability-spec.json"

# (family, value) -> {spec, array (dotted), sub (dotted field within an element), value, contains?,
#                     invalid, code}. `contains` marks an array-valued field (transition.effects).
BINDING_LOCUS = {
    ("assurance", "A3"): {"spec": _CBEC, "array": "attestations", "sub": "observerSet.assurance",
                          "value": "A3", "invalid": "A9", "code": "kernel.attest.invalid_assurance",
                          "msg": "observerSet.assurance, when present, must be one of"},
    ("independence", "independent"): {"spec": _CBEC, "array": "attestations",
                                      "sub": "observerSet.independence", "value": "independent",
                                      "invalid": "solo", "code": "kernel.attest.invalid_independence",
                                      "msg": "observerSet.independence, when present, must be one of"},
    ("bind_min_assurance", "A2"): {"spec": _CE, "array": "participants", "sub": "bindMinAssurance",
                                   "value": "A2", "invalid": "A9",
                                   "code": "kernel.binding.invalid_assurance",
                                   "msg": "bindMinAssurance invalid"},
    ("participant_binding", "fixed"): {"spec": _MPRP, "array": "participants", "sub": "binding",
                                       "value": "fixed", "invalid": "bogus",
                                       "code": "kernel.binding.invalid_mode",
                                       "msg": "binding must be fixed|to_be_bound"},
    ("participant_binding", "to_be_bound"): {"spec": _CE, "array": "participants", "sub": "binding",
                                             "value": "to_be_bound", "invalid": "bogus",
                                             "code": "kernel.binding.invalid_mode",
                                             "msg": "binding must be fixed|to_be_bound"},
    ("terminal_kind", "success"): {"spec": _TK, "array": "lifecycle.states", "sub": "terminalKind",
                                   "value": "success", "invalid": "bogus", "code": "spec.terminal_kind",
                                   "msg": "terminalKind invalid"},
    ("terminal_kind", "aborted"): {"spec": _TK, "array": "lifecycle.states", "sub": "terminalKind",
                                   "value": "aborted", "invalid": "bogus", "code": "spec.terminal_kind",
                                   "msg": "terminalKind invalid"},
    ("terminal_kind", "contested"): {"spec": _TK, "array": "lifecycle.states", "sub": "terminalKind",
                                     "value": "contested", "invalid": "bogus",
                                     "code": "spec.terminal_kind", "msg": "terminalKind invalid"},
    ("transition_effect", "post"): {"spec": _MPRP, "array": "lifecycle.transitions", "sub": "effects",
                                    "value": "post", "contains": True, "invalid": ["bogus"],
                                    "code": "spec.transition_effect", "msg": "effect 'bogus' invalid"},
    ("transition_effect", "compensate"): {"spec": _MPRP, "array": "lifecycle.transitions", "sub": "effects",
                                          "value": "compensate", "contains": True, "invalid": ["bogus"],
                                          "code": "spec.transition_effect", "msg": "effect 'bogus' invalid"},
}

BINDING_CONSUME_PROOFS = {
    ("participant_binding", "fixed"): {
        "locus": "participant",
        "spec": _CE,
        "participant": "EscrowAgent",
        "specField": "binding",
        "topologyField": "lateBindingMode",
        "cellValue": "fixed",
        "controlValue": "to_be_bound",
        "cellTopologyValue": "fixed",
        "controlTopologyValue": "to_be_bound",
        "manifest": {
            "runtime": "evm",
            "assurance": "A2",
            "binder": "escrowco",
        },
        "expected": {"ok": False, "code": "NEU-3001"},
        "controlExpected": {"ok": True},
        "tamper": "flip-lateBindingMode-to-controlTopologyValue",
    },
    ("participant_binding", "to_be_bound"): {
        "locus": "participant",
        "spec": _CE,
        "participant": "EscrowAgent",
        "specField": "binding",
        "topologyField": "lateBindingMode",
        "cellValue": "to_be_bound",
        "controlValue": "fixed",
        "cellTopologyValue": "to_be_bound",
        "controlTopologyValue": "fixed",
        "manifest": {
            "runtime": "evm",
            "assurance": "A2",
            "binder": "escrowco",
        },
        "expected": {"ok": True},
        "controlExpected": {"ok": False, "code": "NEU-3001"},
        "tamper": "flip-lateBindingMode-to-controlTopologyValue",
    },
}

for _assurance, _control in (
        ("A1", "A2"),
        ("A2", "A1"),
        ("A3", "A2"),
        ("A4", "A3")):
    BINDING_CONSUME_PROOFS[("assurance", _assurance)] = {
        "locus": "observerSet",
        "spec": _CBEC,
        "binding": _CBEC_BINDING,
        "observerSet": "customs_oracles",
        "specField": "assurance",
        "bindingField": "assurance",
        "cellValue": _assurance,
        "controlValue": _control,
        "mismatchCode": "binding.observer_assurance_mismatch",
        "tamper": "flip-observer-assurance-to-controlValue",
    }

for _independence, _control in (
        ("independent", "correlated"),
        ("correlated", "independent")):
    BINDING_CONSUME_PROOFS[("independence", _independence)] = {
        "locus": "observerSet",
        "spec": _CBEC,
        "binding": _CBEC_BINDING,
        "observerSet": "customs_oracles",
        "specField": "independence",
        "bindingField": "independence",
        "cellValue": _independence,
        "controlValue": _control,
        "mismatchCode": "binding.observer_independence_mismatch",
        "tamper": "flip-observer-independence-to-controlValue",
    }

for _kind, _state, _control in (
        ("aborted", "REJECTED", "success"),
        ("contested", "CONTESTED", "success"),
        ("success", "CLOSED", "aborted")):
    _tamper_state = {"aborted": "CLOSED", "contested": "CLOSED", "success": "REJECTED"}[_kind]
    BINDING_CONSUME_PROOFS[("terminal_kind", _kind)] = {
        "locus": "lifecycleState",
        "spec": _TK,
        "state": _state,
        "tamperState": _tamper_state,
        "terminalStateField": _kind,
        "specField": "terminalKind",
        "cellValue": _kind,
        "controlValue": _control,
        "mismatchCode": "spec.bad_terminal_state",
        "tamper": "rewire-terminalStates-to-tamperState",
    }

for _idem, _control in (
        ("reject", "noop_on_identical"),
        ("noop_on_identical", "reject")):
    BINDING_CONSUME_PROOFS[("idempotency", _idem)] = {
        "locus": "lifecycleTransition",
        "spec": _MPRP,
        "transition": "COMMIT",
        "specField": "idempotency",
        "cellValue": _idem,
        "controlValue": _control,
        "consumer": "neutrino-gen --target=coordination-plan --from-spec",
    }

for _effect in ("compensate", "consume", "post", "release", "reserve"):
    _control_effect = "reserve" if _effect == "post" else "post"
    BINDING_CONSUME_PROOFS[("transition_effect", _effect)] = {
        "locus": "lifecycleTransition",
        "spec": _MPRP,
        "transition": "COMMIT",
        "specField": "effects",
        "cellValue": [_effect],
        "controlValue": [_control_effect],
        "consumer": "neutrino-gen --target=coordination-plan --from-spec",
    }

for _assurance in ("", "A1"):
    BINDING_CONSUME_PROOFS[("bind_min_assurance", _assurance)] = {
        "locus": "participant",
        "spec": _CE,
        "participant": "EscrowAgent",
        "specField": "bindMinAssurance",
        "topologyField": "minAssurance",
        "cellValue": _assurance,
        "controlValue": "A2",
        "cellTopologyValue": "A1",
        "controlTopologyValue": "A2",
        "manifest": {
            "runtime": "evm",
            "assurance": "A1",
            "binder": "escrowco",
        },
        "expected": {"ok": True},
        "controlExpected": {"ok": False, "code": "NEU-2001"},
        "tamper": "flip-minAssurance-to-controlTopologyValue",
    }

for _assurance, _control, _manifest_assurance in (
        ("A2", "A1", "A1"),
        ("A3", "A2", "A2"),
        ("A4", "A3", "A3")):
    BINDING_CONSUME_PROOFS[("bind_min_assurance", _assurance)] = {
        "locus": "participant",
        "spec": _CE,
        "participant": "EscrowAgent",
        "specField": "bindMinAssurance",
        "topologyField": "minAssurance",
        "cellValue": _assurance,
        "controlValue": _control,
        "cellTopologyValue": _assurance,
        "controlTopologyValue": _control,
        "manifest": {
            "runtime": "evm",
            "assurance": _manifest_assurance,
            "binder": "escrowco",
        },
        "expected": {"ok": False, "code": "NEU-2001"},
        "controlExpected": {"ok": True},
        "tamper": "flip-minAssurance-to-controlTopologyValue",
    }


def build_binding_consume_proofs(schema=None, classification=None):
    """Return closed proofs derived from the active generator contract.

    Static proof families retain their canonical bindings, while transition
    guards are derived from the same schema/classification objects used to
    inventory manifest features. This keeps alternate --schema inputs from
    producing missing or phantom crediting cells.
    """
    proofs = copy.deepcopy(BINDING_CONSUME_PROOFS)
    guard_kinds = _live_schema_values("transition_guard", schema, classification)
    if len(guard_kinds) < 2:
        raise RuntimeError("transition_guard proof requires at least two live schema identities")
    for guard_index, guard_kind in enumerate(guard_kinds):
        control_guard_kind = guard_kinds[(guard_index + 1) % len(guard_kinds)]
        proofs[("transition_guard", guard_kind)] = {
            "locus": "lifecycleTransitionGuard",
            "spec": _MPRP,
            "transition": "COMMIT",
            "specField": "guards",
            "guardDetail": "generalism-guard-kind",
            "cellValue": guard_kind,
            "controlValue": control_guard_kind,
            "consumer": "neutrino-gen --target=coordination-plan --from-spec",
            "producerTamper": "drop-transition-guard-kind-from-capability-spec",
            "consumerTamper": "drop-transition-guard-kind-from-coordination-plan",
        }
    evidence_styles = _live_schema_values("evidence_style", schema, classification)
    if len(evidence_styles) < 2:
        raise RuntimeError("evidence_style proof requires at least two live schema identities")
    for style_index, evidence_style in enumerate(evidence_styles):
        control_style = evidence_styles[(style_index + 1) % len(evidence_styles)]
        proofs[("evidence_style", evidence_style)] = {
            "locus": "lifecycleTransitionEvidence",
            "spec": _MPRP,
            "transition": "COMMIT",
            "specField": "evidence",
            "cellValue": evidence_style,
            "controlValue": control_style,
            "evidenceChained": True,
            "consumer": "neutrino-gen --target=coordination-plan --from-spec",
            "producerTamper": "drop-transition-evidence-style-from-capability-spec",
            "consumerTamper": "drop-transition-evidence-style-from-coordination-plan",
        }
    return proofs

S1C_BINDING_LIFECYCLE_FAMILIES = frozenset({
    "assurance",
    "independence",
    "bind_min_assurance",
    "terminal_kind",
    "idempotency",
    "transition_effect",
    "transition_guard",
    "evidence_style",
    "participant_binding",
})

_S1C_BLOCKED_REASON = (
    "no committed canonical artifact yet proves valid-value carry-and-consume at the first authoritative "
    "binding/render consumer; invalid-enum spec refusal is not coverage credit"
)


def _s1c_disposition_for(fam, val, binding_consume_proofs=None):
    """Return the  disposition for one derived binding/lifecycle row.

    The disposition table is intentionally NOT a coverage table: it records whether the row has a
    non-crediting validator-contract fixture today, or remains blocked until a valid<->valid consumer
    differential exists. The row inventory itself is derived from schema/catalog data.
    """
    if binding_consume_proofs is None:
        binding_consume_proofs = build_binding_consume_proofs()
    key = (fam, val)
    if key in binding_consume_proofs:
        p = binding_consume_proofs[key]
        out = {
            "family": fam,
            "value": val,
            "status": "valid_carry_and_consume",
            "creditsCoverage": True,
            "cellId": f"bind:{fam}:{val}".replace("/", "_").replace("-", "minus"),
            "spec": p["spec"],
            "locus": p.get("locus", "participant"),
            "specField": p["specField"],
            "cellValue": p["cellValue"],
            "controlValue": p["controlValue"],
            "requiredProof": "valid_carry_and_consume",
            "reason": "schema-valid binding/lifecycle value is carried into the derived topology and "
                      "consumed by the binding-manifest validator with a valid<->valid behavioral delta",
        }
        if p.get("locus", "participant") == "participant":
            return out | {
                "participant": p["participant"],
                "topologyField": p["topologyField"],
                "cellTopologyValue": p["cellTopologyValue"],
                "controlTopologyValue": p["controlTopologyValue"],
                "consumer": "scripts/validators/validate_binding_manifest.py",
            }
        if p.get("locus") == "observerSet":
            return out | {
                "binding": p["binding"],
                "observerSet": p["observerSet"],
                "bindingField": p["bindingField"],
                "consumer": "scripts/validators/validate_observation_binding.py",
                "mismatchCode": p["mismatchCode"],
                "reason": "schema-valid observer-set value is carried in a rebuilt capability-spec and "
                          "consumed by the observation-binding validator through an exact valid<->valid "
                          "binding equality check",
            }
        if p.get("locus") == "lifecycleTransitionGuard":
            return out | {
                "transition": p["transition"],
                "guardDetail": p["guardDetail"],
                "consumer": p["consumer"],
                "producerTamper": p["producerTamper"],
                "consumerTamper": p["consumerTamper"],
                "reason": "schema-derived transition guard kind is carried at a content-located guard "
                          "in a rebuilt capability-spec and consumed through an exact valid<->valid "
                          "coordination-plan byte delta with independent producer/consumer drop tampers",
            }
        if p.get("locus") == "lifecycleTransitionEvidence":
            return out | {
                "transition": p["transition"],
                "evidenceChained": p["evidenceChained"],
                "consumer": p["consumer"],
                "producerTamper": p["producerTamper"],
                "consumerTamper": p["consumerTamper"],
                "reason": "schema-derived transition evidence style is carried with an independent "
                          "chained obligation in a rebuilt capability-spec and consumed through an exact "
                          "valid<->valid coordination-plan byte delta with producer/consumer drop tampers",
            }
        if p.get("locus") == "lifecycleTransition":
            return out | {
                "transition": p["transition"],
                "consumer": p["consumer"],
                "reason": "schema-valid transition field is carried in a rebuilt capability-spec and "
                          "consumed by the coordination-plan from-spec renderer through an exact "
                          "valid<->valid coordination-plan byte delta",
            }
        if p.get("locus") == "lifecycleState":
            return out | {
                "state": p["state"],
                "tamperState": p["tamperState"],
                "terminalStateField": p["terminalStateField"],
                "consumer": "scripts/validators/validate_capability_spec.py",
                "mismatchCode": p["mismatchCode"],
                "reason": "schema-valid terminalKind is carried by a terminal lifecycle state and consumed "
                          "by the capability-spec validator through the lifecycle.terminalStates mapping",
            }
        raise AssertionError(f"unsupported consume proof locus {p.get('locus')!r}")
    if key in BINDING_LOCUS:
        e = BINDING_LOCUS[key]
        return {
            "family": fam,
            "value": val,
            "status": "validator_contract",
            "creditsCoverage": False,
            "cellId": f"bind:{fam}:{val}".replace("/", "_").replace("-", "minus"),
            "spec": e["spec"],
            "locator": {"array": e["array"], "sub": e["sub"], "value": e["value"],
                        "contains": bool(e.get("contains"))},
            "refusalCode": e["code"],
            "reason": "field-specific invalid-sentinel validator proof only; awaiting valid-value "
                      "carry-and-consume witness",
        }
    return {
        "family": fam,
        "value": val,
        "status": "blocked",
        "creditsCoverage": False,
        "blockingIssue": "neutrino-",
        "requiredProof": "valid_carry_and_consume",
        "reason": _S1C_BLOCKED_REASON,
    }


def derive_binding_lifecycle_rows(schema, classification):
    features, _ = derive_features(schema, classification)
    return [(fam, val, source, coord) for fam, val, source, coord in features
            if fam in S1C_BINDING_LIFECYCLE_FAMILIES]


def build_binding_lifecycle_dispositions(schema, classification, binding_consume_proofs=None):
    if binding_consume_proofs is None:
        binding_consume_proofs = build_binding_consume_proofs(schema, classification)
    return [
        _s1c_disposition_for(fam, val, binding_consume_proofs) |
        {"source": source, "coordinate": coord}
        for fam, val, source, coord in derive_binding_lifecycle_rows(schema, classification)
    ]


def binding_lifecycle_disposition_violations(manifest, schema=None, classification=None):
    """Fail-closed  ledger check.

    Every derived binding/lifecycle row must have exactly one disposition. Validator-contract rows must
    point at a real NON-CREDITING binding cell that is bound to BINDING_LOCUS; blocked rows must stay
    explicitly non-crediting and name the missing proof. This prevents both hidden debt and accidental
    baseline shrinkage from invalid-schema tests.
    """
    if schema is None:
        schema = json.load(open(SCHEMA, encoding="utf-8"))
    if classification is None:
        classification = json.load(open(CLASSIFICATION, encoding="utf-8"))
    binding_consume_proofs = build_binding_consume_proofs(schema, classification)
    expected = {(fam, val) for fam, val, _source, _coord in
                derive_binding_lifecycle_rows(schema, classification)}
    dispositions = manifest.get("bindingLifecycleDispositions")
    if not isinstance(dispositions, list):
        return ["bindingLifecycleDispositions is missing or not an array"]

    bad = []
    seen = {}
    cells = {c.get("id"): c for c in manifest.get("cells", [])}
    for d in dispositions:
        key = (d.get("family"), d.get("value"))
        if key in seen:
            bad.append(f"duplicate binding/lifecycle disposition for {list(key)}")
            continue
        seen[key] = d
        if key not in expected:
            bad.append(f"disposition {list(key)} is not a derived  binding/lifecycle row")
            continue
        if d.get("creditsCoverage") not in (False, True):
            bad.append(f"disposition {list(key)} must declare creditsCoverage as a boolean")
        status = d.get("status")
        if status == "valid_carry_and_consume":
            if d.get("creditsCoverage") is not True:
                bad.append(f"valid-carry-and-consume disposition {list(key)} must credit coverage")
            proof = binding_consume_proofs.get(key)
            if not proof:
                bad.append(f"valid-carry-and-consume disposition {list(key)} has no closed proof binding")
                continue
            cell = cells.get(d.get("cellId"))
            if not cell:
                bad.append(f"valid-carry-and-consume disposition {list(key)} points at missing cell "
                           f"{d.get('cellId')!r}")
                continue
            if cell.get("credits") is not True:
                bad.append(f"valid-carry-and-consume disposition {list(key)} points at non-crediting cell "
                           f"{cell.get('id')}")
            if tuple((cell.get("covers") or [[]])[0]) != key:
                bad.append(f"valid-carry-and-consume disposition {list(key)} points at cell with covers "
                           f"{cell.get('covers')}")
            if not cell.get("consumeProof"):
                bad.append(f"valid-carry-and-consume disposition {list(key)} points at cell without "
                           "consumeProof")
            if d.get("locus") != proof.get("locus", "participant"):
                bad.append(f"valid-carry-and-consume disposition {list(key)} does not match the closed "
                           "binding consume proof locus")
            if (d.get("spec") != proof["spec"] or d.get("specField") != proof["specField"] or
                    d.get("cellValue") != proof["cellValue"] or d.get("controlValue") != proof["controlValue"]):
                bad.append(f"valid-carry-and-consume disposition {list(key)} does not match the closed "
                           "binding consume proof")
            if proof.get("locus", "participant") == "participant":
                if (d.get("participant") != proof["participant"] or
                        d.get("topologyField") != proof["topologyField"] or
                        d.get("cellTopologyValue") != proof["cellTopologyValue"] or
                        d.get("controlTopologyValue") != proof["controlTopologyValue"]):
                    bad.append(f"valid-carry-and-consume disposition {list(key)} does not match the closed "
                               "participant consume proof")
            elif proof.get("locus") == "observerSet":
                if (d.get("binding") != proof["binding"] or d.get("observerSet") != proof["observerSet"] or
                        d.get("bindingField") != proof["bindingField"] or
                        d.get("mismatchCode") != proof["mismatchCode"]):
                    bad.append(f"valid-carry-and-consume disposition {list(key)} does not match the closed "
                               "observer-set consume proof")
            elif proof.get("locus") == "lifecycleTransition":
                if d.get("transition") != proof["transition"] or d.get("consumer") != proof["consumer"]:
                    bad.append(f"valid-carry-and-consume disposition {list(key)} does not match the closed "
                               "lifecycle-transition consume proof")
            elif proof.get("locus") == "lifecycleTransitionGuard":
                if (d.get("transition") != proof["transition"] or
                        d.get("guardDetail") != proof["guardDetail"] or
                        d.get("consumer") != proof["consumer"] or
                        d.get("producerTamper") != proof["producerTamper"] or
                        d.get("consumerTamper") != proof["consumerTamper"]):
                    bad.append(f"valid-carry-and-consume disposition {list(key)} does not match the closed "
                               "lifecycle-transition-guard consume proof")
            elif proof.get("locus") == "lifecycleTransitionEvidence":
                if (d.get("transition") != proof["transition"] or
                        d.get("evidenceChained") != proof["evidenceChained"] or
                        d.get("consumer") != proof["consumer"] or
                        d.get("producerTamper") != proof["producerTamper"] or
                        d.get("consumerTamper") != proof["consumerTamper"]):
                    bad.append(f"valid-carry-and-consume disposition {list(key)} does not match the closed "
                               "lifecycle-transition-evidence consume proof")
            elif (d.get("state") != proof["state"] or
                  d.get("tamperState") != proof["tamperState"] or
                  d.get("terminalStateField") != proof["terminalStateField"] or
                  d.get("mismatchCode") != proof["mismatchCode"]):
                bad.append(f"valid-carry-and-consume disposition {list(key)} does not match the closed "
                           "lifecycle-state consume proof")
            v = binding_consume_proof_violations(cell, binding_consume_proofs)
            if v:
                bad.append(f"valid-carry-and-consume disposition {list(key)} has unbound consume proof: {v[0]}")
        elif status == "validator_contract":
            if d.get("creditsCoverage") is not False:
                bad.append(f"validator-contract disposition {list(key)} must be explicitly non-crediting")
            cell = cells.get(d.get("cellId"))
            if not cell:
                bad.append(f"validator-contract disposition {list(key)} points at missing cell "
                           f"{d.get('cellId')!r}")
                continue
            if cell.get("credits"):
                bad.append(f"validator-contract disposition {list(key)} points at crediting cell "
                           f"{cell.get('id')}")
            if tuple((cell.get("covers") or [[]])[0]) != key:
                bad.append(f"validator-contract disposition {list(key)} points at cell with covers "
                           f"{cell.get('covers')}")
            v = binding_locus_violations(cell)
            if v:
                bad.append(f"validator-contract disposition {list(key)} has unbound locus: {v[0]}")
            loc = d.get("locator") or {}
            if (d.get("spec") != cell.get("spec") or d.get("refusalCode") != cell.get("refusalCode") or
                    loc != (cell.get("locator") or {})):
                bad.append(f"validator-contract disposition {list(key)} does not match its binding cell")
        elif status == "blocked":
            if d.get("creditsCoverage") is not False:
                bad.append(f"blocked disposition {list(key)} must be explicitly non-crediting")
            if d.get("requiredProof") != "valid_carry_and_consume":
                bad.append(f"blocked disposition {list(key)} must require valid_carry_and_consume")
            if not d.get("blockingIssue") or not d.get("reason"):
                bad.append(f"blocked disposition {list(key)} must carry blockingIssue and reason")
        else:
            bad.append(f"disposition {list(key)} has invalid status {status!r}")

    missing = sorted(expected - set(seen))
    if missing:
        bad.append(f"missing binding/lifecycle disposition(s): {[list(x) for x in missing]}")
    return bad


def _dget(obj, dotted):
    for k in dotted.split("."):
        if not isinstance(obj, dict) or k not in obj:
            return None
        obj = obj[k]
    return obj


def _dset(obj, dotted, value):
    ks = dotted.split(".")
    for k in ks[:-1]:
        obj = obj[k]
    obj[ks[-1]] = value


def _locate(spec, entry):
    """Return the index of the first element of spec[array] whose `sub` field holds `value` (== or, for a
    `contains` array field, membership), or None. Content-based, so array-index drift can't silently
    mis-target."""
    arr = _dget(spec, entry["array"]) or []
    for i, el in enumerate(arr):
        got = _dget(el, entry["sub"])
        if (entry.get("contains") and isinstance(got, list) and entry["value"] in got) or got == entry["value"]:
            return i
    return None


def _consume_proof_for(p):
    common = {
        "kind": "valid_carry_and_consume",
        "locus": p.get("locus", "participant"),
        "spec": p["spec"],
        "specField": p["specField"],
        "cellValue": p["cellValue"],
        "controlValue": p["controlValue"],
    }
    if "tamper" in p:
        common["tamper"] = p["tamper"]
    if p.get("locus") == "observerSet":
        return common | {
            "binding": p["binding"],
            "observerSet": p["observerSet"],
            "bindingField": p["bindingField"],
            "consumer": "scripts/validators/validate_observation_binding.py",
            "mismatchCode": p["mismatchCode"],
            "expectedRelation": "binding observer-set field equals spec observer-set field",
        }
    if p.get("locus") == "lifecycleState":
        return common | {
            "state": p["state"],
            "tamperState": p["tamperState"],
            "terminalStateField": p["terminalStateField"],
            "consumer": "scripts/validators/validate_capability_spec.py",
            "mismatchCode": p["mismatchCode"],
            "expectedRelation": "lifecycle.terminalStates entry resolves to a terminal state with matching "
                                "terminalKind",
        }
    if p.get("locus") == "lifecycleTransitionGuard":
        return common | {
            "transition": p["transition"],
            "guardDetail": p["guardDetail"],
            "consumer": p["consumer"],
            "producerTamper": p["producerTamper"],
            "consumerTamper": p["consumerTamper"],
            "expectedRelation": "content-located coordination-plan transition guard carries the spec "
                                "guard kind byte-for-byte",
        }
    if p.get("locus") == "lifecycleTransitionEvidence":
        return common | {
            "transition": p["transition"],
            "evidenceChained": p["evidenceChained"],
            "consumer": p["consumer"],
            "producerTamper": p["producerTamper"],
            "consumerTamper": p["consumerTamper"],
            "expectedRelation": "content-located coordination-plan transition evidence carries style "
                                "byte-for-byte without inferring the independent chained obligation",
        }
    if p.get("locus") == "lifecycleTransition":
        return common | {
            "transition": p["transition"],
            "consumer": p["consumer"],
            "expectedRelation": "coordination-plan lifecycleTransitions entry carries the spec transition "
                                "field byte-for-byte",
        }
    return common | {
        "participant": p["participant"],
        "topologyField": p["topologyField"],
        "cellTopologyValue": p["cellTopologyValue"],
        "controlTopologyValue": p["controlTopologyValue"],
        "manifest": p["manifest"],
        "consumer": "scripts/validators/validate_binding_manifest.py",
        "expected": p["expected"],
        "controlExpected": p["controlExpected"],
    }


def build_binding_cells(binding_consume_proofs=None):
    """One binding/lifecycle cell per witnessable row. Validator-contract rows use BINDING_LOCUS; valid
    carry-and-consume rows use BINDING_CONSUME_PROOFS and may not have an invalid-sentinel locus."""
    if binding_consume_proofs is None:
        binding_consume_proofs = build_binding_consume_proofs()
    out = []
    keys = sorted(set(BINDING_LOCUS) | set(binding_consume_proofs))
    for fam, val in keys:
        key = (fam, val)
        p = binding_consume_proofs.get(key)
        e = BINDING_LOCUS.get(key)
        if p:
            if p.get("locus", "participant") == "participant":
                locator = {
                    "array": "participants",
                    "sub": p["specField"],
                    "participant": p["participant"],
                    "value": p["cellValue"],
                    "topologyField": p["topologyField"],
                    "topologyValue": p["cellTopologyValue"],
                }
                note = (f"schema-valid {fam}={val} is derived from {p['spec']} by setting "
                        f"{p['participant']}.{p['specField']} to {p['cellValue']!r}; the native slot "
                        f"producer must carry {p['topologyField']}={p['cellTopologyValue']!r} and the "
                        "binding-manifest validator must observe the declared valid<->valid delta")
                note += (
                    "; coverage credit requires valid<->valid carry-and-consume proof: "
                    f"{p['participant']} {p['specField']} {p['cellValue']!r} vs {p['controlValue']!r} changes "
                    "the binding-manifest validator observation"
                )
            elif p.get("locus") == "observerSet":
                locator = {
                    "array": "attestations",
                    "sub": "observerSet." + p["specField"],
                    "observerSet": p["observerSet"],
                    "bindingField": p["bindingField"],
                    "value": p["cellValue"],
                }
                note = (f"schema-valid {fam}={val} is derived from {p['spec']} by setting observer-set "
                        f"{p['observerSet']}.{p['specField']} to {p['cellValue']!r}; the observation-binding "
                        f"consumer must reject the valid control/tamper when {p['bindingField']} no longer "
                        f"matches the rebuilt capability-spec field with {p['mismatchCode']}")
            elif p.get("locus") in ("lifecycleTransition", "lifecycleTransitionGuard",
                                    "lifecycleTransitionEvidence"):
                locator = {
                    "array": "lifecycle.transitions",
                    "sub": p["specField"],
                    "transition": p["transition"],
                    "value": p["cellValue"],
                }
                if p.get("locus") == "lifecycleTransitionGuard":
                    locator["guardDetail"] = p["guardDetail"]
                    note = (f"schema-derived {fam}={val} is inserted at content-located lifecycle "
                            f"transition {p['transition']}.guards detail={p['guardDetail']!r}; the "
                            "coordination-plan from-spec consumer must carry the exact kind, distinguish "
                            "the schema-valid control, and detect independent producer/consumer drops")
                elif p.get("locus") == "lifecycleTransitionEvidence":
                    locator["sub"] = "evidence.style"
                    locator["evidenceChained"] = p["evidenceChained"]
                    note = (f"schema-derived {fam}={val} is inserted at content-located lifecycle "
                            f"transition {p['transition']}.evidence.style with chained fixed independently "
                            f"at {p['evidenceChained']!r}; the coordination-plan from-spec consumer must "
                            "carry the exact object, distinguish the schema-valid style control, and detect "
                            "independent producer/consumer style drops")
                else:
                    note = (f"schema-valid {fam}={val} is derived from {p['spec']} by setting lifecycle "
                            f"transition {p['transition']}.{p['specField']} to {p['cellValue']!r}; the "
                            "coordination-plan from-spec consumer must carry that exact value and produce a "
                            "different coordination-plan artifact for the valid control")
            else:
                locator = {
                    "array": "lifecycle.states",
                    "sub": p["specField"],
                    "state": p["state"],
                    "tamperState": p["tamperState"],
                    "terminalStateField": p["terminalStateField"],
                    "value": p["cellValue"],
                }
                note = (f"schema-valid {fam}={val} is derived from {p['spec']} by setting lifecycle state "
                        f"{p['state']}.{p['specField']} to {p['cellValue']!r}; the capability-spec "
                        f"consumer must reject the valid control/tamper when lifecycle.terminalStates."
                        f"{p['terminalStateField']} resolves to a state whose terminalKind is "
                        f"{p['controlValue']!r} with {p['mismatchCode']}")
            cell = {
                "covers": [fam, val], "witness": "binding_consume", "kind": "binding",
                "spec": p["spec"],
                "locator": locator,
                "note": note,
                "consumeProof": _consume_proof_for(p),
            }
        elif e:
            cell = {
                "covers": [fam, val], "witness": "spec_refusal", "kind": "binding",
                "spec": e["spec"], "locator": {"array": e["array"], "sub": e["sub"], "value": e["value"],
                                               "contains": bool(e.get("contains"))},
                "invalid": e["invalid"], "refusalCode": e["code"], "refusalMessage": e["msg"],
                "note": f"canonical spec carries {fam}={val} at {e['array']}[?].{e['sub']}; invalidating "
                        f"that one field -> the spec validator refuses with the {fam}-specific machine "
                        f"code {e['code']}",
            }
        else:
            raise AssertionError(f"binding key {key!r} has neither consume proof nor validator locus")
        out.append(cell)
    return out


def binding_locus_violations(cell):
    """Bind a binding cell's `covers` to BINDING_LOCUS (the S1c relabel guard): its spec/locator/invalid/
    refusalCode must be exactly the canonical binding for the feature it credits. Empty == correctly bound."""
    covers = cell.get("covers") or []
    if len(covers) != 1:
        return ["a crediting cell must credit exactly one feature"]
    key = tuple(covers[0])
    if key not in BINDING_LOCUS:
        return [f"feature {list(key)} has no canonical binding in BINDING_LOCUS"]
    e = BINDING_LOCUS[key]
    want = {"spec": e["spec"], "array": e["array"], "sub": e["sub"], "value": e["value"],
            "contains": bool(e.get("contains")), "invalid": e["invalid"], "code": e["code"], "msg": e["msg"]}
    got = {"spec": cell.get("spec"), "array": (cell.get("locator") or {}).get("array"),
           "sub": (cell.get("locator") or {}).get("sub"), "value": (cell.get("locator") or {}).get("value"),
           "contains": bool((cell.get("locator") or {}).get("contains")),
           "invalid": cell.get("invalid"), "code": cell.get("refusalCode"), "msg": cell.get("refusalMessage")}
    if got != want:
        return [f"binding cell is not the canonical locus for {list(key)} (relabeled/confounded)"]
    return []


def binding_consume_proof_violations(cell, binding_consume_proofs=None):
    """Bind a crediting binding cell's consumeProof to BINDING_CONSUME_PROOFS. Empty == correctly bound."""
    covers = cell.get("covers") or []
    if len(covers) != 1:
        return ["a crediting binding cell must credit exactly one feature"]
    key = tuple(covers[0])
    if binding_consume_proofs is None:
        binding_consume_proofs = build_binding_consume_proofs()
    proof = binding_consume_proofs.get(key)
    if not proof:
        return [f"feature {list(key)} has no closed binding consume proof"]
    want = _consume_proof_for(proof)
    if cell.get("consumeProof") != want:
        return [f"consumeProof is not the closed proof binding for {list(key)}"]
    return []


def load_seeds(seeds_file):
    """The 16 hand-run regression cells (), committed as stable fixtures. Each seed carries id,
    note, covers, adversarialKind, witness, an inline `neu`, an `adversarial` scenario-override, and (for
    ledger seeds) a `mutation`. Guard seeds are `render`-witnessed (not counted at S1a)."""
    if not os.path.isfile(seeds_file):
        return []
    return json.load(open(seeds_file, encoding="utf-8")).get("cells", [])


WITNESSES = ("ledger", "refusal", "render", "spec_refusal", "binding_consume")


def build_manifest(schema, classification, seeds_file):
    features, unclassified = derive_features(schema, classification)
    binding_consume_proofs = build_binding_consume_proofs(schema, classification)
    seeds = load_seeds(seeds_file)
    covered = {}   # (family, value) -> [cellId,...]  — credited ONLY by controlled-experiment cells
    cells = []

    # 1. Seed cells (regression fixtures). They are realized for a WITNESS-CLASS sanity check (ledger ->
    #    exit 0, refusal -> exit 3/4/6, render -> no signal/usage crash), but they carry NO `control` and
    #    therefore CREDIT NO coverage — coverage rests exclusively on controlled experiments below. (This
    #    is the  P1 fix: cell09/cell11 no longer credit `degenerate/boundary` from unrelated refusals.)
    for s in seeds:
        cells.append({"id": s["id"], "kind": "seed",
                      "covers": [list(c) for c in s.get("covers", [])], "credits": False,
                      "adversarialKind": s.get("adversarialKind"), "witness": s.get("witness"),
                      "note": s.get("note", ""), "input": {"neu": s["neu"]},
                      "scenario": _synth_scenario(s["neu"], s.get("adversarial"))})

    # 2. Controlled-experiment cells — each credits exactly its one covered feature (cell vs control proves
    #    the feature CAUSES the observed difference).
    for built in build_controlled_cells():
        fam, val = built["covers"][0]
        cid = f"gen:{fam}:{val}".replace("/", "_").replace("-", "minus")
        cell = {"id": cid, "kind": "generated", "credits": True,
                "covers": [[fam, val]], "adversarialKind": built["adversarialKind"],
                "witness": built["witness"], "note": built["note"], "input": built["input"],
                "scenario": built["scenario"], "adversarial": built.get("adversarial", {}),
                "mutation": built["mutation"], "control": built["control"]}
        if "refusalCode" in built:
            cell["refusalCode"] = built["refusalCode"]
        cells.append(cell)
        covered.setdefault((fam, val), []).append(cid)

    # 3. S1c binding/lifecycle cells (). Most are NON-CREDITING validator-contract fixtures:
    #    invalidating a field proves the spec validator RECOGNIZES it, but NOT that either schema-valid value
    #    is CONSUMED by the first authoritative consumer. For closed BINDING_CONSUME_PROOFS rows we derive
    #    both schema-valid canonical specs, carry the value through the authoritative locus, and prove the
    #    relevant consumer changes observation. ONLY those rows credit coverage.
    for built in build_binding_cells(binding_consume_proofs):
        fam, val = built["covers"]
        cid = f"bind:{fam}:{val}".replace("/", "_").replace("-", "minus")
        credits = (fam, val) in binding_consume_proofs
        cell = {"id": cid, "kind": "binding", "credits": credits, "covers": [[fam, val]],
                "witness": built["witness"], "note": built["note"], "spec": built["spec"],
                "locator": built["locator"]}
        for optional in ("invalid", "refusalCode", "refusalMessage"):
            if optional in built:
                cell[optional] = built[optional]
        if built.get("consumeProof"):
            cell["consumeProof"] = built["consumeProof"]
        cells.append(cell)
        if credits:
            covered.setdefault((fam, val), []).append(cid)

    uncovered = sorted([list(f[:2]) for f in features if (f[0], f[1]) not in covered])
    witnessed = sum(1 for c in cells if c.get("credits"))
    binding_lifecycle_dispositions = build_binding_lifecycle_dispositions(
        schema, classification, binding_consume_proofs)
    return {
        "schemaId": schema.get("$id"),
        "classificationVersion": classification.get("schemaVersion"),
        "featureCount": len(features),
        "coveredCount": len(features) - len(uncovered),
        "cellCount": len(cells),
        "witnessedCellCount": witnessed,
        "seedCount": len(seeds),
        "unclassifiedCoordinates": unclassified,
        "uncoveredFeatures": uncovered,
        "bindingLifecycleDispositions": binding_lifecycle_dispositions,
        "features": [{"family": f[0], "value": f[1], "source": f[2], "coordinate": f[3],
                      "cells": covered.get((f[0], f[1]), [])} for f in features],
        "cells": cells,
    }


def render(manifest):
    return json.dumps(manifest, indent=2, sort_keys=False) + "\n"


# ---- mechanical witness proof (--prove-witness) ---------------------------------------------------

def _realize(neutrino_gen, neu, scenario, workdir):
    """Run neutrino-gen --target=capability --scenario=<materialized> and return a NORMALIZED observation:
    (exit_code, sha256(solidity.json)|None, sha256(postgres.json)|None, diagnostics_text)."""
    src = os.path.join(workdir, "cell.neu")
    scn = os.path.join(workdir, "scn.json")
    out = os.path.join(workdir, "o")
    open(src, "w", encoding="utf-8").write(neu)
    json.dump(scenario, open(scn, "w", encoding="utf-8"))
    r = subprocess.run([neutrino_gen, "--target=capability", "--scenario=" + scn, src, "-o", out],
                       capture_output=True, text=True)

    def sha(fn):
        p = os.path.join(out, fn)
        return hashlib.sha256(open(p, "rb").read()).hexdigest() if os.path.isfile(p) else None
    return (r.returncode, sha("solidity.json"), sha("postgres.json"), (r.stderr or "") + (r.stdout or ""))


def prove_witness(manifest, neutrino_gen):
    """Prove witnesses against the real CLI. A CREDITING cell is a CONTROLLED EXPERIMENT: realize the cell
    AND its control (identical but for the one feature coordinate) and require the feature CAUSES the
    difference. Non-crediting seed fixtures get a witness-class sanity check only. Returns failure strings
    (empty == all hold)."""
    bad = []
    for c in manifest["cells"]:
        witness = c.get("witness")
        neu = c.get("input", {}).get("neu")
        scn = c.get("scenario")
        if not neu or not scn:
            continue
        with tempfile.TemporaryDirectory() as td:
            cell_obs = _realize(neutrino_gen, neu, scn, td)

            if not c.get("credits"):
                # Seed fixture: witness-class sanity only (it credits no feature;  P1).
                if witness == "ledger" and cell_obs[0] != 0:
                    bad.append(f"{c['id']}: ledger seed does not realize (exit {cell_obs[0]})")
                elif witness == "refusal" and cell_obs[0] not in (3, 4, 6):
                    bad.append(f"{c['id']}: refusal seed did not refuse (exit {cell_obs[0]})")
                elif witness == "render" and cell_obs[0] not in (0, 3, 4, 6):
                    bad.append(f"{c['id']}: render seed crashed (exit {cell_obs[0]}; not a clean 0/3/4/6)")
                continue

            # Crediting controlled experiment. FIRST bind covers->mutation (the mutation must be the
            # canonical locus of the credited feature — no relabeling), THEN the reconstruction check (the
            # control is exactly apply(that mutation, cell) — nothing else differs). ( P1)
            viol = feature_locus_violations(c) or control_reconstruction_violations(c)
            if viol:
                bad.append(f"{c['id']}: {viol[0]}")
                continue
            # Realize the control (its own neu + its own scenario). For a scenario mutation the control
            # shares the cell source and applies the mutation's override; otherwise it uses the derived neu.
            control = c.get("control") or {}
            ctl_neu = control.get("neu") or neu
            ctl_scn = _synth_scenario(ctl_neu, control.get("adversarial") or c.get("adversarial"))
            ctl_obs = _realize(neutrino_gen, ctl_neu, ctl_scn, td)
            if cell_obs[:3] == ctl_obs[:3]:
                bad.append(f"{c['id']}: cell and control produced the SAME observation "
                           f"(exit={cell_obs[0]}, same model sha) — the feature does not CAUSE the "
                           "difference (confounded/non-causal witness)")
                continue
            if witness == "ledger":
                if cell_obs[0] != 0:
                    bad.append(f"{c['id']}: ledger cell does not realize (exit {cell_obs[0]})")
            elif witness == "refusal":
                code = c.get("refusalCode")
                if cell_obs[0] not in (3, 4, 6):
                    bad.append(f"{c['id']}: refusal cell did not refuse (exit {cell_obs[0]}; expected 3/4/6)")
                elif not code or code not in cell_obs[3]:
                    bad.append(f"{c['id']}: refusal is not the intended coded refusal "
                               f"(expected {code!r} in diagnostics)")
                elif code in ctl_obs[3]:
                    bad.append(f"{c['id']}: the control ALSO emits {code!r} — the refusal is not caused by "
                               "the feature (the control was meant to normalize it away)")
    return bad


def _validate_spec(validator, spec_obj, workdir):
    """Run the capability-spec validator on a spec object; return (exit_code, [error {code,message} dicts])."""
    p = os.path.join(workdir, "spec.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(spec_obj, f)
    r = subprocess.run([sys.executable, validator, p], capture_output=True, text=True)
    diags = []
    try:
        rep = json.loads(r.stdout)
        diags = [{"code": d.get("code"), "message": d.get("message", "")}
                 for d in rep.get("diagnostics", []) if d.get("severity") == "error"]
    except (ValueError, KeyError):
        pass
    return r.returncode, diags


def _compact_json(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_json(obj):
    return hashlib.sha256(_compact_json(obj).encode("utf-8")).hexdigest()


def _rebuild_capability_spec_identity(spec):
    """Recompute the same identity fields validate_capability_spec.py enforces. The consume proof mutates a
    schema-valid binding value, so identity must be rebuilt rather than waived."""
    out = copy.deepcopy(spec)
    core = copy.deepcopy(out)
    for k in ("identity", "sourceMap", "targetRequirements", "kind", "schemaVersion"):
        core.pop(k, None)
    capability_hash = _sha256_json(core)
    body = copy.deepcopy(out)
    body["identity"] = {"capabilityHash": capability_hash}
    out["identity"] = {
        "capabilityHash": capability_hash,
        "specHash": _sha256_json(body),
    }
    return out


def _participant(spec, name):
    for p in spec.get("participants") or []:
        if p.get("name") == name:
            return p
    return None


def _spec_with_participant_binding(spec, participant_name, value):
    return _spec_with_participant_field(spec, participant_name, "binding", value)


def _spec_with_participant_field(spec, participant_name, field, value):
    out = copy.deepcopy(spec)
    p = _participant(out, participant_name)
    if p is None:
        raise ValueError(f"participant {participant_name!r} is missing")
    p[field] = value
    return _rebuild_capability_spec_identity(out)


def _attestation_observer_set(spec, ref):
    for a in spec.get("attestations") or []:
        os_ = a.get("observerSet") if isinstance(a, dict) else None
        if isinstance(os_, dict) and os_.get("ref") == ref:
            return os_
    return None


def _spec_with_observer_set_field(spec, observer_set_ref, field, value):
    out = copy.deepcopy(spec)
    os_ = _attestation_observer_set(out, observer_set_ref)
    if os_ is None:
        raise ValueError(f"observer-set {observer_set_ref!r} is missing")
    os_[field] = value
    return _rebuild_capability_spec_identity(out)


def _lifecycle_state(spec, state_name):
    lifecycle = spec.get("lifecycle") or {}
    for s in lifecycle.get("states") or []:
        if isinstance(s, dict) and s.get("name") == state_name:
            return s
    return None


def _spec_with_lifecycle_state_field(spec, state_name, field, value):
    out = copy.deepcopy(spec)
    s = _lifecycle_state(out, state_name)
    if s is None:
        raise ValueError(f"lifecycle state {state_name!r} is missing")
    s[field] = value
    return _rebuild_capability_spec_identity(out)


def _terminal_state_ref(spec, terminal_state_field):
    terminal_states = (spec.get("lifecycle") or {}).get("terminalStates") or {}
    return terminal_states.get(terminal_state_field)


def _spec_with_terminal_state_ref(spec, terminal_state_field, state_name):
    out = copy.deepcopy(spec)
    terminal_states = (out.get("lifecycle") or {}).get("terminalStates")
    if not isinstance(terminal_states, dict):
        raise ValueError("lifecycle.terminalStates is missing")
    if terminal_state_field not in terminal_states:
        raise ValueError(f"terminalStates field {terminal_state_field!r} is missing")
    if _lifecycle_state(out, state_name) is None:
        raise ValueError(f"lifecycle state {state_name!r} is missing")
    terminal_states[terminal_state_field] = state_name
    return _rebuild_capability_spec_identity(out)


def _lifecycle_transition(spec, transition_name):
    lifecycle = spec.get("lifecycle") or {}
    for t in lifecycle.get("transitions") or []:
        if isinstance(t, dict) and t.get("name") == transition_name:
            return t
    return None


def _spec_with_lifecycle_transition_field(spec, transition_name, field, value):
    out = copy.deepcopy(spec)
    t = _lifecycle_transition(out, transition_name)
    if t is None:
        raise ValueError(f"lifecycle transition {transition_name!r} is missing")
    t[field] = value
    return _rebuild_capability_spec_identity(out)


def _transition_guard_by_detail(document, transition_name, detail, coordination_artifact=False):
    transition = (_coordination_plan_lifecycle_transition(document, transition_name)
                  if coordination_artifact else _lifecycle_transition(document, transition_name))
    for guard in (transition or {}).get("guards") or []:
        if isinstance(guard, dict) and guard.get("detail") == detail:
            return guard
    return None


def _spec_with_lifecycle_transition_guard_kind(spec, transition_name, detail, kind):
    out = copy.deepcopy(spec)
    transition = _lifecycle_transition(out, transition_name)
    if transition is None:
        raise ValueError(f"lifecycle transition {transition_name!r} is missing")
    guards = transition.get("guards")
    if not isinstance(guards, list):
        raise ValueError(f"lifecycle transition {transition_name!r} guards is not an array")
    if any(isinstance(g, dict) and g.get("detail") == detail for g in guards):
        raise ValueError(f"lifecycle transition {transition_name!r} already has guard detail {detail!r}")
    guards.append({"kind": kind, "detail": detail})
    return _rebuild_capability_spec_identity(out)


def _spec_with_dropped_transition_guard_kind(spec, transition_name, detail):
    out = copy.deepcopy(spec)
    guard = _transition_guard_by_detail(out, transition_name, detail)
    if guard is None:
        raise ValueError(f"lifecycle transition {transition_name!r} has no guard detail {detail!r}")
    guard.pop("kind", None)
    return _rebuild_capability_spec_identity(out)


def _coordination_plan_with_dropped_transition_guard_kind(coordination_artifact, transition_name, detail):
    out = copy.deepcopy(coordination_artifact)
    guard = _transition_guard_by_detail(out, transition_name, detail, coordination_artifact=True)
    if guard is None:
        raise ValueError(f"coordination-plan transition {transition_name!r} has no guard detail {detail!r}")
    guard.pop("kind", None)
    return out


def _transition_evidence(document, transition_name, coordination_artifact=False):
    transition = (_coordination_plan_lifecycle_transition(document, transition_name)
                  if coordination_artifact else _lifecycle_transition(document, transition_name))
    evidence = (transition or {}).get("evidence")
    return evidence if isinstance(evidence, dict) else None


def _spec_with_lifecycle_transition_evidence_style(spec, transition_name, style, chained):
    out = copy.deepcopy(spec)
    transition = _lifecycle_transition(out, transition_name)
    if transition is None:
        raise ValueError(f"lifecycle transition {transition_name!r} is missing")
    transition["evidence"] = {"style": style, "chained": chained}
    requirements = out.get("targetRequirements")
    if not isinstance(requirements, dict):
        raise ValueError("targetRequirements is missing")
    requirements["evidenceStyle"] = style
    return _rebuild_capability_spec_identity(out)


def _spec_with_dropped_transition_evidence_style(spec, transition_name):
    out = copy.deepcopy(spec)
    evidence = _transition_evidence(out, transition_name)
    if evidence is None:
        raise ValueError(f"lifecycle transition {transition_name!r} has no evidence object")
    evidence.pop("style", None)
    return _rebuild_capability_spec_identity(out)


def _coordination_plan_with_dropped_transition_evidence_style(coordination_artifact, transition_name):
    out = copy.deepcopy(coordination_artifact)
    evidence = _transition_evidence(out, transition_name, coordination_artifact=True)
    if evidence is None:
        raise ValueError(f"coordination-plan transition {transition_name!r} has no evidence object")
    evidence.pop("style", None)
    return out


def _coordination_plan_lifecycle_transition(coordination_plan, transition_name):
    for t in coordination_plan.get("lifecycleTransitions") or []:
        if isinstance(t, dict) and t.get("name") == transition_name:
            return t
    return None


def _capability_spec_identity_is_rebuilt(spec):
    return (spec.get("identity") or {}) == (_rebuild_capability_spec_identity(spec).get("identity") or {})


def _diag_codes(diags):
    return sorted(d.get("code") for d in diags if d.get("code"))


def _observer_binding_set(binding, ref):
    for s in binding.get("observerSets") or []:
        if isinstance(s, dict) and s.get("ref") == ref:
            return s
    return None


def _binding_with_observer_set_field(binding, observer_set_ref, field, value):
    out = copy.deepcopy(binding)
    s = _observer_binding_set(out, observer_set_ref)
    if s is None:
        raise ValueError(f"observer-set binding {observer_set_ref!r} is missing")
    s[field] = value
    return out


def _binding_matching_observer_set(binding, spec, observer_set_ref):
    out = copy.deepcopy(binding)
    s = _observer_binding_set(out, observer_set_ref)
    os_ = _attestation_observer_set(spec, observer_set_ref)
    if s is None:
        raise ValueError(f"observer-set binding {observer_set_ref!r} is missing")
    if os_ is None:
        raise ValueError(f"observer-set {observer_set_ref!r} is missing")
    for field in ("assurance", "independence"):
        if field in os_:
            s[field] = os_[field]
        else:
            s.pop(field, None)
    return out


def _render_slot_topology(slot_spec_renderer, spec, workdir, label):
    """Render slot artifacts through the native public generateSlotFromSpec() path and return the emitted
    binding topology. This is intentionally not a Python topology mirror:  coverage credit rests on the
    authoritative slot producer carrying participant_binding into the consumer-facing artifact."""
    spec_path = os.path.join(workdir, f"{label}.capability-spec.json")
    out_dir = os.path.join(workdir, f"{label}.slot")
    with open(spec_path, "w", encoding="utf-8") as f:
        json.dump(spec, f, sort_keys=True)
    r = subprocess.run([slot_spec_renderer, spec_path, out_dir], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"native slot renderer failed for {label} (exit {r.returncode}): "
                           f"{(r.stderr or r.stdout).strip()}")
    topology_path = os.path.join(out_dir, "binding-topology.json")
    if not os.path.isfile(topology_path):
        raise RuntimeError(f"native slot renderer did not emit binding-topology.json for {label}")
    with open(topology_path, encoding="utf-8") as f:
        return json.load(f)


def _topology_participant_slot(topology, participant_name):
    for org in topology.get("organizations") or []:
        for p in org.get("participants") or []:
            if p.get("participantId") != participant_name:
                continue
            slots = p.get("slots") or []
            return org.get("organizationId") or "", p, slots[0] if slots else None
    return None, None, None


def _binding_manifest_for_topology(topology, proof):
    participant = proof["participant"]
    org_id, _participant_obj, slot = _topology_participant_slot(topology, participant)
    if slot is None:
        raise ValueError(f"participant {participant!r} is missing from emitted topology")
    m = proof["manifest"]
    return {
        "kind": "neutrino.binding-manifest",
        "schemaVersion": 1,
        "capability": topology.get("capability") or "",
        "bindings": [{
            "organizationId": org_id,
            "participantId": participant,
            "slotId": slot.get("slotId") or "",
            "runtime": m["runtime"],
            "assurance": m["assurance"],
            "binder": m["binder"],
        }],
    }


def _set_topology_slot_field(topology, participant_name, field, value, proof):
    """Flip exactly the selected topology field for the participant. Used as the non-vacuity tamper: if the
    consumer result does not change, the proof is not observing the carried value."""
    out = copy.deepcopy(topology)
    _org, _participant_obj, slot = _topology_participant_slot(out, participant_name)
    if slot is None:
        raise ValueError(f"participant {participant_name!r} is missing from topology")
    if field == "minAssurance":
        slot["minAssurance"] = value
        return out
    if field != "lateBindingMode":
        raise ValueError(f"unsupported topology tamper field {field!r}")
    slot["lateBindingMode"] = value
    if value == "to_be_bound":
        slot["allowedRuntimes"] = [proof["manifest"]["runtime"]]
        slot["minAssurance"] = proof["manifest"]["assurance"]
        slot["authorizedBinder"] = proof["manifest"]["binder"]
    else:
        slot["allowedRuntimes"] = []
        slot["minAssurance"] = "A1"
        slot.pop("authorizedBinder", None)
    return out


def _validate_binding_manifest(validator, manifest_obj, topology_obj, workdir):
    mp = os.path.join(workdir, "binding-manifest.json")
    tp = os.path.join(workdir, "binding-topology.json")
    with open(mp, "w", encoding="utf-8") as f:
        json.dump(manifest_obj, f)
    with open(tp, "w", encoding="utf-8") as f:
        json.dump(topology_obj, f)
    r = subprocess.run([sys.executable, validator, "--manifest", mp, "--binding-topology", tp, "--json"],
                       capture_output=True, text=True)
    try:
        rep = json.loads(r.stdout)
    except ValueError:
        rep = {"ok": False, "diagnostics": [{"code": "__invalid_json__", "message": r.stdout + r.stderr}]}
    return r.returncode, rep


def _validate_observation_binding(validator, binding_obj, spec_obj, workdir):
    bp = os.path.join(workdir, "observation-binding.json")
    sp = os.path.join(workdir, "capability-spec.json")
    with open(bp, "w", encoding="utf-8") as f:
        json.dump(binding_obj, f)
    with open(sp, "w", encoding="utf-8") as f:
        json.dump(spec_obj, f, sort_keys=True)
    r = subprocess.run([sys.executable, validator, "--binding", bp, "--spec", sp, "--json"],
                       capture_output=True, text=True)
    try:
        rep = json.loads(r.stdout)
    except ValueError:
        rep = {"ok": False, "diagnostics": [{"code": "__invalid_json__", "message": r.stdout + r.stderr}]}
    return r.returncode, rep


def _render_coordination_plan(neutrino_gen, spec, workdir, label):
    if not neutrino_gen or not os.path.isfile(neutrino_gen):
        raise RuntimeError(f"coordination-plan renderer {neutrino_gen!r} is missing")
    spec_path = os.path.join(workdir, f"{label}.capability-spec.json")
    out_dir = os.path.join(workdir, f"{label}.coordination-plan")
    with open(spec_path, "w", encoding="utf-8") as f:
        json.dump(spec, f, sort_keys=True)
    r = subprocess.run([neutrino_gen, "--target=coordination-plan", "--from-spec", spec_path, "-o", out_dir],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"coordination-plan renderer failed for {label} (exit {r.returncode}): "
                           f"{(r.stderr or r.stdout).strip()}")
    coordination_plan_path = os.path.join(out_dir, "coordination-plan.json")
    if not os.path.isfile(coordination_plan_path):
        raise RuntimeError(f"coordination-plan renderer did not emit coordination-plan.json for {label}")
    with open(coordination_plan_path, encoding="utf-8") as f:
        return json.load(f)


def _consumer_matches(report, expected):
    if bool(report.get("ok")) != bool(expected.get("ok")):
        return False
    want_code = expected.get("code")
    if want_code:
        return any(d.get("code") == want_code for d in report.get("diagnostics", []))
    return True


def _consumer_signature(report):
    return (bool(report.get("ok")), tuple(sorted(d.get("code") for d in report.get("diagnostics", []))))


def _prove_observer_set_consume(c, key, proof, spec_validator, observation_binding_validator):
    bad = []
    base_path = os.path.join(REPO, proof["spec"])
    binding_path = os.path.join(REPO, proof["binding"])
    if not os.path.isfile(base_path):
        return [f"{c['id']}: consume proof base spec {proof['spec']} is missing"]
    if not os.path.isfile(binding_path):
        return [f"{c['id']}: consume proof observation binding {proof['binding']} is missing"]
    with open(base_path, encoding="utf-8") as f:
        base = json.load(f)
    with open(binding_path, encoding="utf-8") as f:
        base_binding = json.load(f)
    try:
        cell_spec = _spec_with_observer_set_field(
            base, proof["observerSet"], proof["specField"], proof["cellValue"])
        control_spec = _spec_with_observer_set_field(
            base, proof["observerSet"], proof["specField"], proof["controlValue"])
        cell_binding = _binding_matching_observer_set(base_binding, cell_spec, proof["observerSet"])
        tampered_binding = _binding_with_observer_set_field(
            cell_binding, proof["observerSet"], proof["bindingField"], proof["controlValue"])
    except ValueError as exc:
        return [f"{c['id']}: {exc}"]

    cell_os = _attestation_observer_set(cell_spec, proof["observerSet"])
    control_os = _attestation_observer_set(control_spec, proof["observerSet"])
    cell_bound = _observer_binding_set(cell_binding, proof["observerSet"])
    if cell_os.get(proof["specField"]) != proof["cellValue"]:
        bad.append(f"{c['id']}: cell spec did not carry {key[0]} {proof['cellValue']!r} at observer-set "
                   f"{proof['observerSet']}.{proof['specField']}")
    if control_os.get(proof["specField"]) != proof["controlValue"]:
        bad.append(f"{c['id']}: control spec did not carry {key[0]} {proof['controlValue']!r} at "
                   f"observer-set {proof['observerSet']}.{proof['specField']}")
    if cell_bound.get(proof["bindingField"]) != proof["cellValue"]:
        bad.append(f"{c['id']}: observation binding did not carry {key[0]} {proof['cellValue']!r} at "
                   f"observer-set {proof['observerSet']}.{proof['bindingField']}")
    if bad:
        return bad

    with tempfile.TemporaryDirectory() as td:
        for label, spec_obj in (("cell", cell_spec), ("control", control_spec)):
            code, diags = _validate_spec(spec_validator, spec_obj, td)
            if code != 0:
                return [f"{c['id']}: derived {label} spec does not validate clean "
                        f"(exit {code}, codes={[d.get('code') for d in diags]})"]
        _, cell_report = _validate_observation_binding(
            observation_binding_validator, cell_binding, cell_spec, td)
        _, control_report = _validate_observation_binding(
            observation_binding_validator, cell_binding, control_spec, td)
        _, tampered_report = _validate_observation_binding(
            observation_binding_validator, tampered_binding, cell_spec, td)
        mismatch = {"ok": False, "code": proof["mismatchCode"]}
        if not _consumer_matches(cell_report, {"ok": True}):
            return [f"{c['id']}: cell observation-binding consumer did not accept matching "
                    f"{proof['bindingField']} (got ok={cell_report.get('ok')} "
                    f"codes={[d.get('code') for d in cell_report.get('diagnostics', [])]})"]
        if not _consumer_matches(control_report, mismatch):
            return [f"{c['id']}: control observation-binding consumer did not reject mismatched "
                    f"{proof['bindingField']} with {proof['mismatchCode']} "
                    f"(got ok={control_report.get('ok')} "
                    f"codes={[d.get('code') for d in control_report.get('diagnostics', [])]})"]
        if not _consumer_matches(tampered_report, mismatch):
            return [f"{c['id']}: tampered observation binding did not reject mismatched "
                    f"{proof['bindingField']} with {proof['mismatchCode']} "
                    f"(got ok={tampered_report.get('ok')} "
                    f"codes={[d.get('code') for d in tampered_report.get('diagnostics', [])]})"]
        if _consumer_signature(cell_report) == _consumer_signature(control_report):
            return [f"{c['id']}: cell and valid control produced the same observation-binding observation"]
        if _consumer_signature(cell_report) == _consumer_signature(tampered_report):
            return [f"{c['id']}: flipping the binding {proof['bindingField']} did not change the "
                    "observation-binding consumer observation (consume proof is vacuous)"]
    return []


def _prove_lifecycle_state_consume(c, key, proof, spec_validator):
    base_path = os.path.join(REPO, proof["spec"])
    if not os.path.isfile(base_path):
        return [f"{c['id']}: consume proof base spec {proof['spec']} is missing"]
    with open(base_path, encoding="utf-8") as f:
        base = json.load(f)
    if _terminal_state_ref(base, proof["terminalStateField"]) != proof["state"]:
        return [f"{c['id']}: lifecycle.terminalStates.{proof['terminalStateField']} does not point at "
                f"{proof['state']!r} in {proof['spec']}"]
    try:
        cell_spec = _spec_with_lifecycle_state_field(
            base, proof["state"], proof["specField"], proof["cellValue"])
        control_spec = _spec_with_lifecycle_state_field(
            base, proof["state"], proof["specField"], proof["controlValue"])
        tampered_spec = _spec_with_terminal_state_ref(
            cell_spec, proof["terminalStateField"], proof["tamperState"])
    except ValueError as exc:
        return [f"{c['id']}: {exc}"]

    cell_state = _lifecycle_state(cell_spec, proof["state"]) or {}
    control_state = _lifecycle_state(control_spec, proof["state"]) or {}
    tampered_state = _lifecycle_state(tampered_spec, proof["state"]) or {}
    tampered_ref = _terminal_state_ref(tampered_spec, proof["terminalStateField"])
    if cell_state.get(proof["specField"]) != proof["cellValue"]:
        return [f"{c['id']}: cell spec did not carry {key[0]} {proof['cellValue']!r} at lifecycle state "
                f"{proof['state']}.{proof['specField']}"]
    if control_state.get(proof["specField"]) != proof["controlValue"]:
        return [f"{c['id']}: control spec did not carry {key[0]} {proof['controlValue']!r} at lifecycle "
                f"state {proof['state']}.{proof['specField']}"]
    if tampered_state.get(proof["specField"]) != proof["cellValue"]:
        return [f"{c['id']}: tamper changed lifecycle state {proof['state']}.{proof['specField']} "
                "instead of the terminalStates relation"]
    if tampered_ref != proof["tamperState"]:
        return [f"{c['id']}: tamper did not rewire lifecycle.terminalStates."
                f"{proof['terminalStateField']} to {proof['tamperState']!r}"]
    if _sha256_json(control_spec) == _sha256_json(tampered_spec):
        return [f"{c['id']}: control and relation-side tamper are the same document"]
    for label, spec_obj in (("cell", cell_spec), ("control", control_spec), ("tampered", tampered_spec)):
        if not _capability_spec_identity_is_rebuilt(spec_obj):
            return [f"{c['id']}: derived {label} spec identity was not rebuilt"]

    with tempfile.TemporaryDirectory() as td:
        cell_code, cell_diags = _validate_spec(spec_validator, cell_spec, td)
        if cell_code != 0:
            return [f"{c['id']}: derived cell spec does not validate clean "
                    f"(exit {cell_code}, codes={[d.get('code') for d in cell_diags]})"]
        control_code, control_diags = _validate_spec(spec_validator, control_spec, td)
        tampered_code, tampered_diags = _validate_spec(spec_validator, tampered_spec, td)
        expected_codes = [proof["mismatchCode"]]
        if control_code == 0 or _diag_codes(control_diags) != expected_codes:
            return [f"{c['id']}: control capability-spec consumer did not reject mismatched "
                    f"terminalKind with {proof['mismatchCode']} "
                    f"(exit {control_code}, codes={_diag_codes(control_diags)})"]
        if tampered_code == 0 or _diag_codes(tampered_diags) != expected_codes:
            return [f"{c['id']}: tampered terminalStates relation did not reject mismatched terminalKind with "
                    f"{proof['mismatchCode']} (exit {tampered_code}, "
                    f"codes={_diag_codes(tampered_diags)})"]
        if _consumer_signature({"ok": True, "diagnostics": cell_diags}) == _consumer_signature(
                {"ok": control_code == 0, "diagnostics": control_diags}):
            return [f"{c['id']}: cell and valid control produced the same capability-spec observation"]
        if _consumer_signature({"ok": True, "diagnostics": cell_diags}) == _consumer_signature(
                {"ok": tampered_code == 0, "diagnostics": tampered_diags}):
            return [f"{c['id']}: flipping terminalKind did not change the capability-spec consumer "
                    "observation (consume proof is vacuous)"]
    return []


def _prove_lifecycle_transition_guard_consume(c, key, proof, spec_validator,
                                              coordination_plan_renderer):
    base_path = os.path.join(REPO, proof["spec"])
    if not os.path.isfile(base_path):
        return [f"{c['id']}: consume proof base spec {proof['spec']} is missing"]
    with open(base_path, encoding="utf-8") as f:
        base = json.load(f)
    try:
        cell_spec = _spec_with_lifecycle_transition_guard_kind(
            base, proof["transition"], proof["guardDetail"], proof["cellValue"])
        control_spec = _spec_with_lifecycle_transition_guard_kind(
            base, proof["transition"], proof["guardDetail"], proof["controlValue"])
        producer_tampered_spec = _spec_with_dropped_transition_guard_kind(
            cell_spec, proof["transition"], proof["guardDetail"])
    except ValueError as exc:
        return [f"{c['id']}: {exc}"]

    for label, spec_obj in (("cell", cell_spec), ("control", control_spec),
                            ("producer-tampered", producer_tampered_spec)):
        if not _capability_spec_identity_is_rebuilt(spec_obj):
            return [f"{c['id']}: derived {label} spec identity was not rebuilt"]
    cell_guard = _transition_guard_by_detail(cell_spec, proof["transition"], proof["guardDetail"]) or {}
    control_guard = _transition_guard_by_detail(control_spec, proof["transition"], proof["guardDetail"]) or {}
    if cell_guard.get("kind") != proof["cellValue"]:
        return [f"{c['id']}: cell producer did not carry transition guard kind {proof['cellValue']!r}"]
    if control_guard.get("kind") != proof["controlValue"]:
        return [f"{c['id']}: control producer did not carry transition guard kind {proof['controlValue']!r}"]

    with tempfile.TemporaryDirectory() as td:
        for label, spec_obj in (("cell", cell_spec), ("control", control_spec)):
            code, diags = _validate_spec(spec_validator, spec_obj, td)
            if code != 0:
                return [f"{c['id']}: derived {label} spec does not validate clean "
                        f"(exit {code}, codes={_diag_codes(diags)})"]
        tamper_code, tamper_diags = _validate_spec(spec_validator, producer_tampered_spec, td)
        if tamper_code == 0 or _diag_codes(tamper_diags) != ["spec.schema"]:
            return [f"{c['id']}: dropping the producer guard kind did not refuse exactly with spec.schema "
                    f"(exit {tamper_code}, codes={_diag_codes(tamper_diags)})"]
        try:
            cell_coordination_artifact = _render_coordination_plan(
                coordination_plan_renderer, cell_spec, td, "cell")
            control_coordination_artifact = _render_coordination_plan(
                coordination_plan_renderer, control_spec, td, "control")
            consumer_tampered_coordination_artifact = _coordination_plan_with_dropped_transition_guard_kind(
                cell_coordination_artifact, proof["transition"], proof["guardDetail"])
        except (RuntimeError, ValueError) as exc:
            return [f"{c['id']}: {exc}"]

    cell_coordination_guard = _transition_guard_by_detail(
        cell_coordination_artifact, proof["transition"], proof["guardDetail"],
        coordination_artifact=True) or {}
    control_coordination_guard = _transition_guard_by_detail(
        control_coordination_artifact, proof["transition"], proof["guardDetail"],
        coordination_artifact=True) or {}
    tampered_coordination_guard = _transition_guard_by_detail(
        consumer_tampered_coordination_artifact, proof["transition"], proof["guardDetail"],
        coordination_artifact=True) or {}
    if cell_coordination_guard.get("kind") != proof["cellValue"]:
        return [f"{c['id']}: coordination-plan did not carry transition guard kind {proof['cellValue']!r}"]
    if control_coordination_guard.get("kind") != proof["controlValue"]:
        return [f"{c['id']}: coordination-plan control did not carry transition guard kind "
                f"{proof['controlValue']!r}"]
    if tampered_coordination_guard.get("kind") is not None:
        return [f"{c['id']}: consumer tamper did not drop the transition guard kind"]
    if _sha256_json(cell_coordination_artifact) == _sha256_json(control_coordination_artifact):
        return [f"{c['id']}: valid guard kinds produced the same coordination-plan artifact"]
    if _sha256_json(cell_coordination_artifact) == _sha256_json(consumer_tampered_coordination_artifact):
        return [f"{c['id']}: dropping the consumed guard kind did not change the coordination-plan artifact"]
    return []


def _prove_lifecycle_transition_evidence_consume(c, key, proof, spec_validator,
                                                 coordination_plan_renderer):
    base_path = os.path.join(REPO, proof["spec"])
    if not os.path.isfile(base_path):
        return [f"{c['id']}: consume proof base spec {proof['spec']} is missing"]
    with open(base_path, encoding="utf-8") as f:
        base = json.load(f)
    try:
        cell_spec = _spec_with_lifecycle_transition_evidence_style(
            base, proof["transition"], proof["cellValue"], proof["evidenceChained"])
        control_spec = _spec_with_lifecycle_transition_evidence_style(
            base, proof["transition"], proof["controlValue"], proof["evidenceChained"])
        producer_tampered_spec = _spec_with_dropped_transition_evidence_style(
            cell_spec, proof["transition"])
    except ValueError as exc:
        return [f"{c['id']}: {exc}"]

    for label, spec_obj in (("cell", cell_spec), ("control", control_spec),
                            ("producer-tampered", producer_tampered_spec)):
        if not _capability_spec_identity_is_rebuilt(spec_obj):
            return [f"{c['id']}: derived {label} spec identity was not rebuilt"]
    cell_evidence = _transition_evidence(cell_spec, proof["transition"]) or {}
    control_evidence = _transition_evidence(control_spec, proof["transition"]) or {}
    if cell_evidence != {"style": proof["cellValue"], "chained": proof["evidenceChained"]}:
        return [f"{c['id']}: cell producer did not carry the exact transition evidence object"]
    if control_evidence != {"style": proof["controlValue"], "chained": proof["evidenceChained"]}:
        return [f"{c['id']}: control producer did not carry the exact transition evidence object"]
    if (cell_spec.get("targetRequirements") or {}).get("evidenceStyle") != proof["cellValue"]:
        return [f"{c['id']}: cell producer did not update targetRequirements.evidenceStyle"]
    if (control_spec.get("targetRequirements") or {}).get("evidenceStyle") != proof["controlValue"]:
        return [f"{c['id']}: control producer did not update targetRequirements.evidenceStyle"]

    with tempfile.TemporaryDirectory() as td:
        for label, spec_obj in (("cell", cell_spec), ("control", control_spec)):
            code, diags = _validate_spec(spec_validator, spec_obj, td)
            if code != 0:
                return [f"{c['id']}: derived {label} spec does not validate clean "
                        f"(exit {code}, codes={_diag_codes(diags)})"]
        tamper_code, tamper_diags = _validate_spec(spec_validator, producer_tampered_spec, td)
        if tamper_code == 0 or _diag_codes(tamper_diags) != ["spec.schema"]:
            return [f"{c['id']}: dropping the producer evidence style did not refuse exactly with "
                    f"spec.schema (exit {tamper_code}, codes={_diag_codes(tamper_diags)})"]
        try:
            cell_coordination_plan = _render_coordination_plan(coordination_plan_renderer, cell_spec, td, "cell")
            control_coordination_plan = _render_coordination_plan(coordination_plan_renderer, control_spec, td, "control")
            consumer_tampered_coordination_plan = _coordination_plan_with_dropped_transition_evidence_style(
                cell_coordination_plan, proof["transition"])
        except (RuntimeError, ValueError) as exc:
            return [f"{c['id']}: {exc}"]

    cell_coordination_plan_evidence = _transition_evidence(cell_coordination_plan, proof["transition"], True) or {}
    control_coordination_plan_evidence = _transition_evidence(control_coordination_plan, proof["transition"], True) or {}
    tampered_coordination_plan_evidence = _transition_evidence(consumer_tampered_coordination_plan, proof["transition"], True) or {}
    if cell_coordination_plan_evidence.get("style") != proof["cellValue"]:
        return [f"{c['id']}: coordination-plan did not carry transition evidence style "
                f"{proof['cellValue']!r}"]
    if control_coordination_plan_evidence.get("style") != proof["controlValue"]:
        return [f"{c['id']}: coordination-plan control did not carry transition evidence style "
                f"{proof['controlValue']!r}"]
    if any(e.get("chained") != proof["evidenceChained"]
           for e in (cell_coordination_plan_evidence, control_coordination_plan_evidence, tampered_coordination_plan_evidence)):
        return [f"{c['id']}: coordination-plan conflated evidence style with chained"]
    if tampered_coordination_plan_evidence.get("style") is not None:
        return [f"{c['id']}: consumer tamper did not drop the transition evidence style"]
    if _sha256_json(cell_coordination_plan) == _sha256_json(control_coordination_plan):
        return [f"{c['id']}: valid evidence styles produced the same coordination-plan artifact"]
    if _sha256_json(cell_coordination_plan) == _sha256_json(consumer_tampered_coordination_plan):
        return [f"{c['id']}: dropping the consumed evidence style did not change the coordination-plan artifact"]
    return []


def _prove_lifecycle_transition_consume(c, key, proof, spec_validator, coordination_plan_renderer):
    base_path = os.path.join(REPO, proof["spec"])
    if not os.path.isfile(base_path):
        return [f"{c['id']}: consume proof base spec {proof['spec']} is missing"]
    with open(base_path, encoding="utf-8") as f:
        base = json.load(f)
    try:
        cell_spec = _spec_with_lifecycle_transition_field(
            base, proof["transition"], proof["specField"], proof["cellValue"])
        control_spec = _spec_with_lifecycle_transition_field(
            base, proof["transition"], proof["specField"], proof["controlValue"])
    except ValueError as exc:
        return [f"{c['id']}: {exc}"]

    cell_t = _lifecycle_transition(cell_spec, proof["transition"]) or {}
    control_t = _lifecycle_transition(control_spec, proof["transition"]) or {}
    if cell_t.get(proof["specField"]) != proof["cellValue"]:
        return [f"{c['id']}: cell spec did not carry {key[0]} {proof['cellValue']!r} at lifecycle "
                f"transition {proof['transition']}.{proof['specField']}"]
    if control_t.get(proof["specField"]) != proof["controlValue"]:
        return [f"{c['id']}: control spec did not carry {key[0]} {proof['controlValue']!r} at lifecycle "
                f"transition {proof['transition']}.{proof['specField']}"]
    if not _capability_spec_identity_is_rebuilt(cell_spec):
        return [f"{c['id']}: derived cell spec identity was not rebuilt"]
    if not _capability_spec_identity_is_rebuilt(control_spec):
        return [f"{c['id']}: derived control spec identity was not rebuilt"]

    with tempfile.TemporaryDirectory() as td:
        for label, spec_obj in (("cell", cell_spec), ("control", control_spec)):
            code, diags = _validate_spec(spec_validator, spec_obj, td)
            if code != 0:
                return [f"{c['id']}: derived {label} spec does not validate clean "
                        f"(exit {code}, codes={[d.get('code') for d in diags]})"]
        try:
            cell_coordination_plan = _render_coordination_plan(coordination_plan_renderer, cell_spec, td, "cell")
            control_coordination_plan = _render_coordination_plan(coordination_plan_renderer, control_spec, td, "control")
        except RuntimeError as exc:
            return [f"{c['id']}: {exc}"]
        except ValueError as exc:
            return [f"{c['id']}: {exc}"]

        cell_coordination_plan_t = _coordination_plan_lifecycle_transition(cell_coordination_plan, proof["transition"]) or {}
        control_coordination_plan_t = _coordination_plan_lifecycle_transition(control_coordination_plan, proof["transition"]) or {}
        if cell_coordination_plan_t.get(proof["specField"]) != proof["cellValue"]:
            return [f"{c['id']}: coordination-plan did not carry {key[0]} {proof['cellValue']!r} at "
                    f"lifecycle transition {proof['transition']}.{proof['specField']}"]
        if control_coordination_plan_t.get(proof["specField"]) != proof["controlValue"]:
            return [f"{c['id']}: coordination-plan control did not carry {key[0]} "
                    f"{proof['controlValue']!r} at lifecycle transition "
                    f"{proof['transition']}.{proof['specField']}"]
        if _sha256_json(cell_coordination_plan) == _sha256_json(control_coordination_plan):
            return [f"{c['id']}: cell and valid control produced the same coordination-plan artifact"]
    return []


def prove_binding_consume(manifest, slot_spec_renderer, binding_manifest_validator, spec_validator,
                          observation_binding_validator=None, coordination_plan_renderer=None,
                          binding_consume_proofs=None):
    """Prove  valid_carry_and_consume verticals. For each crediting binding cell: derive the cell and
    control specs from the same committed source by mutating ONLY the declared field; rebuild identity;
    then run the first authoritative consumer for that locus. Participant rows use the native public
    generateSlotFromSpec() path plus binding-manifest validation; observer-set rows use observation-binding
    equality; lifecycle-state rows use the capability-spec validator's terminalStates consistency check;
    lifecycle-transition idempotency/effect/guard/evidence rows use the coordination-plan from-spec
    renderer; guard and evidence rows additionally prove independent producer- and consumer-side dropped
    field tampers."""
    if binding_consume_proofs is None:
        binding_consume_proofs = build_binding_consume_proofs()
    bad = []
    crediting = [c for c in manifest.get("cells", [])
                 if c.get("kind") == "binding" and c.get("credits")]
    for c in crediting:
        key = tuple((c.get("covers") or [[]])[0])
        proof = c.get("consumeProof") or {}
        closed = binding_consume_proofs.get(key)
        if not closed:
            bad.append(f"{c.get('id')}: crediting binding cell has no closed consume proof")
            continue
        if proof != _consume_proof_for(closed):
            bad.append(f"{c.get('id')}: consumeProof is not the closed binding consume proof binding")
            continue
        if proof.get("locus") == "observerSet":
            obs_validator = observation_binding_validator or os.path.join(
                REPO, "scripts", "validators", "validate_observation_binding.py")
            bad.extend(_prove_observer_set_consume(c, key, proof, spec_validator, obs_validator))
            continue
        if proof.get("locus") == "lifecycleState":
            bad.extend(_prove_lifecycle_state_consume(c, key, proof, spec_validator))
            continue
        if proof.get("locus") == "lifecycleTransitionGuard":
            bad.extend(_prove_lifecycle_transition_guard_consume(
                c, key, proof, spec_validator, coordination_plan_renderer))
            continue
        if proof.get("locus") == "lifecycleTransitionEvidence":
            bad.extend(_prove_lifecycle_transition_evidence_consume(
                c, key, proof, spec_validator, coordination_plan_renderer))
            continue
        if proof.get("locus") == "lifecycleTransition":
            bad.extend(_prove_lifecycle_transition_consume(
                c, key, proof, spec_validator, coordination_plan_renderer))
            continue
        if not slot_spec_renderer or not os.path.isfile(slot_spec_renderer):
            bad.append(f"slot producer helper {slot_spec_renderer!r} is missing; build slot-spec-smoke first")
            continue
        base_path = os.path.join(REPO, proof["spec"])
        if not os.path.isfile(base_path):
            bad.append(f"{c['id']}: consume proof base spec {proof['spec']} is missing")
            continue
        with open(base_path, encoding="utf-8") as f:
            base = json.load(f)
        try:
            cell_spec = _spec_with_participant_field(
                base, proof["participant"], proof["specField"], proof["cellValue"])
            control_spec = _spec_with_participant_field(
                base, proof["participant"], proof["specField"], proof["controlValue"])
        except ValueError as exc:
            bad.append(f"{c['id']}: {exc}")
            continue
        if _participant(cell_spec, proof["participant"]).get(proof["specField"]) != proof["cellValue"]:
            bad.append(f"{c['id']}: cell spec did not carry {proof['cellValue']!r} at participant "
                       f"{proof['participant']}.{proof['specField']}")
            continue
        if _participant(control_spec, proof["participant"]).get(proof["specField"]) != proof["controlValue"]:
            bad.append(f"{c['id']}: control spec did not carry {proof['controlValue']!r} at participant "
                       f"{proof['participant']}.{proof['specField']}")
            continue
        with tempfile.TemporaryDirectory() as td:
            for label, spec_obj in (("cell", cell_spec), ("control", control_spec)):
                code, diags = _validate_spec(spec_validator, spec_obj, td)
                if code != 0:
                    bad.append(f"{c['id']}: derived {label} spec does not validate clean "
                               f"(exit {code}, codes={[d.get('code') for d in diags]})")
                    break
            else:
                try:
                    cell_topology = _render_slot_topology(slot_spec_renderer, cell_spec, td, "cell")
                    control_topology = _render_slot_topology(slot_spec_renderer, control_spec, td, "control")
                except RuntimeError as exc:
                    bad.append(f"{c['id']}: {exc}")
                    continue
                for label, topology, expected_value in (
                        ("cell", cell_topology, proof["cellTopologyValue"]),
                        ("control", control_topology, proof["controlTopologyValue"])):
                    _org, _participant_obj, slot = _topology_participant_slot(topology, proof["participant"])
                    if slot is None:
                        bad.append(f"{c['id']}: native slot producer emitted no slot for participant "
                                   f"{proof['participant']!r} in {label} topology")
                        break
                    if slot.get(proof["topologyField"]) != expected_value:
                        bad.append(f"{c['id']}: native slot producer did not carry {key[0]} "
                                   f"{expected_value!r} into {label} topology field "
                                   f"{proof['topologyField']} (got {slot.get(proof['topologyField'])!r})")
                        break
                else:
                    try:
                        manifest_obj = _binding_manifest_for_topology(cell_topology, proof)
                    except ValueError as exc:
                        bad.append(f"{c['id']}: {exc}")
                        continue
                    _, cell_report = _validate_binding_manifest(binding_manifest_validator, manifest_obj,
                                                                cell_topology, td)
                    _, control_report = _validate_binding_manifest(binding_manifest_validator, manifest_obj,
                                                                   control_topology, td)
                    if not _consumer_matches(cell_report, proof["expected"]):
                        bad.append(f"{c['id']}: cell consumer observation does not match expected "
                                   f"{proof['expected']} (got ok={cell_report.get('ok')} "
                                   f"codes={[d.get('code') for d in cell_report.get('diagnostics', [])]})")
                        continue
                    if not _consumer_matches(control_report, proof["controlExpected"]):
                        bad.append(f"{c['id']}: control consumer observation does not match expected "
                                   f"{proof['controlExpected']} (got ok={control_report.get('ok')} "
                                   f"codes={[d.get('code') for d in control_report.get('diagnostics', [])]})")
                        continue
                    if _consumer_signature(cell_report) == _consumer_signature(control_report):
                        bad.append(f"{c['id']}: cell and valid control produced the same consumer observation")
                        continue
                    try:
                        tampered_topology = _set_topology_slot_field(
                            cell_topology, proof["participant"], proof["topologyField"],
                            proof["controlTopologyValue"], proof)
                    except ValueError as exc:
                        bad.append(f"{c['id']}: {exc}")
                        continue
                    _, tampered_report = _validate_binding_manifest(binding_manifest_validator, manifest_obj,
                                                                    tampered_topology, td)
                    if _consumer_signature(tampered_report) == _consumer_signature(cell_report):
                        bad.append(f"{c['id']}: flipping the carried {proof['topologyField']} in topology "
                                   "did not change the consumer observation (consume proof is vacuous)")
                    continue
                continue
    return bad


def prove_binding(manifest, validator):
    """S1c binding proof (), pure-Python via the capability-spec validator. For each binding cell: the
    committed canonical spec must validate CLEAN (cell), the value must be present at the located field
    (carry), and invalidating THAT ONE field must make the validator refuse with the cell's field-specific
    `refusalCode` that the clean spec does NOT emit (causal, coded). Returns failure strings."""
    import copy
    bad = []
    for c in manifest["cells"]:
        if c.get("kind") != "binding":   # non-crediting contract fixtures (): still proven, not counted
            continue
        if "refusalCode" not in c:
            continue
        v = binding_locus_violations(c)
        if v:
            bad.append(f"{c['id']}: {v[0]}")
            continue
        spec_path = os.path.join(REPO, c["spec"])
        if not os.path.isfile(spec_path):
            bad.append(f"{c['id']}: committed spec {c['spec']} is missing")
            continue
        with open(spec_path, encoding="utf-8") as f:
            spec = json.load(f)
        loc = c["locator"]
        entry = {"array": loc["array"], "sub": loc["sub"], "value": loc["value"],
                 "contains": loc.get("contains")}
        idx = _locate(spec, entry)
        if idx is None:
            bad.append(f"{c['id']}: value {loc['value']!r} no longer present at {loc['array']}.{loc['sub']} "
                       f"in {c['spec']} (the artifact drifted — re-derive BINDING_LOCUS)")
            continue
        code, msg = c["refusalCode"], c.get("refusalMessage")
        with tempfile.TemporaryDirectory() as td:
            cell_code, cell_diags = _validate_spec(validator, spec, td)
            if cell_code != 0:
                bad.append(f"{c['id']}: committed spec does not validate clean (exit {cell_code})")
                continue
            if any(d["code"] == code for d in cell_diags):
                bad.append(f"{c['id']}: the clean spec already emits code {code!r} — not caused by the mutation")
                continue
            # Single JSON-path mutation: invalidate ONLY the located field.
            mutated = copy.deepcopy(spec)
            arr = _dget(mutated, loc["array"])
            _dset(arr[idx], loc["sub"], c["invalid"])
            ctl_code, ctl_diags = _validate_spec(validator, mutated, td)
            # The coverage contract is the MACHINE CODE, matched EXACTLY ( P1); the message is only
            # additional context.
            hit = [d for d in ctl_diags if d["code"] == code]
            if ctl_code == 0:
                bad.append(f"{c['id']}: invalidating {loc['sub']} did not make the spec refuse (the field "
                           "is not enforced by the validator)")
            elif not hit:
                bad.append(f"{c['id']}: the refusal does not carry the field-specific machine code "
                           f"(expected code {code!r} in {[d['code'] for d in ctl_diags]})")
            elif msg and not any(msg in d["message"] for d in hit):
                bad.append(f"{c['id']}: the {code!r} diagnostic lost its expected message context "
                           f"(expected {msg!r})")
    return bad


def main():
    ap = argparse.ArgumentParser(description="schema-derived generalism cell generator ( S1a)")
    ap.add_argument("--schema", default=SCHEMA)
    ap.add_argument("--classification", default=CLASSIFICATION)
    ap.add_argument("--seeds", default=SEEDS)
    ap.add_argument("--out", default=os.path.join(REPO, "test", "generalism", "generalism-cells.manifest.json"))
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--prove-witness", metavar="NEUTRINO_GEN",
                    help="realize every ledger/refusal cell (and each ledger cell's feature-removal "
                         "mutant) with this neutrino-gen and assert the declared witness actually holds "
                         "(ledger: cell realizes + mutant differs; refusal: coded refusal). render cells "
                         "are deferred to the render-witness child of .")
    ap.add_argument("--prove-binding", metavar="VALIDATOR", nargs="?",
                    const=os.path.join(REPO, "scripts", "validators", "validate_capability_spec.py"),
                    help="prove every S1c binding/lifecycle cell () with the capability-spec VALIDATOR "
                         "(pure-Python, build-free): the committed canonical spec validates clean, and "
                         "invalidating the one located field makes it refuse with the field-specific code.")
    ap.add_argument("--prove-binding-consume", metavar="SLOT_SPEC_RENDERER",
                    help="prove the crediting  valid_carry_and_consume cells: participant-slot rows "
                         "render real slot artifacts with SLOT_SPEC_RENDERER and validate the binding "
                         "manifest; observer-set rows validate exact observation-binding/spec equality.")
    ap.add_argument("--coordination-plan-renderer", metavar="NEUTRINO_GEN",
                    help="neutrino-gen binary used by --prove-binding-consume for lifecycle-transition "
                         "rows via --target=coordination-plan --from-spec.")
    args = ap.parse_args()
    schema = json.load(open(args.schema, encoding="utf-8"))
    classification = json.load(open(args.classification, encoding="utf-8"))
    manifest = build_manifest(schema, classification, args.seeds)
    if args.prove_binding_consume:
        coordination_plan_renderer = args.coordination_plan_renderer
        if not coordination_plan_renderer:
            sibling = os.path.join(os.path.dirname(os.path.abspath(args.prove_binding_consume)), "neutrino-gen")
            coordination_plan_renderer = sibling if os.path.isfile(sibling) else None
        bad = prove_binding_consume(
            manifest,
            args.prove_binding_consume,
            os.path.join(REPO, "scripts", "validators", "validate_binding_manifest.py"),
            os.path.join(REPO, "scripts", "validators", "validate_capability_spec.py"),
            coordination_plan_renderer=coordination_plan_renderer,
            binding_consume_proofs=build_binding_consume_proofs(schema, classification))
        if bad:
            print("generalism BINDING CONSUME PROOF FAILED ():", file=sys.stderr)
            for b in bad:
                print(f"    {b}", file=sys.stderr)
            return 1
        n = sum(1 for c in manifest["cells"] if c.get("kind") == "binding" and c.get("credits"))
        print(f"generalism binding consume proof OK: {n} binding/lifecycle rows proved by valid<->valid "
              "carry through the authoritative producer/consumer path")
        return 0
    if args.prove_binding:
        bad = prove_binding(manifest, args.prove_binding)
        if bad:
            print("generalism BINDING PROOF FAILED ( S1c):", file=sys.stderr)
            for b in bad:
                print(f"    {b}", file=sys.stderr)
            return 1
        n = sum(1 for c in manifest["cells"]
                if c.get("kind") == "binding" and c.get("refusalCode"))
        print(f"generalism binding proof OK: all {n} non-crediting S1c validator-contract cells witnessed "
              "against the capability-spec validator (committed spec validates clean; invalidating the "
              "one located field refuses with the field-specific coded diagnostic)")
        return 0
    if args.prove_witness:
        bad = prove_witness(manifest, args.prove_witness)
        if bad:
            print("generalism WITNESS PROOF FAILED (a declared witness does not hold):", file=sys.stderr)
            for b in bad:
                print(f"    {b}", file=sys.stderr)
            return 1
        n = manifest["witnessedCellCount"]
        print(f"generalism witness proof OK: all {n} crediting cells are controlled experiments proven "
              "against the real --target=capability CLI (cell vs control differ, and the feature CAUSES "
              "the difference: ledger cells realize while the control refuses; refusal cells emit their "
              "coded refusal while the control normalizes it away); seed fixtures pass witness-class sanity")
        return 0
    text = render(manifest)
    if args.check:
        cur = open(args.out, encoding="utf-8").read() if os.path.isfile(args.out) else ""
        if cur != text:
            print(f"STALE: {args.out} is out of date — run the generator", file=sys.stderr)
            return 1
        return 0
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(text)
    m = json.loads(text)
    print(f"wrote {args.out}: {m['cellCount']} cells ({m['seedCount']} seed, "
          f"{m['witnessedCellCount']} witnessed) covering {m['coveredCount']}/{m['featureCount']} "
          f"derived features; {len(m['uncoveredFeatures'])} uncovered (deferred to  children)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

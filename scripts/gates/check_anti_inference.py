#!/usr/bin/env python3
"""[ M6 semantic-lowering S4 /  M6  S2] Backend anti-inference
boundary + one-waist sibling-projection gate + schema-derived
coordination-plan-decision completeness gate.

The compiler rule this enforces: **semantics normalize once; targets legalize;
CodeText prints.** A coordination's semantics are normalized ONCE into the typed
CoordinationPlan () — the workflow key, the balanced obligation, the guard
partition, the lifecycle-terminal projection, the effect->attestation policy
binding — and VERIFIED there (planFromSpec / assemblePlan). A backend's
contract-legalization TU LEGALIZES those already-decided facts into a typed
target model (); CodeText prints it. A legalization TU must therefore never
reach back into the raw capability-spec (JSON) to re-derive a shared semantic
decision.

This gate makes the boundary durable at the SOURCE (the complement of the runtime
differential ) and is FAIL-CLOSED for new code. The governed backend source
set (TUs AND headers) is derived from the extraction manifests + the backend dirs,
and a source is either on a *reviewed* JSON-legitimate allowlist (ingress / decode
/ harness / policy) or it must be structurally JSON-free.

  (A) TYPE/DEPENDENCY boundary — a JSON-free source names no `llvm::json` type and
      pulls in no JSON header, so it cannot hold a spec object to read at all;
      `spec["effects"]`, `spec.find(...)`, `getString(...)`, or a helper are then
      structurally impossible, not merely unmatched by an access-syntax list.
      (Residual: a facade header that re-exports a spec reader under a non-JSON
      type is out of a lexical gate's reach — covered by code review + the runtime
      differential/generalism runner (-), not by this lexical source gate.)
  (B) SEMANTIC-INFERENCE patterns — the coordination decisions the coordination plan already
      makes (first-effect workflow-key selection, renderer-local balance /
      lifecycle discovery) are forbidden in EVERY governed source, allowlisted or
      not, with named diagnostics.
  (C) COMPLETENESS — the behavior-field inventory is DERIVED by walking
      docs/schemas/capability-spec.schema.json RECURSIVELY (following local $refs
      with cycle detection for the self-referential AST, DESCENDING oneOf/anyOf/
      allOf combinators, pruned at documented subtree roots) and checking equality
      against a reviewed classification, so a NEW field at ANY depth — including
      one hidden inside a combinator branch — must be triaged normalized/
      structural/meta. Pruned recursive/owned subcontracts (expression AST,
      operands, lifecycle states/transitions, attestation policy) have their OWN
      recursive inventories, so a new child under a prune root is still a
      conscious classification change. Every normalized field is then proven
      parsed by an OBJECT-SCOPED access witness (`<obj>->getX("<key>")`, tied to
      the effect/compute/input/lifecycle/subcontract object it is read from), NOT
      a bare key token: three different `"name"` reads no longer satisfy each
      other, and a dead string literal cannot stand in for a real getter access.

The comment/char-literal/raw-string scanner is REUSED from check_cpp_policy.py
() — not reimplemented — so a `char q = '"';` cannot hide a following read.

S2 extends the same governance surface instead of adding a parallel scanner:
targets/evaluators/reducers must consume the verified CoordinationPlan waist.
The canonical capability-spec is a sibling projection. External specs may return
only through `planFromSpec`; spec-only leaves and self-emitted sibling artifacts
are explicitly reviewed, while backend/evaluator/core reducer consumers may not
read capability-spec, L2, or domain-specific labels directly.

`--file F` scans one file; `--selftest` proves the gate discovers the sources,
passes the committed tree, and BITES on: injected JSON access, first-effect
selection in an allowlisted source through the full `check_all()` CI path, a
char-literal-obfuscated read, a legalizer DECLARATION masquerading as an
implementation, a dropped object-scoped coordination-plan-field parse WITHOUT
false-flagging its aliased `name` siblings (+ a dead literal that must not
rescue it), and a new unclassified schema field — top-level, nested, inside
a oneOf combinator, and under pruned transition/operand/attestation
subcontracts.
"""

import argparse
import ast
import collections
import copy
import glob
import hashlib
import json
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from check_cpp_policy import strip_comments  # hardened  scanner — reused

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "..", ".."))

# --- The reviewed JSON-legitimate allowlist -----------------------------------
# The ONLY backend production sources that may read the raw capability-spec (JSON):
# the ingress entry that forwards the spec to a harness, the shared spec-decode
# primitives (TU + seam header), the test-artifact harnesses (which render from
# the spec's STRUCTURAL surface, not the coordination contract — a tracked
# follow-up makes them coordination-plan-driven), and the oracle POLICY renderer.
# Every OTHER backend source — the legalizers, the printers, the model headers,
# and ANY new file — must be JSON-free. A new source that reads JSON without a
# conscious entry here FAILS (fail-closed).
JSON_LEGITIMATE = {
    "lib/backends/postgres/GenPostgresSpec.cpp":
        "ingress: forwards the spec to the db-test harness "
        "(generatePostgresDbTestFromSpec)",
    "lib/backends/postgres/provider/PostgresSpecModel.cpp":
        "decode: shared spec-operand/type primitives (obj / operandSql / sqlType)",
    "lib/backends/postgres/leaf/PostgresSpecInternal.h":
        "decode seam: declares the shared spec-operand/type primitives + the "
        "harness entry",
    "lib/backends/postgres/harness/PostgresDbTest.cpp":
        "harness: renders the docker/psql TEST artifact from the spec's structural "
        "surface (follow-up: make coordination-plan-driven)",
    "lib/backends/solidity/harness/GenSolidityTest.cpp":
        "harness: renders the Foundry TEST artifact from the spec's structural "
        "surface (follow-up: make coordination-plan-driven)",
    "lib/backends/solidity/provider/SolidityEmit.cpp":
        "decode: shared spec-operand/type primitives "
        "(contractStr / contractUint / solType)",
    "lib/backends/oracle/GenOracleObserverSpec.cpp":
        "policy renderer: renders the observer set from the attestation POLICY + "
        "binding (), not a coordination contract",
}

# --- The type/dependency boundary (A) -----------------------------------------
JSON_TYPE = re.compile(r"\bjson::(Object|Array|Value|OStream)\b|\bllvm::json\b")
JSON_INCLUDE = re.compile(
    r'#\s*include\s+"(?:llvm/Support/JSON\.h|Neutrino/JsonUtil\.h)"')

# --- The semantic-inference patterns (B) — never legitimate in ANY governed
#     source, allowlisted or not: these are coordination DECISIONS the coordination plan already
#     makes. (Iterating effects for test values, or reading a policy in the oracle
#     POLICY renderer, is NOT a coordination-decision re-derivation and is not
#     matched here.)
SEMANTIC_INFERENCE = [
    (re.compile(r'effects\s*\[\s*0\s*\]|'
                r'getArray\(\s*"effects"\s*\)[^;{}]*?->\s*(?:front|begin)\s*\(|'
                r'getArray\(\s*"effects"\s*\)[^;{}]*?->\s*at\s*\(\s*0\s*\)'),
     "first-effect / positional workflow-key selection — the key is decided once "
     "(): use coordinationPlan.workflowKey"),
    (re.compile(r'getString\(\s*"workflowKey"|getString\(\s*"idempotencyKey"'),
     "workflow-key inference from the spec — use coordinationPlan.workflowKey"),
    (re.compile(r'getArray\(\s*"invariants"'),
     "renderer-local balance discovery — use coordinationPlan.balanced"),
    (re.compile(r'getObject\(\s*"lifecycle"|getObject\(\s*"terminalStates"|'
                r'requiredLifecycleSuccessTerminal'),
     "renderer-local lifecycle-terminal discovery — use coordinationPlan.terminal"),
]

# --- The converged backend adapters (for the floor) ----------------------------
#  removes backend-local CoordinationPlan legalizers.  The replacement floor
# is the graph-only materialization definition in each production backend.
ADAPTER_SIG = re.compile(
    r"\bmaterialize(?:Solidity|Postgres)Projection(?:Artifact)?\s*\(\s*"
    r"const\s+projection::BackendProjectionGraph\b[^;{]*\)\s*\{")
MIN_ADAPTERS = 2  # Solidity + PostgreSQL today; a DROP is a regression.
# Stable gate-integrity baseline name retained while its source fact advances
# from the retired legalizer floor to the graph-only adapter floor.
MIN_LEGALIZERS = 2
MIN_GOVERNED = 12   # backend production TUs + headers the manifests/dirs own today.
MIN_ONE_WAIST_CONSUMERS = 10  # backend/evaluator/reducer/tool seams governed by S2.

# --- The one-waist sibling-projection boundary ( /  S2) --------------
# These sources consume the verified CoordinationPlan waist or generic reduction
# seam. The set combines the existing manifest-owned source derivation with
# normalizer/evaluator/reducer/tool entry points outside extraction manifests.
# A floor catches accidental source-set erosion.
ONE_WAIST_EXTRA_SOURCES = {
    "include/Neutrino/CoordinationEval.h",
    "include/Neutrino/GenCoordinationTrace.h",
    "include/Neutrino/L2Reduction.h",
    "include/Neutrino/PlanLegality.h",
    "lib/L2Reduction.cpp",
    "lib/PlanLegality.cpp",
    "lib/spec-contract/CoordinationEval.cpp",
    "lib/targets/CoordinationTraceTarget.cpp",
    "tools/neutrino-gen/neutrino-gen.cpp",
    "tools/neutrino-emit/neutrino-emit.cpp",
}

# Sibling projection leaves may consume the canonical capability-spec as their
# direct contract. They do not feed backend/evaluator decisions below the waist.
SPEC_SIBLING_LEGITIMATE = {
    "lib/policy/capability-profile/GenCapabilityModelSpec.cpp":
        "sibling capability-model projection from capability-spec",
    "lib/coverage/GenCoverageSpec.cpp":
        "sibling coverage projection from capability-spec",
    "lib/security/GenSecuritySpec.cpp":
        "sibling security report projection from capability-spec",
    "lib/slots/GenSlotSpec.cpp":
        "sibling slot projection from capability-spec",
    "lib/views/GenViewsSpec.cpp":
        "sibling participant-view projection from capability-spec",
    "lib/backends/oracle/GenOracleObserverSpec.cpp":
        "oracle observer sibling/policy projection from capability-spec + binding",
    "lib/backends/postgres/harness/PostgresDbTest.cpp":
        "test-harness sibling projection from the same capability-spec",
    "lib/backends/solidity/harness/GenSolidityTest.cpp":
        "test-harness sibling projection from the same capability-spec",
    "lib/backends/solidity/provider/SolidityEmit.cpp":
        "spec operand/type decode primitive for sibling Solidity test rendering",
    "lib/backends/postgres/provider/PostgresSpecModel.cpp":
        "spec operand/type decode primitive for sibling PostgreSQL test rendering",
    "lib/backends/postgres/leaf/PostgresSpecInternal.h":
        "declaration seam for sibling PostgreSQL spec decode primitives",
}

# Target wrappers may self-emit the sibling capability-spec so companion
# artifacts (test harnesses, policy leaves) share the public contract, but they
# must still drive core realization through CoordinationPlan.
SELF_EMITTED_SPEC_WRAPPERS = {
    "lib/targets/SolidityTarget.cpp",
    "lib/targets/PostgresTarget.cpp",
    "lib/coverage/CoverageTarget.cpp",
    "lib/security/SecurityTarget.cpp",
    "lib/slots/SlotTarget.cpp",
    "lib/views/ViewsTarget.cpp",
    "lib/targets/AgreementIdentityTarget.cpp",
}

EVALUATOR_WAIST_SOURCES = {
    "include/Neutrino/CoordinationEval.h",
    "include/Neutrino/GenCoordinationTrace.h",
    "include/Neutrino/PlanLegality.h",
    "lib/PlanLegality.cpp",
    "lib/spec-contract/CoordinationEval.cpp",
    "lib/targets/CoordinationTraceTarget.cpp",
}

GENERIC_REDUCTION_SOURCES = {
    "include/Neutrino/L2Reduction.h",
    "lib/L2Reduction.cpp",
}

EXTERNAL_SPEC_SEAM = "tools/neutrino-gen/neutrino-gen.cpp"
TARGET_REGISTRY = "include/Neutrino/TargetRegistry.def"
DIRECT_SPEC_RENDER = re.compile(
    r"(?:\bgenerate(?:SolidityContract|SoliditySources|PostgresProcedure|CoordinationTrace)"
    r"FromSpec|\bdispatchExternal)\s*\(\s*\*?\s*specObj\b")
L2_OR_UPPER_LAYER = re.compile(
    r"\b(?:neutrino::)?l2::|\bL2Dialect\b|\bDomainOp\b|#include\s+\"Neutrino/L2")
SYNTHETIC_DOMAIN_LABELS = {
    "__neu_gate_synthetic_domain_alpha",
    "__neu_gate_synthetic_domain_beta",
}
CORE_ROOTS = ("lib", "include/Neutrino", "tools")
CORE_SOURCE_SUFFIXES = (
    ".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".inc", ".td", ".def",
)
ADVERSARIAL_FIXTURE = (
    "test/gates/anti_inference/fixture_domain_inference.cpp"
)
ADVERSARIAL_FIXTURE_SHA256 = (
    "b968b2b362cff8ce32e7c0708ac45ac503915ff90f67bedf21d5790bd7416e23"
)
FINDING_DOMAIN_LABEL = "anti_inference.domain_label"
SEMANTIC_FINDING_IDENTITIES = (
    "anti_inference.semantic_inference.first_effect",
    "anti_inference.semantic_inference.workflow_key",
    "anti_inference.semantic_inference.balance_discovery",
    "anti_inference.semantic_inference.lifecycle_terminal",
)
EXPECTED_FIXTURE_IDENTITIES = (
    FINDING_DOMAIN_LABEL,
    FINDING_DOMAIN_LABEL,
    *SEMANTIC_FINDING_IDENTITIES,
)
SUPPRESSION_RE = re.compile(
    r"(?:anti[_ -]?inference.{0,40}(?:ignore|suppress|disable)|"
    r"(?:ignore|suppress|disable).{0,40}anti[_ -]?inference|"
    r"ANTI_INFERENCE_(?:IGNORE|SUPPRESS|DISABLE))",
    re.IGNORECASE,
)
CAPABILITY_SPEC_DECISION_KEY = (
    r"(?:effects|computes|inputs|invariants|lifecycle|participants|topology|"
    r"targetRequirements|attestations|procedure|trigger)"
)
CAPABILITY_SPEC_DECISION_READ = re.compile(
    r"(?:\b(?:getArray|getObject|getString|getBoolean|getNumber|get|find)\s*\(\s*\""
    + CAPABILITY_SPEC_DECISION_KEY
    + r"\"\s*\)|\[\s*\""
    + CAPABILITY_SPEC_DECISION_KEY
    + r"\"\s*\])"
)

# --- The completeness inventory (C), keyed by the AUTHORITATIVE schema ---------
SCHEMA = "docs/schemas/capability-spec.schema.json"
COORDINATION_PLAN_SPEC = "lib/spec-contract/CoordinationPlan.cpp"

# The top-level schema is walked RECURSIVELY, following local $refs (with cycle
# detection), and PRUNED at these subtree roots. A prune root is still classified
# here; children under behavior-bearing prunes are covered by the subordinate
# recursive inventories below, so a new leaf under lifecycle/operand/expression/
# attestation subcontracts is still fail-closed without exploding the cyclic AST.
PRUNE_ROOTS = frozenset({
    "attestations", "computes[].ast", "effects[].when", "effects[].amount",
    "effects[].currency", "effects[].party", "effects[].idempotencyKey",
    "lifecycle.states", "lifecycle.transitions", "lifecycle.instanceKey",
    "identity", "participants", "topology", "targetRequirements", "sourceMap",
})

def _acc(var, method, key):
    r"""A SCOPED getter-access witness regex: `spec.<method>("<key>")` when var is
    'spec', else `<var>-><method>("<key>")`, tolerant of formatter spacing. Tying
    each path's proof to the OBJECT it is read from (eo=effect, co=compute,
    o=input/compute-in-typeSpecExprs, io=invariant, life/term=lifecycle) makes the
    witness path-specific: three different `"name"` reads (inputs/computes/effects)
    can no longer satisfy each other, so dropping `effects[].name` is detected even
    while the other two remain. The leading `\b` keeps `o`-scoped witnesses from
    matching `eo`/`co`; a bare string literal appended anywhere cannot match a
    getter-access, so completeness cannot be spoofed by a dead token."""
    deref = r"\s*\.\s*" if var == "spec" else r"\s*->\s*"
    return re.compile(r"\b" + re.escape(var) + deref + re.escape(method) +
                      r"\s*\(\s*\"" + re.escape(key) + r"\"\s*\)")


# Every recursive schema PATH (to a leaf or a prune root) is classified. A
# `normalized` path is behavior-driving and MUST be parsed into the
# CoordinationPlan by the coordination-plan contract — asserted by a SCOPED access
# witness (`_acc`) tied to the exact object the field is read from, not a bare
# key token shared across paths. `structural` paths feed other renderers
# (views/security/profile/lifecycle-model), `meta` paths are envelope metadata.
# A NEW schema path not listed here fails the equality check (conscious triage).
SCHEMA_FIELD_ROLE = {
    # meta (envelope)
    "schemaVersion": ("meta", None),
    "kind": ("meta", None),
    "specVersion": ("meta", None),
    "sourceMap": ("meta", None),
    # normalized — top level (read off `spec` directly)
    "procedure": ("normalized", _acc("spec", "getString", "procedure")),
    "trigger": ("normalized", _acc("spec", "getString", "trigger")),
    "inputs": ("normalized", _acc("spec", "getArray", "inputs")),
    "computes": ("normalized", _acc("spec", "getArray", "computes")),
    "effects": ("normalized", _acc("spec", "getArray", "effects")),
    "invariants": ("normalized", _acc("spec", "getArray", "invariants")),
    "lifecycle": ("normalized", _acc("spec", "getObject", "lifecycle")),
    "attestations": ("normalized", re.compile(r"\battestationPoliciesFromSpec\s*\(")),
    # normalized — inputs (the input object `o`)
    "inputs[].name": ("normalized", _acc("o", "getString", "name")),
    "inputs[].type": ("normalized", _acc("o", "getString", "type")),
    "inputs[].category": ("structural", None),
    # normalized — computes (`co` in planFromSpec; the typed AST is read as `ast`)
    "computes[].name": ("normalized", _acc("co", "getString", "name")),
    # The compute SOURCE TEXT is a byte-compat projection that the contract does
    # NOT parse into the coordination plan — the typed `computes[].ast` IS the form
    # (cf. effects[].when, which carries both text and ast). Structural, not a
    # false-normalized entry the aliased `"expr"` token used to hide.
    "computes[].expr": ("structural", None),
    "computes[].category": ("normalized", _acc("co", "getString", "category")),
    "computes[].deps": ("normalized", _acc("co", "getArray", "deps")),
    "computes[].ast": ("normalized", _acc("o", "get", "ast")),
    # normalized — effects (the effect object `eo`)
    "effects[].kind": ("normalized", _acc("eo", "getString", "kind")),
    "effects[].name": ("normalized", _acc("eo", "getString", "name")),
    "effects[].ledger": ("normalized", _acc("eo", "getString", "ledger")),
    "effects[].memo": ("normalized", _acc("eo", "getString", "memo")),
    "effects[].amount": ("normalized", _acc("eo", "getObject", "amount")),
    "effects[].currency": ("normalized", _acc("eo", "getObject", "currency")),
    "effects[].party": ("normalized", _acc("eo", "getObject", "party")),
    "effects[].idempotencyKey": ("normalized", _acc("eo", "getObject", "idempotencyKey")),
    "effects[].when": ("normalized", _acc("eo", "getObject", "when")),
    "effects[].owner": ("structural", None),
    "effects[].participant": ("structural", None),
    # normalized — invariants (the invariant object `io`)
    "invariants[].kind": ("normalized", _acc("io", "getString", "kind")),
    # normalized — lifecycle terminal projection (`life`/`term`); rest is the model
    "lifecycle.instanceKey": ("normalized", _acc("life", "getObject", "instanceKey")),
    "lifecycle.terminalStates": ("normalized", _acc("life", "getObject", "terminalStates")),
    "lifecycle.terminalStates.success": ("normalized", _acc("term", "getString", "success")),
    "lifecycle.terminalStates.aborted": ("normalized", _acc("term", "getString", "aborted")),
    "lifecycle.terminalStates.contested": ("normalized", _acc("term", "getString", "contested")),
    "lifecycle.initialState": ("structural", None),
    "lifecycle.states": ("structural", None),
    "lifecycle.transitions": ("structural", None),
    # structural sub-objects (other renderers)
    "identity": ("structural", None),
    "participants": ("structural", None),
    "topology": ("structural", None),
    "targetRequirements": ("structural", None),
}

# The pruned roots above are not ignored. They are owned by subordinate parser
# contracts whose schemas can be cyclic (`exprNode`) or intentionally projected
# outside the backend coordination plan (`lifecycle.transitions`,
# `attestations`). This inventory keeps those subcontracts fail-closed too: a
# new field under a prune root must be classified here, and normalized fields
# must have a scoped parser witness in their owning contract.
SUBCONTRACT_FIELD_ROLE = {
    # lifecycle state contract — consumed by lifecycleModelFromSpec.
    "state.name": ("normalized", _acc("s", "getString", "name"),
                   "lib/spec-contract/Lifecycle.cpp"),
    "state.terminal": ("normalized", _acc("s", "getBoolean", "terminal"),
                       "lib/spec-contract/Lifecycle.cpp"),
    "state.terminalKind": ("normalized", _acc("s", "getString", "terminalKind"),
                           "lib/spec-contract/Lifecycle.cpp"),
    # lifecycle transition contract. Current backend coordination consumes the
    # name/from/to/effects projection; guards/idempotency/evidence are lifecycle
    # structural contract fields validated by the schema/validator, not backend
    # lowering decisions.
    "transition.name": ("normalized", _acc("t", "getString", "name"),
                        "lib/spec-contract/Lifecycle.cpp"),
    "transition.from": ("normalized", _acc("t", "getString", "from"),
                        "lib/spec-contract/Lifecycle.cpp"),
    "transition.to": ("normalized", _acc("t", "getString", "to"),
                      "lib/spec-contract/Lifecycle.cpp"),
    "transition.effects": ("normalized", _acc("t", "getArray", "effects"),
                           "lib/spec-contract/Lifecycle.cpp"),
    "transition.guards": ("structural", None, None),
    "transition.guards[].kind": ("structural", None, None),
    "transition.guards[].detail": ("structural", None, None),
    "transition.idempotency": ("structural", None, None),
    "transition.evidence": ("structural", None, None),
    "transition.evidence.style": ("structural", None, None),
    "transition.evidence.chained": ("structural", None, None),
    # lifecycle explicit instance-key contract. `fields` is consumed by the
    # lifecycle projector; `declared` drives workflow-key selection in the
    # coordination plan.
    "instanceKey.fields": ("normalized", _acc("ik", "getArray", "fields"),
                           "lib/spec-contract/Lifecycle.cpp"),
    "instanceKey.declared": ("normalized", _acc("ik", "getString", "declared"),
                             "lib/spec-contract/CoordinationPlan.cpp"),
    # debit/credit operand contract — normalized into PlanEffectInput identity.
    "operand.kind": ("normalized", _acc("o", "getString", "kind"),
                     "lib/spec-contract/CoordinationPlan.cpp"),
    "operand.value": ("normalized", _acc("o", "getString", "value"),
                      "lib/spec-contract/CoordinationPlan.cpp"),
    # typed expression AST contract — normalized/validated by exprFromJson +
    # typeExpr/typeGuard before coordination assembly.
    "exprNode.kind": ("normalized", _acc("o", "getString", "kind"),
                      "lib/spec-contract/Expr.cpp"),
    "exprNode.dtype": ("normalized", _acc("o", "getString", "dtype"),
                       "lib/spec-contract/Expr.cpp"),
    "exprNode.num": ("normalized", _acc("o", "getInteger", "num"),
                     "lib/spec-contract/Expr.cpp"),
    "exprNode.name": ("normalized", _acc("o", "getString", "name"),
                      "lib/spec-contract/Expr.cpp"),
    "exprNode.op": ("normalized", _acc("o", "getString", "op"),
                    "lib/spec-contract/Expr.cpp"),
    "exprNode.lhs": ("normalized", _acc("o", "get", "lhs"),
                     "lib/spec-contract/Expr.cpp"),
    "exprNode.rhs": ("normalized", _acc("o", "get", "rhs"),
                     "lib/spec-contract/Expr.cpp"),
    "exprNode.args": ("normalized", _acc("o", "getArray", "args"),
                      "lib/spec-contract/Expr.cpp"),
    # effect condition contract — raw text is preserved as the canonical guard
    # key and `ast` is re-parsed/typed through the expression contract.
    "when.expr": ("normalized", _acc("w", "getString", "expr"),
                  "lib/spec-contract/CoordinationPlan.cpp"),
    "when.ast": ("normalized", _acc("w", "get", "ast"),
                 "lib/spec-contract/CoordinationPlan.cpp"),
    "when.ast.kind": ("normalized", _acc("o", "getString", "kind"),
                      "lib/spec-contract/Expr.cpp"),
    "when.ast.dtype": ("normalized", _acc("o", "getString", "dtype"),
                       "lib/spec-contract/Expr.cpp"),
    "when.ast.num": ("normalized", _acc("o", "getInteger", "num"),
                     "lib/spec-contract/Expr.cpp"),
    "when.ast.name": ("normalized", _acc("o", "getString", "name"),
                      "lib/spec-contract/Expr.cpp"),
    "when.ast.op": ("normalized", _acc("o", "getString", "op"),
                    "lib/spec-contract/Expr.cpp"),
    "when.ast.lhs": ("normalized", _acc("o", "get", "lhs"),
                     "lib/spec-contract/Expr.cpp"),
    "when.ast.rhs": ("normalized", _acc("o", "get", "rhs"),
                     "lib/spec-contract/Expr.cpp"),
    "when.ast.args": ("normalized", _acc("o", "getArray", "args"),
                      "lib/spec-contract/Expr.cpp"),
    # attestation policy contract — normalized by attestationPoliciesFromSpec.
    "attestationPolicy.input": ("normalized", _acc("o", "getString", "input"),
                                "lib/spec-contract/Attestation.cpp"),
    "attestationPolicy.quorum": ("normalized", _acc("o", "getObject", "quorum"),
                                 "lib/spec-contract/Attestation.cpp"),
    "attestationPolicy.quorum.threshold":
        ("normalized", _acc("q", "getInteger", "threshold"),
         "lib/spec-contract/Attestation.cpp"),
    "attestationPolicy.observerSet":
        ("normalized", _acc("o", "getObject", "observerSet"),
         "lib/spec-contract/Attestation.cpp"),
    "attestationPolicy.observerSet.ref":
        ("normalized", _acc("os", "getString", "ref"),
         "lib/spec-contract/Attestation.cpp"),
    "attestationPolicy.observerSet.role":
        ("normalized", _acc("os", "getString", "role"),
         "lib/spec-contract/Attestation.cpp"),
    "attestationPolicy.observerSet.assurance":
        ("normalized", _acc("os", "getString", "assurance"),
         "lib/spec-contract/Attestation.cpp"),
    "attestationPolicy.observerSet.independence":
        ("normalized", _acc("os", "getString", "independence"),
         "lib/spec-contract/Attestation.cpp"),
    "attestationPolicy.canonicalization":
        ("normalized", _acc("o", "getObject", "canonicalization"),
         "lib/spec-contract/Attestation.cpp"),
    "attestationPolicy.canonicalization.mode":
        ("normalized", _acc("c", "getString", "mode"),
         "lib/spec-contract/Attestation.cpp"),
    "attestationPolicy.canonicalization.tolerance":
        ("normalized", _acc("c", "getString", "tolerance"),
         "lib/spec-contract/Attestation.cpp"),
    "attestationPolicy.timeout": ("normalized", _acc("o", "getString", "timeout"),
                                  "lib/spec-contract/Attestation.cpp"),
    "attestationPolicy.fallback": ("normalized", _acc("o", "getString", "fallback"),
                                   "lib/spec-contract/Attestation.cpp"),
    # Structural renderer-owned subcontracts. They are not behavior-driving for
    # backend semantic lowering, but they are still fail-closed so a new child
    # under a pruned structural root must be triaged consciously.
    "identity.capabilityHash": ("structural", None, None),
    "identity.specHash": ("structural", None, None),
    "participants[].name": ("structural", None, None),
    "participants[].role": ("structural", None, None),
    "participants[].org": ("structural", None, None),
    "participants[].capabilities": ("structural", None, None),
    "participants[].binding": ("structural", None, None),
    "participants[].bindRuntimes": ("structural", None, None),
    "participants[].bindMinAssurance": ("structural", None, None),
    "topology.allowedOrgPairs": ("structural", None, None),
    "topology.allowedOrgPairs[].orgA": ("structural", None, None),
    "topology.allowedOrgPairs[].orgB": ("structural", None, None),
    "topology.allowedOrgPairs[].roleA": ("structural", None, None),
    "topology.allowedOrgPairs[].roleB": ("structural", None, None),
    "targetRequirements.requirements": ("structural", None, None),
    "targetRequirements.requirements[].feature": ("structural", None, None),
    "targetRequirements.requirements[].primitive": ("structural", None, None),
    "targetRequirements.requirements[].source": ("structural", None, None),
    "targetRequirements.requirements[].source.line": ("structural", None, None),
    "targetRequirements.requirements[].source.column": ("structural", None, None),
    "targetRequirements.requirements[].requirement": ("structural", None, None),
    "targetRequirements.requirements[].fallback": ("structural", None, None),
    "targetRequirements.evidenceStyle": ("structural", None, None),
    "targetRequirements.unsupportedConstructs": ("structural", None, None),
    "sourceMap[].specPath": ("structural", None, None),
    "sourceMap[].construct": ("structural", None, None),
    "sourceMap[].source": ("structural", None, None),
    "sourceMap[].source.line": ("structural", None, None),
    "sourceMap[].source.column": ("structural", None, None),
}

PRUNE_SUBCONTRACT_ROOTS = {
    "attestations": ("attestationPolicy", "#/$defs/attestationPolicy"),
    "computes[].ast": ("exprNode", "#/$defs/exprNode"),
    "effects[].amount": ("operand", "#/$defs/operand"),
    "effects[].currency": ("operand", "#/$defs/operand"),
    "effects[].party": ("operand", "#/$defs/operand"),
    "effects[].idempotencyKey": ("operand", "#/$defs/operand"),
    "effects[].when": ("when", None),
    "lifecycle.instanceKey": ("instanceKey", None),
    "lifecycle.states": ("state", "#/$defs/state"),
    "lifecycle.transitions": ("transition", "#/$defs/transition"),
    "identity": ("identity", None),
    "participants": ("participants", None),
    "topology": ("topology", None),
    "targetRequirements": ("targetRequirements", None),
    "sourceMap": ("sourceMap", None),
}


def schema_paths(schema_path=None):
    """Every capability-spec schema path (to a leaf or a PRUNE_ROOTS subtree),
    walked recursively and following LOCAL $refs into $defs with cycle detection
    (the compute/guard AST is self-referential)."""
    sp = os.path.join(REPO, schema_path) if schema_path else os.path.join(REPO, SCHEMA)
    doc = json.load(open(sp, encoding="utf-8"))
    defs = doc.get("$defs", {})
    paths = set()

    def walk(node, prefix, seen):
        if isinstance(node, dict) and "$ref" in node:
            ref = node["$ref"]
            if ref in seen:
                return
            seen = seen | {ref}
            if ref.startswith("#/$defs/"):
                node = defs.get(ref.split("/")[-1], {})
        if not isinstance(node, dict):
            return
        for k, v in (node.get("properties") or {}).items():
            p = f"{prefix}.{k}" if prefix else k
            paths.add(p)
            if p not in PRUNE_ROOTS:
                walk(v, p, seen)
        if node.get("type") == "array" and "items" in node and prefix not in PRUNE_ROOTS:
            walk(node["items"], prefix + "[]", seen)
        # Schema COMBINATORS (oneOf/anyOf/allOf) are alternative/compound schemas
        # for the SAME node: descend each branch at the same prefix so a property
        # declared only inside a combinator is still discovered (the "new field at
        # any depth" guarantee). A combinator under a PRUNE_ROOT is never reached
        # (its parent stops the descent). Today all three schema combinators sit
        # under prune roots; this keeps the guarantee if a future one does not.
        if prefix not in PRUNE_ROOTS:
            for comb in ("oneOf", "anyOf", "allOf"):
                for sub in (node.get(comb) or []):
                    walk(sub, prefix, seen)

    walk(doc, "", set())
    return paths


def _schema_node_for_path(doc, path):
    """Resolve a dotted schema path to the node at that path. Array path
    components use the inventory form (`effects[]`). The returned node keeps its
    final `$ref` intact; intermediate refs are resolved so paths can cross $defs."""
    defs = doc.get("$defs", {})
    node = doc
    for part in path.split("."):
        if isinstance(node, dict) and "$ref" in node:
            node = defs.get(node["$ref"].split("/")[-1], {})
        is_array = part.endswith("[]")
        key = part[:-2] if is_array else part
        if not isinstance(node, dict):
            raise KeyError(path)
        props = node.get("properties") or {}
        if key not in props:
            raise KeyError(path)
        node = props[key]
        if is_array:
            if isinstance(node, dict) and "$ref" in node:
                node = defs.get(node["$ref"].split("/")[-1], {})
            if not isinstance(node, dict) or "items" not in node:
                raise KeyError(path)
            node = node["items"]
    return node


def _root_ref(node):
    if isinstance(node, dict) and "$ref" in node:
        return node["$ref"]
    if (isinstance(node, dict) and node.get("type") == "array"
            and isinstance(node.get("items"), dict)
            and "$ref" in node["items"]):
        return node["items"]["$ref"]
    return None


def _has_child_surface(node, defs):
    if not isinstance(node, dict):
        return False
    if "$ref" in node and node["$ref"].startswith("#/$defs/"):
        node = defs.get(node["$ref"].split("/")[-1], {})
    if node.get("properties"):
        return True
    if node.get("type") == "array" and "items" in node:
        return True
    return False


def subcontract_schema_paths(schema_path=None):
    """Every path under the schema subcontracts owned by PRUNE_ROOTS. Traversal
    starts from the ACTUAL pruned schema nodes (with optional expected-ref
    binding), so a new inline child or repointed `$ref` fails closed. Local refs
    and combinators are followed, but recursive refs stop at the first cycle (so
    exprNode.lhs/rhs/args are classified without infinite expansion)."""
    sp = os.path.join(REPO, schema_path) if schema_path else os.path.join(REPO, SCHEMA)
    doc = json.load(open(sp, encoding="utf-8"))
    defs = doc.get("$defs", {})
    paths = set()
    fails = []

    def walk(node, prefix, seen):
        if isinstance(node, dict) and "$ref" in node:
            ref = node["$ref"]
            if ref in seen:
                return
            seen = seen | {ref}
            if ref.startswith("#/$defs/"):
                node = defs.get(ref.split("/")[-1], {})
        if not isinstance(node, dict):
            return
        for k, v in (node.get("properties") or {}).items():
            p = f"{prefix}.{k}" if prefix else k
            paths.add(p)
            walk(v, p, seen)
        if node.get("type") == "array" and "items" in node:
            walk(node["items"], prefix + "[]", seen)
        for comb in ("oneOf", "anyOf", "allOf"):
            for sub in (node.get(comb) or []):
                walk(sub, prefix, seen)

    for prune in sorted(PRUNE_ROOTS):
        if prune not in PRUNE_SUBCONTRACT_ROOTS:
            node = _schema_node_for_path(doc, prune)
            if _has_child_surface(node, defs):
                fails.append(f"prune root '{prune}' has child schema surface but "
                             f"no subordinate inventory binding")
            continue
        alias, expected_ref = PRUNE_SUBCONTRACT_ROOTS[prune]
        node = _schema_node_for_path(doc, prune)
        actual_ref = _root_ref(node)
        seen = set()
        if expected_ref:
            if actual_ref != expected_ref:
                fails.append(f"prune root '{prune}' expected {expected_ref} but "
                             f"schema now points at {actual_ref or 'inline schema'}")
                continue
            seen.add(expected_ref)
            node = defs.get(expected_ref.split("/")[-1], {})
        walk(node, alias, seen)

    for prune in sorted(set(PRUNE_SUBCONTRACT_ROOTS) - set(PRUNE_ROOTS)):
        fails.append(f"subordinate inventory binding '{prune}' is not a PRUNE_ROOT "
                     f"(stale — remove it)")
    if fails:
        raise ValueError("; ".join(fails))
    return paths


def _code(path):
    r"""Comment/char-literal-stripped source with string CONTENT kept (so a
    `getArray("effects")` arg is visible but a `'"'` char cannot hide a read)."""
    text = open(path, encoding="utf-8", errors="replace").read()
    return strip_comments(text, keep_string_content=True)


def _section(md, heading):
    out, grab = [], False
    for line in open(md, encoding="utf-8", errors="replace"):
        s = line.strip()
        if s.startswith("## "):
            grab = (s[3:].strip() == heading)
            continue
        if grab and s.startswith("- "):
            out.append(s[2:].strip())
    return out


def governed_sources():
    """The backend production sources: the .cpp the extraction manifests own
    (`Sources owned`, equated to CMake by check_extraction_manifests) PLUS every
    production header under a backend dir — so inference cannot hide in a header."""
    srcs = []
    for md in sorted(glob.glob(os.path.join(REPO, "lib", "backends", "*",
                                            "EXTRACTION.md"))):
        leaf = os.path.dirname(md)
        for s in _section(md, "Sources owned"):
            if s.endswith(".cpp") and not s.startswith("test/"):
                srcs.append(os.path.relpath(os.path.join(leaf, s), REPO))
    for h in sorted(glob.glob(os.path.join(REPO, "lib", "backends", "**", "*.h"),
                              recursive=True)):
        srcs.append(os.path.relpath(h, REPO))
    return srcs


def _target_file_stem(name):
    overrides = {
        "postgres": "Postgres",
    }
    if name in overrides:
        return overrides[name]
    return "".join(part[:1].upper() + part[1:] for part in name.split("-"))


def registered_gated_target_sources():
    """Gated target wrappers from the declarative target registry.

    This keeps  fail-closed for new agent/backend-facing targets: adding a
    gated registry row also adds the conventional wrapper to the one-waist scan.
    """
    path = os.path.join(REPO, TARGET_REGISTRY)
    if not os.path.isfile(path):
        return []
    text = open(path, encoding="utf-8", errors="replace").read()
    out = []
    retained_core_paths = {
        "slot": "lib/slots/SlotTarget.cpp",
        "views": "lib/views/ViewsTarget.cpp",
    }
    for m in re.finditer(r'NEUTRINO_TARGET\(\s*"([^"]+)"\s*,[^)]*?/[*]\s*gated\s*=[*]/\s*true', text):
        name = m.group(1)
        out.append(retained_core_paths.get(
            name, f"lib/targets/{_target_file_stem(name)}Target.cpp"))
    return sorted(set(out))


def discovered_domain_labels():
    import check_conformance_domain_exclusion as conformance_domains
    return set(conformance_domains._production_domains(REPO))


def domain_label_regex(labels=None):
    labels = sorted(
        SYNTHETIC_DOMAIN_LABELS | discovered_domain_labels()
        if labels is None else set(labels)
    )
    if not labels:
        raise ValueError("anti_inference.matcher_vacuous")
    return re.compile(r"\b(?:" + "|".join(re.escape(label) for label in labels) + r")\b")


def has_domain_label(code):
    return bool(domain_label_regex().search(code))


def _finding(identity, path, detail):
    return {"identity": identity, "path": path, "detail": detail}


def _fixture_char_sequences(text):
    """Decode brace-enclosed character arrays without evaluating source code."""
    out = []
    for block in re.finditer(
            r"\{(?:\s*'(?:\\.|[^'\\])'\s*,?)+\s*\}", text, re.S):
        chars = re.findall(r"'(?:\\.|[^'\\])'", block.group(0))
        try:
            out.append("".join(ast.literal_eval(char) for char in chars))
        except (SyntaxError, ValueError):
            continue
    return out


def scan_fixture(path, expected_digest=ADVERSARIAL_FIXTURE_SHA256):
    rel = os.path.relpath(path, REPO) if path.startswith(REPO) else path
    if not os.path.isfile(path):
        return [_finding(
            "anti_inference.fixture_missing", rel,
            "the literal adversarial fixture path does not exist",
        )]
    raw_bytes = open(path, "rb").read()
    raw = raw_bytes.decode("utf-8", errors="replace")
    digest = hashlib.sha256(raw_bytes).hexdigest()
    if not raw.strip() or digest != expected_digest:
        return [_finding(
            "anti_inference.fixture_empty", rel,
            "fixture is empty or differs from its gate-integrity digest pin",
        )]
    try:
        matcher = domain_label_regex(SYNTHETIC_DOMAIN_LABELS)
    except ValueError as exc:
        return [_finding(str(exc), rel, "domain-label matcher has no vocabulary")]
    if len(SEMANTIC_INFERENCE) != len(SEMANTIC_FINDING_IDENTITIES):
        return [_finding(
            "anti_inference.fixture_undetected", rel,
            "semantic detector and fixture identity tables differ in cardinality",
        )]

    identities = [
        FINDING_DOMAIN_LABEL
        for _match in matcher.finditer(_ingestion_code(raw))
    ]
    for decoded in _fixture_char_sequences(raw):
        identities.extend(
            FINDING_DOMAIN_LABEL for _match in matcher.finditer(decoded)
        )
    identities.extend(
        identity
        for identity, (pattern, _detail) in zip(
            SEMANTIC_FINDING_IDENTITIES, SEMANTIC_INFERENCE)
        if pattern.search(_ingestion_code(raw))
    )

    current = collections.Counter(identities)
    expected = collections.Counter(EXPECTED_FIXTURE_IDENTITIES)
    findings = []
    for identity in sorted((expected - current).elements()):
        findings.append(_finding(
            "anti_inference.fixture_undetected", rel,
            f"missing expected injected finding {identity}",
        ))
    for identity in sorted((current - expected).elements()):
        findings.append(_finding(
            "anti_inference.fixture_unexpected", rel,
            f"unexpected injected finding {identity}",
        ))
    return findings


def _generated_manifest_paths(root, candidates):
    """Resolve committed generated products only from generator manifests."""
    generated = {}
    manifests = sorted(glob.glob(
        os.path.join(root, "packaging", "*", "extraction-manifest.json")))
    for manifest in manifests:
        data = json.load(open(manifest, encoding="utf-8"))
        authority = os.path.relpath(manifest, root).replace(os.sep, "/")
        names = set()
        products = data.get("generatedBuildProducts", [])
        if isinstance(products, dict):
            products = products.get("committed", [])
        for item in products if isinstance(products, list) else []:
            names.add(item.get("file") if isinstance(item, dict) else item)
        edges = data.get("dependencyGraph", {}).get("generatedEdges", {})
        if isinstance(edges, dict):
            names.update(edges)
        for name in sorted(n for n in names if isinstance(n, str)):
            matches = [
                rel for rel in candidates
                if rel == name or rel.endswith("/" + name)
            ]
            if len(matches) == 1:
                generated[matches[0]] = (
                    f"generated-product:{authority}"
                )
    return generated


def _externalized_roots(root):
    roots = {}
    for manifest in sorted(glob.glob(
            os.path.join(root, "packaging", "*", "extraction-manifest.json"))):
        data = json.load(open(manifest, encoding="utf-8"))
        rel_manifest = os.path.relpath(manifest, root).replace(os.sep, "/")
        unit_root = data.get("unitRoot")
        boundary = data.get("sourceBoundary")
        if isinstance(unit_root, str):
            roots[unit_root.rstrip("/")] = f"external-package:{rel_manifest}"
        elif isinstance(boundary, str) and boundary.endswith("/EXTRACTION.md"):
            roots[boundary.rsplit("/", 1)[0]] = (
                f"external-package:{rel_manifest}"
            )
    return roots


def _externalized_owned_sources(root):
    owned = {}
    for manifest in sorted(glob.glob(
            os.path.join(root, "lib", "backends", "*", "EXTRACTION.md"))):
        authority = os.path.relpath(manifest, root).replace(os.sep, "/")
        base = os.path.dirname(authority)
        for item in _section(manifest, "Sources owned"):
            if item.startswith("test/"):
                continue
            owned[f"{base}/{item}"] = f"external-package:{authority}"
    return owned


def core_source_files(root=REPO):
    files = []
    for rel_root in CORE_ROOTS:
        base = os.path.join(root, rel_root)
        if not os.path.isdir(base):
            continue
        for dirpath, _dirnames, filenames in os.walk(base):
            for filename in filenames:
                if filename.endswith(CORE_SOURCE_SUFFIXES):
                    files.append(
                        os.path.relpath(
                            os.path.join(dirpath, filename), root
                        ).replace(os.sep, "/")
                    )
    return sorted(files)


def authenticated_core_exclusions(root, candidates):
    exclusions = {}
    generated = _generated_manifest_paths(root, candidates)
    external_roots = _externalized_roots(root)
    external_owned = _externalized_owned_sources(root)
    for rel in candidates:
        parts = rel.split("/")
        if rel in generated:
            exclusions[rel] = generated[rel]
        elif "test" in parts[:-1]:
            exclusions[rel] = "non-production:test-tree"
        elif rel in external_owned:
            exclusions[rel] = external_owned[rel]
        else:
            for prefix, authority in external_roots.items():
                if rel == prefix or rel.startswith(prefix + "/"):
                    exclusions[rel] = authority
                    break
    exclusions[ADVERSARIAL_FIXTURE] = "pinned-adversarial-fixture"
    return exclusions


def core_report(
        root=REPO,
        fixture_path=None,
        expected_fixture_digest=ADVERSARIAL_FIXTURE_SHA256,
        extra_exclusions=None):
    findings = []
    try:
        matcher = domain_label_regex()
    except ValueError as exc:
        matcher = None
        findings.append(_finding(
            str(exc), "<matcher>", "domain-label matcher has no vocabulary"))

    candidates = core_source_files(root)
    exclusions = authenticated_core_exclusions(root, candidates)
    for path, authority in (extra_exclusions or {}).items():
        exclusions[path] = authority
        if not authority:
            findings.append(_finding(
                "anti_inference.unauthenticated_exclusion", path,
                "excluded path has no generator, test-tree, package, or fixture authority",
            ))
    included = [rel for rel in candidates if rel not in exclusions]
    if not included:
        findings.append(_finding(
            "anti_inference.corpus_empty", "<core>",
            "the real-core scan discovered zero production source files",
        ))

    one_waist = set(one_waist_sources())
    for rel in included:
        path = os.path.join(root, rel)
        raw = open(path, encoding="utf-8", errors="replace").read()
        code = strip_comments(raw, keep_string_content=True)
        if SUPPRESSION_RE.search(raw):
            findings.append(_finding(
                "anti_inference.suppressed_finding", rel,
                "source contains an anti-inference suppression mechanism",
            ))
        if matcher:
            for match in matcher.finditer(code):
                findings.append(_finding(
                    FINDING_DOMAIN_LABEL, rel,
                    f"production-domain label {match.group(0)!r}",
                ))
        if rel in one_waist:
            for identity, (pattern, detail) in zip(
                    SEMANTIC_FINDING_IDENTITIES, SEMANTIC_INFERENCE):
                if pattern.search(code):
                    findings.append(_finding(identity, rel, detail))

    fixture_path = fixture_path or os.path.join(root, ADVERSARIAL_FIXTURE)
    findings.extend(scan_fixture(fixture_path, expected_fixture_digest))
    return {
        "kind": "neutrino.anti-inference-core-report/1",
        "executed": True,
        "scannedFileCount": len(included),
        "excludedPathCount": len(exclusions),
        "excludedPaths": [
            {"path": path, "authority": exclusions[path]}
            for path in sorted(exclusions)
        ],
        "fixturePath": ADVERSARIAL_FIXTURE,
        "fixtureSha256": expected_fixture_digest,
        "findings": findings,
    }


def _write_execution_record(path, report):
    with open(path, "w", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write("\n")


def registered_core_report(record_path=None, writer=_write_execution_record):
    owned_tmp = None
    if record_path is None:
        owned_tmp = tempfile.TemporaryDirectory(
            prefix="anti_inference_core_record.")
        record_path = os.path.join(owned_tmp.name, "report.json")
    if os.path.exists(record_path):
        os.unlink(record_path)
    report = core_report()
    try:
        writer(record_path, report)
    except OSError:
        pass
    try:
        recorded = json.load(open(record_path, encoding="utf-8"))
    except (OSError, ValueError):
        recorded = {}
    if recorded.get("executed") is not True:
        report["findings"].append(_finding(
            "anti_inference.not_executed", record_path,
            "registered production execution record is absent or malformed",
        ))
    if owned_tmp:
        owned_tmp.cleanup()
    return report


def _print_core_report(report):
    for excluded in report["excludedPaths"]:
        print(
            f"anti-inference excluded: {excluded['path']} "
            f"[{excluded['authority']}]"
        )
    for finding in report["findings"]:
        print(
            f"{finding['identity']}: {finding['path']}: {finding['detail']}",
            file=sys.stderr,
        )
    if not report["findings"]:
        print(
            "anti-inference core OK: "
            f"{report['scannedFileCount']} production source file(s) scanned; "
            f"{report['excludedPathCount']} authenticated exclusion(s); "
            "fixture identities 6/6; zero core findings"
        )


def check_core(record_path=None):
    report = registered_core_report(record_path)
    _print_core_report(report)
    if not report["findings"]:
        return 0
    infrastructure = {
        "anti_inference.fixture_missing",
        "anti_inference.fixture_empty",
        "anti_inference.fixture_undetected",
        "anti_inference.fixture_unexpected",
        "anti_inference.corpus_empty",
        "anti_inference.matcher_vacuous",
        "anti_inference.unauthenticated_exclusion",
        "anti_inference.not_executed",
    }
    return 2 if any(
        finding["identity"] in infrastructure
        for finding in report["findings"]
    ) else 1


CORE_PROBE_IDENTITIES = {
    "fixture-missing": "anti_inference.fixture_missing",
    "fixture-empty": "anti_inference.fixture_empty",
    "fixture-undetected": "anti_inference.fixture_undetected",
    "fixture-unexpected": "anti_inference.fixture_unexpected",
    "corpus-empty": "anti_inference.corpus_empty",
    "matcher-vacuous": "anti_inference.matcher_vacuous",
    "unauthenticated-exclusion": "anti_inference.unauthenticated_exclusion",
    "suppressed-finding": "anti_inference.suppressed_finding",
    "not-executed": "anti_inference.not_executed",
}


def core_probe_findings(name):
    fixture = os.path.join(REPO, ADVERSARIAL_FIXTURE)
    if name == "fixture-missing":
        return scan_fixture(fixture + ".missing")
    if name in {
            "fixture-empty", "fixture-undetected", "fixture-unexpected"}:
        original = open(fixture, encoding="utf-8").read()
        if name == "fixture-empty":
            mutated = ""
            digest = ADVERSARIAL_FIXTURE_SHA256
        elif name == "fixture-undetected":
            mutated = original.replace("effects[0]", "effect_at_zero", 1)
            digest = hashlib.sha256(mutated.encode()).hexdigest()
        else:
            mutated = (
                original
                + '\nconst char *unexpected = '
                  '"__neu_gate_synthetic_domain_alpha";\n'
            )
            digest = hashlib.sha256(mutated.encode()).hexdigest()
        with tempfile.NamedTemporaryFile(
                "w", suffix=".cpp", delete=False) as stream:
            stream.write(mutated)
            path = stream.name
        try:
            return scan_fixture(path, digest)
        finally:
            os.unlink(path)
    if name == "matcher-vacuous":
        try:
            domain_label_regex(set())
        except ValueError as exc:
            return [_finding(
                str(exc), "<matcher>", "empty matcher mutation rejected")]
        return []
    if name == "not-executed":
        with tempfile.TemporaryDirectory(
                prefix="anti_inference_not_executed.") as tmp:
            report = registered_core_report(
                os.path.join(tmp, "report.json"),
                writer=lambda _path, _report: None,
            )
            return report["findings"]

    with tempfile.TemporaryDirectory(
            prefix="anti_inference_core_probe.") as tmp:
        lib = os.path.join(tmp, "lib")
        os.makedirs(lib)
        probe = os.path.join(lib, "probe.cpp")
        if name == "suppressed-finding":
            _overwrite(probe, "#define ANTI_INFERENCE_DISABLE 1\n")
            report = core_report(root=tmp, fixture_path=fixture)
        elif name == "unauthenticated-exclusion":
            _overwrite(probe, "namespace core_probe {}\n")
            report = core_report(
                root=tmp,
                fixture_path=fixture,
                extra_exclusions={"lib/probe.cpp": ""},
            )
        elif name == "corpus-empty":
            report = core_report(root=tmp, fixture_path=fixture)
        else:
            return []
        return report["findings"]


def run_core_probe(name):
    expected = CORE_PROBE_IDENTITIES[name]
    findings = core_probe_findings(name)
    if any(finding["identity"] == expected for finding in findings):
        print(f"probe-failed-as-expected:{name} {expected}")
        return 1
    print(
        f"probe unexpectedly passed {name}: "
        f"{[finding['identity'] for finding in findings]}"
    )
    return 0


def one_waist_sources():
    """Every below-waist consumer governed by .

    Backend files are derived from the existing extraction/CMake ownership
    surface; evaluator/reducer/tool seams are named because they live outside
    backend manifests. Sibling-projection leaves stay reviewed separately and do
    not widen this consumer surface.
    """
    srcs = set(governed_sources())
    srcs.update(ONE_WAIST_EXTRA_SOURCES)
    srcs.update(registered_gated_target_sources())
    return sorted(srcs)


def scan_semantic(code):
    return [why for rx, why in SEMANTIC_INFERENCE if rx.search(code)]


def is_json_free(code):
    return not JSON_TYPE.search(code) and not JSON_INCLUDE.search(code)


def _ingestion_code(src):
    """The comment/char-stripped coordination-plan contract source — the full
    spec-ingestion surface: planFromSpec AND the spec-reading helpers it calls
    (typeSpecExprs, attestationPoliciesFromSpec, operandKey, acceptedInputFromAst)
    all live in THIS one file. Each completeness witness is an object-scoped
    getter access, so searching the whole (stripped) file is safe — a bare string
    literal cannot satisfy a `<obj>->getX("<key>")` witness."""
    return strip_comments(src, keep_string_content=True)


def check_completeness(schema_path=None, contract_path=None):
    fails = []
    try:
        paths = schema_paths(schema_path)
    except Exception as e:  # noqa: BLE001 — a broken schema fails closed
        return [f"cannot read the capability-spec schema {SCHEMA}: {e}"]
    classified = set(SCHEMA_FIELD_ROLE)
    for f in sorted(paths - classified):
        fails.append(f"capability-spec schema path '{f}' is NOT classified in the "
                     f"anti-inference inventory — triage it normalized/structural/"
                     f"meta (a new behavior-driving field must normalize into the "
                     f"CoordinationPlan ; a new subtree may need a PRUNE_ROOT)")
    for f in sorted(classified - paths):
        fails.append(f"inventory path '{f}' is not a capability-spec schema path "
                     f"(stale — remove it)")
    pp = os.path.join(REPO, contract_path) if contract_path else os.path.join(
        REPO, COORDINATION_PLAN_SPEC)
    code = _ingestion_code(open(pp, encoding="utf-8", errors="replace").read())
    if "planFromSpec" not in code:
        return fails + [f"planFromSpec not found in {COORDINATION_PLAN_SPEC}"]
    for f, (role, witness) in SCHEMA_FIELD_ROLE.items():
        if role == "normalized" and not witness.search(code):
            fails.append(f"schema field '{f}' is behavior-driving but the "
                         f"coordination-plan contract has no scoped parse "
                         f"(/{witness.pattern}/) reading it into the coordination "
                         f"plan (a dropped/renamed decision — the coordination plan "
                         f"no longer validates it, or the parse's object variable "
                         f"was renamed)")
    fails += check_subcontract_completeness(schema_path)
    return fails


def check_subcontract_completeness(schema_path=None):
    fails = []
    try:
        paths = subcontract_schema_paths(schema_path)
    except Exception as e:  # noqa: BLE001 — a broken schema fails closed
        return [f"cannot read capability-spec subcontracts from {SCHEMA}: {e}"]
    classified = set(SUBCONTRACT_FIELD_ROLE)
    for f in sorted(paths - classified):
        fails.append(f"capability-spec subcontract path '{f}' is NOT classified "
                     f"in the anti-inference inventory — triage it normalized/"
                     f"structural/meta or bind it to a subordinate parser gate")
    for f in sorted(classified - paths):
        fails.append(f"subcontract inventory path '{f}' is not a capability-spec "
                     f"schema path (stale — remove it)")

    cache = {}
    def source(rel):
        if rel not in cache:
            p = os.path.join(REPO, rel)
            cache[rel] = strip_comments(open(p, encoding="utf-8",
                                             errors="replace").read(),
                                        keep_string_content=True)
        return cache[rel]

    for f, (role, witness, rel) in SUBCONTRACT_FIELD_ROLE.items():
        if role == "normalized" and not witness.search(source(rel)):
            fails.append(f"schema subcontract field '{f}' is behavior-driving but "
                         f"{rel} has no scoped parser witness "
                         f"(/{witness.pattern}/) consuming or validating it")
    return fails


def _scan_source(rel, code):
    fails = []
    for why in scan_semantic(code):
        fails.append(f"{rel}: {why}")
    if rel not in JSON_LEGITIMATE and not is_json_free(code):
        fails.append(f"{rel}: reads the raw capability-spec (a `json::` type / JSON "
                     f"header) but is not on the reviewed JSON-legitimate allowlist "
                     f"— legalize off coordinationPlan only, or add a conscious "
                     f"entry with a role reason")
    if L2_OR_UPPER_LAYER.search(code):
        fails.append(f"{rel}: backend source reads L2 / upper-layer artifacts below "
                     f"the one-waist boundary — consume verified CoordinationPlan")
    if has_domain_label(code):
        fails.append(f"{rel}: branches on a domain-specific label below the one-waist "
                     f"boundary — keep reducers/targets domain-blind")
    return fails


def check_one_waist_boundary():
    fails = []
    sources = one_waist_sources()
    gated_targets = set(registered_gated_target_sources())
    if len(sources) < MIN_ONE_WAIST_CONSUMERS:
        fails.append(f"discovered {len(sources)} one-waist consumer source(s) < "
                     f"{MIN_ONE_WAIST_CONSUMERS} (backend/evaluator/reducer/tool "
                     f"surface eroded or is mis-derived)")
    for rel in sources:
        p = os.path.join(REPO, rel)
        if not os.path.isfile(p):
            fails.append(f"{rel}: one-waist governed source is missing")
            continue
        code = _code(p)
        for why in scan_semantic(code):
            fails.append(f"{rel}: {why}")
        if rel in EVALUATOR_WAIST_SOURCES and CAPABILITY_SPEC_DECISION_READ.search(code):
            fails.append(f"{rel}: evaluator/trace code reads capability-spec decision "
                         f"fields directly — consume the verified CoordinationPlan")
        if rel in gated_targets and CAPABILITY_SPEC_DECISION_READ.search(code):
            fails.append(f"{rel}: gated target wrapper reads capability-spec decision "
                         f"fields directly — production artifact decisions must consume "
                         f"the verified CoordinationPlan")
        if rel in EVALUATOR_WAIST_SOURCES and L2_OR_UPPER_LAYER.search(code):
            fails.append(f"{rel}: evaluator code reaches above/beside the waist "
                         f"(L2/domain artifacts) — consume CoordinationPlan only")
        if has_domain_label(code):
            fails.append(f"{rel}: domain-specific label appears below the one-waist "
                         f"boundary — reducer/target/evaluator code must be "
                         f"domain-blind")
        if (rel not in GENERIC_REDUCTION_SOURCES
                and rel not in {EXTERNAL_SPEC_SEAM, "tools/neutrino-emit/neutrino-emit.cpp"}
                and rel not in SELF_EMITTED_SPEC_WRAPPERS
                and rel not in SPEC_SIBLING_LEGITIMATE
                and L2_OR_UPPER_LAYER.search(code)):
            fails.append(f"{rel}: reads L2 / upper-layer artifacts below the one-waist "
                         f"boundary — consume verified CoordinationPlan")

    seam = os.path.join(REPO, EXTERNAL_SPEC_SEAM)
    if os.path.isfile(seam):
        seam_code = _code(seam)
        if "planFromSpec" not in seam_code:
            fails.append(f"{EXTERNAL_SPEC_SEAM}: external capability-spec seam no "
                         f"longer passes through planFromSpec")
        if DIRECT_SPEC_RENDER.search(seam_code):
            fails.append(f"{EXTERNAL_SPEC_SEAM}: external capability-spec bypasses "
                         f"planFromSpec and renders a target directly from specObj")
    else:
        fails.append(f"{EXTERNAL_SPEC_SEAM}: external capability-spec seam is missing")

    for rel, reason in SPEC_SIBLING_LEGITIMATE.items():
        p = os.path.join(REPO, rel)
        if not os.path.isfile(p):
            fails.append(f"spec-sibling allowlist entry {rel} is missing ({reason})")
            continue
        code = _code(p)
        if is_json_free(code) and "SelfEmittedSpec" not in code:
            fails.append(f"spec-sibling allowlist entry {rel} no longer consumes the "
                         f"capability-spec sibling projection — remove it ({reason})")

    return fails


def check_all():
    fails = []
    governed = governed_sources()
    if len(governed) < MIN_GOVERNED:
        fails.append(f"discovered {len(governed)} governed backend source(s) < "
                     f"{MIN_GOVERNED} (manifests + backend dirs — mis-derived?)")

    adapters = 0
    for rel in governed:
        p = os.path.join(REPO, rel)
        if not os.path.isfile(p):
            fails.append(f"{rel}: governed but the file is missing")
            continue
        code = _code(p)
        fails += _scan_source(rel, code)
        # Count only .cpp IMPLEMENTATIONS toward the floor — a header declaration
        # cannot inflate the graph-only adapter floor.
        if (rel.endswith(".cpp") and ADAPTER_SIG.search(code)
                and rel not in JSON_LEGITIMATE):
            adapters += 1

    for rel, reason in JSON_LEGITIMATE.items():
        if rel not in governed:
            fails.append(f"JSON-legitimate allowlist entry {rel} is not a governed "
                         f"backend source (stale — remove it)")
        elif os.path.isfile(os.path.join(REPO, rel)) and is_json_free(
                _code(os.path.join(REPO, rel))):
            fails.append(f"JSON-legitimate allowlist entry {rel} no longer reads "
                         f"JSON — remove it so the boundary tightens ({reason})")

    if adapters < MIN_ADAPTERS:
        fails.append(f"discovered {adapters} graph-only backend adapter(s) < "
                     f"{MIN_ADAPTERS} (a materialize<X>Projection("
                     "const BackendProjectionGraph&) TU was renamed / moved / relaxed?)")

    fails += check_completeness()
    fails += check_one_waist_boundary()

    if fails:
        print("anti-inference boundary VIOLATED ():\n  " + "\n  ".join(fails),
              file=sys.stderr)
        return 1
    print(f"anti-inference gate OK: {len(governed)} governed backend source(s) "
          f"({adapters} graph-only backend adapters, {len(JSON_LEGITIMATE)} reviewed "
          f"JSON-legitimate); no raw-spec semantic inference; all "
          f"{sum(1 for r, _ in SCHEMA_FIELD_ROLE.values() if r == 'normalized')} "
          f"behavior-driving schema fields normalize into the coordination plan ()")
    return 0


def check_one(path):
    code = _code(path)
    fails = list(scan_semantic(code))
    if not is_json_free(code):
        fails.append("reads the raw capability-spec (a `json::` type / JSON header) "
                     "in a legalization TU — legalize off coordinationPlan only")
    if L2_OR_UPPER_LAYER.search(code):
        fails.append("reads L2 / upper-layer artifacts below the one-waist boundary "
                     "— consume verified CoordinationPlan")
    if has_domain_label(code):
        fails.append("branches on a domain-specific label below the one-waist "
                     "boundary — reducers/targets must be domain-blind")
    if fails:
        rel = os.path.relpath(path, REPO) if path.startswith(REPO) else path
        print("anti-inference boundary VIOLATED ():\n  " +
              "\n  ".join(f"{rel}: {w}" for w in fails), file=sys.stderr)
        return 1
    print(f"ok: {os.path.basename(path)} does no raw-spec semantic inference")
    return 0


def _overwrite(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def selftest():
    fails = []
    governed = governed_sources()
    if len(governed) < MIN_GOVERNED:
        fails.append(f"floor: {len(governed)} governed source(s) < {MIN_GOVERNED}")
    production = core_report()
    if production["findings"]:
        fails.append(
            "the committed core tree or pinned fixture does not pass the "
            "two-leg gate: " + "; ".join(
                finding["identity"] for finding in production["findings"]))
    for probe, expected in CORE_PROBE_IDENTITIES.items():
        findings = core_probe_findings(probe)
        if not any(finding["identity"] == expected for finding in findings):
            fails.append(
                f"two-leg probe {probe} did not reach {expected}: "
                f"{[finding['identity'] for finding in findings]}"
            )

    one_waist = one_waist_sources()
    if len(one_waist) < MIN_ONE_WAIST_CONSUMERS:
        fails.append(f"floor: {len(one_waist)} one-waist source(s) < "
                     f"{MIN_ONE_WAIST_CONSUMERS}")
    discovered = sorted(discovered_domain_labels())
    gated_targets = registered_gated_target_sources()
    for expected in ("lib/targets/PostgresTarget.cpp",
                     "lib/slots/SlotTarget.cpp", "lib/views/ViewsTarget.cpp"):
        if expected not in gated_targets or expected not in one_waist:
            fails.append(f"registry-derived gated target wrapper {expected} is not "
                         f"in the one-waist governed surface")

    # (A/B) --file injection into a real graph-only backend adapter.
    adapter = next((os.path.join(REPO, r) for r in governed
                      if r.endswith(".cpp") and r not in JSON_LEGITIMATE
                      and ADAPTER_SIG.search(_code(os.path.join(REPO, r)))), None)
    if not adapter:
        fails.append("could not find a graph-only adapter to drive the injection probe")
    else:
        base = open(adapter, encoding="utf-8", errors="replace").read()
        for inj, label in [
            ('void _l(const llvm::json::Object &spec){auto k=spec.getArray("effects")'
             '->front();(void)k;}\n', "first-effect key (json param)"),
            ('void _l(const llvm::json::Object &spec){char q=\'"\';(void)q;'
             'auto x=spec.find("effects");(void)x;}\n', "char-literal-obfuscated find"),
        ]:
            with tempfile.NamedTemporaryFile("w", suffix=".cpp", delete=False) as t:
                t.write(base + "\n" + inj)
                tmp = t.name
            try:
                if check_one(tmp) == 0:
                    fails.append(f"--file did NOT reject an injected {label}")
            finally:
                os.unlink(tmp)

        with tempfile.NamedTemporaryFile("w", suffix=".cpp", delete=False) as t:
            t.write(base + '\n#include "Neutrino/L2Dialect.h"\n'
                    'void _l2(neutrino::l2::DomainOp d){(void)d;}\n')
            tmp = t.name
        try:
            if check_one(tmp) == 0:
                fails.append("--file did NOT reject a backend L2 read below the "
                             "one-waist boundary")
        finally:
            os.unlink(tmp)

        with tempfile.NamedTemporaryFile("w", suffix=".cpp", delete=False) as t:
            t.write(base + '\nstatic bool _domain(const char *name) {\n'
                    '  return name == std::string("__neu_gate_synthetic_domain_alpha");\n}\n')
            tmp = t.name
        try:
            if check_one(tmp) == 0:
                fails.append("--file did NOT reject a below-waist domain label branch")
        finally:
            os.unlink(tmp)

    # (A/B) FULL-GATE tamper: mutate a real ALLOWLISTED source in place with a
    # first-effect selection, run the full check_all() CI path, assert it rejects,
    # then restore — proving the CI path (not just --file) covers allowlisted TUs.
    harness = next((os.path.join(REPO, r) for r in JSON_LEGITIMATE
                    if r.endswith(".cpp") and os.path.isfile(os.path.join(REPO, r))
                    and "Test" in r), None)
    if harness:
        original = open(harness, encoding="utf-8", errors="replace").read()
        try:
            _overwrite(harness, original + '\nvoid _fg(const llvm::json::Object &s)'
                       '{auto k=s.getArray("effects")->front();(void)k;}\n')
            if check_all() == 0:
                fails.append("check_all() did NOT reject inference injected into an "
                             "allowlisted source (the CI path is vacuous!)")
        finally:
            _overwrite(harness, original)

    # ( /  S2) FULL-GATE tampers for the one-waist sibling-projection
    # rule. These mutate real governed sources in place and restore them, proving
    # CI catches direct evaluator spec reads, external spec bypasses, reducer
    # domain branching, and target domain labels on the complete source surface.
    evaluator = os.path.join(REPO, "lib/spec-contract/CoordinationEval.cpp")
    original = open(evaluator, encoding="utf-8", errors="replace").read()
    try:
        _overwrite(evaluator, original + '\n#include "llvm/Support/JSON.h"\n'
                   'void _eval_spec(const llvm::json::Object &spec) {\n'
                   '  (void)spec.getArray("effects");\n}\n')
        if not any("evaluator/trace code reads capability-spec" in f
                   for f in check_one_waist_boundary()):
            fails.append("one-waist gate did NOT reject evaluator direct "
                         "capability-spec decision reads")
    finally:
        _overwrite(evaluator, original)

    seam = os.path.join(REPO, EXTERNAL_SPEC_SEAM)
    original = open(seam, encoding="utf-8", errors="replace").read()
    try:
        _overwrite(seam, original + "\nvoid _external_bypass("
                   "const llvm::json::Object &specObj) { "
                   "generatePostgresProcedureFromSpec(specObj); }\n")
        if not any("bypasses planFromSpec" in f
                   for f in check_one_waist_boundary()):
            fails.append("one-waist gate did NOT reject an external "
                         "specObj -> target render bypass")
    finally:
        _overwrite(seam, original)

    reducer = os.path.join(REPO, "lib/L2Reduction.cpp")
    original = open(reducer, encoding="utf-8", errors="replace").read()
    try:
        _overwrite(reducer, original + '\nstatic bool _domain_branch() {\n'
                   '  return std::string("__neu_gate_synthetic_domain_alpha").size() != 0;\n}\n')
        if not any("domain-specific label" in f
                   for f in check_one_waist_boundary()):
            fails.append("one-waist gate did NOT reject a generic reducer "
                         "domain-specific branch")
    finally:
        _overwrite(reducer, original)

    if discovered:
        original = open(reducer, encoding="utf-8", errors="replace").read()
        try:
            _overwrite(reducer, original + '\nstatic bool _real_domain_branch() {\n'
                       f'  return std::string("{discovered[0]}").size() != 0;\n'
                       '}\n')
            if not any("domain-specific label" in f
                       for f in check_one_waist_boundary()):
                fails.append("one-waist gate did NOT reject a dynamically discovered "
                             "real domain label below the waist")
        finally:
            _overwrite(reducer, original)

    target = os.path.join(REPO, "lib/targets/PostgresTarget.cpp")
    original = open(target, encoding="utf-8", errors="replace").read()
    try:
        _overwrite(target, original + '\nstatic bool _target_domain_branch() {\n'
                   '  return std::string("__neu_gate_synthetic_domain_beta").size() != 0;\n}\n')
        if not any("domain-specific label" in f
                   for f in check_one_waist_boundary()):
            fails.append("one-waist gate did NOT reject a below-waist target "
                         "domain-specific branch")
    finally:
        _overwrite(target, original)

    for spelling, label in (
            ('spec.getArray("effects")', "typed getter"),
            ('spec.get("effects")', "base Object::get"),
            ('spec["effects"]', "direct subscript")):
        original = open(target, encoding="utf-8", errors="replace").read()
        try:
            _overwrite(target, original + '\n#include "llvm/Support/JSON.h"\n'
                       'void _target_spec(const llvm::json::Object &spec) {\n'
                       f'  (void){spelling};\n}}\n')
            if not any("gated target wrapper reads capability-spec decision" in f
                       for f in check_one_waist_boundary()):
                fails.append("one-waist gate did NOT reject a gated target wrapper "
                             f"{label} capability-spec decision read")
        finally:
            _overwrite(target, original)

    # (P2) ADAPTER_SIG counts definitions, not declarations.
    declaration = (
        "SolidityContract materializeSolidityProjection("
        "const projection::BackendProjectionGraph &g);"
    )
    definition = (
        "Foo materializeSolidityProjection("
        "const projection::BackendProjectionGraph &g) {\n}"
    )
    if ADAPTER_SIG.search(declaration):
        fails.append("ADAPTER_SIG matched a declaration ending in ';' — the "
                     "adapter floor would count non-implementations")
    if not ADAPTER_SIG.search(definition):
        fails.append("ADAPTER_SIG did NOT match a real definition body ') {'")

    # (C) completeness mutations through the real check paths — the SCOPED-witness
    # proof. The reviewer's ALIASING probe: `"name"` is read for inputs, computes,
    # AND effects; renaming ONLY effects[].name's object-scoped read must fail
    # THAT path and NOT its two siblings — and a bare "name" literal appended must
    # not rescue it.
    contract = os.path.join(REPO, COORDINATION_PLAN_SPEC)
    txt = open(contract, encoding="utf-8", errors="replace").read()
    if 'eo->getString("name")' not in txt:
        fails.append('selftest expected `eo->getString("name")` in the contract')
    else:
        mutated = (txt.replace('eo->getString("name")', 'eo->getString("dropped")', 1)
                   + '\nstatic const char *_dead = "name";\n')  # must not rescue
        with tempfile.NamedTemporaryFile("w", suffix=".cpp", delete=False) as t:
            t.write(mutated)
            tmp = t.name
        try:
            rel = os.path.relpath(tmp, REPO) if tmp.startswith(REPO) else tmp
            failed = check_completeness(contract_path=rel)
            if not any("'effects[].name'" in f for f in failed):
                fails.append("completeness did NOT fail on a dropped effects[].name "
                             "scoped read (aliasing hole still open, or a dead "
                             "literal rescued it)")
            aliased = [f for f in failed if "'inputs[].name'" in f
                       or "'computes[].name'" in f]
            if aliased:
                fails.append("completeness WRONGLY flagged a sibling 'name' path "
                             "when only effects[].name was dropped (witness not "
                             "scoped): " + "; ".join(aliased))
        finally:
            os.unlink(tmp)

    # Nested-field scoped renames (top-level, effect object, compute object,
    # lifecycle terminal) — each must fail its OWN path.
    for real, label in [('spec.getArray("invariants")', "top-level invariants"),
                        ('eo->getObject("when")', "nested effects[].when"),
                        ('co->getString("category")', "nested computes[].category"),
                        ('term->getString("success")', "nested lifecycle terminal")]:
        if real not in txt:
            fails.append(f"selftest expected `{real}` in the contract ({label})")
            continue
        with tempfile.NamedTemporaryFile("w", suffix=".cpp", delete=False) as t:
            t.write(txt.replace(real, real.replace('"', '"_x', 1), 1))
            tmp = t.name
        try:
            rel = os.path.relpath(tmp, REPO) if tmp.startswith(REPO) else tmp
            if not check_completeness(contract_path=rel):
                fails.append(f"completeness did NOT fail on a dropped {label} parse")
        finally:
            os.unlink(tmp)

    # A NEW unclassified schema field — top-level, NESTED (under effects[]), AND
    # hidden inside a oneOf/anyOf/allOf COMBINATOR at an unpruned node — must fail
    # the recursive equality check (the walker descends combinators, so the
    # "new field at any depth" guarantee holds even under a future combinator).
    for mutate, label in [
        (lambda s: s["properties"].__setitem__("_newTop", {"type": "string"}),
         "new top-level field"),
        (lambda s: s["properties"]["effects"]["items"]["properties"].__setitem__(
            "_newNested", {"type": "string"}), "new nested effects[] field"),
        (lambda s: s["properties"]["effects"]["items"].__setitem__(
            "oneOf", [{"properties": {"_newInComb": {"type": "string"}}}]),
         "new field inside an effects[] oneOf combinator"),
    ]:
        sd = json.load(open(os.path.join(REPO, SCHEMA), encoding="utf-8"))
        mutate(sd)
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as t:
            json.dump(sd, t)
            tmp = t.name
        try:
            rel = os.path.relpath(tmp, REPO) if tmp.startswith(REPO) else tmp
            if not check_completeness(schema_path=rel):
                fails.append(f"completeness did NOT fail on a {label}")
        finally:
            os.unlink(tmp)

    # P1 re-review (): PRUNE_ROOTS must not hide new semantic leaves. Each
    # owned subtree has a subordinate inventory, so a field added under lifecycle
    # transition, operand, or attestation policy is still rejected.
    for mutate, label in [
        (lambda s: s["$defs"]["transition"]["properties"].__setitem__(
            "_new_behavior", {"type": "string"}), "new transition leaf under a prune root"),
        (lambda s: s["$defs"]["operand"]["properties"].__setitem__(
            "_new_operand_leaf", {"type": "string"}), "new operand leaf under a prune root"),
        (lambda s: s["$defs"]["attestationPolicy"]["properties"]["observerSet"]
         ["properties"].__setitem__("_new_attestation_leaf", {"type": "string"}),
         "new attestation leaf under a prune root"),
        (lambda s: s["properties"]["lifecycle"]["properties"]["instanceKey"]
         ["properties"].__setitem__("_new_behavior", {"type": "string"}),
         "new inline instanceKey leaf under a prune root"),
        (lambda s: (
            s["$defs"].__setitem__("transitionV2", copy.deepcopy(s["$defs"]["transition"])),
            s["$defs"]["transitionV2"]["properties"].__setitem__(
                "_new_behavior", {"type": "string"}),
            s["properties"]["lifecycle"]["properties"]["transitions"]["items"]
            .__setitem__("$ref", "#/$defs/transitionV2")),
         "repointed transition prune-root ref"),
    ]:
        sd = json.load(open(os.path.join(REPO, SCHEMA), encoding="utf-8"))
        mutate(sd)
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as t:
            json.dump(sd, t)
            tmp = t.name
        try:
            rel = os.path.relpath(tmp, REPO) if tmp.startswith(REPO) else tmp
            if not check_completeness(schema_path=rel):
                fails.append(f"subcontract completeness did NOT fail on a {label}")
        finally:
            os.unlink(tmp)

    if fails:
        print("anti-inference SELFTEST FAILED:\n  " + "\n  ".join(fails),
              file=sys.stderr)
        return 1
    print(f"anti-inference selftest PASS ({len(governed)} governed sources swept; "
          "the committed tree is clean; the gate rejects injected json-access / "
          "char-literal-obfuscated reads, a first-effect selection in an allowlisted "
          "source through check_all(), backend L2 reads, evaluator spec reads, "
          "external spec render bypasses, reducer/target domain-label branches, a "
          "gated target-wrapper typed-getter, base-get, and subscript "
          "capability-spec decision read, a "
          "legalizer DECLARATION (not a definition), a "
          "dropped OBJECT-SCOPED parse without flagging its aliased `name` siblings, "
          "and a new unclassified schema field — top-level, nested, and inside a "
          "oneOf combinator, plus new transition/operand/attestation leaves under "
          "pruned subcontracts, inline instanceKey children, and prune-root ref drift)")
    return 0


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", help="scan a single source (the tamper probe)")
    ap.add_argument("--selftest", action="store_true",
                    help="prove the gate discovers the sources and bites on a bypass")
    ap.add_argument("--check-core", action="store_true",
                    help="run the registered real-core + pinned-fixture production gate")
    ap.add_argument("--execution-record",
                    help="write and verify the production execution record at PATH")
    ap.add_argument("--probe-core", choices=sorted(CORE_PROBE_IDENTITIES),
                    help="run one externally addressable two-leg mutation")
    args = ap.parse_args()
    if sum(bool(item) for item in (
            args.selftest, args.file, args.check_core,
            args.probe_core)) > 1:
        ap.error(
            "--selftest, --file, --check-core, and --probe-core are "
            "mutually exclusive")
    if args.selftest:
        return selftest()
    if args.check_core:
        return check_core(args.execution_record)
    if args.probe_core:
        return run_core_probe(args.probe_core)
    if args.file:
        return check_one(args.file)
    return check_all()


if __name__ == "__main__":
    sys.exit(main())

#ifndef NEUTRINO_GEN_SPEC_H
#define NEUTRINO_GEN_SPEC_H

#include "Neutrino/CoordinationPlan.h"
#include "Neutrino/Scenario.h"
#include "Neutrino/SelfEmittedSpec.h"
#include "Neutrino/View.h"

#include <string>
#include <vector>

namespace neutrino {

// `--target=capability-spec` (M5 WP1d, ): emit the canonical compiled
// capability-spec — the ONLY frozen external contract of the M5 architecture
// (ADR D1). The capability-spec is a deterministic, canonical (sorted-key) JSON
// serialization of the semantic model (typed inputs, compute ASTs, effects,
// invariants, participants, topology, the coordination lifecycle machine,
// structured target requirements, source map) that every renderer consumes
// instead of re-deriving from ProcedureView. Emitted from SOURCE ALONE — the
// Scenario argument is ignored (D2: the capability-spec is scenario-free) — so
// it is present only to satisfy the shared EmitFn signature. Writes
// capability-spec.json. Schema: docs/schemas/capability-spec.schema.json;
// validator: scripts/validators/validate_capability_spec.py. See
// docs/spec/CAPABILITY_SPEC.md.
// (: "spec" is a network/runtime concept; the translator emits a compiled
// capability-spec. This header keeps its GenSpec.h name as an internal detail.)
std::vector<std::string>
emitCapabilitySpec(const ProcedureView &view, const Scenario &,
                   const std::string &outDir,
                   const CoordinationPlan &coordinationPlan);

// The canonical capability-spec JSON for `view` (the exact bytes written to
// capability-spec.json). Exposed for tests. Deterministic and
// byte-reproducible: no timestamps / git sha, sorted keys, hashes computed over
// the compact canonical form of the relevant subsets.
std::string capabilitySpecJson(const ProcedureView &view,
                               const CoordinationPlan &coordinationPlan);

// The single emit-side seam ( S3 / ) every registry entry uses to
// obtain the frozen capability-spec object for `view`: it emits
// capabilitySpecJson(view) and ingests it via the shared SelfEmittedSpec
// adapter, which fails CLOSED (report_fatal_error) on the internal invariant
// that our OWN output must parse to an object. Returned by value; C++17
// guaranteed copy elision initializes the caller's local with no move. Keeps
// the ProcedureView on the emit side of the boundary — the leaf renderers
// receive only the resulting `object()`.
SelfEmittedSpec ingestSelfEmittedSpec(const ProcedureView &view,
                                      const CoordinationPlan &coordinationPlan);

// The capabilityHash for `view`: sha256 over the compact canonical semantic
// core — the SAME value the spec's identity.capabilityHash carries. It is a
// function of the source-derived ProcedureView ALONE (no scenario), so folding
// a scenario never changes it. Exposed so the test-realization companion (M5
// WP2, ) can reference the capability it realizes without recomputing or
// duplicating the hash definition.
std::string capabilityHashOf(const ProcedureView &view,
                             const CoordinationPlan &coordinationPlan);

// The exact preimage bytes of capabilityHash: the compact, sorted-key canonical
// JSON of the capability-spec SEMANTIC CORE (no envelope discriminators, no
// sourceMap / targetRequirements / identity). capabilityHashOf(view) ==
// sha256Hex(canonicalSemanticBytes(view)). Exposed so the agreement-identity
// () can bind the SAME canonical semantic bytes without re-deriving them,
// so its identity cannot drift from the frozen capability-spec contract.
std::string canonicalSemanticBytes(const ProcedureView &view,
                                   const CoordinationPlan &coordinationPlan);

// The capability-spec schema version a GIVEN spec emits (the `schemaVersion` on
// capability-spec.json). CONDITIONAL: an ATTESTATION policy (/) is
// schemaVersion 3 — the first point where a consumer that IGNORES the policy is
// UNSAFE (the S2 lowering renders the on-chain M-of-N acceptance guard FROM it,
// so a pre-3 backend would deploy the coordination without the quorum check);
// it subsumes the guard bump (3 > 2). A conditional guard (, `when` on any
// effect) is schemaVersion 2 — a semantics-changing feature a v1 consumer must
// refuse rather than silently drop (dropping `when` posts a leg
// unconditionally); a plain spec stays schemaVersion 1 and byte-identical.
// Single source of truth so a derived artifact (e.g. a participant view's
// provenance.specContract, ) references the ACTUAL spec version it was
// projected under.
int capabilitySpecSchemaVersion(const ProcedureView &view);
// The highest schema version this emitter can produce (the current schema).
int capabilitySpecSchemaVersion();

} // namespace neutrino

#endif // NEUTRINO_GEN_SPEC_H

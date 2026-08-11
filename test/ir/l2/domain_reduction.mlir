// RUN: %neutrino-emit --kind=domain-reduction %s --reduce-against %test/ir/samples/Inputs/core_document_escrow/generated/capability-spec/capability-spec.json | %FileCheck %s
//
// Source/artifact coordination-plan PARITY of the reduction: the canonical
// reduction is byte-identical whether the coordination plan is built via
// planFromSpec (the committed capability-spec) or via the DIRECT normalizePlan
// path (the source .neu -> view). Both coordination plan paths, one reduction.
// RUN: %neutrino-emit --kind=domain-reduction %s --reduce-against %test/ir/samples/Inputs/core_document_escrow/generated/capability-spec/capability-spec.json > %t.spec
// RUN: %neutrino-emit --kind=domain-reduction %s --reduce-against %test/ir/samples/Inputs/core_document_escrow/source/core_document_escrow.neu > %t.src
// RUN: diff %t.spec %t.src
//
// v2-sidecar RE-INGEST parity: emit the visible domain-semantics sidecar, then
// reduce FROM it. The .json path validates the sidecar at the trust seam (full
// v2 contract: envelope, authoritative dialect verifier, recomputed hash) before
// reducing, and the validated canonical artifact yields the byte-identical
// reduction as the direct IR (both feed one shared reduce core) — a provably
// faithful stand-in. The negative seam cases + the C++/stdlib validator drift
// corpus live in sidecar_reingest_contract.test.
// RUN: %neutrino-emit --kind=domain-semantics %s > %t.sidecar.json
// RUN: %neutrino-emit --kind=domain-reduction %t.sidecar.json --reduce-against %test/ir/samples/Inputs/core_document_escrow/generated/capability-spec/capability-spec.json > %t.reingest
// RUN: diff %t.spec %t.reingest
//
// FULL coordination-plan projection parity — the spine the reduction subset
// rides on. The WHOLE coordination plan (not just the two reduced features) is
// byte-identical whether built via normalizePlan (source) or planFromSpec.
// RUN: %neutrino-gen --target=coordination-plan %test/ir/samples/Inputs/core_document_escrow/source/core_document_escrow.neu -o %t.cpsrc
// RUN: %neutrino-gen --target=coordination-plan --from-spec %test/ir/samples/Inputs/core_document_escrow/generated/capability-spec/capability-spec.json -o %t.cpspec
// RUN: diff %t.cpsrc/coordination-plan.json %t.cpspec/coordination-plan.json
//
// A mutation to a NORMALIZED field the reduction does NOT select — the release
// guard >= -> > (guard:conditional, which this domain never reduces) — still
// breaks the full coordination-plan parity. So the coordination plan the
// reduction binds against is pinned in its ENTIRETY, not only at the two reduced
// features: reduction parity is not a lax subset check hiding a coordination-plan
// divergence elsewhere.
// RUN: sed 's/"op": ">="/"op": ">"/' %test/ir/samples/Inputs/core_document_escrow/generated/capability-spec/capability-spec.json > %t.guard.json
// RUN: %neutrino-gen --target=coordination-plan --from-spec %t.guard.json -o %t.cpguard
// RUN: %not diff %t.cpsrc/coordination-plan.json %t.cpguard/coordination-plan.json
//
// --reduce-against is rejected on an inspection kind, so a caller can never get
// success without the reduction gate running.
// RUN: %not %neutrino-emit --kind=events %s --reduce-against %test/ir/samples/Inputs/core_document_escrow/generated/capability-spec/capability-spec.json 2>&1 | %FileCheck %s --check-prefix=REJECT
//
// The verified L2->L1 reduction ( PR3): a verified l2.domain reduces onto the
// CLOSED semantic-requirement vocabulary its source CoordinationPlan induces
// (coordinationPlanRequirements / knownSemanticFeatures — the SAME registry
// coordination-plan legality uses), DATA-driven ( §2). The emitted reduction
// is an INTERNAL, sorted PROJECTION (no kind/schemaVersion/hash) whose only job
// is to be byte-comparable across the two reduction sources and the two
// coordination-plan construction paths.

// CHECK: "bindings": [
// CHECK: "concept": "escrow_funded"
// CHECK: "edge": "r_funded"
// CHECK: "feature": "effect:debit"
// CHECK: "inducedBy": "effect buyer_escrow"
// CHECK: "relation": "expands"
// CHECK: "concept": "settlement_balanced"
// CHECK: "edge": "r_balanced"
// CHECK: "feature": "invariant:balanced"
// CHECK: "inducedBy": "balance obligation"
// CHECK: "relation": "protects"
// CHECK: "domain": "coordinate.core_document_escrow"

// REJECT: --reduce-against applies only to --kind=domain-semantics|domain-reduction

l2.domain "coordinate.core_document_escrow" attributes {version = "1.0.0", implements = "coordinate.core_document_escrow", coverage = "partial"} {
  l2.l1_feature "effect:debit" {kind = "primitive"}
  l2.l1_feature "invariant:balanced" {kind = "obligation"}
  l2.failure_mode "escrow_reversal" {}
  l2.concept "escrow_funded" {kind = "state", classification = "executable"}
  l2.concept "settlement_balanced" {kind = "concept", classification = "descriptive"}
  l2.reduce "r_funded" "escrow_funded" -> "effect:debit" {relation = "expands", lossiness = "lossless"}
  l2.reduce "r_balanced" "settlement_balanced" -> "invariant:balanced" {relation = "protects", lossiness = "lossless"}
  l2.invariant "escrow_stays_balanced" {predicate = "buyer_escrow == escrow_holding", on_failure = "escrow_reversal"}
  l2.provenance "r_funded" {source = "UCC-9", status = "accepted", excerpt_hash = "0000000000000000000000000000000000000000000000000000000000000000"}
}

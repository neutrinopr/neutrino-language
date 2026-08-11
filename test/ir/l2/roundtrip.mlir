// RUN: %neutrino-opt %s | %FileCheck %s
//
// The generic L2 domain-semantics meta-model (): a domain is DATA —
// instances of the closed `l2` op vocabulary — so adding a domain never adds a
// C++ op/class ( §4). This parses a well-formed domain, runs the C++ domain
// verifier (reference resolution, traceability to a declared L1 anchor,
// classification, provenance binding), and re-prints it. Modelled on the
// committed core_document_escrow (release) L2 sidecar fixture. (This is a
// parse/verify/print check; byte-golden serialization and source-location
// fidelity are proved by the emitter slice, not here.)

// CHECK: l2.domain "coordinate.core_document_escrow"
// CHECK-SAME: implements = "coordinate.core_document_escrow"
l2.domain "coordinate.core_document_escrow" attributes {version = "1.0.0", implements = "coordinate.core_document_escrow", coverage = "partial"} {
  // A versioned import of another L2 domain — a foreign reference resolved
  // against the registry by the import resolver, not a local identity.
  // CHECK: l2.import "coordinate.core_dual_offer" {version = "1.0.0"}
  l2.import "coordinate.core_dual_offer" {version = "1.0.0"}
  // CHECK: l2.l1_feature "effect:debit" {kind = "primitive"}
  l2.l1_feature "effect:debit" {kind = "primitive"}
  // CHECK: l2.l1_feature "invariant:balanced" {kind = "obligation"}
  l2.l1_feature "invariant:balanced" {kind = "obligation"}
  // CHECK: l2.failure_mode "escrow_reversal"
  l2.failure_mode "escrow_reversal" {}
  // CHECK: l2.concept "escrow_funded" {classification = "executable", kind = "state"}
  l2.concept "escrow_funded" {kind = "state", classification = "executable"}
  // CHECK: l2.concept "settlement_balanced" {classification = "descriptive", kind = "concept"}
  l2.concept "settlement_balanced" {kind = "concept", classification = "descriptive"}
  // An executable concept expands onto a declared L1 primitive; carries accepted provenance below.
  // CHECK: l2.reduce "r_funded" "escrow_funded" -> "effect:debit" {lossiness = "lossless", relation = "expands"}
  l2.reduce "r_funded" "escrow_funded" -> "effect:debit" {relation = "expands", lossiness = "lossless"}
  // A descriptive concept only protects a declared obligation (never an executable relation).
  // CHECK: l2.reduce "r_balanced" "settlement_balanced" -> "invariant:balanced" {lossiness = "lossless", relation = "protects"}
  l2.reduce "r_balanced" "settlement_balanced" -> "invariant:balanced" {relation = "protects", lossiness = "lossless"}
  // CHECK: l2.invariant "escrow_stays_balanced"
  l2.invariant "escrow_stays_balanced" {predicate = "buyer_escrow == escrow_holding", on_failure = "escrow_reversal"}
  // CHECK: l2.provenance "r_funded"
  l2.provenance "r_funded" {source = "UCC-9", status = "accepted", excerpt_hash = "0000000000000000000000000000000000000000000000000000000000000000"}
}

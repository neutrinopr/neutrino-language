// RUN: %neutrino-emit --kind=domain-semantics %s | %FileCheck %s
// RUN: %neutrino-emit --kind=domain-semantics %s > %t.1
// RUN: %neutrino-emit --kind=domain-semantics %s > %t.2
// RUN: diff %t.1 %t.2
// RUN: %neutrino-emit --kind=domain-semantics %s | python3 %scripts/domain/validate_l2_domain_semantics_v3.py --artifact -
// RUN: python3 %scripts/domain/validate_l2_domain_semantics_v3.py --canonicalize %t.1 > %t.canon
// RUN: diff %t.1 %t.canon
//
// The visible L2 domain-semantics artifact (), emitted under the SETTLED
// identity neutrino.l2-domain-semantics schemaVersion 3 (: the M7-intake
// executable-graph contract — v2's graph plus a REQUIRED intakeVersioning object;
// v2 is retained UNCHANGED as the legacy compatibility baseline). The two emits +
// diff prove byte-reproducibility; the pinned domainSemanticsHash proves the hash
// BINDS the content (including intakeVersioning); piping the bytes back through the
// v3 validator proves they RE-ENTER the verified generic-L2 contract (shape + the
// same cross-record rules the C++ DomainOp::verify() enforces + recomputed hash),
// not just a checksum; and canonicalize(emit) diffing byte-identical to emit proves
// the artifact->L2->artifact round-trip. Sibling artifact: reads only the l2 IR,
// touches no capability-spec or backend ( §7).

// CHECK: "domainSemanticsHash": "[[HASH:[0-9a-f]{64}]]"
// CHECK: "imports": [
// CHECK: "capability": "coordinate.core_dual_offer"
// CHECK: "version": "1.0.0"
// CHECK: "intakeVersioning": {
// CHECK: "reductionSemanticsVersion": 1
// CHECK: "semanticProfileVersion": 3
// CHECK: "kind": "neutrino.l2-domain-semantics"
// CHECK: "l1Features": [
// CHECK: "name": "effect:debit"
// CHECK: "reductions": [
// CHECK: "relation": "expands"
// CHECK: "schemaVersion": 3
l2.domain "coordinate.core_document_escrow" attributes {version = "1.0.0", implements = "coordinate.core_document_escrow", coverage = "partial"} {
  // A versioned import is part of the hashed contract: it is emitted into the
  // sidecar and covered by domainSemanticsHash (an import change bites the hash).
  l2.import "coordinate.core_dual_offer" {version = "1.0.0"}
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

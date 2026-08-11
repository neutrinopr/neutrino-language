// RUN: %not %neutrino-emit --kind=domain-reduction %S/Inputs/reduction_unregistered.mlir --reduce-against %test/ir/samples/Inputs/core_document_escrow/generated/capability-spec/capability-spec.json 2>&1 | %FileCheck %s --check-prefix=UNREG
// RUN: %not %neutrino-emit --kind=domain-reduction %S/Inputs/reduction_misclassified.mlir --reduce-against %test/ir/samples/Inputs/core_document_escrow/generated/capability-spec/capability-spec.json 2>&1 | %FileCheck %s --check-prefix=MISCLASS
// RUN: %not %neutrino-emit --kind=domain-reduction %S/Inputs/reduction_not_induced.mlir --reduce-against %test/ir/samples/Inputs/core_document_escrow/generated/capability-spec/capability-spec.json 2>&1 | %FileCheck %s --check-prefix=ABSENT
// RUN: %not %neutrino-emit --kind=domain-reduction %s --reduce-against %S/Inputs/spec_no_balanced.json 2>&1 | %FileCheck %s --check-prefix=MUTATION
//
// Fail-closed L2->L1 reduction ( PR3): a declared l1_feature is resolved
// against the CLOSED semantic vocabulary the coordination plan induces, and the
// three failure modes are DISTINCT — unregistered feature, misclassified
// primitive/obligation, and a registered feature the coordination plan does not induce. The
// last RUN is the parity-BITING mutation: the SAME valid domain, reduced against
// a coordination plan whose balanced invariant was dropped, now fails because
// invariant:balanced is no longer induced — so a coordination plan-semantic change the domain
// depends on cannot pass silently. (The v2-sidecar re-ingest trust seam — shape,
// verifier, and hash equivalence with the stdlib validator — is exercised in
// sidecar_reingest_contract.test.)

// UNREG: l1_feature 'totally:madeup' is not a registered semantic feature
// MISCLASS: l1_feature 'invariant:balanced' is a obligation, not declared kind 'primitive'
// ABSENT: l1_feature 'attestation:quorum' is a registered feature the coordination plan does not induce
// MUTATION: l1_feature 'invariant:balanced' is a registered feature the coordination plan does not induce

l2.domain "coordinate.core_document_escrow" attributes {version = "1.0.0", implements = "coordinate.core_document_escrow", coverage = "partial"} {
  l2.l1_feature "effect:debit" {kind = "primitive"}
  l2.l1_feature "invariant:balanced" {kind = "obligation"}
  l2.concept "escrow_funded" {kind = "state", classification = "executable"}
  l2.concept "settlement_balanced" {kind = "concept", classification = "descriptive"}
  l2.reduce "r_funded" "escrow_funded" -> "effect:debit" {relation = "expands", lossiness = "lossless"}
  l2.reduce "r_balanced" "settlement_balanced" -> "invariant:balanced" {relation = "protects", lossiness = "lossless"}
  l2.provenance "r_funded" {source = "UCC-9", status = "accepted"}
}

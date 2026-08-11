// The reduction TRUST-SEAM gate ( PR3): a domain that declares l2.import
// records may NOT reduce until those imports resolve against a registry — so a
// dangling/unknown/ambiguous/cyclic import can never ride through reduction
// silently. The imports are part of the hashed v2 contract, so this holds for
// the direct IR path here and the v2-sidecar re-ingest path alike.
//
// Without a registry, an importing domain is refused (fail-closed):
// RUN: %not %neutrino-emit --kind=domain-reduction %s --reduce-against %test/ir/samples/Inputs/core_document_escrow/generated/capability-spec/capability-spec.json 2>&1 | %FileCheck %s --check-prefix=NEEDREG
//
// With a registry whose import is dangling, reduction is refused at resolution:
// RUN: %not %neutrino-emit --kind=domain-reduction %s --reduce-against %test/ir/samples/Inputs/core_document_escrow/generated/capability-spec/capability-spec.json --registry %S/Inputs/imports/registry_dangling.json --registry-root %examples/.. 2>&1 | %FileCheck %s --check-prefix=DANGLING
//
// With a registry that resolves the import, reduction proceeds:
// RUN: %neutrino-emit --kind=domain-reduction %s --reduce-against %test/ir/samples/Inputs/core_document_escrow/generated/capability-spec/capability-spec.json --registry %S/Inputs/imports/registry_ok.json --registry-root %examples/.. | %FileCheck %s --check-prefix=OK

// NEEDREG: declares l2.import records; --registry
// DANGLING: domain.import.dangling: import 'coordinate.b'
// OK: "feature": "effect:debit"

l2.domain "coordinate.core_document_escrow" attributes {version = "1.0.0", implements = "coordinate.core_document_escrow", coverage = "partial"} {
  l2.import "coordinate.b" {version = "1.0.0"}
  l2.l1_feature "effect:debit" {kind = "primitive"}
  l2.l1_feature "invariant:balanced" {kind = "obligation"}
  l2.concept "escrow_funded" {kind = "state", classification = "executable"}
  l2.concept "settlement_balanced" {kind = "concept", classification = "descriptive"}
  l2.reduce "r_funded" "escrow_funded" -> "effect:debit" {relation = "expands", lossiness = "lossless"}
  l2.reduce "r_balanced" "settlement_balanced" -> "invariant:balanced" {relation = "protects", lossiness = "lossless"}
  l2.provenance "r_funded" {source = "UCC-9", status = "accepted"}
}

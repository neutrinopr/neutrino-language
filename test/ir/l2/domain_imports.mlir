// Versioned L2 domain import resolution ( PR3): a domain's l2.import records
// are resolved against a versioned domain REGISTRY (the cross-rail catalog
// shape), DATA-driven ( §2). The graph is keyed by (capability, version) and
// EVERY transitive edge is resolved and validated; resolution emits the sorted
// resolved import graph and fails CLOSED and DISTINCTLY on the four broken-
// mapping modes — direct AND transitive.
//
// RUN: %neutrino-emit --kind=domain-imports %S/Inputs/imports/importer.mlir --registry %S/Inputs/imports/registry_ok.json --registry-root %examples/.. | %FileCheck %s
//
// A capability may be published at several versions (normal); the imported
// version uniquely selects one, so this is NOT ambiguous:
// RUN: %neutrino-emit --kind=domain-imports %S/Inputs/imports/importer.mlir --registry %S/Inputs/imports/registry_multiversion.json --registry-root %examples/.. | %FileCheck %s
//
// A deep transitive chain (b@1 -> c@1) resolves:
// RUN: %neutrino-emit --kind=domain-imports %S/Inputs/imports/importer.mlir --registry %S/Inputs/imports/registry_transitive_ok.json --registry-root %examples/.. | %FileCheck %s
//
// Fail-closed DIRECT modes, each a DISTINCT diagnostic code:
// RUN: %not %neutrino-emit --kind=domain-imports %S/Inputs/imports/importer.mlir --registry %S/Inputs/imports/registry_dangling.json --registry-root %examples/.. 2>&1 | %FileCheck %s --check-prefix=DANGLING
// RUN: %not %neutrino-emit --kind=domain-imports %S/Inputs/imports/importer.mlir --registry %S/Inputs/imports/registry_unknown.json --registry-root %examples/.. 2>&1 | %FileCheck %s --check-prefix=UNKNOWN
// RUN: %not %neutrino-emit --kind=domain-imports %S/Inputs/imports/importer.mlir --registry %S/Inputs/imports/registry_ambiguous.json --registry-root %examples/.. 2>&1 | %FileCheck %s --check-prefix=AMBIGUOUS
//
// Fail-closed TRANSITIVE modes — every edge in the graph is validated, not just
// the root's direct imports:
// RUN: %not %neutrino-emit --kind=domain-imports %S/Inputs/imports/importer.mlir --registry %S/Inputs/imports/registry_transitive_dangling.json --registry-root %examples/.. 2>&1 | %FileCheck %s --check-prefix=TDANGLING
// RUN: %not %neutrino-emit --kind=domain-imports %S/Inputs/imports/importer.mlir --registry %S/Inputs/imports/registry_transitive_unknown.json --registry-root %examples/.. 2>&1 | %FileCheck %s --check-prefix=TUNKNOWN
// RUN: %not %neutrino-emit --kind=domain-imports %S/Inputs/imports/importer.mlir --registry %S/Inputs/imports/registry_cyclic.json --registry-root %examples/.. 2>&1 | %FileCheck %s --check-prefix=CYCLIC
//
// The transitive edges are read from GOVERNED, hash-pinned v2 sidecars: a
// registry entry without a governed sidecar, or with a hash pin that does not
// match the artifact, is rejected (not silently treated as a leaf):
// RUN: %not %neutrino-emit --kind=domain-imports %S/Inputs/imports/importer.mlir --registry %S/Inputs/imports/registry_ungoverned.json --registry-root %examples/.. 2>&1 | %FileCheck %s --check-prefix=UNGOVERNED
// RUN: %not %neutrino-emit --kind=domain-imports %S/Inputs/imports/importer.mlir --registry %S/Inputs/imports/registry_forged_hash.json --registry-root %examples/.. 2>&1 | %FileCheck %s --check-prefix=FORGED
//
// The resolver requires EXACTLY one input l2.domain (no silent first-of-many):
// RUN: %not %neutrino-emit --kind=domain-imports %S/Inputs/imports/importer_two.mlir --registry %S/Inputs/imports/registry_ok.json --registry-root %examples/.. 2>&1 | %FileCheck %s --check-prefix=TWO
//
// --registry is rejected on any inspection kind, so a caller cannot get success
// without the import-resolution gate running.
// RUN: %not %neutrino-emit --kind=events %S/Inputs/imports/importer.mlir --registry %S/Inputs/imports/registry_ok.json --registry-root %examples/.. 2>&1 | %FileCheck %s --check-prefix=REJECT

// CHECK: "domain": "coordinate.a"
// CHECK: "imports": [
// CHECK: "capability": "coordinate.b"
// CHECK: "version": "1.0.0"

// DANGLING: domain.import.dangling: import 'coordinate.b' resolves to no capability in the registry
// UNKNOWN: domain.import.unknown: import 'coordinate.b' at version '1.0.0' is not published in the registry
// AMBIGUOUS: domain.import.ambiguous: import 'coordinate.b' at version '1.0.0' resolves to 2 registry entries
// TDANGLING: domain.import.dangling: import 'coordinate.c' resolves to no capability in the registry
// TUNKNOWN: domain.import.unknown: import 'coordinate.c' at version '1.0.0' is not published in the registry
// CYCLIC: domain.import.cyclic: import graph contains a cycle: coordinate.a@1.0.0 -> coordinate.b@1.0.0 -> coordinate.a@1.0.0
// UNGOVERNED: domain.import.ungoverned: import 'coordinate.b' at version '1.0.0' has no governed v2 sidecar
// FORGED: domain.import.ungoverned: governed v2 sidecar for import 'coordinate.b' has hash that does not match the catalog pin
// TWO: more than one l2.domain
// REJECT: --registry applies only to --kind=domain-imports|domain-reduction

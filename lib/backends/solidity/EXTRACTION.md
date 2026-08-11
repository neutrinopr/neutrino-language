# Extraction manifest — NeutrinoBackendSolidity (`lib/backends/solidity`)

The in-tree ownership view remains machine-checked by . The exact
clean-clone package inventory is
[`packaging/solidity/extraction-manifest.json`](../../../packaging/solidity/extraction-manifest.json);
that machine-readable manifest is authoritative for  materialization,
digests, generated build products, tests, fixtures, and provenance. A candidate
is built from those rows only, never by copying this directory wholesale.

The lists below are machine-checked against the CMake/link graph by
[`scripts/gates/check_extraction_manifests.py`](../../../scripts/gates/check_extraction_manifests.py): declared
Sources == the module's CMake sources + its link-smoke, Leaf dependencies == its `LINK_LIBS PUBLIC`, and
every declared public header exists. A drift between this manifest and `CMakeLists.txt` fails CI.

Structural subdirs ( R1): provider/handwritten renderers, harness/ scenario
harness, generated/ committed generator artifacts, model/ + recipes/ the `.td`
sources of truth (not `.cpp`/`.inc`, so not listed below). The two
security-carve-out `.sol.inc` stay at the backend root by design.

## Clean-clone package contract ()

- The installed core contributes the 13 artifacts in
  `docs/m7-core-installed-export.json`: six executables, the signed  ADR,
  and six schema files. Its C++ ABI policy is `forbidden`.
- The package consumes the exact, versioned
  `neutrino.backend-source-runtime/1` source dependency recorded in the JSON
  manifest: the finalized-projection consumer/codec, protocol state machine,
  target-blind recipe runtime, and CodeText printer. Its 16 sources and 16
  headers have exact byte identities in
  `packaging/shared/backend-source-runtime-v1.json`; per-target compiler
  closures prove the six Solidity-specific headers remain package-owned.
  The same contract names the two header-only consumer APIs whose dependency
  edges necessarily appear in the package-private target.
  `CoordinationPlan`, attestation/lifecycle construction, and the projection
  producer remain excluded. No installed C++ ABI crosses the subprocess
  boundary.
- All eight recipe/node `.inc` files named by
  `generatedBuildProducts` are regenerated in the candidate build directory
  from the declared `.td` and generator inputs. The candidate does not copy
  their committed in-tree counterparts.
- `SolidityCallableCoverage.inc` and `SolidityRecipePackage.inc` are declared
  authored validation/include-order companions rather than generator outputs.
- The package entry receives `neutrino.backend-startup/1` plus a private,
  absolute path to the exact parent-verified descriptor bytes. It validates
  and recomputes that descriptor's manifest identity itself before negotiating
  `neutrino.backend-protocol/1`; missing, malformed, and mismatched startup
  inputs fail before Hello. It then decodes the canonical finalized projection
  and returns only ordered named-source bytes. Artifact publication remains
  core-owned.
- The receipt binds every copied installed-core artifact by path, length, and
  digest, plus their canonical tree identity, before the copied
  `neutrino-gen` executes. It also binds every manifested source blob to the
  exact source commit/tree.
- The clean-clone proof compares `CoreDocumentEscrow.sol` byte-for-byte and
  runs its existing Foundry test. Five mutations reject a hidden header, an
  undeclared generated asset, a sibling-backend path, a private-core path, and
  a checkout reach-back injected into an already-declared CMake input. The
  configure/build/test/invocation commands run with translator-checkout reads
  denied by the OS sandbox. A separate one-byte installed-core mutation must
  fail identity verification before invocation. A sixth classification
  mutation proves a Solidity-only header cannot be relabeled as shared runtime.
- License identity and public publication remain explicitly blocked on .
  Mechanical success here is not a license grant and does not authorize a
  public package.

## Sources owned
- provider/GenSoliditySpec.cpp
- provider/SolidityTargetValidation.cpp
- provider/SolidityTargetAdapter.cpp
- provider/SolidityRenderer.cpp
- provider/SolidityRecipeProvider.cpp
- harness/GenSolidityTest.cpp
- GenSolidityQuorumGuard.cpp
- provider/SolidityEmit.cpp
- ThresholdQuorumAcceptance.sol.inc
- CoordinationEnvelope.sol.inc
- generated/SolidityTargetNodes.inc
- generated/SolidityPrinterHandlers.inc
- generated/SolidityTargetEnums.inc
- provider/SolidityCallableCoverage.inc
- generated/SolidityEmitBuilderDecls.inc
- generated/SolidityEmitBuilders.inc
- generated/SolidityRecipeBuilders.inc
- provider/SolidityRecipePackage.inc
- generated/SolidityProjection.inc
- test/backend_solidity_smoke.cpp
- test/solidity_model_test.cpp
- test/solidity_optional_extent_test.cpp
- test/solidity_recipe_provider_test.cpp
- test/solidity_recipe_render_referee.cpp
- test/solidity_stmt_shell_render_harness.cpp

The `SolStmt::Kind` enum + node-metadata registry and the first generated printer handler are GENERATED
(/) from `model/SolidityTargetNodes.td` (the source of truth, using the shared
`lib/backends/TargetPrinter.td` schema) into the committed `generated/SolidityTargetNodes.inc` and
`generated/SolidityPrinterHandlers.inc` by
[`scripts/generators/gen_target_node_registry.py`](../../../scripts/generators/gen_target_node_registry.py),
reconciled against the generated+remaining handwritten printer dispatch by
[`scripts/gates/check_target_node_registry.py`](../../../scripts/gates/check_target_node_registry.py).
The `.td` is not a compiled/linked source (it is a TableGen schema over the pinned llvm-tblgen); the backend
stays MLIR-free and leaf-only.

## Shared leaf dependencies
- NeutrinoSpecContract
- NeutrinoCodeText
- NeutrinoRecipe

## Public headers
- Neutrino/GenSoliditySpec.h
- Neutrino/SolidityPackageArtifacts.h
- Neutrino/SolidityEmit.h

## Integration headers
- Neutrino/RecipeSessionStore.h

## Conformance slice
- `backend-solidity-smoke` — the leaf-only link-smoke (`test/`)
- `solidity-model-test` — the typed-legalization-model unit test (structure + fail-closed single source, `test/`)
- `solidity-raw-seam-sealed` — the  compile-NEGATIVE boundary: an external TU (`test/cmake/raw_seam_sealed.cpp`) must fail to compile a raw-authoring call (`test/`)
- `solidity-{localdecl,assign,compound,doccomment,spdx}-golden` / `…-td-mutation` — the / `.td`→generated→golden proof: one render harness (`test/solidity_stmt_shell_render_harness.cpp`, node selected by `-DNODE_ASSIGN`/`-DNODE_COMPOUND`/`-DNODE_DOCCOMMENT`/`-DNODE_SPDX`) compiled against the committed printer include reproduces the golden shell line (LocalDecl in `ShipmentEvidenceAnchor`; Assign `attested[_k] = true;`, CompoundAssign `debitTotal[_k] += u_amount;`, DocComment `/// Generated by the Neutrino Translator from verified MLIR.`, and SpdxLicense `// SPDX-License-Identifier: MIT` in `CoreSupplyIssue`), and against a `.td`-mutated regenerated include (real generator + pinned llvm-tblgen) renders the mutated form and fails it (`test/`)
- `anti-inference-boundary` — the  S4 gate: the exact validation,
  target-adapter, renderer, and recipe-provider ownership surfaces consume only
  verified projection facts and reintroduce no raw-spec semantic inference
  (semantics normalize once; targets legalize; CodeText prints)
- `test/ir/backend/solidity_goldens.test` — the `[83]` byte-golden contract + harness
- `test/ir/backend/solidity_from_spec.test`, `test/ir/backend/solidity_2state.test`
- `test/ir/legality/solidity_legality.test` — the render-gate
- `test/ir/oracle/oracle_delivery.neu` — the S2c quorum-guard byte-golden + gating

## Non-ownership (explicit)
- Does NOT own a core registry `EmitFn`. The installed core discovers the exact
  package descriptor and invokes `packaging/solidity/src/SolidityBackendMain.cpp`
  through `neutrino.backend-protocol/1`; `NeutrinoEmit` has no Solidity source,
  include, or link edge.
- Does NOT own the `include/Neutrino/` directory — it EXPOSES only its own headers (above); the shared
  contract/adapter headers (`Expr.h`, `ValueModel.h`, `Attestation.h`, `StrCase.h`, `CodeText.h`,
  `CoordinationEnvelope.h` — the  execution-claim/coordination-identity digest the temporal contract +
  harness recompute) are the leaves'.
- Does NOT own domain byte-goldens (`examples/domains/*/generated/`) — those are the shared conformance
  corpus, validated across all backends.
- Does NOT own cross-cutting gates (`scripts/check_*`, the lit non-vacuous manifest, the root CMake).

> ** — generated `.inc` are BUILD PRODUCTS.** The artifacts marked above are
> no longer committed. They are produced into
> `${CMAKE_CURRENT_BINARY_DIR}/generated`, which is on the unit's private
> include path, so in-package `#include`s resolve unchanged. An extraction must
> carry the `.td` sources and the generator, not the `.inc`: the artifact is
> reproducible from them and byte-identical regeneration is what proves the
> extraction preserved semantics. A source-tree copy reappearing is a defect,
> not a fallback.

# docs/

Normative specifications and decision records for the translator. The architectural narrative is the
top-level [README.md](../README.md); this folder holds the contracts behind it.

## Layout

Docs are grouped by subsystem; the machine-readable artifacts (`schemas/`, `*.json`) stay at this root.

| Folder | Covers |
| --- | --- |
| [`language/`](language/) | the `.neu` language, expression + value models, diagnostics, language levels/boundary/intelligence |
| [`domains/`](domains/) | domain dialects + L2 semantics, proposals/dataset-extraction, adding a domain, sample portfolio, lower-layer maps |
| [`backends/`](backends/) | generators, target catalog + profiles, maturity, capability model, solidity/codetext, cross-rail |
| [`spec/`](spec/) | the capability-spec, its consumer contract, feature matrix, slot artifact contract |
| [`binding/`](binding/) | binding manifest/policy, trust + late-binding, parties/topology, participant views, oracle observation |
| [`testing/`](testing/) | test tiers + realization, verification, static analysis, sanitizers, native-build gate, security pass |
| [`process/`](process/) | release/versioning/compatibility, the M5 ADRs + decision records, scorecard, M6 extraction, tooling/script inventory |

## Start here

- **Language:** [NEU_LANGUAGE_SPEC.md](language/NEU_LANGUAGE_SPEC.md) (the `.neu` grammar, pinned by
  `test/conformance/`) · [LANGUAGE_LEVELS.md](language/LANGUAGE_LEVELS.md) (language levels L1–L10) ·
  [VALUE_MODEL.md](language/VALUE_MODEL.md) · [EXPRESSION_MODEL.md](language/EXPRESSION_MODEL.md) (typed compute
  expressions + extension process) · [LANGUAGE_INTELLIGENCE.md](language/LANGUAGE_INTELLIGENCE.md) (editor
  grammar / Linguist / compiler-backed LSP) · [COMPATIBILITY.md](process/COMPATIBILITY.md) (stability contract).
- **Realization layers** (core/domain/binding; the `L1/L2/L3` of [ADR D3](process/M5_DECISIONS_ADR.md) —
  distinct from language levels, see the [`L*` map](process/M5_DECISIONS_ADR_ADDENDUM.md)):
  [L2_DOMAIN_SEMANTICS.md](domains/L2_DOMAIN_SEMANTICS.md) (realization L2 · domain) ·
  [BINDING_MANIFEST.md](binding/BINDING_MANIFEST.md) / [SLOT_ARTIFACT_CONTRACT.md](spec/SLOT_ARTIFACT_CONTRACT.md)
  (realization L3 · binding) · [DOMAIN_DIALECT.md](domains/DOMAIN_DIALECT.md) / [DOMAIN_PROPOSAL.md](domains/DOMAIN_PROPOSAL.md).
- **Spec contract:** [CAPABILITY_SPEC.md](spec/CAPABILITY_SPEC.md) — the canonical executable
  capability-spec (`neutrino-gen --target=capability-spec`), M5's only frozen external contract ·
  [SPEC_CONSUMER_CONTRACT.md](spec/SPEC_CONSUMER_CONTRACT.md) — the consumer-facing view for
  agents/network/console (what to rely on + how each rail consumes it, WP8) ·
  [TARGET_PROFILES.md](backends/TARGET_PROFILES.md) — target profiles + the fail-closed spec-legality gate
  (WP4) · [TEST_REALIZATION.md](testing/TEST_REALIZATION.md) — the test-realization companion
  (`--target=test-realization`): scenario/test cases folded once, outside the capability hash (WP2).
- **Backends:** [BACKEND_TARGET_CATALOG.md](backends/BACKEND_TARGET_CATALOG.md) (every generator target +
  maturity + entry-point) · [BACKEND_GENERATORS.md](backends/BACKEND_GENERATORS.md) ·
  [BACKEND_VALIDATION.md](backends/BACKEND_VALIDATION.md) ·
  [SOLIDITY_CLASSIFICATION.md](backends/SOLIDITY_CLASSIFICATION.md) (translator-owned checker for the
  solidity-samples `classification.json` profile shape) ·
  [CROSS_RAIL_DRY_RUN.md](backends/CROSS_RAIL_DRY_RUN.md) (the three rails lining up around the slot contract).
- **Samples:** [M3_SAMPLE_PORTFOLIO.md](domains/M3_SAMPLE_PORTFOLIO.md) ·
  [ADDING_A_NEW_DOMAIN.md](domains/ADDING_A_NEW_DOMAIN.md) · [DOMAIN_LAYOUT.md](domains/DOMAIN_LAYOUT.md).
- **Security / verification:** [SECURITY_PASS.md](testing/SECURITY_PASS.md) · [VERIFICATION.md](testing/VERIFICATION.md)
  · [DIAGNOSTIC_TAXONOMY.md](language/DIAGNOSTIC_TAXONOMY.md) (the shared failure taxonomy: stable
  diagnostic codes + root-cause ordering) · [STATIC_ANALYSIS.md](testing/STATIC_ANALYSIS.md) · [TESTING.md](testing/TESTING.md)
  · [NATIVE_BUILD_GATE.md](testing/NATIVE_BUILD_GATE.md) (generated code must compile/validate natively) ·
  [FORGE_TOOLCHAIN.md](testing/FORGE_TOOLCHAIN.md) (provisioning the Foundry/native closure the
  `requires-forge` rows drive, its preflight and its machine receipts) ·
  [SCRIPT_INVENTORY.md](process/SCRIPT_INVENTORY.md) (committed script inventory + invocation map).
- **Release / milestones:** [RELEASE.md](process/RELEASE.md) · [M5_DECISIONS_ADR.md](process/M5_DECISIONS_ADR.md)
  (+ [addendum](process/M5_DECISIONS_ADR_ADDENDUM.md): `L*` terminology map, primitive promotion,
  profile versioning, trust boundary) · [VERSIONING.md](process/VERSIONING.md) ·
  [M6_EXTRACTION_PATH.md](process/M6_EXTRACTION_PATH.md) — the mechanical M6 `git filter-repo` carve for a
  backend extraction unit (manifests + boundary gate + shared corpus), prep vs extraction ·
  [M6_DYNAMIC_REALIZATION_ADR.md](process/M6_DYNAMIC_REALIZATION_ADR.md) — the M6 dynamic-realization
  architecture contract (DC1–DC12: bounded coordinator, three-layer identity, cross-mode equivalence,
  the falsifiable experiment's go/no-go; ). ·
  [M6_ONTOLOGY_BRIDGE_BOUNDARY.md](process/M6_ONTOLOGY_BRIDGE_BOUNDARY.md) — the M6→ontology bridge
  contract (): TableGen mechanizes the typed-target-model printer, not legalization or per-domain ops;
  the two rejected anti-patterns; success/stop metrics. ·
  [M6_L2_BRIDGE_ADR.md](process/M6_L2_BRIDGE_ADR.md) — the M6 L2 domain-generalization bridge & hourglass
  contract (**provisional**  decision record;  closes on the  register): L2 as canonical normalized
  shock-absorber, the single closed `CoordinationPlan` waist (capability-spec is its sibling projection,
  re-hydrated via `planFromSpec` before any backend), agreement identity exact vs schema-compat additive,
  stratification discipline, and the backend-agnostic wide bottom as a hard M7-entry gate. ·
  [M6_BACKEND_PROJECTION_MODEL.md](process/M6_BACKEND_PROJECTION_MODEL.md) — the normative below-waist
  backend projection model (design artifact for ; gates stay OPEN pending Tier-2 inventories + sign-off):
  `projectBackendGraph(CoordinationPlan)` as a separate boundary, the closed node/edge/verifier graph,
  finalized primitive kinds (`QuorumAcceptance.Single`/`.PerPolicy`) + the total resolver rule, projection-schema
  version vs `agreementHash`, three node-by-node traces, and  as the security-registry companion. ·
  [M6_DECLARATIVE_IDIOM_RECIPE_BOUNDARY.md](process/M6_DECLARATIVE_IDIOM_RECIPE_BOUNDARY.md) — the
  post-projection declarative idiom contract (): closed non-Turing recipe grammar, typed inputs,
  exact leaf hooks and  carve-outs, package ownership, machine composition inventory, and the
  reset per-PR/terminal test policy required before / closure.
- **JSON Schemas:** [schemas/](schemas) — the machine-readable artifact schemas.

These are **trusted source** (hand-authored); they are the contracts the C++ tools and the sidecar
validators enforce.

# Keep network-dependent gtest configuration opt-in.
option(NEUTRINO_BUILD_UNITTESTS "Build the gtest C++ unit tier (unittests/, )" OFF)
if(NEUTRINO_BUILD_UNITTESTS)
  add_subdirectory(unittests)
endif()

# The declared Forge tool identity () — must precede every `requires-forge` registration
# below, which attaches NEUTRINO_FORGE_TEST_ENVIRONMENT to its test.
include(${CMAKE_CURRENT_LIST_DIR}/NeutrinoForgeToolchain.cmake)

# Keep the umbrella label free of "fast"; CTest label filters use regexes.
neutrino_register_test(NAME fast COMMAND python3 -m unittest discover
  -s ${PROJECT_SOURCE_DIR}/test/checks/fast -p *_test.py
  -t ${PROJECT_SOURCE_DIR}/test/checks/fast)
neutrino_register_test_properties(fast PROPERTIES LABELS "umbrella")

# Rows are ctest-name=module=comma-separated-labels.
set(NEUTRINO_FAST_CHECKS
  "fast-l2-domain-semantics=l2_domain_semantics=fast,validator,schema,domain"
  "fast-domain-dialect=domain_dialect=fast,validator,schema,domain"
  "fast-cross-rail-catalog=cross_rail_catalog=fast,validator,contract"
  "fast-l2-branch-compat=l2_branch_compat=fast,validator,contract,domain"
  "fast-sample-portfolio=sample_portfolio=fast,validator,completeness"
  "fast-native-build-gate=native_build_gate=fast,contract,artifact"
  "fast-release-manifest=release_manifest=fast,artifact,release"
  "fast-solidity-classification=solidity_classification=fast,validator,schema"
  "fast-capability-spec=capability_spec=fast,validator,schema,contract"
  "fast-target-profile-legality=target_profile_legality=fast,validator,contract"
  "fast-test-realization=test_realization=fast,validator,contract"
  "fast-participant-view=participant_view=fast,validator,contract"
  "fast-spec-feature-matrix=spec_feature_matrix=fast,completeness,contract"
  "fast-core-feature-example-matrix=core_feature_example_matrix=fast,completeness,contract,schema"
  "fast-m6-curated-example-corpus=m6_curated_example_corpus=fast,completeness,contract,schema"
  "fast-domain-pack-v2=domain_pack_v2=fast,completeness,contract,release"
  "fast-domain-observation-set=domain_observation_set=fast,validator,schema,domain"
  "fast-observation-binding=observation_binding=fast,validator,schema,oracle"
  "fast-renderer-include-boundary=renderer_include_boundary=fast,contract,completeness"
  "fast-corpus-proposal=corpus_proposal=fast,validator,domain"
  "fast-artifact-pins=artifact_pins=fast,contract,artifact"
  "fast-terminology-hardcut=terminology_hardcut=fast,contract,completeness"
  "fast-ci-runner-routing=ci_runner_routing=fast,policy,completeness"
  "fast-makefile-contract=makefile_contract=fast,policy,contract,completeness"
  "fast-neu-grammar=neu_grammar=fast,grammar,completeness"
  "fast-linguist-assets=linguist_assets=fast,grammar,artifact"
  "fast-generalism-result=generalism_result=fast,validator,contract"
  "fast-pressure-loop-register=pressure_loop_register=fast,validator,schema,contract"
  "fast-pressure-loop-forcing=pressure_loop_forcing=fast,contract,completeness"
  "fast-pressure-loop-mutation-protocol=pressure_loop_mutation_protocol=fast,contract,completeness"
  "fast-canonical-reduction-domain-blindness=canonical_reduction_domain_blindness=fast,contract,completeness,policy"
  "fast-solidity-syntax-authority=solidity_syntax_authority=fast,contract,completeness"
  "fast-decision-path-lock=decision_path_lock=fast,contract,completeness,policy"
  "fast-idiom-table-capability=idiom_table_capability=fast,contract,completeness,policy"
  "fast-postgres-syntax-authority=postgres_syntax_authority=fast,contract,completeness"
  "fast-m7-intake-seam=m7_intake_seam=fast,contract,completeness,domain"
  "fast-m7-reduction-conformance=m7_reduction_conformance=fast,contract,completeness,domain"
  "fast-m7-intake-bijection=m7_intake_bijection=fast,contract,completeness,domain,policy"
  "fast-backend-convergence=backend_convergence=fast,contract,completeness,policy"
  "fast-slot-descriptor-authority=slot_descriptor_authority=fast,slot,contract,completeness"
  "fast-slot-descriptor-bijection=slot_descriptor_bijection=fast,slot,contract,completeness"
  "fast-postgres-package-extraction=postgres_package_extraction=fast,contract,artifact,completeness"
  "fast-forge-toolchain-receipt=forge_toolchain_receipt=fast,validator,schema,contract"
  "fast-lit-suite-accounting=lit_suite_accounting=fast,policy,completeness,contract")
foreach(_row IN LISTS NEUTRINO_FAST_CHECKS)
  string(REGEX MATCH "^([^=]+)=([^=]+)=(.+)$" _m "${_row}")
  string(REPLACE "," ";" _labels "${CMAKE_MATCH_3}")
  neutrino_register_test(NAME ${CMAKE_MATCH_1}
    COMMAND python3 ${PROJECT_SOURCE_DIR}/test/checks/fast/${CMAKE_MATCH_2}_test.py)
  neutrino_register_test_properties(${CMAKE_MATCH_1} PROPERTIES LABELS "${_labels}")
endforeach()

neutrino_register_test(NAME core-feature-example-matrix-selftest
  COMMAND python3 ${PROJECT_SOURCE_DIR}/scripts/gates/check_core_feature_example_matrix.py --selftest)
neutrino_register_test_properties(core-feature-example-matrix-selftest PROPERTIES LABELS "contract;completeness")

find_program(NEUTRINO_FILECHECK NAMES FileCheck
  HINTS ${LLVM_TOOLS_BINARY_DIR} ${LLVM_BINARY_DIR}/bin)

# Build-only jobs may omit lit; CI asserts registration in test jobs.
find_program(NEUTRINO_LIT NAMES lit llvm-lit)
if(NEUTRINO_LIT)
  set(NEUTRINO_OPT "${CMAKE_BINARY_DIR}/tools/neutrino-opt/neutrino-opt")
  set(NEUTRINO_TRANSLATE "${CMAKE_BINARY_DIR}/tools/neutrino-translate/neutrino-translate")
  set(NEUTRINO_EMIT "${CMAKE_BINARY_DIR}/tools/neutrino-emit/neutrino-emit")
  set(NEUTRINO_GEN "${CMAKE_BINARY_DIR}/tools/neutrino-gen/neutrino-gen")
  set(NEUTRINO_EQUIV_TOOL "${CMAKE_BINARY_DIR}/tools/neutrino-equiv/neutrino-equiv")
  set(NEUTRINO_BUNDLE_TOOL "${CMAKE_BINARY_DIR}/tools/neutrino-bundle/neutrino-bundle")
  get_filename_component(_llvm_bin "${NEUTRINO_FILECHECK}" DIRECTORY)
  find_program(NEUTRINO_NOT NAMES not HINTS ${_llvm_bin} ${LLVM_TOOLS_BINARY_DIR})
  if(NOT NEUTRINO_NOT)
    message(FATAL_ERROR "LLVM `not` not found (needed by lit reject tests); expected next to FileCheck in ${_llvm_bin}")
  endif()
  set(NEUTRINO_LIT_CFG "${PROJECT_SOURCE_DIR}/test/ir/lit.cfg.py")
  set(NEUTRINO_LIT_EXEC_ROOT "${CMAKE_BINARY_DIR}/test/ir")
  set(NEUTRINO_EXAMPLES "${PROJECT_SOURCE_DIR}/examples")
  set(NEUTRINO_SCRIPTS "${PROJECT_SOURCE_DIR}/scripts")
  set(NEUTRINO_DOCS "${PROJECT_SOURCE_DIR}/docs")
  configure_file(${PROJECT_SOURCE_DIR}/test/ir/lit.site.cfg.py.in
    ${CMAKE_BINARY_DIR}/test/ir/lit.site.cfg.py @ONLY)
  neutrino_register_test(NAME lit
    COMMAND python3 ${PROJECT_SOURCE_DIR}/scripts/gates/run_lit_suite_accounting.py
      --lit ${NEUTRINO_LIT}
      --suite ${CMAKE_BINARY_DIR}/test/ir
      --report ${CMAKE_BINARY_DIR}/test/ir/lit-suite-accounting.json
      --baseline ${PROJECT_SOURCE_DIR}/docs/m6-lit-suite-accounting-baseline.json)
  neutrino_register_test_properties(lit PROPERTIES LABELS "ir;lit;frontend")
else()
  message(WARNING "lit not found — the IR regression suite () is NOT registered. Install it with "
                  "`pip install lit`. CI's build-and-test job requires + asserts it.")
endif()

neutrino_register_test(NAME core-feature-example-matrix
  COMMAND python3 ${PROJECT_SOURCE_DIR}/scripts/samples/make_core_feature_example_matrix.py
    --check
    --neutrino-gen $<TARGET_FILE:neutrino-gen>
    --neutrino-translate $<TARGET_FILE:neutrino-translate>)
neutrino_register_test_properties(core-feature-example-matrix PROPERTIES LABELS "contract;completeness;ctest-native")

# Source-only policy and architecture gates.
neutrino_register_test(NAME renderer-include-lock
  COMMAND python3 ${PROJECT_SOURCE_DIR}/scripts/gates/check_renderer_includes.py
    --selftest --build-dir ${PROJECT_BINARY_DIR})
neutrino_register_test_properties(renderer-include-lock PROPERTIES LABELS "contract;completeness")

# The production path scans the real retained-core corpus and authenticates
# every exclusion before separately checking the digest-pinned adversarial
# fixture. Its execution record distinguishes a clean scan from no execution.
neutrino_register_test(NAME anti-inference-production
  COMMAND python3 ${PROJECT_SOURCE_DIR}/scripts/gates/check_anti_inference.py --check-core --execution-record ${PROJECT_BINARY_DIR}/anti-inference-production-report.json)
neutrino_register_test_properties(anti-inference-production PROPERTIES
  LABELS "contract;completeness;policy")

# Mutation coverage is a separate registration and cannot satisfy production.
neutrino_register_test(NAME anti-inference-selftest
  COMMAND python3 ${PROJECT_SOURCE_DIR}/scripts/gates/check_anti_inference.py --selftest)
neutrino_register_test_properties(anti-inference-selftest PROPERTIES
  LABELS "contract;completeness;policy")

#  M6 red-line 2: the backend decision path (registry-backed target entry -> typed
# legalizer -> shared projection/printer core) must remain MLIR target-dialect /
# PDL / rewrite free. The governed source set is derived from TargetRegistry.def
# + lib/**/CMakeLists.txt; selftest proves every red-line bite independently.
neutrino_register_test(NAME decision-path-lock
  COMMAND python3 ${PROJECT_SOURCE_DIR}/scripts/gates/check_decision_path_lock.py --selftest)
neutrino_register_test_properties(decision-path-lock PROPERTIES LABELS "contract;completeness;policy")

#  M6 red-line 1: generated idiom tables are a closed capability surface —
# literal shape/idiom data plus dense positional bindings to finalized projection
# operands, with no predicates, alternate dispatch key, semantic lookup, ignored
# operands, or value-dependent branching.
neutrino_register_test(NAME idiom-table-capability
  COMMAND python3 ${PROJECT_SOURCE_DIR}/scripts/gates/check_idiom_table_capability.py --selftest)
neutrino_register_test_properties(idiom-table-capability PROPERTIES LABELS "contract;completeness;policy")

neutrino_register_test(NAME backend-convergence
  COMMAND python3 ${PROJECT_SOURCE_DIR}/scripts/gates/check_backend_convergence.py --selftest)
neutrino_register_test_properties(backend-convergence PROPERTIES LABELS "contract;completeness;policy")

#  M7 S0-C0: the slot-descriptor authority census. PROBE/CENSUS ONLY — it
# grants no retirement authority. The selftest proves the two non-vacuity
# properties: a field can neither disappear nor slip in unclassified, and
# authority cannot be assigned wholesale by function/file.
neutrino_register_test(NAME slot-descriptor-authority
  COMMAND python3 ${PROJECT_SOURCE_DIR}/scripts/gates/check_slot_descriptor_authority.py --selftest)
neutrino_register_test_properties(slot-descriptor-authority PROPERTIES LABELS "slot;contract;completeness")

#  M7 S0-C1: the slot-descriptor authority BIJECTION. Modelling only (the
# S0-C3 verdict authorizes no retirement). Its selftest drives the four exit-bar
# mutations: source substitution, ordering drift, duplicated independent
# derivation, and a newly introduced target/deploy authority.
neutrino_register_test(NAME slot-descriptor-bijection
  COMMAND python3 ${PROJECT_SOURCE_DIR}/scripts/gates/check_slot_descriptor_bijection.py --selftest)
neutrino_register_test_properties(slot-descriptor-bijection PROPERTIES LABELS "slot;contract;completeness")

# Read-only S0 census of handwritten backend idiom composition.  Clang AST
# extraction is build-dependent; the synthetic classifier probe remains
# available in source-only tiers.
neutrino_register_test(NAME backend-idiom-composition
  COMMAND python3 ${PROJECT_SOURCE_DIR}/scripts/gates/check_backend_idiom_composition.py
    --build-dir ${PROJECT_BINARY_DIR})
neutrino_register_test_properties(backend-idiom-composition
  PROPERTIES LABELS "contract;completeness;ctest-native")

neutrino_register_test(NAME attestation-validator-mirror
  COMMAND python3 ${PROJECT_SOURCE_DIR}/scripts/validators/validate_capability_spec.py --selftest)
neutrino_register_test_properties(attestation-validator-mirror PROPERTIES LABELS "validator;contract")

neutrino_register_test(NAME l2-domain-semantics-v2-validator
  COMMAND python3 ${PROJECT_SOURCE_DIR}/scripts/domain/validate_l2_domain_semantics_v2.py --selftest)
neutrino_register_test_properties(l2-domain-semantics-v2-validator PROPERTIES LABELS "validator;contract")

neutrino_register_test(NAME pressure-loop-register-validator
  COMMAND python3 ${PROJECT_SOURCE_DIR}/scripts/validators/validate_pressure_loop_register.py --selftest)
neutrino_register_test_properties(pressure-loop-register-validator PROPERTIES LABELS "validator;contract")

neutrino_register_test(NAME pressure-loop-forcing-runner
  COMMAND python3 ${PROJECT_SOURCE_DIR}/scripts/generators/run_pressure_loop_forcing.py --selftest)
neutrino_register_test_properties(pressure-loop-forcing-runner PROPERTIES LABELS "contract;completeness")

neutrino_register_test(NAME pressure-loop-mutation-protocol
  COMMAND python3 ${PROJECT_SOURCE_DIR}/scripts/gates/check_pressure_loop_mutation_protocol.py --selftest)
neutrino_register_test_properties(pressure-loop-mutation-protocol PROPERTIES LABELS "contract;completeness")

neutrino_register_test(NAME canonical-reduction-domain-blindness
  COMMAND python3 ${PROJECT_SOURCE_DIR}/scripts/gates/check_canonical_reduction_domain_blindness.py --selftest)
neutrino_register_test_properties(canonical-reduction-domain-blindness PROPERTIES LABELS "contract;completeness;policy")

neutrino_register_test(NAME pressure-loop-forcing-real-tools
  COMMAND python3 ${PROJECT_SOURCE_DIR}/scripts/generators/run_pressure_loop_forcing.py
    ${PROJECT_SOURCE_DIR}/examples/pressure-loop-forcing/fixtures.json
    --neutrino-gen $<TARGET_FILE:neutrino-gen>
    --neutrino-emit $<TARGET_FILE:neutrino-emit>
    --out ${PROJECT_BINARY_DIR}/pressure-loop-forcing/register.json
    --evidence-dir ${PROJECT_BINARY_DIR}/pressure-loop-forcing/evidence)
neutrino_register_test_properties(pressure-loop-forcing-real-tools PROPERTIES LABELS "contract;completeness;e2e")

neutrino_register_test(NAME cpp-policy
  COMMAND python3 ${PROJECT_SOURCE_DIR}/scripts/gates/check_cpp_policy.py --selftest)
neutrino_register_test_properties(cpp-policy PROPERTIES LABELS "policy;completeness")

neutrino_register_test(NAME arch-backend-isolation
  COMMAND python3 ${PROJECT_SOURCE_DIR}/scripts/gates/check_architecture_boundaries.py --rule backend --selftest)
neutrino_register_test_properties(arch-backend-isolation PROPERTIES LABELS "policy;domain-scaling")

neutrino_register_test(NAME arch-domain-isolation
  COMMAND python3 ${PROJECT_SOURCE_DIR}/scripts/gates/check_architecture_boundaries.py --rule domain --selftest)
neutrino_register_test_properties(arch-domain-isolation PROPERTIES LABELS "policy;domain-scaling")

neutrino_register_test(NAME arch-root-scripts
  COMMAND python3 ${PROJECT_SOURCE_DIR}/scripts/gates/check_architecture_boundaries.py --rule root-scripts --selftest)
neutrino_register_test_properties(arch-root-scripts PROPERTIES LABELS "policy;domain-scaling")

neutrino_register_test(NAME extraction-manifests-selftest
  COMMAND python3 ${PROJECT_SOURCE_DIR}/scripts/gates/check_extraction_manifests.py --selftest)
neutrino_register_test_properties(extraction-manifests-selftest PROPERTIES LABELS "policy;completeness")

neutrino_register_test(NAME extraction-manifests
  COMMAND python3 ${PROJECT_SOURCE_DIR}/scripts/gates/check_extraction_manifests.py)
neutrino_register_test_properties(extraction-manifests PROPERTIES LABELS "policy;completeness")

neutrino_register_test(NAME extraction-boundaries-selftest
  COMMAND python3 ${PROJECT_SOURCE_DIR}/scripts/gates/check_extraction_boundaries.py --selftest)
neutrino_register_test_properties(extraction-boundaries-selftest PROPERTIES LABELS "policy;completeness")

neutrino_register_test(NAME extraction-boundaries
  COMMAND python3 ${PROJECT_SOURCE_DIR}/scripts/gates/check_extraction_boundaries.py)
neutrino_register_test_properties(extraction-boundaries PROPERTIES LABELS "policy;completeness")

neutrino_register_test(NAME arch-link-direction
  COMMAND python3 ${PROJECT_SOURCE_DIR}/scripts/gates/check_link_direction.py --selftest)
neutrino_register_test_properties(arch-link-direction PROPERTIES LABELS "policy;domain-scaling;completeness")

# M5 scripts B4 (): every committed script is reachable from an entrypoint (or a documented
# manual-only allowlist) — the durable anti-cruft ratchet so the / script sprawl can't regrow.
neutrino_register_test(NAME no-orphan-scripts
  COMMAND python3 ${PROJECT_SOURCE_DIR}/scripts/gates/check_no_orphan_scripts.py --selftest)
neutrino_register_test_properties(no-orphan-scripts PROPERTIES LABELS "policy;completeness")

# Shared language vocabulary (): LanguageVocabulary.def is the single source for frontend
# recognition helpers and languageMetadataJson(); raw keyword idioms outside the helpers fail closed.
neutrino_register_test(NAME parser-metadata-keywords
  COMMAND python3 ${PROJECT_SOURCE_DIR}/scripts/gates/check_parser_keyword_metadata.py --selftest)
neutrino_register_test_properties(parser-metadata-keywords PROPERTIES LABELS "grammar;completeness")

# M5 : the BACKEND_TARGET_CATALOG generator-targets table must not drift from the authoritative
# TargetRegistry.def — every target reconciles by name + gated/scenario classification (oracle-observer
# is the one allowed non-registry special case).
neutrino_register_test(NAME catalog-registry
  COMMAND python3 ${PROJECT_SOURCE_DIR}/scripts/gates/check_catalog_registry.py --selftest)
neutrino_register_test_properties(catalog-registry PROPERTIES LABELS "contract;completeness")

# Semantic-authority discovery and its negative controls are substrate for the
# scoped semantic-convergence gate below.
neutrino_register_test(NAME semantic-authority-selftest
  COMMAND python3 ${PROJECT_SOURCE_DIR}/scripts/gates/check_semantic_authority.py --selftest)
neutrino_register_test_properties(semantic-authority-selftest PROPERTIES LABELS "contract;completeness")

# One versioned external L2/domain artifact is admitted through the registered
# capability namespace, reduced against the
# canonical CoordinationPlan input, rendered through every governed backend
# derived by the authority discovery contract, and compared by the existing
# normalized trace/effect oracle. Solidity/SQL bytes are deliberately not
# compared. The selftest plants four failure classes without modifying
# the source tree.
neutrino_register_test(NAME source-neutral-backend-witness-selftest
  COMMAND python3
    ${PROJECT_SOURCE_DIR}/test/ir/l2/check_source_neutral_backend_witness.py
    --selftest)
neutrino_register_test_properties(source-neutral-backend-witness-selftest PROPERTIES
  LABELS "contract;completeness;domain")

# Necessary anti-reinference enforcement: require zero semantic authority
# outside the verified security carve-outs, require the source-neutral witness
# across every governed backend, and emit one deterministic scoped report.
# Recipe-candidate zero, package separation, and terminal M7 evidence are
# intentionally outside this sub-gate.
neutrino_register_test(NAME semantic-convergence-selftest
  COMMAND python3
    ${PROJECT_SOURCE_DIR}/scripts/gates/check_semantic_convergence.py --selftest)
neutrino_register_test_properties(semantic-convergence-selftest PROPERTIES
  LABELS "contract;completeness;domain;policy")
neutrino_register_test(NAME semantic-convergence
  COMMAND python3
    ${PROJECT_SOURCE_DIR}/scripts/gates/check_semantic_convergence.py
    --neutrino-gen $<TARGET_FILE:neutrino-gen>
    --neutrino-emit $<TARGET_FILE:neutrino-emit>
    --neutrino-equiv $<TARGET_FILE:neutrino-equiv>
    --output ${PROJECT_BINARY_DIR}/semantic-convergence-report.json)
neutrino_register_test_properties(semantic-convergence PROPERTIES
  LABELS "contract;completeness;domain;policy;ctest-native")

# [] M6 replacement-grade TableGen printer substrate: the Solidity typed-target-model statement kinds
# () and generated printer handlers are generated from SolidityTargetNodes.td. This ctest runs the
# full pinned-tblgen gate: stale-output for both committed generated files, deterministic-order, complete
# handler coverage, no multiply-bound handwritten+generated handlers, and the handwritten-inventory
# retirement ratchet. Non-vacuity tampers run tblgen-free in test/ir/pipeline/target_node_registry.test.
# The PR-relative ratchet needs the authoritative base explicitly (): CI passes
# the event base via PR_BASE_SHA/GITHUB_BASE_SHA (honored when set), and this local
# ctest surface names origin/main as the declared base — never a silent fallback.
neutrino_register_test(NAME target-node-registry
  COMMAND python3 ${PROJECT_SOURCE_DIR}/scripts/gates/check_target_node_registry.py --selftest
          --base-ref origin/main --tblgen ${LLVM_TOOLS_BINARY_DIR}/llvm-tblgen)
neutrino_register_test_properties(target-node-registry PROPERTIES LABELS "contract;completeness")

# [ R5a] Canonical recipe-record round-trip on the production Solidity corpus.
# Uses the configured pinned llvm-tblgen (no workstation fallback). Selftest covers
# fixture round-trip; the main invocation runs membership, normalize, freshness,
# and mutation rejection against temporary mutated packages.
neutrino_register_test(NAME recipe-roundtrip-selftest
  COMMAND python3 ${PROJECT_SOURCE_DIR}/scripts/gates/check_recipe_roundtrip.py
          --backend solidity
          --tblgen ${LLVM_TOOLS_BINARY_DIR}/llvm-tblgen
          --selftest)
neutrino_register_test_properties(recipe-roundtrip-selftest PROPERTIES LABELS "contract;completeness")
neutrino_register_test(NAME recipe-roundtrip
  COMMAND python3 ${PROJECT_SOURCE_DIR}/scripts/gates/check_recipe_roundtrip.py
          --backend solidity
          --tblgen ${LLVM_TOOLS_BINARY_DIR}/llvm-tblgen)
neutrino_register_test_properties(recipe-roundtrip PROPERTIES LABELS "contract;completeness")

# [ S1a] Backend-generalism matrix: prove every crediting cell is a CONTROLLED EXPERIMENT against the
# real `neutrino-gen --target=capability --scenario=<materialized>` CLI — realize the cell AND its control
# (identical but for the one covered feature coordinate) and require the feature CAUSES the difference: a
# ledger cell realizes (exit 0) while its control refuses; a refusal cell emits its coded refusalCode while
# the control normalizes it away ( P1: prove causation, not "something changed"). Seed fixtures get a
# witness-class sanity check and credit no coverage. `render` cells (guard-blindness , a silent
# emitted-code divergence) are deferred to the render-witness child . The fresh + coverage +
# monotonicity ratchet runs tblgen-free in the fast tier (test/checks/fast/generalism_cells_test.py).
neutrino_register_test(NAME generalism-cells-validate
  COMMAND python3 ${PROJECT_SOURCE_DIR}/scripts/generators/gen_generalism_cells.py
          --prove-witness $<TARGET_FILE:neutrino-gen>)
neutrino_register_test_properties(generalism-cells-validate PROPERTIES LABELS "contract;completeness")

# [ S1c / ] Backend-generalism matrix, binding/lifecycle track: prove every binding cell against the
# capability-spec VALIDATOR (build-free, pure-Python) — remaining validator-contract rows validate clean
# and refuse on a field-specific invalid sentinel. Crediting valid_carry_and_consume rows are proven by
# the generalism matrix below through their first authoritative consumers.
neutrino_register_test(NAME generalism-binding-witness
  COMMAND python3 ${PROJECT_SOURCE_DIR}/scripts/generators/gen_generalism_cells.py --prove-binding)
neutrino_register_test_properties(generalism-binding-witness PROPERTIES LABELS "contract;completeness")

# [ S2] Generalism orchestration: drive all schema-derived cells through the CANONICAL stack —
# the canonical capability-spec (the frozen spec identity), the reference evaluator
# (`neutrino-gen --target=coordination-trace`, /, the PREDICTION), the rigid Solidity/Postgres
# targets, `neutrino-equiv` (trace-equivalence + LIVE compile/execute adapters with a structured
# compile-vs-runtime failure stage), and the spec-contract validator for binding cells — and emit one
#  `neutrino.generalism-result` envelope per EXACT execution identity, each carrying GENUINE per-run
# S4 evidence (trace -> receipt -> signed package -> verification report) produced through the pinned
# authoritative build-tools verifier (), plus a run manifest referencing every cell (for ).
# `--validate` runs the UNMODIFIED  validator (crypto-verifies the evidence) — no evidence exception.
#
# Two tiers. The main-build run validates the ORCHESTRATION + envelope + evidence with the live compile
# adapters absent (`--no-live-adapters`, so a cell needing a live compile fails closed to BROKEN, never a
# vacuous FAITHFUL). The e2e run (skip-when-absent) provisions forge + postgres and exercises the real
# compile/runtime adapters, so FAITHFUL is proven, not assumed. Both need the build-tools verifier
# provisioned under .ci/neutrino-build-tools (CI checkout; locally `make setup-build-tools-verifier`).
set(_gm_env
  "NEUTRINO_BUILD_TOOLS_GENERALISM_REPORT_CLI=${PROJECT_SOURCE_DIR}/.ci/neutrino-build-tools/m4/generalism_verification_report.py;NEUTRINO_BUILD_TOOLS_GENERALISM_REPORT_REVISION=2cf85d5b8baf38e259a574357045f7ded12f9395")
neutrino_register_test(NAME generalism-matrix-run
  COMMAND python3 ${PROJECT_SOURCE_DIR}/scripts/generators/run_generalism_matrix.py
          --neutrino-gen $<TARGET_FILE:neutrino-gen>
          --neutrino-translate $<TARGET_FILE:neutrino-translate>
          --neutrino-equiv $<TARGET_FILE:neutrino-equiv>
          --slot-spec-renderer $<TARGET_FILE:slot-spec-smoke>
          --out-dir ${CMAKE_CURRENT_BINARY_DIR}/generalism-matrix
          --timeout 60 --no-live-adapters --validate)
neutrino_register_test_properties(generalism-matrix-run PROPERTIES LABELS "contract;completeness"
  ENVIRONMENT "${_gm_env}" SKIP_RETURN_CODE 77)

neutrino_register_test(NAME generalism-matrix-e2e
  COMMAND python3 ${PROJECT_SOURCE_DIR}/scripts/generators/run_generalism_matrix.py
          --neutrino-gen $<TARGET_FILE:neutrino-gen>
          --neutrino-translate $<TARGET_FILE:neutrino-translate>
          --neutrino-equiv $<TARGET_FILE:neutrino-equiv>
          --slot-spec-renderer $<TARGET_FILE:slot-spec-smoke>
          --out-dir ${CMAKE_CURRENT_BINARY_DIR}/generalism-matrix-e2e
          --validate)
# The e2e tier drives forge through neutrino-equiv's live adapters, so it carries the same
# declared Forge tool identity as the acceptance rows ().
neutrino_register_test_properties(generalism-matrix-e2e PROPERTIES
  LABELS "e2e;requires-forge;requires-postgres;backend-solidity;backend-postgres" TIMEOUT 1800
  ENVIRONMENT "${_gm_env};${NEUTRINO_FORGE_TEST_ENVIRONMENT}" SKIP_RETURN_CODE 77)

# Generated artifact DAG and golden drift checks.
include(${CMAKE_CURRENT_LIST_DIR}/NeutrinoArtifactTests.cmake)

# Heavy provisioning / e2e acceptance tests (solc/forge/postgres), skip-when-absent.
include(${CMAKE_CURRENT_LIST_DIR}/NeutrinoAcceptanceTests.cmake)

# The CTest-label taxonomy guard (): ownership+heaviness labels stay in the
# declared vocabulary, and no backend-owned test depends on a second backend
# (two backend-* labels) unless it is explicitly an e2e test.
neutrino_register_test(NAME ctest-labels
  COMMAND python3 ${PROJECT_SOURCE_DIR}/scripts/gates/check_ctest_labels.py --selftest)
neutrino_register_test_properties(ctest-labels PROPERTIES LABELS "policy;completeness")

# These gates deliberately inject temporary source-tree mutations to prove
# their scanners bite. Readers of the governed source tree share the same lock
# so parallel CTest cannot observe another gate's transient probe or race its
# restoration. Lit holds the lock because its policy-ratchet fixture runs one
# of the same source-mutating self-tests.
set(_neutrino_source_tree_gate_tests
  fast
  core-feature-example-matrix-selftest
  renderer-include-lock
  anti-inference-production
  anti-inference-selftest
  decision-path-lock
  idiom-table-capability
  backend-idiom-composition
  canonical-reduction-domain-blindness
  cpp-policy
  arch-backend-isolation
  arch-domain-isolation
  arch-root-scripts
  extraction-manifests
  extraction-boundaries
  arch-link-direction
  no-orphan-scripts
  parser-metadata-keywords
  catalog-registry
  semantic-authority-selftest
  source-neutral-backend-witness-selftest
  semantic-convergence-selftest
  semantic-convergence
  target-node-registry
  recipe-roundtrip-selftest
  recipe-roundtrip
  ctest-labels)
if(NEUTRINO_LIT)
  list(APPEND _neutrino_source_tree_gate_tests lit)
endif()
neutrino_register_test_properties(${_neutrino_source_tree_gate_tests} PROPERTIES
  RESOURCE_LOCK neutrino_source_tree_gate)
unset(_neutrino_source_tree_gate_tests)

neutrino_register_test(NAME source-tree-gate-lock
  COMMAND python3 ${PROJECT_SOURCE_DIR}/scripts/gates/check_ctest_source_tree_lock.py
    --selftest --build-dir ${PROJECT_BINARY_DIR})
neutrino_register_test_properties(source-tree-gate-lock PROPERTIES LABELS "policy;completeness")

# Standalone integration slices.
set(_s5f_msi ${PROJECT_SOURCE_DIR}/test/ir/pipeline/Inputs/core_sample_installment)
set(_s5f_sns ${PROJECT_SOURCE_DIR}/test/ir/pipeline/Inputs/core_scheme_settlement)

neutrino_register_test(NAME s5f-property
  COMMAND python3 ${PROJECT_SOURCE_DIR}/scripts/property_test.py
    --source ${_s5f_msi}/source/core_sample_installment.neu
    --scenario ${_s5f_msi}/scenario/core_sample_installment_happy_path.json
    --equiv $<TARGET_FILE:neutrino-equiv>
    --out ${CMAKE_BINARY_DIR}/s5f/property --n 12)
neutrino_register_test_properties(s5f-property PROPERTIES LABELS "s5f;ctest-native")

neutrino_register_test(NAME s5f-mutation
  COMMAND ${CMAKE_COMMAND}
    -DPY=python3 -DMUT=${PROJECT_SOURCE_DIR}/scripts/mutation_test.py
    -DSRC=${_s5f_msi}/source/core_sample_installment.neu
    -DTRANSLATE=$<TARGET_FILE:neutrino-translate> -DOPT=$<TARGET_FILE:neutrino-opt>
    -DOUT=${CMAKE_BINARY_DIR}/s5f/mutation
    -P ${PROJECT_SOURCE_DIR}/test/cmake/s5f_mutation.cmake)
neutrino_register_test_properties(s5f-mutation PROPERTIES LABELS "s5f;ctest-native")

neutrino_register_test(NAME s5f-generality
  COMMAND ${CMAKE_COMMAND}
    -DTRANSLATE=$<TARGET_FILE:neutrino-translate> -DOPT=$<TARGET_FILE:neutrino-opt>
    -DGEN=$<TARGET_FILE:neutrino-gen>
    -DSRC2=${_s5f_sns}/source/core_scheme_settlement.neu
    -DSCENARIO2=${_s5f_sns}/scenario/core_scheme_settlement_happy_path.json
    -DOUT=${CMAKE_BINARY_DIR}/s5f/generality
    -P ${PROJECT_SOURCE_DIR}/test/cmake/s5f_generality.cmake)
neutrino_register_test_properties(s5f-generality PROPERTIES LABELS "s5f;ctest-native")

# Link-smokes enforce standalone module boundaries.
add_executable(spec-contract-smoke test/spec_contract_smoke.cpp)
target_link_libraries(spec-contract-smoke PRIVATE NeutrinoSpecContract)
neutrino_register_test(NAME spec-contract-smoke COMMAND spec-contract-smoke)
neutrino_register_test_properties(spec-contract-smoke PROPERTIES LABELS "contract;ctest-native")

# [] valid_carry_and_consume proof: derive schema-valid specs and feed them to the authoritative
# first consumer. Participant-slot rows render real slot artifacts through generateSlotFromSpec() via
# slot-spec-smoke, then validate_binding_manifest.py consumes binding-topology.json. Observer-set rows
# validate exact spec/binding trust-posture equality through validate_observation_binding.py.
neutrino_register_test(NAME generalism-binding-consume-witness
  COMMAND python3 ${PROJECT_SOURCE_DIR}/scripts/generators/gen_generalism_cells.py
          --prove-binding-consume $<TARGET_FILE:slot-spec-smoke>
          --coordination-plan-renderer $<TARGET_FILE:neutrino-gen>)
neutrino_register_test_properties(generalism-binding-consume-witness PROPERTIES LABELS "contract;completeness;ctest-native")

#  security-primitive carve-out: the default-deny registry gate + its biting selftest.
neutrino_register_test(NAME security-primitive-carveout
  COMMAND python3 ${PROJECT_SOURCE_DIR}/scripts/gates/check_security_primitive_carveout.py)
neutrino_register_test_properties(security-primitive-carveout PROPERTIES
  LABELS "policy;contract;completeness")
neutrino_register_test(NAME security-primitive-carveout-selftest
  COMMAND python3 ${PROJECT_SOURCE_DIR}/scripts/gates/check_security_primitive_carveout.py --selftest)
neutrino_register_test_properties(security-primitive-carveout-selftest PROPERTIES
  LABELS "policy;contract;completeness")

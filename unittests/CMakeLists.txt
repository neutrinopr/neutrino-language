# ---- C++ unit tests (gtest) for pure, non-user-facing logic ( /  S5-F2) ----
#
# The LLVM-idiomatic unit tier: gtest under unittests/, reserved for
# support/data-structure/API logic that has no good textual/tool surface for lit
# (value model, JSON/hash primitives, the pure front-end scanners). Everything
# with a CLI/IR surface stays in lit or the validator gates — this tier is only
# for direct C++ assertions.
#
# Gated the standard out-of-tree way (flang D80377, MLIR standalone PR ):
# if the LLVM we build against shipped its gtest (LLVM_INSTALL_GTEST=ON ->
# `llvm_gtest` target), reuse it; otherwise vendor googletest via FetchContent.
# A prebuilt/brew LLVM (our usual toolchain) does NOT ship gtest, so the
# FetchContent branch is the one that normally runs.

set(NEUTRINO_UNITTEST_SOURCES
  ValueModelTest.cpp
  JsonUtilTest.cpp
  ParseUtilTest.cpp
  CodeTextTest.cpp
  CoordinationPlanTest.cpp
  BackendProjectionTest.cpp
  BackendProtocolTest.cpp
  BackendPackageTest.cpp
  CapabilityModelTest.cpp
  BackendInvokerTest.cpp
  BackendDispatchReceiptTest.cpp
  ArtifactPublicationTest.cpp
  SelfEmittedSpecTest.cpp
  PostgresSpecModelTest.cpp
  CoordinationEvalTest.cpp
  PlanLegalityTest.cpp
  TraceEquivalenceTest.cpp
  AgreementEnvelopeTest.cpp
  BoundedCoordinatorTest.cpp
  ExprAttrTest.cpp
  RecipeRuntimeTest.cpp
  RecipeModuleTest.cpp
  RecipeInterpreterTest.cpp
  SolidityEvidenceRecipeTest.cpp
  PgRecipeBuildersTest.cpp)

# : generate the synthetic backend package's RecipeModule .inc from the
# test-only fixture (test/recipe/SyntheticIdiomRecipes.td) via the real recipe
# generator under the pinned llvm-tblgen. RecipeModuleTest.cpp #includes it. This
# also proves the generator + generated ABI compile and are deterministic.
set(_synth_recipes_inc ${CMAKE_CURRENT_BINARY_DIR}/synthetic_recipes.inc)
add_custom_command(OUTPUT ${_synth_recipes_inc}
  COMMAND python3 ${PROJECT_SOURCE_DIR}/scripts/generators/gen_backend_idiom_recipes.py
    --td ${PROJECT_SOURCE_DIR}/test/recipe/SyntheticIdiomRecipes.td
    --tblgen ${LLVM_TOOLS_BINARY_DIR}/llvm-tblgen
    -I ${PROJECT_SOURCE_DIR}/lib/backends
    --symbol synthetic
    -o ${_synth_recipes_inc}
  DEPENDS ${PROJECT_SOURCE_DIR}/test/recipe/SyntheticIdiomRecipes.td
          ${PROJECT_SOURCE_DIR}/lib/backends/BackendIdiom.td
          ${PROJECT_SOURCE_DIR}/scripts/generators/gen_backend_idiom_recipes.py
  COMMENT "Generating synthetic recipe module ()")
add_custom_target(synthetic-recipes-inc DEPENDS ${_synth_recipes_inc})

# Regression fixture for the empty-recipe-table fix: a package with ZERO leaf
# hooks. Before the fix its generated .inc did not compile (ambiguous ArrayRef
# ctor from `{nullptr, 0}`); RecipeModuleTest.cpp #includes it.
set(_zerohook_recipes_inc ${CMAKE_CURRENT_BINARY_DIR}/zerohook_recipes.inc)
add_custom_command(OUTPUT ${_zerohook_recipes_inc}
  COMMAND python3 ${PROJECT_SOURCE_DIR}/scripts/generators/gen_backend_idiom_recipes.py
    --td ${PROJECT_SOURCE_DIR}/test/recipe/ZeroHookIdiomRecipes.td
    --tblgen ${LLVM_TOOLS_BINARY_DIR}/llvm-tblgen
    -I ${PROJECT_SOURCE_DIR}/lib/backends
    --symbol zeroHook
    -o ${_zerohook_recipes_inc}
  DEPENDS ${PROJECT_SOURCE_DIR}/test/recipe/ZeroHookIdiomRecipes.td
          ${PROJECT_SOURCE_DIR}/lib/backends/BackendIdiom.td
          ${PROJECT_SOURCE_DIR}/scripts/generators/gen_backend_idiom_recipes.py
  COMMENT "Generating zero-hook recipe module (empty-table regression)")
add_custom_target(zerohook-recipes-inc DEPENDS ${_zerohook_recipes_inc})

# : generate the REAL Solidity package module from
# lib/backends/solidity/recipes/SolidityIdiomRecipes.td — the  guard consumers +
# (via its include) A's  evidence-contract recipe, exactly as the production
# package. SolidityEvidenceRecipeTest.cpp #includes it and asserts the reachable
# evidence key is owned by the full contract recipe, which Calls the internal
# guard consumer (no stand-in; the real rekeyed + composition).
set(_sol_package_recipes_inc ${CMAKE_CURRENT_BINARY_DIR}/solidity_package_recipes.inc)
add_custom_command(OUTPUT ${_sol_package_recipes_inc}
  COMMAND python3 ${PROJECT_SOURCE_DIR}/scripts/generators/gen_backend_idiom_recipes.py
    --td ${PROJECT_SOURCE_DIR}/lib/backends/solidity/recipes/SolidityIdiomRecipes.td
    --tblgen ${LLVM_TOOLS_BINARY_DIR}/llvm-tblgen
    -I ${PROJECT_SOURCE_DIR}/lib/backends
    --symbol solidityPackage
    -o ${_sol_package_recipes_inc}
  DEPENDS ${PROJECT_SOURCE_DIR}/lib/backends/solidity/recipes/SolidityIdiomRecipes.td
          ${PROJECT_SOURCE_DIR}/lib/backends/solidity/recipes/SolidityEvidenceIdiomRecipes.td
          ${PROJECT_SOURCE_DIR}/lib/backends/BackendIdiom.td
          ${PROJECT_SOURCE_DIR}/scripts/generators/gen_backend_idiom_recipes.py
  COMMENT "Generating REAL Solidity package recipe module ( guard +  evidence)")
add_custom_target(solidity-package-recipes-inc DEPENDS ${_sol_package_recipes_inc})

# The pure functions under test live in the core dialect lib (ValueModel,
# JsonUtil), the front-end lib (ParseUtil), and the code-emitter leaf (CodeText,
# ); linking these pulls their MLIR/LLVM deps transitively. No MLIRContext is
# constructed — the functions are pure. NeutrinoCodeText linked here ALSO proves
# the leaf is usable standalone (no hidden backend/View dep).
set(NEUTRINO_UNITTEST_LIBS NeutrinoDialect NeutrinoFrontend NeutrinoCodeText NeutrinoRecipe
  NeutrinoBackendPostgres NeutrinoCapabilityProfile NeutrinoTargetCatalog NeutrinoTooling MLIRParser)

add_executable(NeutrinoSyntheticBackend SyntheticBackendProcess.cpp)
target_link_libraries(NeutrinoSyntheticBackend PRIVATE NeutrinoSpecContract)

add_executable(NeutrinoSyntheticManifestCollisionBackend
  SyntheticBackendProcess.cpp)
target_compile_definitions(NeutrinoSyntheticManifestCollisionBackend
  PRIVATE NEUTRINO_SYNTHETIC_ARTIFACT_PATH="manifest.json")
target_link_libraries(NeutrinoSyntheticManifestCollisionBackend
  PRIVATE NeutrinoSpecContract)

add_executable(NeutrinoSyntheticDiagnosticsCollisionBackend
  SyntheticBackendProcess.cpp)
target_compile_definitions(NeutrinoSyntheticDiagnosticsCollisionBackend
  PRIVATE NEUTRINO_SYNTHETIC_ARTIFACT_PATH="diagnostics.json/payload")
target_link_libraries(NeutrinoSyntheticDiagnosticsCollisionBackend
  PRIVATE NeutrinoSpecContract)

add_executable(NeutrinoSyntheticReceiptCollisionBackend
  SyntheticBackendProcess.cpp)
target_compile_definitions(NeutrinoSyntheticReceiptCollisionBackend
  PRIVATE
    NEUTRINO_SYNTHETIC_ARTIFACT_PATH="backend-dispatch-receipt.json/payload")
target_link_libraries(NeutrinoSyntheticReceiptCollisionBackend
  PRIVATE NeutrinoSpecContract)

# : a third backend is discovered from a verified package without a
# TargetRegistry.def edit, then traverses the production projection -> invoker
# -> race-safe publication chain. The same catalog drives introspection,
# profile lookup, selection, and diagnostics.
neutrino_register_test(NAME external-target-catalog
  COMMAND python3
    ${PROJECT_SOURCE_DIR}/test/ir/compat/check_external_target_catalog.py
    --neutrino-gen $<TARGET_FILE:neutrino-gen>
    --backend $<TARGET_FILE:NeutrinoSyntheticBackend>
    --manifest-collision-backend
      $<TARGET_FILE:NeutrinoSyntheticManifestCollisionBackend>
    --diagnostics-collision-backend
      $<TARGET_FILE:NeutrinoSyntheticDiagnosticsCollisionBackend>
    --receipt-collision-backend
      $<TARGET_FILE:NeutrinoSyntheticReceiptCollisionBackend>
    --profile ${PROJECT_SOURCE_DIR}/examples/target-profiles/solidity.target-profile.json
    --projection-schema ${PROJECT_SOURCE_DIR}/docs/schemas/finalized-projection-v1.schema.json
    --source ${PROJECT_SOURCE_DIR}/test/ir/oracle/accepted_multi_policy.neu
    --scenario ${PROJECT_SOURCE_DIR}/test/ir/oracle/accepted_multi_policy.scn.json
    --insecure-spec
      ${PROJECT_SOURCE_DIR}/test/core/security/insecure-capability-spec.json
    --registry ${PROJECT_SOURCE_DIR}/include/Neutrino/TargetRegistry.def
    --registry-source ${PROJECT_SOURCE_DIR}/lib/emit/TargetRegistry.cpp
    --emit-cmake ${PROJECT_SOURCE_DIR}/lib/CMakeLists.txt
    --gen-source ${PROJECT_SOURCE_DIR}/tools/neutrino-gen/neutrino-gen.cpp
    --capability-model-source
      ${PROJECT_SOURCE_DIR}/lib/policy/capability-profile/GenCapabilityModelSpec.cpp
    --emit-library $<TARGET_FILE:NeutrinoEmit>
    --repository-package ${NEUTRINO_SOLIDITY_REPOSITORY_PACKAGE_DIR})
neutrino_register_test_properties(external-target-catalog
  PROPERTIES LABELS "contract;ctest-native")

neutrino_register_test(NAME bundle-target-catalog
  COMMAND python3
    ${PROJECT_SOURCE_DIR}/test/ir/compat/check_bundle_target_catalog.py
    --neutrino-bundle $<TARGET_FILE:neutrino-bundle>
    --neutrino-gen $<TARGET_FILE:neutrino-gen>
    --backend $<TARGET_FILE:NeutrinoSyntheticBackend>
    --profile ${PROJECT_SOURCE_DIR}/examples/target-profiles/solidity.target-profile.json
    --projection-schema ${PROJECT_SOURCE_DIR}/docs/schemas/finalized-projection-v1.schema.json
    --source ${PROJECT_SOURCE_DIR}/test/ir/oracle/accepted_multi_policy.neu
    --scenario ${PROJECT_SOURCE_DIR}/test/ir/oracle/accepted_multi_policy.scn.json)
neutrino_register_test_properties(bundle-target-catalog
  PROPERTIES LABELS "contract;ctest-native")

neutrino_register_test(NAME equiv-target-catalog
  COMMAND python3
    ${PROJECT_SOURCE_DIR}/test/ir/compat/check_equiv_target_catalog.py
    --neutrino-equiv $<TARGET_FILE:neutrino-equiv>
    --backend $<TARGET_FILE:NeutrinoSyntheticBackend>
    --profile ${PROJECT_SOURCE_DIR}/examples/target-profiles/solidity.target-profile.json
    --projection-schema ${PROJECT_SOURCE_DIR}/docs/schemas/finalized-projection-v1.schema.json
    --source
      ${PROJECT_SOURCE_DIR}/test/ir/pipeline/Inputs/core_sample_installment/source/core_sample_installment.neu
    --scenario
      ${PROJECT_SOURCE_DIR}/test/ir/pipeline/Inputs/core_sample_installment/scenario/core_sample_installment_happy_path.json
    --registry ${PROJECT_SOURCE_DIR}/include/Neutrino/TargetRegistry.def)
neutrino_register_test_properties(equiv-target-catalog
  PROPERTIES LABELS "contract;ctest-native")

if(TARGET llvm_gtest)
  # In-tree / LLVM built with LLVM_INSTALL_GTEST=ON: reuse LLVM's gtest.
  add_llvm_unittest(NeutrinoUnitTests ${NEUTRINO_UNITTEST_SOURCES})
  target_link_libraries(NeutrinoUnitTests PRIVATE ${NEUTRINO_UNITTEST_LIBS})
else()
  # Prebuilt LLVM without gtest: vendor googletest (pinned) via FetchContent.
  message(STATUS "llvm_gtest not found — vendoring googletest for unittests/ ()")
  include(FetchContent)
  FetchContent_Declare(googletest
    URL https://github.com/google/googletest/archive/refs/tags/v1.14.0.tar.gz
    URL_HASH SHA256=8ad598c73ad796e0d8280b082cebd82a630d73e73cd3c70057938a6501bba5d7
    DOWNLOAD_EXTRACT_TIMESTAMP TRUE)
  # Don't install googletest or let it clobber our compiler/CRT settings.
  set(INSTALL_GTEST OFF CACHE BOOL "" FORCE)
  set(gtest_force_shared_crt ON CACHE BOOL "" FORCE)
  FetchContent_MakeAvailable(googletest)

  add_executable(NeutrinoUnitTests ${NEUTRINO_UNITTEST_SOURCES})
  target_link_libraries(NeutrinoUnitTests
    PRIVATE ${NEUTRINO_UNITTEST_LIBS} GTest::gtest_main)
endif()

target_compile_definitions(NeutrinoUnitTests
  PRIVATE NEUTRINO_SOURCE_ROOT="${PROJECT_SOURCE_DIR}")

neutrino_register_test(NAME target-profile-validator-agreement
  COMMAND python3
    ${PROJECT_SOURCE_DIR}/test/ir/compat/check_target_profile_validator_agreement.py
    --fixture
      ${PROJECT_SOURCE_DIR}/test/ir/compat/Inputs/target-profile-validator-agreement.json
    --schema
      ${PROJECT_SOURCE_DIR}/docs/schemas/backend-package-target-profile-v1.schema.json
    --validator
      ${PROJECT_SOURCE_DIR}/scripts/validators/validate_backend_package_target_profile.py
    --schema-validator
      ${PROJECT_SOURCE_DIR}/scripts/validators/verify_domain_pack.py
    --public-schema
      ${PROJECT_SOURCE_DIR}/docs/schemas/target-profile.schema.json
    --public-validator
      ${PROJECT_SOURCE_DIR}/scripts/validators/validate_target_profile.py)
neutrino_register_test_properties(target-profile-validator-agreement
  PROPERTIES LABELS "contract;ctest-native")

# PostgresSpecModelTest reaches the leaf's INTERNAL seam header (not a public include).
target_include_directories(NeutrinoUnitTests PRIVATE
  ${CMAKE_CURRENT_SOURCE_DIR}/../lib/backends/postgres
  #  R1: PgRecipeBuildersTest.cpp #includes the moved model/PostgresModel.h +
  # generated/PostgresRecipeBuilders.inc with bare spellings (byte-identical to the
  # pre- flat header); the package subdirs give the bare includes their pre-move
  # flat-sibling resolution.
  ${CMAKE_CURRENT_SOURCE_DIR}/../lib/backends/postgres/model
  ${PROJECT_BINARY_DIR}/lib/backends/postgres/generated
  ${CMAKE_CURRENT_SOURCE_DIR}/../lib/backends/postgres/provider
  ${CMAKE_CURRENT_SOURCE_DIR}/../lib/backends/postgres/leaf)

# : RecipeModuleTest.cpp + RecipeInterpreterTest.cpp #include the
# build-generated synthetic_recipes.inc.
add_dependencies(NeutrinoUnitTests synthetic-recipes-inc)
# RecipeModuleTest.cpp also #includes the zero-hook regression module.
add_dependencies(NeutrinoUnitTests zerohook-recipes-inc)
# : SolidityEvidenceRecipeTest.cpp #includes the generated evidence module.
add_dependencies(NeutrinoUnitTests solidity-package-recipes-inc)
add_dependencies(NeutrinoUnitTests postgres-recipe-builders-inc)
add_dependencies(NeutrinoUnitTests NeutrinoSyntheticBackend)
target_compile_definitions(NeutrinoUnitTests PRIVATE
  NEUTRINO_SYNTHETIC_BACKEND_PATH="$<TARGET_FILE:NeutrinoSyntheticBackend>")
target_include_directories(NeutrinoUnitTests PRIVATE ${CMAKE_CURRENT_BINARY_DIR})

# One CTest test running the whole gtest binary (gtest names each case in its own
# output). Labeled so `ctest -L unit` selects it; `ctest -L cpp` groups the C++ tier.
neutrino_register_test(NAME unittests COMMAND NeutrinoUnitTests)
neutrino_register_test_properties(unittests PROPERTIES LABELS "unit;cpp")

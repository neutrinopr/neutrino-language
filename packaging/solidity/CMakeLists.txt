cmake_minimum_required(VERSION 3.20)
project(NeutrinoSolidityBackendPackage LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

find_package(LLVM 15 REQUIRED CONFIG)
list(APPEND CMAKE_MODULE_PATH "${LLVM_CMAKE_DIR}")
include(AddLLVM)
llvm_map_components_to_libnames(NEUTRINO_SOLIDITY_LLVM_LIBS Support)
find_program(NEUTRINO_SOLIDITY_TBLGEN llvm-tblgen
  HINTS "${LLVM_TOOLS_BINARY_DIR}" REQUIRED)
find_package(Python3 REQUIRED COMPONENTS Interpreter)

set(PACKAGE_ROOT "${CMAKE_CURRENT_SOURCE_DIR}")
set(PACKAGE_BACKEND "${PACKAGE_ROOT}/lib/backends/solidity")
set(PACKAGE_GENERATORS "${PACKAGE_ROOT}/scripts/generators")
set(PACKAGE_GENERATED "${CMAKE_CURRENT_BINARY_DIR}/generated")
file(MAKE_DIRECTORY "${PACKAGE_GENERATED}")

set(SOLIDITY_NODE_TD "${PACKAGE_BACKEND}/model/SolidityTargetNodes.td")
set(SOLIDITY_RECIPE_TD
  "${PACKAGE_BACKEND}/recipes/SolidityIdiomRecipes.td")
set(SOLIDITY_PROJECTION_TD
  "${PACKAGE_BACKEND}/recipes/SolidityProjectionSchema.td")
set(BACKEND_SCHEMA_DIR "${PACKAGE_ROOT}/lib/backends")

set(FINALIZED_PROJECTION_SCHEMA
  "${PACKAGE_ROOT}/docs/schemas/finalized-projection-v1.schema.json")
add_custom_command(
  OUTPUT
    "${PACKAGE_GENERATED}/finalized-projection-v1.schema.json"
    "${PACKAGE_GENERATED}/BackendProjectionCodecFields.inc"
  COMMAND "${Python3_EXECUTABLE}"
    "${PACKAGE_GENERATORS}/gen_finalized_projection_schema.py"
    --header "${PACKAGE_ROOT}/include/Neutrino/BackendProjection.h"
    --coordination-header
      "${PACKAGE_ROOT}/include/Neutrino/CoordinationPlan.h"
    --gate-mode-header
      "${PACKAGE_ROOT}/include/Neutrino/ProjectionGateMode.h"
    --output "${PACKAGE_GENERATED}/finalized-projection-v1.schema.json"
    --codec-fields-output
      "${PACKAGE_GENERATED}/BackendProjectionCodecFields.inc"
  COMMAND "${CMAKE_COMMAND}" -E compare_files
    "${PACKAGE_GENERATED}/finalized-projection-v1.schema.json"
    "${FINALIZED_PROJECTION_SCHEMA}"
  DEPENDS
    "${PACKAGE_ROOT}/include/Neutrino/BackendProjection.h"
    "${PACKAGE_ROOT}/include/Neutrino/CoordinationPlan.h"
    "${PACKAGE_ROOT}/include/Neutrino/ProjectionGateMode.h"
    "${FINALIZED_PROJECTION_SCHEMA}"
    "${PACKAGE_GENERATORS}/gen_finalized_projection_schema.py"
  VERBATIM)

add_custom_command(
  OUTPUT
    "${PACKAGE_GENERATED}/SolidityTargetNodes.inc"
    "${PACKAGE_GENERATED}/SolidityPrinterHandlers.inc"
    "${PACKAGE_GENERATED}/SolidityTargetEnums.inc"
  COMMAND "${Python3_EXECUTABLE}"
    "${PACKAGE_GENERATORS}/gen_target_node_registry.py"
    --td "${SOLIDITY_NODE_TD}"
    --out "${PACKAGE_GENERATED}/SolidityTargetNodes.inc"
    --printer-out "${PACKAGE_GENERATED}/SolidityPrinterHandlers.inc"
    --enums-out "${PACKAGE_GENERATED}/SolidityTargetEnums.inc"
    --tblgen "${NEUTRINO_SOLIDITY_TBLGEN}"
  DEPENDS
    "${SOLIDITY_NODE_TD}"
    "${BACKEND_SCHEMA_DIR}/TargetPrinter.td"
    "${PACKAGE_GENERATORS}/gen_target_node_registry.py")

add_custom_command(
  OUTPUT "${PACKAGE_GENERATED}/SolidityRecipeBuilders.inc"
  COMMAND "${Python3_EXECUTABLE}"
    "${PACKAGE_GENERATORS}/backend_recipe_gen.py"
    --profile solidity-recipe-adapter
    --td "${SOLIDITY_RECIPE_TD}"
    --target-td "${SOLIDITY_NODE_TD}"
    --tblgen "${NEUTRINO_SOLIDITY_TBLGEN}"
    -I "${BACKEND_SCHEMA_DIR}"
    -o "${PACKAGE_GENERATED}/SolidityRecipeBuilders.inc"
  DEPENDS
    "${SOLIDITY_RECIPE_TD}"
    "${PACKAGE_BACKEND}/recipes/SolidityEvidenceIdiomRecipes.td"
    "${PACKAGE_BACKEND}/recipes/SolidityTemporalIdiomRecipes.td"
    "${PACKAGE_BACKEND}/recipes/SolidityEffectfulIdiomRecipes.td"
    "${SOLIDITY_NODE_TD}"
    "${BACKEND_SCHEMA_DIR}/BackendIdiom.td"
    "${PACKAGE_GENERATORS}/backend_recipe_gen.py")

add_custom_command(
  OUTPUT "${PACKAGE_GENERATED}/SolidityProjection.inc"
  COMMAND "${Python3_EXECUTABLE}"
    "${PACKAGE_GENERATORS}/backend_recipe_gen.py"
    --profile solidity-projection
    --td "${SOLIDITY_PROJECTION_TD}"
    --target-td "${SOLIDITY_NODE_TD}"
    --tblgen "${NEUTRINO_SOLIDITY_TBLGEN}"
    -I "${BACKEND_SCHEMA_DIR}"
    -o "${PACKAGE_GENERATED}/SolidityProjection.inc"
  DEPENDS
    "${SOLIDITY_PROJECTION_TD}"
    "${SOLIDITY_NODE_TD}"
    "${BACKEND_SCHEMA_DIR}/TargetPrinter.td"
    "${PACKAGE_GENERATORS}/backend_recipe_gen.py")

add_custom_command(
  OUTPUT
    "${PACKAGE_GENERATED}/SolidityEmitBuilderDecls.inc"
    "${PACKAGE_GENERATED}/SolidityEmitBuilders.inc"
  COMMAND "${Python3_EXECUTABLE}"
    "${PACKAGE_GENERATORS}/backend_recipe_gen.py"
    --profile solidity-emit-builders
    --td "${SOLIDITY_NODE_TD}"
    --tblgen "${NEUTRINO_SOLIDITY_TBLGEN}"
    -I "${BACKEND_SCHEMA_DIR}"
    --decls "${PACKAGE_GENERATED}/SolidityEmitBuilderDecls.inc"
    --defs "${PACKAGE_GENERATED}/SolidityEmitBuilders.inc"
  DEPENDS
    "${SOLIDITY_NODE_TD}"
    "${BACKEND_SCHEMA_DIR}/TargetPrinter.td"
    "${PACKAGE_GENERATORS}/backend_recipe_gen.py")

add_custom_command(
  OUTPUT "${PACKAGE_GENERATED}/solidity_recipes.inc"
  COMMAND "${Python3_EXECUTABLE}"
    "${PACKAGE_GENERATORS}/gen_backend_idiom_recipes.py"
    --td "${SOLIDITY_RECIPE_TD}"
    --tblgen "${NEUTRINO_SOLIDITY_TBLGEN}"
    -I "${BACKEND_SCHEMA_DIR}"
    --symbol solidity
    -o "${PACKAGE_GENERATED}/solidity_recipes.inc"
  DEPENDS
    "${SOLIDITY_RECIPE_TD}"
    "${PACKAGE_BACKEND}/recipes/SolidityEvidenceIdiomRecipes.td"
    "${PACKAGE_BACKEND}/recipes/SolidityTemporalIdiomRecipes.td"
    "${PACKAGE_BACKEND}/recipes/SolidityEffectfulIdiomRecipes.td"
    "${BACKEND_SCHEMA_DIR}/BackendIdiom.td"
    "${PACKAGE_GENERATORS}/gen_backend_idiom_recipes.py")

add_custom_target(solidity-package-generated DEPENDS
  "${PACKAGE_GENERATED}/BackendProjectionCodecFields.inc"
  "${PACKAGE_GENERATED}/SolidityTargetNodes.inc"
  "${PACKAGE_GENERATED}/finalized-projection-v1.schema.json"
  "${PACKAGE_GENERATED}/SolidityPrinterHandlers.inc"
  "${PACKAGE_GENERATED}/SolidityTargetEnums.inc"
  "${PACKAGE_GENERATED}/SolidityRecipeBuilders.inc"
  "${PACKAGE_GENERATED}/SolidityProjection.inc"
  "${PACKAGE_GENERATED}/SolidityEmitBuilderDecls.inc"
  "${PACKAGE_GENERATED}/SolidityEmitBuilders.inc"
  "${PACKAGE_GENERATED}/solidity_recipes.inc")

set(BACKEND_SOURCE_RUNTIME_SOURCES
  lib/spec-contract/ValueModel.cpp
  lib/spec-contract/JsonUtil.cpp
  lib/spec-contract/Expr.cpp
  lib/spec-contract/BackendProjection.cpp
  lib/spec-contract/BackendProjectionCodec.cpp
  lib/spec-contract/BackendProtocol.cpp
  lib/spec-contract/BackendStartup.cpp
  lib/spec-contract/StrCase.cpp
  lib/codetext/CodeText.cpp
  lib/codetext/TargetPrinter.cpp
  lib/recipe/RecipeRuntime.cpp
  lib/recipe/RecipeModule.cpp
  lib/recipe/RecipeInterpreter.cpp
  lib/recipe/RecipeExecutor.cpp
  lib/recipe/RecipeProviderRegistry.cpp)

set(SOLIDITY_PACKAGE_PRIVATE_SOURCES
  lib/backends/solidity/provider/SolidityTargetValidation.cpp
  lib/backends/solidity/provider/SolidityTargetAdapter.cpp
  lib/backends/solidity/provider/SolidityRenderer.cpp
  lib/backends/solidity/provider/SolidityRecipeProvider.cpp
  lib/backends/solidity/GenSolidityQuorumGuard.cpp
  lib/backends/solidity/provider/SolidityEmit.cpp)

add_library(neutrino-backend-source-runtime STATIC
  ${BACKEND_SOURCE_RUNTIME_SOURCES})
add_dependencies(neutrino-backend-source-runtime
  solidity-package-generated)
target_include_directories(neutrino-backend-source-runtime PRIVATE
  "${PACKAGE_ROOT}/include"
  "${PACKAGE_GENERATED}"
  "${LLVM_INCLUDE_DIRS}")
set_source_files_properties(
  lib/spec-contract/BackendProjectionCodec.cpp
  PROPERTIES OBJECT_DEPENDS
    "${PACKAGE_GENERATED}/BackendProjectionCodecFields.inc;${PACKAGE_GENERATED}/finalized-projection-v1.schema.json")
target_compile_definitions(neutrino-backend-source-runtime PRIVATE
  NEUTRINO_PROJECTION_CONSUMER_ONLY
  ${LLVM_DEFINITIONS})
target_compile_options(neutrino-backend-source-runtime PRIVATE
  -fexceptions -frtti)
target_link_libraries(neutrino-backend-source-runtime PRIVATE
  ${NEUTRINO_SOLIDITY_LLVM_LIBS})

add_library(neutrino-solidity-package-private STATIC
  ${SOLIDITY_PACKAGE_PRIVATE_SOURCES})
add_dependencies(neutrino-solidity-package-private
  solidity-package-generated)
set_source_files_properties(
  lib/backends/solidity/provider/SolidityRecipeProvider.cpp
  PROPERTIES OBJECT_DEPENDS
    "${PACKAGE_GENERATED}/solidity_recipes.inc;${PACKAGE_GENERATED}/SolidityProjection.inc")
target_include_directories(neutrino-solidity-package-private PRIVATE
  "${PACKAGE_ROOT}/include"
  "${PACKAGE_BACKEND}"
  "${PACKAGE_BACKEND}/generated"
  "${PACKAGE_BACKEND}/provider"
  "${PACKAGE_GENERATED}"
  "${LLVM_INCLUDE_DIRS}")
target_compile_definitions(neutrino-solidity-package-private PRIVATE
  NEUTRINO_PROJECTION_CONSUMER_ONLY
  NEUTRINO_SOLIDITY_PACKAGE_ONLY
  ${LLVM_DEFINITIONS})
target_compile_options(neutrino-solidity-package-private PRIVATE
  -fexceptions -frtti)
target_link_libraries(neutrino-solidity-package-private PRIVATE
  neutrino-backend-source-runtime ${NEUTRINO_SOLIDITY_LLVM_LIBS})

add_executable(neutrino-solidity-backend
  packaging/solidity/src/SolidityBackendMain.cpp)
target_compile_definitions(neutrino-solidity-backend PRIVATE
  NEUTRINO_PROJECTION_CONSUMER_ONLY)
target_include_directories(neutrino-solidity-backend PRIVATE
  "${PACKAGE_ROOT}/include"
  "${PACKAGE_BACKEND}"
  "${PACKAGE_BACKEND}/generated"
  "${PACKAGE_BACKEND}/provider"
  "${PACKAGE_GENERATED}"
  "${LLVM_INCLUDE_DIRS}")
target_link_libraries(neutrino-solidity-backend PRIVATE
  neutrino-solidity-package-private ${NEUTRINO_SOLIDITY_LLVM_LIBS})

enable_testing()
add_executable(solidity-package-render-test
  lib/backends/solidity/test/solidity_stmt_shell_render_harness.cpp)
target_compile_definitions(solidity-package-render-test PRIVATE
  NEUTRINO_PROJECTION_CONSUMER_ONLY
  NODE_SPDX
  NODE_INC="${PACKAGE_GENERATED}/SolidityPrinterHandlers.inc")
target_include_directories(solidity-package-render-test PRIVATE
  "${PACKAGE_ROOT}/include"
  "${PACKAGE_BACKEND}/provider"
  "${PACKAGE_BACKEND}/generated"
  "${PACKAGE_GENERATED}"
  "${LLVM_INCLUDE_DIRS}")
target_link_libraries(solidity-package-render-test PRIVATE
  neutrino-solidity-package-private ${NEUTRINO_SOLIDITY_LLVM_LIBS})
neutrino_register_test(NAME solidity-package-render
  COMMAND solidity-package-render-test
    "${PACKAGE_ROOT}/test/ir/samples/Inputs/core_document_escrow/generated/solidity/src/CoreDocumentEscrow.sol")

install(TARGETS neutrino-solidity-backend
  RUNTIME DESTINATION bin)

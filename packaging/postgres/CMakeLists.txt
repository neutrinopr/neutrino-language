# =============================================================================
# NeutrinoBackendPostgres — standalone package build/install SKELETON ()
# =============================================================================
# A repository-extraction CANDIDATE: this configures, builds, and installs the
# PostgreSQL backend as a self-contained package against an INSTALLED public
# core, with every generated `.inc` produced at build time as a BUILD PRODUCT
# (never a copied source).
#
# This is a standalone CMake project — it is NOT add_subdirectory()'d by the
# translator root CMake, so it does not affect the in-tree build. It is
# CURRENT STATE:
#     *   LANDED — the installable backend-free public-core artifact exists.
#     * SHARED prerequisites LANDED — the schema/startup/discovery contracts
#               neutrino.backend-source-runtime/1 and neutrino.backend-startup/1
#               exist.  itself remains OPEN, and the PostgreSQL-specific
#               package moves (PgDdl.h -> package-internal, recipe-runtime
#               relocation) are PENDING work for the second  clean-clone PR.
#     * The clean-clone execution itself is a separate, second  PR.
#     *   PENDING-RATIFICATION — publication/license only; not an
#               engineering stop.
#   Disjoint from  (this regenerates `.inc`; it does not delete the
#   committed copies from the translator tree).
#
# The authoritative inventory this skeleton reproduces is
# `packaging/postgres/extraction-manifest.json`; the boundary it targets is
# `docs/process/M7_BACKEND_PACKAGE_BOUNDARY_ADR.md` ().
# =============================================================================
cmake_minimum_required(VERSION 3.20)
project(NeutrinoBackendPostgres LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# --- Package layout inputs ----------------------------------------------------
# In a clean clone the unit sources sit at the package root; while this skeleton
# lives inside the translator tree, point at the in-tree unit by default so the
# graph is reproducible and reviewable today.
set(NBP_UNIT_DIR "${CMAKE_CURRENT_SOURCE_DIR}/lib/backends/postgres"
    CACHE PATH "PostgreSQL backend unit source root")
# NBP_TRANSLATOR_ROOT is deliberately GONE. Every input the candidate needs is
# materialized under the package as extraction payload: unit/ (backend sources
# and .td), payload/generators/, payload/backends/, lib/recipe/,
# include/. The monorepo remains the single source of truth for their
# CONTENT -- these are manifest payloads copied into the candidate, never a
# second implementation -- but nothing here resolves into a source checkout at
# configure or build time. A clean clone has no such checkout, so any surviving
# reference would build green in-tree and fail where it actually matters.

# --- Public-core dependency ( / ) -----------------------------------
# --- The installed backend-free core () -----------------------------------
# The  boundary is BYTES OVER A VERSIONED SUBPROCESS PROTOCOL, not a C++ ABI.
# The  installed export encodes exactly that: cppAbiPolicy `forbidden`, with
# publicTargets / publicHeaders / cmakeExports ALL EMPTY. There is therefore no
# CMake package to find, and `find_package(NeutrinoCore)` is not merely unused —
# it is unsatisfiable by construction, and a fallback to in-tree targets would be
# the private reach-back this package exists to forbid.
#
# The core is consumed as INSTALLED RUNTIME ARTIFACTS discovered through the
# descriptor, and invoked over the versioned protocol. No C++ dependency, no
# fallback.
set(NBP_CORE_PREFIX "" CACHE PATH
    "Prefix of an installed backend-free core (). Required for a standalone build.")
set(NBP_CORE_RECEIPT "" CACHE FILEPATH
    "Release receipt for the installed core (/), delivered OUT-OF-BAND. \
Required for a standalone build. A receipt resolving inside NBP_CORE_PREFIX is \
refused — it would prove only that the prefix agrees with itself.")
set(NBP_CORE_BUILD_TARGET "" CACHE STRING
    "Consuming platform triple, compared against the receipt's buildTarget. \
Admission refuses when it cannot be established: artifact digests are \
platform-specific, so an unproven platform is not a match.")
option(NBP_STANDALONE_CORE "Build against an installed backend-free core" OFF)

if(NBP_STANDALONE_CORE)
  if(NOT NBP_CORE_PREFIX)
    message(FATAL_ERROR
      "[] NBP_STANDALONE_CORE=ON requires NBP_CORE_PREFIX to point at an "
      "installed backend-free core (). There is no find_package() seam: the "
      "core exports no CMake package and no C++ ABI by design.")
  endif()
  # Validate the installed tree against the  export manifest: every declared
  # runtime artifact must be present and executable. Fail closed — a missing
  # artifact means the core is not the one this package was built against.
  # The manifest MUST come from the supplied prefix. Falling back to the
  # translator source tree would authenticate the checkout we are trying to prove
  # absent, so there is deliberately no fallback.
  set(NBP_CORE_EXPORT "${NBP_CORE_PREFIX}/share/neutrino/m7-core-installed-export.json")
  if(NOT EXISTS "${NBP_CORE_EXPORT}")
    message(FATAL_ERROR
      "[] the installed core at ${NBP_CORE_PREFIX} carries no  export "
      "manifest. Admission requires the manifest FROM THE PREFIX; the source-tree "
      "copy is not accepted.")
  endif()
  file(READ "${NBP_CORE_EXPORT}" NBP_CORE_EXPORT_TEXT)
  string(JSON NBP_CORE_ABI GET "${NBP_CORE_EXPORT_TEXT}" cppAbiPolicy)
  if(NOT NBP_CORE_ABI STREQUAL "forbidden")
    message(FATAL_ERROR
      "[] the installed core declares cppAbiPolicy='${NBP_CORE_ABI}'; this "
      "package consumes bytes over the protocol and refuses a C++ ABI edge.")
  endif()
  string(JSON NBP_CORE_RT_COUNT LENGTH "${NBP_CORE_EXPORT_TEXT}" runtimeArtifacts)
  math(EXPR NBP_CORE_RT_LAST "${NBP_CORE_RT_COUNT} - 1")
  foreach(_i RANGE ${NBP_CORE_RT_LAST})
    string(JSON _art GET "${NBP_CORE_EXPORT_TEXT}" runtimeArtifacts ${_i})
    set(_full "${NBP_CORE_PREFIX}/${_art}")
    if(NOT EXISTS "${_full}")
      message(FATAL_ERROR
        "[] installed core is incomplete: ${_art} declared by the  export "
        "is absent under ${NBP_CORE_PREFIX}")
    endif()
    # Actually verify it is a non-empty regular executable, not merely a path that
    # exists: six empty chmod +x files must not pass admission.
    if(IS_DIRECTORY "${_full}")
      message(FATAL_ERROR "[] declared runtime artifact is a directory: ${_art}")
    endif()
    file(SIZE "${_full}" _sz)
    if(_sz EQUAL 0)
      message(FATAL_ERROR
        "[] declared runtime artifact ${_art} is EMPTY — an installed core "
        "cannot be authenticated by path existence alone")
    endif()
    execute_process(COMMAND test -x "${_full}" RESULT_VARIABLE _notexe)
    if(NOT _notexe EQUAL 0)
      message(FATAL_ERROR "[] declared runtime artifact ${_art} is not executable")
    endif()
  endforeach()

  # AUTHENTICATION ( Mode A). The checks above are diagnostics: they show
  # the prefix is shaped like a core, never that it IS the core the release
  # contract selected. The prefix-local digest sidecar that used to sit here
  # could not close that gap — it was derived from the prefix it described, so
  # substituting every artifact and recomputing it together passed. It is gone,
  # replaced by byte-binding against a producer-emitted release receipt that
  # reaches us out-of-band ().
  if(NOT NBP_CORE_RECEIPT)
    message(FATAL_ERROR
      "[] NBP_STANDALONE_CORE=ON requires NBP_CORE_RECEIPT to point at the "
      "release receipt for this core, delivered out-of-band ( section 3 "
      "Mode A). A receipt resolving inside NBP_CORE_PREFIX is refused: a record "
      "travelling with the artifacts proves only self-consistency.")
  endif()
  execute_process(
    COMMAND "${CMAKE_COMMAND}" -E env
            "NBP_BUILD_TARGET=${NBP_CORE_BUILD_TARGET}"
            python3 "${CMAKE_CURRENT_SOURCE_DIR}/scripts/admit_core_receipt.py"
            --prefix "${NBP_CORE_PREFIX}"
            --receipt "${NBP_CORE_RECEIPT}"
            --installed-export "${NBP_CORE_EXPORT}"
    RESULT_VARIABLE _admit_rc
    OUTPUT_VARIABLE _admit_out
    ERROR_VARIABLE _admit_err)
  if(NOT _admit_rc EQUAL 0)
    message(FATAL_ERROR "[] core receipt admission FAILED:\n${_admit_err}")
  endif()
  string(STRIP "${_admit_out}" _admit_out)
  message(STATUS
    "[] core prefix AUTHENTICATED at ${NBP_CORE_PREFIX}: cppAbiPolicy="
    "forbidden, ${NBP_CORE_RT_COUNT} declared runtime artifacts byte-bound to "
    "producer-declared {path, sha256, mode}. ${_admit_out}. Consumed via "
    "descriptor discovery + the versioned subprocess protocol.")
else()
  message(STATUS
    "[] NBP_STANDALONE_CORE=OFF: in-tree review configuration. The standalone "
    "clean clone sets it ON with NBP_CORE_PREFIX. There is no find_package() seam "
    "and no C++ fallback by design. Publication and license ratification remain "
    "gated on .")
endif()

# --- Pinned package-internal shared-runtime source contract () ----------
# The standalone build compiles these; it links no core C++ target.
set(NBP_RUNTIME_CONTRACT "${CMAKE_CURRENT_SOURCE_DIR}/../shared/backend-source-runtime-v1.json")
set(NBP_SHARED_RUNTIME_SOURCES "")
set(NBP_SHARED_RUNTIME_DEFINITIONS "")
if(EXISTS "${NBP_RUNTIME_CONTRACT}")
  file(READ "${NBP_RUNTIME_CONTRACT}" NBP_RC_TEXT)
  string(JSON NBP_RC_N LENGTH "${NBP_RC_TEXT}" sources)
  math(EXPR NBP_RC_LAST "${NBP_RC_N} - 1")
  foreach(_i RANGE ${NBP_RC_LAST})
    string(JSON _e GET "${NBP_RC_TEXT}" sources ${_i})
    string(JSON _p GET "${_e}" path)
    if(_p MATCHES "\\.cpp$")
      list(APPEND NBP_SHARED_RUNTIME_SOURCES "${CMAKE_CURRENT_SOURCE_DIR}/${_p}")
    endif()
  endforeach()
  string(JSON NBP_RC_DN LENGTH "${NBP_RC_TEXT}" compileDefinitions)
  math(EXPR NBP_RC_DLAST "${NBP_RC_DN} - 1")
  foreach(_i RANGE ${NBP_RC_DLAST})
    string(JSON _d GET "${NBP_RC_TEXT}" compileDefinitions ${_i})
    list(APPEND NBP_SHARED_RUNTIME_DEFINITIONS "${_d}")
  endforeach()
endif()

# --- Toolchain (pinned) -------------------------------------------------------
# NBP_LLVM_TBLGEN is an EXPLICIT pinned input, never discovered. Searching PATH
# would silently bind whichever llvm-tblgen a host happens to expose, and the
# .inc products are only reproducible against the pinned LLVM. A clean clone
# must state its toolchain rather than inherit the builder's environment.
set(NBP_LLVM_REQUIRED_MAJOR "15")
set(NBP_LLVM_TBLGEN "" CACHE FILEPATH
    "Absolute path to the pinned LLVM 15 llvm-tblgen. Required: not searched \
for on PATH, and there is no source-tree fallback.")
set(NBP_LLVM_NM "" CACHE FILEPATH
    "Absolute path to the pinned llvm-nm ( channel-2 authority gates).")
set(NBP_LLVM_INCLUDE_DIR "" CACHE PATH
    "Absolute include directory of the pinned LLVM 15. Required: never searched \
for, never inferred from a package manager prefix.")

if(NOT NBP_LLVM_INCLUDE_DIR)
  message(FATAL_ERROR
    "[] NBP_LLVM_INCLUDE_DIR is required and must name the pinned LLVM "
    "${NBP_LLVM_REQUIRED_MAJOR} include directory explicitly, e.g. "
    "-DNBP_LLVM_INCLUDE_DIR=/path/to/llvm@${NBP_LLVM_REQUIRED_MAJOR}/include. "
    "It is deliberately not discovered: inferring it from PATH or a Homebrew "
    "prefix would bind whichever LLVM the host exposes, and the shared runtime "
    "compiles only against the pinned headers.")
endif()
if(NOT EXISTS "${NBP_LLVM_INCLUDE_DIR}/llvm/ADT/ArrayRef.h")
  message(FATAL_ERROR
    "[] NBP_LLVM_INCLUDE_DIR=${NBP_LLVM_INCLUDE_DIR} does not contain "
    "llvm/ADT/ArrayRef.h — it is not an LLVM include tree.")
endif()
# Bind the major version to the headers themselves, so a directory that merely
# looks like an LLVM tree cannot stand in for the pinned one.
if(NOT EXISTS "${NBP_LLVM_INCLUDE_DIR}/llvm/Config/llvm-config.h")
  message(FATAL_ERROR
    "[] NBP_LLVM_INCLUDE_DIR carries no llvm/Config/llvm-config.h; the "
    "pinned major version cannot be confirmed.")
endif()
file(STRINGS "${NBP_LLVM_INCLUDE_DIR}/llvm/Config/llvm-config.h" _llvm_major
     REGEX "^#define LLVM_VERSION_MAJOR ")
if(NOT _llvm_major MATCHES "LLVM_VERSION_MAJOR ${NBP_LLVM_REQUIRED_MAJOR}$")
  message(FATAL_ERROR
    "[] pinned header mismatch: ${NBP_LLVM_INCLUDE_DIR} reports "
    "'${_llvm_major}', expected LLVM_VERSION_MAJOR ${NBP_LLVM_REQUIRED_MAJOR}.")
endif()

if(NOT NBP_LLVM_TBLGEN)
  message(FATAL_ERROR
    "[] NBP_LLVM_TBLGEN is required and must name the pinned LLVM "
    "${NBP_LLVM_REQUIRED_MAJOR} llvm-tblgen explicitly, e.g. "
    "-DNBP_LLVM_TBLGEN=/path/to/llvm@${NBP_LLVM_REQUIRED_MAJOR}/bin/llvm-tblgen. "
    "It is deliberately NOT searched for on PATH: the .inc build products are "
    "reproducible only against the pinned toolchain, so the clean clone states "
    "it rather than inheriting whatever the host exposes.")
endif()
if(NOT EXISTS "${NBP_LLVM_TBLGEN}")
  message(FATAL_ERROR "[] NBP_LLVM_TBLGEN does not exist: ${NBP_LLVM_TBLGEN}")
endif()
execute_process(COMMAND "${NBP_LLVM_TBLGEN}" --version
                RESULT_VARIABLE _tg_rc OUTPUT_VARIABLE _tg_out ERROR_QUIET)
if(NOT _tg_rc EQUAL 0)
  message(FATAL_ERROR
    "[] NBP_LLVM_TBLGEN is not executable: ${NBP_LLVM_TBLGEN}")
endif()
if(NOT _tg_out MATCHES "LLVM version ${NBP_LLVM_REQUIRED_MAJOR}\\.")
  string(REGEX MATCH "LLVM version [0-9]+\\.[0-9]+\\.[0-9]+" _tg_ver "${_tg_out}")
  message(FATAL_ERROR
    "[] pinned toolchain mismatch: NBP_LLVM_TBLGEN reports '${_tg_ver}', "
    "expected LLVM ${NBP_LLVM_REQUIRED_MAJOR}.x. The .inc products are not "
    "reproducible across TableGen major versions.")
endif()
set(NBP_GEN "${CMAKE_CURRENT_SOURCE_DIR}/payload/generators")   #  vendors these
set(NBP_BACKENDS_INC "${CMAKE_CURRENT_SOURCE_DIR}/lib/backends") # shared .td schemas
set(NBP_GENDIR "${CMAKE_CURRENT_BINARY_DIR}/generated")
file(MAKE_DIRECTORY ${NBP_GENDIR})

# --- Generated build products (never copied sources) --------------------------
# Each `.inc` is REGENERATED from its `.td` source of truth into the build tree.
# A clean clone produces these; it does not vendor the committed bytes as source.
# (Byte-identity to the committed copies is the translator tree's  concern,
# not the package's — the package's contract is the `.td`, not the `.inc`.)

# 1) Target-node registry / enums / printer handlers  <- model/PostgresTargetNodes.td
foreach(_reg PostgresTargetNodes PostgresTargetEnums PostgresPrinterHandlers)
  list(APPEND NBP_REGISTRY_OUTS ${NBP_GENDIR}/${_reg}.inc)
endforeach()
add_custom_command(OUTPUT ${NBP_REGISTRY_OUTS}
  # NOTE: --schema/--outdir were never real flags on this generator; the package
  # had been written against an older CLI and this path had never executed. The
  # invocation below matches the generator actually shipped in the payload.
  COMMAND python3 ${NBP_GEN}/gen_target_node_registry.py
          --td ${NBP_UNIT_DIR}/model/PostgresTargetNodes.td
          --out ${NBP_GENDIR}/PostgresTargetNodes.inc
          --enums-out ${NBP_GENDIR}/PostgresTargetEnums.inc
          --printer-out ${NBP_GENDIR}/PostgresPrinterHandlers.inc
          --tblgen ${NBP_LLVM_TBLGEN}
  DEPENDS ${NBP_UNIT_DIR}/model/PostgresTargetNodes.td
          ${NBP_BACKENDS_INC}/TargetPrinter.td
  COMMENT "[] Regenerating PostgreSQL target-node registry (build product)")

# 2) Recipe builders (+ decls)  <- model/PostgresTargetNodes.td
add_custom_command(
  OUTPUT ${NBP_GENDIR}/PostgresRecipeBuilders.inc
         ${NBP_GENDIR}/PostgresRecipeBuilders.decl.inc
  COMMAND python3 ${NBP_GEN}/backend_recipe_gen.py --profile postgres-recipe-builders
          --td ${NBP_UNIT_DIR}/model/PostgresTargetNodes.td
          --tblgen ${NBP_LLVM_TBLGEN} -I ${NBP_BACKENDS_INC}
          --decl-out ${NBP_GENDIR}/PostgresRecipeBuilders.decl.inc
          --def-out ${NBP_GENDIR}/PostgresRecipeBuilders.inc
  DEPENDS ${NBP_UNIT_DIR}/model/PostgresTargetNodes.td
  COMMENT "[] Regenerating PostgreSQL recipe builders (build product)")

# 3) Recipe adapter  <- recipes/PostgresIdiomRecipes.td
add_custom_command(OUTPUT ${NBP_GENDIR}/PostgresRecipeAdapter.inc
  COMMAND python3 ${NBP_GEN}/backend_recipe_gen.py --profile postgres-recipe-adapter
          --td ${NBP_UNIT_DIR}/recipes/PostgresIdiomRecipes.td
          --tblgen ${NBP_LLVM_TBLGEN} -I ${NBP_BACKENDS_INC}
          -o ${NBP_GENDIR}/PostgresRecipeAdapter.inc
  DEPENDS ${NBP_UNIT_DIR}/recipes/PostgresIdiomRecipes.td
  COMMENT "[] Regenerating PostgreSQL recipe adapter (build product)")

# 4) Projection resolver  <- recipes/PostgresProjectionSchema.td
add_custom_command(OUTPUT ${NBP_GENDIR}/PostgresProjection.inc
  COMMAND python3 ${NBP_GEN}/backend_recipe_gen.py --profile postgres-projection
          --td ${NBP_UNIT_DIR}/recipes/PostgresProjectionSchema.td
          --tblgen ${NBP_LLVM_TBLGEN} -I ${NBP_BACKENDS_INC}
          -o ${NBP_GENDIR}/PostgresProjection.inc
  DEPENDS ${NBP_UNIT_DIR}/recipes/PostgresProjectionSchema.td
  COMMENT "[] Regenerating PostgreSQL projection resolver (build product)")

# 5) DDL carrier builders  <- model/PostgresDdlCarrier.td
add_custom_command(OUTPUT ${NBP_GENDIR}/PgDdlBuilders.inc
  COMMAND python3 ${NBP_GEN}/backend_recipe_gen.py --profile postgres-ddl-builders
          --td ${NBP_UNIT_DIR}/model/PostgresDdlCarrier.td
          --tblgen ${NBP_LLVM_TBLGEN} -I ${NBP_BACKENDS_INC}
          -o ${NBP_GENDIR}/PgDdlBuilders.inc
  DEPENDS ${NBP_UNIT_DIR}/model/PostgresDdlCarrier.td
  COMMENT "[] Regenerating PostgreSQL DDL carrier builders (build product)")

# 6) Build-time recipe modules (never committed even in-tree)
#    <- recipes/PostgresIdiomRecipes.td (+ rails + BackendIdiom.td)
add_custom_command(OUTPUT ${NBP_GENDIR}/postgres_recipes.inc
  COMMAND python3 ${NBP_GEN}/gen_backend_idiom_recipes.py
          --td ${NBP_UNIT_DIR}/recipes/PostgresIdiomRecipes.td
          --tblgen ${NBP_LLVM_TBLGEN} -I ${NBP_BACKENDS_INC}
          --symbol postgres -o ${NBP_GENDIR}/postgres_recipes.inc
  DEPENDS ${NBP_UNIT_DIR}/recipes/PostgresIdiomRecipes.td
          ${NBP_UNIT_DIR}/recipes/PostgresEvidenceIdiomRecipes.td
          ${NBP_UNIT_DIR}/recipes/PostgresTemporalIdiomRecipes.td
          ${NBP_UNIT_DIR}/recipes/PostgresSchemaIdiomRecipes.td
          ${NBP_UNIT_DIR}/recipes/PostgresEffectfulIdiomRecipes.td
          ${NBP_BACKENDS_INC}/BackendIdiom.td
  COMMENT "[] Generating PostgreSQL recipe module (build-time, uncommitted)")

add_custom_target(nbp-generated DEPENDS
  ${NBP_REGISTRY_OUTS}
  ${NBP_GENDIR}/PostgresRecipeBuilders.inc
  ${NBP_GENDIR}/PostgresRecipeAdapter.inc
  ${NBP_GENDIR}/PostgresProjection.inc
  ${NBP_GENDIR}/PgDdlBuilders.inc
  ${NBP_GENDIR}/postgres_recipes.inc)

# --- The library (mirrors the in-tree NeutrinoBackendPostgres) ----------------
add_library(NeutrinoBackendPostgres STATIC
  ${NBP_UNIT_DIR}/GenPostgresSpec.cpp
  ${NBP_UNIT_DIR}/provider/PostgresSpecModel.cpp
  ${NBP_UNIT_DIR}/model/PostgresModel.cpp
  ${NBP_UNIT_DIR}/provider/PostgresRecipeProvider.cpp
  ${NBP_UNIT_DIR}/leaf/PgSqlText.cpp
  ${NBP_UNIT_DIR}/leaf/PgSqlSyntax.cpp
  ${NBP_UNIT_DIR}/harness/PostgresDbTest.cpp)
add_dependencies(NeutrinoBackendPostgres nbp-generated)

# The generated `.inc` come from the build tree; the reviewed carve-out
# (CoordinationEnvelope.sql.inc) + the unit's private role subdirs come from source.
target_include_directories(NeutrinoBackendPostgres PRIVATE
  ${NBP_GENDIR}
  ${CMAKE_CURRENT_SOURCE_DIR}/include
  ${NBP_UNIT_DIR}
  ${NBP_UNIT_DIR}/recipes ${NBP_UNIT_DIR}/model ${NBP_UNIT_DIR}/generated
  ${NBP_UNIT_DIR}/provider ${NBP_UNIT_DIR}/leaf ${NBP_UNIT_DIR}/harness)

# --- Bundled recipe runtime (package-internal per  §5) -------------------
# The C++/LLVM TargetRecipeProvider + recipe runtime NEVER cross the boundary
# (ADR §5, normative). The package BUNDLES them as an OBJECT library whose
# objects are FOLDED into the backend archive via $<TARGET_OBJECTS:> — there is
# NO link edge and NO export target, so the installed targets surface never
# exposes a recipe-runtime name (it is a private implementation detail, not
# public package topology). It does NOT link Neutrino::Recipe from the installed
# public core, which would recreate exactly the forbidden C++ ABI edge. Sources
# are vendored from lib/recipe today (NBP_RECIPE_DIR resolves into the translator
# tree). Relocating them under the package is PENDING work for the second
# clean-clone PR — not something  landed;  is the Solidity  PR.
# The shared recipe runtime is PACKAGE-INTERNAL ( §5). It is materialized
# under the package so a clean clone with the translator tree physically absent
# still builds; the pinned  source contract is the authority for its content.
# MATERIALIZED, not referenced: lib/recipe/*.cpp and
# runtime/include/Neutrino/*.h are real files under the package. There is no
# NBP_RECIPE_DIR indirection and NO source-tree fallback — a fallback lets the
# package build green in-tree while a genuine clean clone fails, which is the
# exact defect this proof exists to rule out.
set(NBP_RUNTIME_DIR "${CMAKE_CURRENT_SOURCE_DIR}")
add_library(nbp_recipe_runtime OBJECT
  ${NBP_RUNTIME_DIR}/lib/recipe/RecipeRuntime.cpp
  ${NBP_RUNTIME_DIR}/lib/recipe/RecipeModule.cpp
  ${NBP_RUNTIME_DIR}/lib/recipe/RecipeInterpreter.cpp
  ${NBP_RUNTIME_DIR}/lib/recipe/RecipeExecutor.cpp
  ${NBP_RUNTIME_DIR}/lib/recipe/RecipeProviderRegistry.cpp)
target_include_directories(nbp_recipe_runtime PRIVATE ${NBP_RUNTIME_DIR}/include ${NBP_LLVM_INCLUDE_DIR})
# Fold the compiled objects into the backend archive — not a linked/exported
# target dependency.
target_sources(NeutrinoBackendPostgres PRIVATE $<TARGET_OBJECTS:nbp_recipe_runtime>)

if(NBP_STANDALONE_CORE)
  # NO C++ ABI EDGE. Neutrino::SpecContract / Neutrino::CodeText are imported
  # targets that the  export deliberately does NOT publish (cppAbiPolicy
  # forbidden, zero publicTargets), so linking them here would both contradict the
  # boundary and fail generation against a real installed core.
  #
  # The package instead COMPILES the pinned package-internal shared-runtime source
  # contract ( neutrino.backend-source-runtime/1), which supplies exactly
  # these units as SOURCES — codetext, the finalized-projection codec, the
  # protocol/startup seam and the recipe runtime. The package is therefore
  # self-contained and links no core target at all.
  if(NOT NBP_SHARED_RUNTIME_SOURCES)
    message(FATAL_ERROR
      "[] standalone build requires the pinned shared-runtime source contract; "
      "no C++ core target may be linked.")
  endif()
  target_sources(NeutrinoBackendPostgres PRIVATE ${NBP_SHARED_RUNTIME_SOURCES})
  target_compile_definitions(NeutrinoBackendPostgres PRIVATE
                             ${NBP_SHARED_RUNTIME_DEFINITIONS})
endif()

# --- Install / export surface (NEW — none exists in-tree) ---------------------
include(GNUInstallDirs)
# ONLY the backend target is exported — the bundled recipe runtime's objects are
# already inside its archive (above), so the installed targets file exposes no
# recipe-runtime name.
install(TARGETS NeutrinoBackendPostgres
        EXPORT NeutrinoBackendPostgresTargets
        ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR})
# Public headers the package exposes (extraction-manifest.json publicHeaders).
# PgDdl.h is NO LONGER public: `pgddl::RawSql` never crosses the serialized
# boundary — only the finalized-projection artifact crosses in and SQL bytes cross
# out — so the header is PACKAGE-INTERNAL and is not installed. Its only non-unit
# includer was the in-process registry entry, which the clean clone does not use.
install(FILES
        ${CMAKE_CURRENT_SOURCE_DIR}/include/Neutrino/GenPostgresSpec.h
        DESTINATION ${CMAKE_INSTALL_INCLUDEDIR}/Neutrino)
install(EXPORT NeutrinoBackendPostgresTargets
        NAMESPACE Neutrino::
        DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/NeutrinoBackendPostgres)

# Emit the export set into the build tree so check_standalone_configure.sh can
# assert the installed targets surface exposes ONLY the backend — proving the
# bundled recipe runtime is not public package topology ( §5).
export(EXPORT NeutrinoBackendPostgresTargets NAMESPACE Neutrino::
       FILE ${CMAKE_CURRENT_BINARY_DIR}/NeutrinoBackendPostgresTargets.cmake)

include(CMakePackageConfigHelpers)
configure_package_config_file(
  ${CMAKE_CURRENT_SOURCE_DIR}/cmake/NeutrinoBackendPostgresConfig.cmake.in
  ${CMAKE_CURRENT_BINARY_DIR}/NeutrinoBackendPostgresConfig.cmake
  INSTALL_DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/NeutrinoBackendPostgres)
install(FILES ${CMAKE_CURRENT_BINARY_DIR}/NeutrinoBackendPostgresConfig.cmake
        DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/NeutrinoBackendPostgres)

# Also install the package descriptor + manifest as package metadata (
# neutrino.backend-package/1 is emitted by ; the extraction manifest ships
# alongside for provenance).
install(FILES ${CMAKE_CURRENT_SOURCE_DIR}/extraction-manifest.json
        DESTINATION ${CMAKE_INSTALL_DATADIR}/NeutrinoBackendPostgres)

# --- Reach-back audit (fail-closed) -------------------------------------------
# Prove no owned file reaches outside the declared package + public-core surface.
add_custom_target(nbp-reachback-audit ALL
  COMMAND python3 ${CMAKE_CURRENT_SOURCE_DIR}/scripts/check_package_reachback.py
          --repo ${CMAKE_CURRENT_SOURCE_DIR}
  COMMENT "[] PostgreSQL package reach-back audit (fail-closed)")

# The DECLARED Forge tool identity for every `requires-forge` CTest row ().
#
# One configured executable + one configured native-library prefix, attached to the tests
# themselves — so a bare `ctest -L acceptance` carries the same identity as `make acceptance`,
# with no shell-profile dependency. Without this, a prebuilt macOS Foundry aborts in dyld
# (`Library not loaded: …/libusb-1.0.0.dylib`) before any conformance is measured on a box whose
# Homebrew prefix is not the default one.
#
# The prefix is DERIVED, never hard-coded: scripts/gates/check_forge_toolchain.py is the single
# authority (honouring -DNEUTRINO_FORGE_LIBRARY_PATH, else `brew --prefix libusb` on Darwin,
# else nothing). macOS SIP strips DYLD_* from a protected process's environment, so the value
# travels in the neutral FORGE_DYLD_LIBRARY_PATH and is re-materialised as DYLD_LIBRARY_PATH
# only where a launcher directly spawns forge.
#
# Override any of these at configure time:
#   -DNEUTRINO_FORGE=/path/to/forge
#   -DNEUTRINO_SOLC=/path/to/solc
#   -DNEUTRINO_FORGE_LIBRARY_PATH=/path/to/dir-containing-the-native-dependency

find_program(NEUTRINO_FORGE NAMES forge
  HINTS "${PROJECT_SOURCE_DIR}/.foundry/bin" ENV FOUNDRY_BIN
  DOC "Foundry `forge` driving the requires-forge acceptance rows")
find_program(NEUTRINO_SOLC NAMES solc
  DOC "Solidity compiler passed to forge as --use")

set(NEUTRINO_FORGE_LIBRARY_PATH "" CACHE STRING
  "Declared native-library prefix for the configured forge (empty = derive it)")

if(NEUTRINO_FORGE_LIBRARY_PATH STREQUAL "")
  execute_process(
    COMMAND python3 "${PROJECT_SOURCE_DIR}/scripts/gates/check_forge_toolchain.py"
            --print-library-path
    OUTPUT_VARIABLE _neutrino_forge_libdir
    OUTPUT_STRIP_TRAILING_WHITESPACE
    RESULT_VARIABLE _neutrino_forge_libdir_rc)
  if(_neutrino_forge_libdir_rc EQUAL 0)
    set(NEUTRINO_FORGE_LIBRARY_PATH "${_neutrino_forge_libdir}" CACHE STRING
      "Declared native-library prefix for the configured forge (empty = derive it)" FORCE)
  endif()
endif()

# The environment every requires-forge test runs under. Applied through the CTest ENVIRONMENT
# property (not an ambient export), so the identity is declared once and is visible in
# `ctest --show-only=json-v1`.
set(NEUTRINO_FORGE_TEST_ENVIRONMENT "")
if(NEUTRINO_FORGE)
  list(APPEND NEUTRINO_FORGE_TEST_ENVIRONMENT "FORGE=${NEUTRINO_FORGE}")
endif()
if(NEUTRINO_SOLC)
  list(APPEND NEUTRINO_FORGE_TEST_ENVIRONMENT "SOLC=${NEUTRINO_SOLC}")
endif()
if(NOT NEUTRINO_FORGE_LIBRARY_PATH STREQUAL "")
  list(APPEND NEUTRINO_FORGE_TEST_ENVIRONMENT
    "FORGE_DYLD_LIBRARY_PATH=${NEUTRINO_FORGE_LIBRARY_PATH}")
endif()

message(STATUS "Forge tool identity: ${NEUTRINO_FORGE} "
  "(native library path: ${NEUTRINO_FORGE_LIBRARY_PATH})")

# The negative probe: with the declared native dependency renamed inside a private copy of the
# closure, the preflight must fail as INFRASTRUCTURE before any conformance step. Skips (77) on a
# box that provisions no forge / no native dependencies.
neutrino_register_test(NAME forge-toolchain-probe
  COMMAND python3
          "${PROJECT_SOURCE_DIR}/scripts/gates/check_forge_toolchain.py" --selftest)
neutrino_register_test_properties(forge-toolchain-probe PROPERTIES
  LABELS "policy;requires-forge;acceptance" SKIP_RETURN_CODE 77
  ENVIRONMENT "${NEUTRINO_FORGE_TEST_ENVIRONMENT}")

# The recorded machine receipt still describes THIS machine (same forge bytes, same native
# dependency digests). Not-applicable (77) on any box the receipt does not record.
file(GLOB _neutrino_forge_receipts
  "${PROJECT_SOURCE_DIR}/docs/testing/forge-toolchain-receipts/*.receipt.json")
foreach(_receipt IN LISTS _neutrino_forge_receipts)
  get_filename_component(_receipt_id "${_receipt}" NAME_WE)
  neutrino_register_test(NAME forge-toolchain-receipt-${_receipt_id}
    COMMAND python3
            "${PROJECT_SOURCE_DIR}/scripts/gates/check_forge_toolchain.py"
            --verify-receipt "${_receipt}")
  neutrino_register_test_properties(forge-toolchain-receipt-${_receipt_id} PROPERTIES
    LABELS "policy;requires-forge;acceptance" SKIP_RETURN_CODE 77
    ENVIRONMENT "${NEUTRINO_FORGE_TEST_ENVIRONMENT}")
endforeach()

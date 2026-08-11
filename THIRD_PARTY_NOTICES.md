# Third-Party Notices

This snapshot is licensed under Apache License 2.0 except where an individual
file or embedded artifact carries a different license notice.

## LLVM and MLIR

The compiler builds against LLVM and MLIR but does not vendor their source.
LLVM is distributed under the Apache License v2.0 with LLVM Exceptions. See
<https://llvm.org/LICENSE.txt>.

## OpenZeppelin EIP-712 pattern

`lib/backends/solidity/ThresholdQuorumAcceptance.sol.inc` records that its
domain-separator cache/rebuild design follows the OpenZeppelin EIP-712 pattern.
OpenZeppelin Contracts is distributed under the MIT License. The embedded
Solidity artifact retains its original SPDX notice. See
<https://github.com/OpenZeppelin/openzeppelin-contracts/blob/v5.0.2/LICENSE>.

## Embedded and generated Solidity artifacts

Generated Solidity, recorded goldens, and test fixtures retain their existing
SPDX identifiers byte-for-byte. Their notices were not replaced by the
repository-level Apache-2.0 license during this historyless publication.

## CMake package configuration helper

`packaging/postgres/cmake/NeutrinoBackendPostgresConfig.cmake.in` uses CMake's
`@PACKAGE_INIT@` expansion from `CMakePackageConfigHelpers.cmake`. CMake is
distributed under the BSD 3-Clause License. See <https://cmake.org/licensing/>.

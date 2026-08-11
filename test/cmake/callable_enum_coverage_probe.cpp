// SPDX-License-Identifier: Apache-2.0
//===- callable_enum_coverage_probe.cpp - enum coverage probe TU ---------===//
//
// A minimal TU that runs the generated CallableKind/CallableModifier coverage
// assertions (SolidityCallableCoverage.inc) exactly as the real build does. The
// callable-enum-alias compile-NEGATIVE test compiles this TU against a TEMP
// copy of the generated enum source into which an ALIAS member has been
// injected, and asserts it FAILS to compile on the position-drift diagnostic —
// proving a hand-edited alias in the generated enum cannot pass coverage.
//
//===----------------------------------------------------------------------===//

#include "SolidityTargetAdapter.h"

#include "SolidityPrinterHandlers.inc"

namespace neutrino {
namespace solidity_model {
#include "SolidityCallableCoverage.inc"
} // namespace solidity_model
} // namespace neutrino

int main() { return 0; }

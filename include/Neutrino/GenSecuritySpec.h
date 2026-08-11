#ifndef NEUTRINO_GENSECURITYSPEC_H
#define NEUTRINO_GENSECURITYSPEC_H

#include "llvm/Support/JSON.h"

#include <string>

namespace neutrino {

// Capability Security Pass, spec-driven (M5  B2, ). Renders the
// domain-aware security.json report from the frozen capability-spec JSON (the
//  contract) instead of ProcedureView — so this renderer holds NO
// ProcedureView and includes no View.h / Analysis.h, joining postgres/solidity/
// slot/views under the renderer include-boundary lock (). Output is
// byte-identical to the ProcedureView path it replaces (committed goldens).
//
// The report and the gate derive from the SAME spec-driven category builder, so
// they cannot disagree: `securityReportFromSpec` renders security.json and
// `specHasSecurityViolations` is the hard-gate predicate over the same
// categories. The registry EmitFn entry (SecurityTarget.cpp) emits the spec via
// `capabilitySpecJson`, re-parses it, and calls these.
std::string securityReportFromSpec(const llvm::json::Object &spec);
bool specHasSecurityViolations(const llvm::json::Object &spec);

} // namespace neutrino

#endif // NEUTRINO_GENSECURITYSPEC_H

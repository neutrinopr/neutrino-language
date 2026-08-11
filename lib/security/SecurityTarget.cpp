//===- SecurityTarget.cpp - the `security` target registry entry --------===//
//
// The public-core `security` target emits the canonical capability-spec
// (`capabilitySpecJson`) and re-parses it, so the actual analysis + rendering
// (`securityReportFromSpec`, GenSecuritySpec.cpp) consumes ONLY the frozen
// capability-spec JSON — no ProcedureView, no Analysis.h/View.h. This TU keeps
// `ProcedureView` solely as the registry EmitFn / gate signature (it is the
// producer/entry, not a renderer). The
// gate (`hasSecurityViolations`, used by neutrino-gen before a gated render)
// and the report derive from the SAME spec-driven categories, so they cannot
// disagree. Output is byte-identical to the prior ProcedureView path (committed
// security goldens).
//
//===----------------------------------------------------------------------===//

#include "Neutrino/GenSecurity.h"
#include "Neutrino/GenSecuritySpec.h"
#include "Neutrino/GenSpec.h"
#include "Neutrino/Validate.h"
#include "SecurityAdmission.h"

#include "llvm/Support/JSON.h"

#include <filesystem>
#include <fstream>
#include <string>
#include <vector>

using namespace neutrino;

std::vector<std::string>
neutrino::emitSecurity(const ProcedureView &view, const Scenario &,
                       const std::string &outDir,
                       const CoordinationPlan &coordinationPlan) {
  namespace fs = std::filesystem;
  fs::create_directories(outDir);

  // The shared adapter emits + re-parses our OWN spec and fails closed (abort,
  // not a user diagnostic) if it does not parse to an object — an internal
  // invariant, off the  throw ratchet ().
  SelfEmittedSpec spec = ingestSelfEmittedSpec(view, coordinationPlan);
  std::string report = securityReportFromSpec(spec.object());

  std::string path = (fs::path(outDir) / "security.json").string();
  std::ofstream(path) << report;
  return {path};
}

bool neutrino::hasSecurityViolations(const ProcedureView &view,
                                     const CoordinationPlan &coordinationPlan) {
  SelfEmittedSpec spec = ingestSelfEmittedSpec(view, coordinationPlan);
  return hasSecurityViolations(spec.object());
}

bool neutrino::hasSecurityViolations(const llvm::json::Object &spec) {
  return !evaluateSecurityForDispatch(spec).authorized();
}

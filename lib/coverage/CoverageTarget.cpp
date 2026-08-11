//===- CoverageTarget.cpp - the `coverage` target registry entry --------===//
//
// The public-core adapter emits and re-parses the canonical capability-spec, so
// coverage analysis consumes only the frozen JSON contract. ProcedureView is
// retained here solely as the registry entry signature, not as report input.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/GenCoverage.h"
#include "Neutrino/GenCoverageSpec.h"
#include "Neutrino/GenSpec.h"
#ifndef NEUTRINO_CORE_ONLY
#include "CoverageBackendMaturity.h"
#endif

#include "llvm/Support/JSON.h"

#include <filesystem>
#include <fstream>
#include <string>
#include <vector>

using namespace neutrino;

std::vector<std::string>
neutrino::emitCoverage(const ProcedureView &view, const Scenario &,
                       const std::string &outDir,
                       const CoordinationPlan &coordinationPlan) {
  namespace fs = std::filesystem;
  fs::create_directories(outDir);

  // The shared adapter emits + re-parses our OWN spec and fails closed (abort,
  // not a user diagnostic) if it does not parse to an object.
  SelfEmittedSpec spec = ingestSelfEmittedSpec(view, coordinationPlan);

#ifdef NEUTRINO_CORE_ONLY
  std::string report = coverageReportFromSpec(spec.object());
#else
  std::string report = coverageReportWithBundledMaturityFromSpec(spec.object());
#endif
  std::string path = (fs::path(outDir) / "coverage.json").string();
  std::ofstream(path) << report;
  return {path};
}

//===- ViewsTarget.cpp - per-participant narrowed views target entry ----===//
//
// Trust lane (T5): the `views` generation target's EmitFn entry. Each declared
// participant gets one `<participant>.json` showing only the slice it is
// responsible for. : the per-view RENDERING is migrated onto the canonical
// spec — this entry emits the spec (`capabilitySpecJson`) and re-parses it, so
// the migrated renderer (`generateParticipantViewsFromSpec`, GenViewsSpec.cpp)
// consumes exactly the frozen external contract () with no View.h and no
// ProcedureView. emitViews keeps ProcedureView solely as the registry EmitFn
// signature (it builds the spec; the Scenario is unused — views are
// scenario-free). See docs/backends/BACKEND_GENERATORS.md.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/GenSpec.h"
#include "Neutrino/GenViews.h"
#include "Neutrino/GenViewsSpec.h"

#include "llvm/Support/JSON.h"

#include <filesystem>
#include <fstream>

using namespace neutrino;

std::vector<std::string>
neutrino::emitViews(const ProcedureView &view, const Scenario &,
                    const std::string &outDir,
                    const CoordinationPlan &coordinationPlan) {
  namespace fs = std::filesystem;
  fs::create_directories(outDir);

  // The shared adapter emits + re-parses our OWN spec and fails closed (abort,
  // not a user diagnostic) if it does not parse to an object — an internal
  // invariant, off the  throw ratchet ().
  SelfEmittedSpec spec = ingestSelfEmittedSpec(view, coordinationPlan);

  std::vector<std::string> written;
  // One narrowed view per declared participant, in spec participant order.
  // Sources without participants emit nothing (no views directory content).
  for (const auto &pv : generateParticipantViewsFromSpec(spec.object())) {
    std::string path = (fs::path(outDir) / (pv.first + ".json")).string();
    std::ofstream(path) << pv.second;
    written.push_back(path);
  }
  return written;
}

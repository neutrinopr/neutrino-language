//===- SlotTarget.cpp - the `slot` target registry entry ----------------===//
//
// The public-core adapter emits and re-parses the canonical capability-spec, so
// slot projection consumes only the frozen JSON contract. ProcedureView is
// retained solely as the registry entry signature.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/GenSlot.h"
#include "Neutrino/GenSlotSpec.h"
#include "Neutrino/GenSpec.h"

#include "llvm/Support/JSON.h"

#include <filesystem>
#include <fstream>
#include <string>
#include <utility>
#include <vector>

std::vector<std::string>
neutrino::emitSlotProject(const ProcedureView &view, const Scenario &,
                          const std::string &outDir,
                          const CoordinationPlan &coordinationPlan) {
  namespace fs = std::filesystem;
  fs::create_directories(outDir);

  // The shared adapter emits + re-parses our OWN spec and fails closed (abort,
  // not a user diagnostic) if it does not parse to an object.
  SelfEmittedSpec spec = ingestSelfEmittedSpec(view, coordinationPlan);

  //  S0-C2R: no build-profile overlay decorates the descriptor. Backend
  // availability is package/target discovery, not agreement content, and the
  // former overlay was folded into the hashed capability descriptor — which made
  // the capability identity depend on the producer's build profile.
  SlotArtifacts files = generateSlotFromSpec(spec.object());

  // D1b: binding-topology.json is emitted only when participants are declared;
  // when they are not, actively remove any stale artifact so reusing an output
  // directory can never leave one from a prior run.
  bool hasBindingTopology = false;
  for (const auto &f : files)
    if (f.name == "binding-topology.json")
      hasBindingTopology = true;
  if (!hasBindingTopology) {
    std::error_code ec;
    fs::remove(fs::path(outDir) / "binding-topology.json", ec);
  }

  std::vector<std::string> written;
  for (const auto &f : files) {
    std::string path = (fs::path(outDir) / f.name).string();
    std::ofstream os(path);
    os << f.content;
    written.push_back(path);
  }
  return written;
}

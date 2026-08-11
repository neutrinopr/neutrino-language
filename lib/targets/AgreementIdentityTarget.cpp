//===- AgreementIdentityTarget.cpp - agreement identity target entry ----===//
//
// The from-MLIR emitter for the portable agreement identity: it computes the
// capability-spec's canonical semantic bytes from the verified view (the SAME
// bytes capabilityHash is computed from) and hands them to the MLIR-free
// identity core (AgreementEnvelope.h). So the from-MLIR and --from-spec paths
// produce byte-identical identity, and identity can never drift from the spec.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/GenAgreementEnvelope.h"

#include "Neutrino/AgreementEnvelope.h"
#include "Neutrino/GenSpec.h"

#include <filesystem>
#include <fstream>

namespace neutrino {

std::string agreementIdentityJson(const ProcedureView &view,
                                  const CoordinationPlan &coordinationPlan) {
  return agreementIdentityFromBytes(
      canonicalSemanticBytes(view, coordinationPlan));
}

std::vector<std::string>
emitAgreementIdentity(const ProcedureView &view, const Scenario &,
                      const std::string &outDir,
                      const CoordinationPlan &coordinationPlan) {
  namespace fs = std::filesystem;
  fs::create_directories(outDir);
  std::string path = (fs::path(outDir) / "agreement-identity.json").string();
  std::ofstream os(path);
  os << agreementIdentityJson(view, coordinationPlan);
  return {path};
}

} // namespace neutrino

#ifndef NEUTRINO_GEN_AGREEMENT_ENVELOPE_H
#define NEUTRINO_GEN_AGREEMENT_ENVELOPE_H

#include "Neutrino/CoordinationPlan.h"
#include "Neutrino/Scenario.h"
#include "Neutrino/View.h"

#include <string>
#include <vector>

namespace neutrino {

// The view-based emitter for the portable agreement identity (). It binds
// the SAME canonical semantic bytes capabilityHash is computed from
// (canonicalSemanticBytes, GenSpec.h) into the domain-separated agreementHash;
// the MLIR-free identity core is in AgreementEnvelope.h.

// The agreement-identity artifact JSON for a verified view (from-MLIR path).
std::string agreementIdentityJson(const ProcedureView &view,
                                  const CoordinationPlan &coordinationPlan);

// EmitFn (target registry): writes agreement-identity.json from the verified
// view. Scenario-free (identity is a function of the source alone).
std::vector<std::string>
emitAgreementIdentity(const ProcedureView &view, const Scenario &,
                      const std::string &outDir,
                      const CoordinationPlan &coordinationPlan);

} // namespace neutrino

#endif // NEUTRINO_GEN_AGREEMENT_ENVELOPE_H

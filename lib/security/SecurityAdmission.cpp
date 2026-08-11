#include "SecurityAdmission.h"

#include "Neutrino/GenSecuritySpec.h"

neutrino::SecurityDispatchDecision
neutrino::evaluateSecurityForDispatch(const llvm::json::Object &spec) {
  return SecurityDispatchDecision(!specHasSecurityViolations(spec));
}

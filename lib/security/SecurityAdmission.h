#ifndef NEUTRINO_SECURITY_ADMISSION_H
#define NEUTRINO_SECURITY_ADMISSION_H

#include "llvm/Support/JSON.h"

namespace neutrino {

// Core-internal pre-dispatch decision. Callers cannot supply an override: a
// hard security violation always produces a refusal before package dispatch.
class SecurityDispatchDecision {
public:
  bool authorized() const { return authorized_; }

private:
  explicit SecurityDispatchDecision(bool authorized)
      : authorized_(authorized) {}

  bool authorized_;

  friend SecurityDispatchDecision
  evaluateSecurityForDispatch(const llvm::json::Object &spec);
};

SecurityDispatchDecision
evaluateSecurityForDispatch(const llvm::json::Object &spec);

} // namespace neutrino

#endif // NEUTRINO_SECURITY_ADMISSION_H

#ifndef NEUTRINO_COVERAGE_BACKEND_MATURITY_H
#define NEUTRINO_COVERAGE_BACKEND_MATURITY_H

#include "llvm/Support/JSON.h"

#include <string>

namespace neutrino {

// Full-profile compatibility overlay. The retained core report deliberately
// contains no claims about production backend availability or maturity.
std::string
coverageReportWithBundledMaturityFromSpec(const llvm::json::Object &spec);

} // namespace neutrino

#endif // NEUTRINO_COVERAGE_BACKEND_MATURITY_H

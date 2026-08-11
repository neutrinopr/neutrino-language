#ifndef NEUTRINO_STR_CASE_H
#define NEUTRINO_STR_CASE_H

#include "llvm/ADT/StringRef.h"

#include <string>

namespace neutrino {

// PascalCase of a snake_case name (splits on '_', capitalizes each part). A
// pure string utility with no ProcedureView / MLIR dependency, split out of
// View.h so a spec-consuming renderer (M5 WP6/) can name contracts/events
// from the spec WITHOUT including View.h. View.h re-includes this so existing
// `pascalCase` callers are unaffected.
std::string pascalCase(llvm::StringRef name);

} // namespace neutrino

#endif // NEUTRINO_STR_CASE_H

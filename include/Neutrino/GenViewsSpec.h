#ifndef NEUTRINO_GENVIEWS_SPEC_H
#define NEUTRINO_GENVIEWS_SPEC_H

#include "llvm/Support/JSON.h"

#include <string>
#include <utility>
#include <vector>

namespace neutrino {

// Render every per-participant narrowed view from the canonical capability spec
// (M5 , the last renderer migrated off ProcedureView). This translation
// unit is View.h-free: it consumes ONLY the spec JSON (the frozen external
// contract, ) — no ProcedureView. Returns [(participantName, viewJson)] in
// spec participant order; output is byte-identical to the ProcedureView path it
// replaces (proved by the fixture gate). See
// docs/backends/BACKEND_GENERATORS.md.
std::vector<std::pair<std::string, std::string>>
generateParticipantViewsFromSpec(const llvm::json::Object &spec);

} // namespace neutrino

#endif // NEUTRINO_GENVIEWS_SPEC_H

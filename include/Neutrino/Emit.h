#ifndef NEUTRINO_EMIT_H
#define NEUTRINO_EMIT_H

#include "mlir/IR/BuiltinOps.h"
#include <string>

namespace neutrino {

// Event choreography: an INSPECTION-only text projection of the IR's expected
// fact ordering (a runtime can compare its emitted facts to this). It is NOT a
// backend artifact — the backends are the spec-derived `neutrino-gen
// --target=postgres|solidity` paths. The naive SQL / coordination-contract
// projections that walked raw MLIR (incl. the buggy no-upsert UPDATE SQL) were
// retired in .
std::string emitEvents(mlir::ModuleOp module);

// Document outline (editor intelligence, D8 / issue ): procedures + their
// declarations with translator-owned source ranges, as deterministic JSON.
// Ranges come from the front-end's op locations (the console renders this; it
// does not re-parse), so invoke on .neu source — ranges are relative to the
// parsed file (a module parsed from .mlir yields .mlir-relative, not
// .neu-source, lines).
std::string emitSymbols(mlir::ModuleOp module);

} // namespace neutrino

#endif // NEUTRINO_EMIT_H

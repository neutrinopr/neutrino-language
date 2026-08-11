#ifndef NEUTRINO_FRONTEND_H
#define NEUTRINO_FRONTEND_H

#include "mlir/IR/BuiltinOps.h"
#include "mlir/IR/MLIRContext.h"
#include "mlir/IR/OwningOpRef.h"
#include "llvm/ADT/StringRef.h"

namespace neutrino {

// Parse Neutrino DSL source into a verified-shape MLIR module. On error, emits
// a diagnostic to llvm::errs() and returns a null OwningOpRef. The DSL source
// surface is `.neu`.
mlir::OwningOpRef<mlir::ModuleOp> parseNeutrinoSource(llvm::StringRef text,
                                                      llvm::StringRef filename,
                                                      mlir::MLIRContext &ctx);

// True when `path` is a Neutrino DSL source file (to be parsed by
// parseNeutrinoSource) rather than MLIR. `.neu` is the one canonical extension;
// it only selects the front-end and never affects semantics or any
// capability/semantic hash.
bool isDslSourcePath(llvm::StringRef path);

} // namespace neutrino

#endif // NEUTRINO_FRONTEND_H

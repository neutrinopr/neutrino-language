#ifndef NEUTRINO_SOURCELOAD_H
#define NEUTRINO_SOURCELOAD_H

#include "mlir/IR/BuiltinOps.h"
#include "mlir/IR/OwningOpRef.h"
#include "llvm/ADT/StringRef.h"

#include <string>

namespace mlir {
class MLIRContext;
} // namespace mlir

namespace neutrino {

// Shared CLI run-context: load an input as Neutrino MLIR (T9 R1 pattern ).
// The artifact tools (neutrino-emit / -gen / -equiv) all route .neu through the
// front-end and parse anything else as textual MLIR; this centralizes that so
// they cannot drift. The loader prints nothing beyond what parseNeutrinoSource
// / parseSourceFile already emit — each caller maps the status to its own exit
// code and message, which differ by tool.
enum class LoadStatus {
  Ok,
  SourceIoError,    // .neu path: file could not be read (see detail)
  SourceParseError, // .neu did not lower to valid IR
  IrParseError,     // textual .mlir did not parse
  IrVerifyError,    // .mlir parsed but failed verification
};

struct LoadResult {
  LoadStatus status;
  std::string detail;                       // the IO error message (SourceIoError)
  mlir::OwningOpRef<mlir::ModuleOp> module;  // valid only when status == Ok
};

// Load inputFile as Neutrino MLIR: .neu are lowered via the front-end
// (routing matches isDslSourcePath); anything else is parsed as textual MLIR
// and verified. The NeutrinoDialect must already be loaded into ctx.
LoadResult loadModule(llvm::StringRef inputFile, mlir::MLIRContext &ctx);

} // namespace neutrino

#endif // NEUTRINO_SOURCELOAD_H

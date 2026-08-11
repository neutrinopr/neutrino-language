//===- SourceLoad.cpp - shared CLI source/IR loading ---------------------===//
//
// T9 R1 pattern  (shared run context): the artifact tools repeated the same
// "load .neu via the front-end, else parse textual .mlir and verify"
// block. Centralize it here, byte-for-byte, returning a staged status so each
// tool maps it to its own (differing) exit codes and messages.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/SourceLoad.h"

#include "Neutrino/Frontend.h"

#include "mlir/IR/Diagnostics.h"
#include "mlir/IR/MLIRContext.h"
#include "mlir/IR/Verifier.h"
#include "mlir/Parser/Parser.h"
#include "llvm/Support/MemoryBuffer.h"

neutrino::LoadResult neutrino::loadModule(llvm::StringRef inputFile,
                                          mlir::MLIRContext &ctx) {
  LoadResult r;
  // Capture the FIRST error diagnostic (front-end typing or op verifier) so a
  // tool can surface its machine code — e.g. `[expr.type]` — rather than a
  // generic load-stage code (). The handler doesn't consume the diagnostic,
  // so the default handler still prints it.
  std::string firstError;
  mlir::ScopedDiagnosticHandler capture(&ctx, [&](mlir::Diagnostic &d) {
    if (d.getSeverity() == mlir::DiagnosticSeverity::Error &&
        firstError.empty())
      firstError = d.str();
    return mlir::failure();
  });
  auto withDetail = [&](LoadResult res) {
    if (res.status != LoadStatus::Ok && res.detail.empty())
      res.detail = firstError;
    return res;
  };
  if (isDslSourcePath(inputFile)) {
    auto buf = llvm::MemoryBuffer::getFileOrSTDIN(inputFile);
    if (std::error_code ec = buf.getError()) {
      r.status = LoadStatus::SourceIoError;
      r.detail = ec.message();
      return r;
    }
    r.module = parseNeutrinoSource((*buf)->getBuffer(), inputFile, ctx);
    r.status = r.module ? LoadStatus::Ok : LoadStatus::SourceParseError;
    return withDetail(std::move(r));
  }
  r.module = mlir::parseSourceFile<mlir::ModuleOp>(inputFile, &ctx);
  if (!r.module) {
    r.status = LoadStatus::IrParseError;
    return withDetail(std::move(r));
  }
  if (mlir::failed(mlir::verify(r.module.get().getOperation()))) {
    r.status = LoadStatus::IrVerifyError;
    r.module = nullptr; // discard the invalid module
    return withDetail(std::move(r));
  }
  r.status = LoadStatus::Ok;
  return r;
}

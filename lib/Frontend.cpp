//===- Frontend.cpp - .neu source -> Neutrino MLIR --------------------===//
//
//===----------------------------------------------------------------------===//

#include "Neutrino/Frontend.h"
#include "FrontendParser.h"
#include "Neutrino/Lexer.h"

using namespace mlir;

OwningOpRef<ModuleOp> neutrino::parseNeutrinoSource(llvm::StringRef text,
                                                    llvm::StringRef filename,
                                                    MLIRContext &ctx) {
  frontend::Parser parser(logicalLines(text), filename, ctx);
  return parser.parse();
}

bool neutrino::isDslSourcePath(llvm::StringRef path) {
  return path.endswith(".neu");
}

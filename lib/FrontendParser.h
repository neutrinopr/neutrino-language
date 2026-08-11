//===- FrontendParser.h - Private .neu parser state ---------------------===//
//
//===----------------------------------------------------------------------===//

#ifndef NEUTRINO_FRONTEND_PARSER_H
#define NEUTRINO_FRONTEND_PARSER_H

#include "Neutrino/ExprAttr.h"
#include "Neutrino/Lexer.h"
#include "Neutrino/ValueModel.h"

#include "mlir/IR/Builders.h"
#include "mlir/IR/BuiltinOps.h"
#include "mlir/IR/Location.h"
#include "llvm/ADT/SmallVector.h"
#include "llvm/ADT/StringMap.h"
#include "llvm/ADT/StringSet.h"
#include "llvm/ADT/Twine.h"

#include <cstddef>
#include <string>
#include <vector>

namespace neutrino::frontend {

class Parser {
public:
  Parser(std::vector<Line> lines, llvm::StringRef filename,
         mlir::MLIRContext &ctx);

  mlir::OwningOpRef<mlir::ModuleOp> parse();

private:
  std::vector<Line> lines;
  std::string filename;
  mlir::MLIRContext &ctx;
  mlir::OpBuilder builder;
  size_t pos = 0;
  llvm::StringSet<> explicitParticipants;

  mlir::Location loc();
  mlir::Location locAt(int line);
  mlir::Location locSpan(int startLine, int endLine);
  const Line &cur();

  mlir::OwningOpRef<mlir::ModuleOp> err(int line, const llvm::Twine &msg);
  mlir::LogicalResult fail(int line, const llvm::Twine &msg);

  mlir::StringAttr str(llvm::StringRef s);
  mlir::Type valueType();
  ValueCategory catOf(mlir::Value v);
  mlir::LogicalResult buildExprAttr(llvm::StringRef text, llvm::StringRef what,
                                    int line,
                                    const llvm::StringMap<mlir::Value> &defined,
                                    bool guard, ExprAttr &out);

  mlir::LogicalResult parseValue(llvm::StringRef tok, int line, bool &isRef,
                                 std::string &out);
  mlir::LogicalResult quotedStrings(llvm::StringRef t, int line,
                                    llvm::SmallVectorImpl<std::string> &out);

  mlir::LogicalResult parseProcedure();
  mlir::LogicalResult parseInput(llvm::StringRef t, int line,
                                 llvm::StringMap<mlir::Value> &defined);
  mlir::LogicalResult parseCompute(llvm::StringRef t, int line,
                                   llvm::StringMap<mlir::Value> &defined);
  mlir::LogicalResult parseParticipant();
  mlir::LogicalResult parseAllow();
  mlir::LogicalResult parseAttest(llvm::StringMap<mlir::Value> &defined);
  mlir::LogicalResult parseEntry(llvm::StringMap<mlir::Value> &defined);
};

} // namespace neutrino::frontend

#endif // NEUTRINO_FRONTEND_PARSER_H

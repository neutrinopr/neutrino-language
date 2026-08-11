#ifndef NEUTRINO_EXPR_ATTR_H
#define NEUTRINO_EXPR_ATTR_H

#include "Neutrino/Expr.h"
#include "Neutrino/NeutrinoDialect.h"
#include "llvm/ADT/ArrayRef.h"
#include "llvm/ADT/StringMap.h"

#include <string>

namespace neutrino {

// Bridge the leaf typed AST (ExprNode, name-bound) and the in-IR structured
// attribute (#neutrino.expr, ), which is SSA-slot-bound. `toExprAttr`
// lowers a TYPED ExprNode into the attribute, mapping each var NAME to its
// dependency SLOT via `slotOf` (name -> index into the owning op's deps).
// `toExprNode` reconstructs the ExprNode, resolving each var SLOT back to its
// symbol via `depSyms` (deps[slot] -> name) and restoring the node's dtype — so
// a consumer reads the already-typed, name-resolved AST without re-inferring.
ExprAttr toExprAttr(const ExprNode &n, mlir::MLIRContext *ctx,
                    const llvm::StringMap<int64_t> &slotOf);
ExprPtr toExprNode(ExprAttr attr, llvm::ArrayRef<std::string> depSyms);

// The distinct dependency slots referenced by any `var` leaf in `attr`, for the
// op verifier's bijection check.
void collectSlots(ExprAttr attr, llvm::SmallVectorImpl<int64_t> &out);

} // namespace neutrino

#endif // NEUTRINO_EXPR_ATTR_H

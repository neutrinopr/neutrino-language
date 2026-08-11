//===- ExprAttr.cpp - ExprNode <-> #neutrino.expr bridge () -----------===//
//
// One conversion between the leaf typed AST (ExprNode, name-bound) and the
// in-IR structured attribute (#neutrino.expr, SSA-slot-bound). The frontend
// builds the attribute from a typed ExprNode; viewOf and the verifier read it
// back. Var leaves are bound to a dependency SLOT (index into the owning op's
// deps), not a name — the name is resolved from the slot at projection time, so
// structure + typing + the SSA binding live in the IR and no consumer re-parses
// or re-infers.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/ExprAttr.h"

#include "Neutrino/ValueModel.h"
#include "llvm/ADT/SmallVector.h"

using namespace mlir;

namespace neutrino {

ExprAttr toExprAttr(const ExprNode &n, MLIRContext *ctx,
                    const llvm::StringMap<int64_t> &slotOf) {
  llvm::SmallVector<ExprAttr> children;
  std::string kind, name, binop;
  int64_t num = 0, slot = -1;
  switch (n.kind) {
  case ExprNode::Num:
    kind = "num";
    num = n.num;
    break;
  case ExprNode::Var:
    kind = "var";
    // SSA-bind the leaf to its dependency slot; a name absent from the deps
    // maps to -1 and the op verifier rejects it.
    slot = slotOf.count(n.name) ? slotOf.lookup(n.name) : -1;
    break;
  case ExprNode::Bin:
    kind = "bin";
    binop = std::string(1, n.op);
    children.push_back(toExprAttr(*n.lhs, ctx, slotOf));
    children.push_back(toExprAttr(*n.rhs, ctx, slotOf));
    break;
  case ExprNode::Cmp:
    kind = "cmp";
    name = n.name;
    children.push_back(toExprAttr(*n.lhs, ctx, slotOf));
    children.push_back(toExprAttr(*n.rhs, ctx, slotOf));
    break;
  case ExprNode::Call:
    kind = "call";
    name = n.name;
    for (const auto &a : n.args)
      children.push_back(toExprAttr(*a, ctx, slotOf));
    break;
  }
  return ExprAttr::get(ctx, kind, categoryName(n.dtype).str(), num, slot, name,
                       binop, children);
}

ExprPtr toExprNode(ExprAttr attr, llvm::ArrayRef<std::string> depSyms) {
  auto n = std::make_unique<ExprNode>();
  n->dtype = categoryFromName(attr.getDtype());
  llvm::StringRef kind = attr.getKind();
  llvm::ArrayRef<ExprAttr> kids = attr.getChildren();
  if (kind == "num") {
    n->kind = ExprNode::Num;
    n->num = attr.getNum();
  } else if (kind == "var") {
    n->kind = ExprNode::Var;
    int64_t slot = attr.getSlot();
    n->name = (slot >= 0 && slot < (int64_t)depSyms.size()) ? depSyms[slot]
                                                            : std::string();
  } else if (kind == "bin") {
    n->kind = ExprNode::Bin;
    n->op = attr.getBinop().empty() ? 0 : attr.getBinop()[0];
    n->lhs = toExprNode(kids[0], depSyms);
    n->rhs = toExprNode(kids[1], depSyms);
  } else if (kind == "cmp") {
    n->kind = ExprNode::Cmp;
    n->name = attr.getName().str();
    n->lhs = toExprNode(kids[0], depSyms);
    n->rhs = toExprNode(kids[1], depSyms);
  } else if (kind == "call") {
    n->kind = ExprNode::Call;
    n->name = attr.getName().str();
    for (ExprAttr c : kids)
      n->args.push_back(toExprNode(c, depSyms));
  }
  return n;
}

void collectSlots(ExprAttr attr, llvm::SmallVectorImpl<int64_t> &out) {
  if (attr.getKind() == "var")
    out.push_back(attr.getSlot());
  for (ExprAttr c : attr.getChildren())
    collectSlots(c, out);
}

} // namespace neutrino

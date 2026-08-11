// SPDX-License-Identifier: Apache-2.0
//===- ExprAttrTest.cpp -  recursive expr-attribute round-trip spike --===//
//
// De-risk (architect condition on ): prove the self-referential
// #neutrino.expr<…> AttrDef prints, parses back, and verifies on the pinned
// LLVM 15 — on a genuinely nested expression, round(a*b/100 - 0 + 1, 2).
//
//===----------------------------------------------------------------------===//

#include "Neutrino/NeutrinoDialect.h"

#include "mlir/AsmParser/AsmParser.h"
#include "mlir/IR/MLIRContext.h"
#include "llvm/Support/raw_ostream.h"
#include "gtest/gtest.h"

using namespace mlir;
using namespace neutrino;

namespace {

ExprAttr num(MLIRContext *c, int64_t n) {
  return ExprAttr::get(c, "num", "decimal", n, -1, "", "", {});
}
ExprAttr var(MLIRContext *c, int64_t slot) {
  return ExprAttr::get(c, "var", "money", 0, slot, "", "", {});
}
ExprAttr bin(MLIRContext *c, llvm::StringRef op, ExprAttr l, ExprAttr r) {
  return ExprAttr::get(c, "bin", "money", 0, -1, "", op, {l, r});
}

// round(dep0*dep1/100 - 0 + 1, 2)
ExprAttr buildNested(MLIRContext *c) {
  ExprAttr mul = bin(c, "*", var(c, 0), var(c, 1));
  ExprAttr div = bin(c, "/", mul, num(c, 100));
  ExprAttr sub = bin(c, "-", div, num(c, 0));
  ExprAttr add = bin(c, "+", sub, num(c, 1));
  return ExprAttr::get(c, "call", "money", 0, -1, "round", "",
                       {add, num(c, 2)});
}

TEST(ExprAttr, NestedRoundTrips) {
  MLIRContext ctx;
  ctx.loadDialect<NeutrinoDialect>();

  ExprAttr e = buildNested(&ctx);
  ASSERT_TRUE(e);

  std::string text;
  llvm::raw_string_ostream os(text);
  Attribute(e).print(os);
  os.flush();

  // It prints as the dialect attribute.
  EXPECT_NE(text.find("#neutrino.expr"), std::string::npos);

  // Parse the printed form back; uniquing makes structural equality pointer
  // equality, so a correct round-trip is exactly attribute equality.
  Attribute parsed = parseAttribute(text, &ctx);
  ASSERT_TRUE(parsed);
  EXPECT_EQ(parsed, Attribute(e));
}

TEST(ExprAttr, VerifierRejectsBadArity) {
  MLIRContext ctx;
  ctx.loadDialect<NeutrinoDialect>();
  // A bin node with the wrong child count must fail verification. getChecked
  // routes through ExprAttr::verify and returns null on failure.
  ExprAttr bad = ExprAttr::getChecked(
      [&] { return emitError(UnknownLoc::get(&ctx)); }, &ctx, "bin", "money", 0,
      -1, "", "+", {var(&ctx, 0)});
  EXPECT_FALSE(bad);
}

} // namespace

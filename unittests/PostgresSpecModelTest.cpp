// SPDX-License-Identifier: Apache-2.0
//===- PostgresSpecModelTest.cpp - PG decode-primitive unit tests ---------===//
//
// The decode/model-preparation primitives of the PostgreSQL leaf
// (PostgresSpecModel.cpp, ): value- type mapping, SQL escaping/quoting,
// operand lowering, and required-field access. Split out of the 720-line
// renderer, they are pure and directly assertable here rather than only through
// end-to-end SQL goldens. See docs/testing/TESTING.md.
//
//===----------------------------------------------------------------------===//

#include "PostgresSpecInternal.h"

#include "Neutrino/Expr.h"

#include "gtest/gtest.h"

using namespace neutrino;
using namespace neutrino::postgres_detail;

namespace {

TEST(PostgresSqlType, MoneyAndDecimalAreBigintElseText) {
  EXPECT_EQ(sqlType("money"), "bigint");
  EXPECT_EQ(sqlType("decimal"), "bigint");
  EXPECT_EQ(sqlType("string"), "text");
  EXPECT_EQ(sqlType("party"), "text");
}

TEST(PostgresSqlEsc, DoublesSingleQuotesForSafeLiterals) {
  EXPECT_EQ(sqlEsc("plain"), "plain");
  EXPECT_EQ(sqlEsc("O'Brien"), "O''Brien");
  EXPECT_EQ(sqlQuote("x"), "'x'");
  EXPECT_EQ(sqlQuote("O'Brien"), "'O''Brien'");
}

TEST(PostgresOperandSql, LiteralIsQuotedRefIsInputOrComputePrefixed) {
  llvm::json::Object lit{{"kind", "literal"}, {"value", "USD"}};
  EXPECT_EQ(operandSql(lit, {}), "'USD'");

  llvm::json::Object ref{{"kind", "ref"}, {"value", "amount"}};
  EXPECT_EQ(operandSql(ref, {"amount"}), "p_amount"); // a declared input -> p_
  EXPECT_EQ(operandSql(ref, {}), "v_amount"); // otherwise a compute -> v_
}

TEST(PostgresObj, ReturnsObjectOrThrowsSpecAst) {
  llvm::json::Value valid = llvm::json::Object{{"a", 1}};
  EXPECT_NO_THROW(obj(&valid, "thing"));

  llvm::json::Value notObject = llvm::json::Value(42);
  EXPECT_THROW(obj(&notObject, "thing"),
               ExprError);                        // valid JSON, not an object
  EXPECT_THROW(obj(nullptr, "thing"), ExprError); // missing field
}

} // namespace

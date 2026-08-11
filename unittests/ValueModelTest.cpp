// SPDX-License-Identifier: Apache-2.0
//===- ValueModelTest.cpp - unit tests for the typed value model () ---===//
//
// The value model (include/Neutrino/ValueModel.h) is the single source of truth
// for value-type classification, consumed by the frontend, verifier, scenario
// validation, and every backend. It is pure and total, so it belongs in the C++
// unit layer — asserted directly here rather than only indirectly through the
// CLI. See docs/testing/TESTING.md (§ C++ unit tests).
//
//===----------------------------------------------------------------------===//

#include "Neutrino/ValueModel.h"

#include "gtest/gtest.h"

using namespace neutrino;

namespace {

TEST(ValueModel, GovernedTypesClassifyToTheirCategory) {
  EXPECT_EQ(classifyValueType("money"), ValueCategory::Money);
  EXPECT_EQ(classifyValueType("decimal"), ValueCategory::Decimal);
  EXPECT_EQ(classifyValueType("party"), ValueCategory::Party);
  EXPECT_EQ(classifyValueType("currency"), ValueCategory::Currency);
  EXPECT_EQ(classifyValueType("evidence"), ValueCategory::Evidence);
  EXPECT_EQ(classifyValueType("string"), ValueCategory::String);
}

TEST(ValueModel, NumericSpellingsFoldToDecimal) {
  // number/int/integer/uint are alternate spellings of the numeric category,
  // preserving the historical isNumericType set exactly (money + these).
  for (const char *alias : {"number", "int", "integer", "uint"})
    EXPECT_EQ(classifyValueType(alias), ValueCategory::Decimal) << alias;
}

TEST(ValueModel, UnknownTypeIsExtensionNotAFailure) {
  // Total: any name outside the governed set classifies as Extension (accepted
  // verbatim, no type-specific semantics) — it never fails.
  EXPECT_EQ(classifyValueType("timestamp"), ValueCategory::Extension);
  EXPECT_EQ(classifyValueType(""), ValueCategory::Extension);
  EXPECT_EQ(classifyValueType("Money"),
            ValueCategory::Extension); // case-sensitive
}

TEST(ValueModel, IsNumericCategoryIsExactlyMoneyAndDecimal) {
  EXPECT_TRUE(isNumericCategory(ValueCategory::Money));
  EXPECT_TRUE(isNumericCategory(ValueCategory::Decimal));
  EXPECT_FALSE(isNumericCategory(ValueCategory::Party));
  EXPECT_FALSE(isNumericCategory(ValueCategory::Currency));
  EXPECT_FALSE(isNumericCategory(ValueCategory::Evidence));
  EXPECT_FALSE(isNumericCategory(ValueCategory::String));
  EXPECT_FALSE(isNumericCategory(ValueCategory::Extension));
}

TEST(ValueModel, IsCanonicalCategoryIsEverythingButExtension) {
  for (ValueCategory c : governedCategories())
    EXPECT_TRUE(isCanonicalCategory(c)) << categoryName(c).str();
  EXPECT_FALSE(isCanonicalCategory(ValueCategory::Extension));
}

TEST(ValueModel, GovernedCategoriesAreTheSixCanonicalTypesInOrder) {
  llvm::ArrayRef<ValueCategory> g = governedCategories();
  ASSERT_EQ(g.size(), 6u);
  EXPECT_EQ(g[0], ValueCategory::Money);
  EXPECT_EQ(g[1], ValueCategory::Decimal);
  EXPECT_EQ(g[2], ValueCategory::Party);
  EXPECT_EQ(g[3], ValueCategory::Currency);
  EXPECT_EQ(g[4], ValueCategory::Evidence);
  EXPECT_EQ(g[5], ValueCategory::String);
}

TEST(ValueModel, CategoryNameIsStableLowercaseAndRoundTrips) {
  // categoryName is the machine-readable identity; for the governed types it
  // must round-trip back through classifyValueType.
  for (ValueCategory c : governedCategories()) {
    llvm::StringRef name = categoryName(c);
    EXPECT_FALSE(name.empty());
    EXPECT_EQ(name.lower(), name.str()); // already lowercase
    EXPECT_EQ(classifyValueType(name), c) << name.str();
  }
  EXPECT_EQ(categoryName(ValueCategory::Extension), "extension");
}

} // namespace

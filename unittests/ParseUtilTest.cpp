// SPDX-License-Identifier: Apache-2.0
//===- ParseUtilTest.cpp - unit tests for the pure front-end scanners -----===//
//
// ParseUtil (include/Neutrino/ParseUtil.h) holds the front-end's pure
// token/expression scanning — no MLIR, no parser state, no diagnostics. That
// makes it exactly the "CTest/lit doesn't fit" layer the C++ unit tier is for
// (): the compute-dependency extraction, value-token classification,
// quoted- string collection, block-header split, and the
// `allow`-grammar/version scanners, asserted directly. See
// docs/testing/TESTING.md.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/ParseUtil.h"

#include "llvm/ADT/SmallVector.h"

#include "gtest/gtest.h"

using namespace neutrino;

namespace {

TEST(ComputeDeps, FirstAppearanceOrderDeduped) {
  EXPECT_EQ(computeDeps("subsidy_rate * amount"),
            (std::vector<std::string>{"subsidy_rate", "amount"}));
  EXPECT_EQ(computeDeps("a + a + b"), (std::vector<std::string>{"a", "b"}));
  EXPECT_TRUE(computeDeps("42 * 100").empty());
}

TEST(ComputeDeps, FunctionCallNamesAreExcludedButArgumentsKept) {
  // An identifier immediately followed by '(' is a call, not an operand.
  EXPECT_EQ(computeDeps("min(a, b) + c"),
            (std::vector<std::string>{"a", "b", "c"}));
  // Whitespace between the name and '(' still counts as a call.
  EXPECT_EQ(computeDeps("floor (x)"), (std::vector<std::string>{"x"}));
}

TEST(ParseValueToken, QuotedLiteral) {
  bool isRef = true;
  std::string out;
  EXPECT_TRUE(parseValueToken("  \"USD\" ", isRef, out));
  EXPECT_FALSE(isRef);
  EXPECT_EQ(out, "USD");
  EXPECT_TRUE(parseValueToken("\"\"", isRef, out));
  EXPECT_EQ(out, "");
}

TEST(ParseValueToken, Reference) {
  bool isRef = false;
  std::string out;
  EXPECT_TRUE(parseValueToken("%amount", isRef, out));
  EXPECT_TRUE(isRef);
  EXPECT_EQ(out, "amount");
}

TEST(ParseValueToken, NeitherIsRejected) {
  bool isRef = false;
  std::string out;
  EXPECT_FALSE(parseValueToken("amount", isRef, out)); // bare word
  EXPECT_FALSE(parseValueToken("%", isRef, out));      // lone sigil
  EXPECT_FALSE(parseValueToken("\"unterminated", isRef, out));
}

TEST(CollectQuotedStrings, LeftToRightAndUnterminatedFails) {
  llvm::SmallVector<std::string> out;
  EXPECT_TRUE(collectQuotedStrings("allow \"acme\" with \"globex\"", out));
  EXPECT_EQ(out, (llvm::SmallVector<std::string>{"acme", "globex"}));

  out.clear();
  EXPECT_FALSE(collectQuotedStrings("\"open but not closed", out));
}

TEST(SplitBlockHeader, RequiresTrailingBrace) {
  llvm::SmallVector<llvm::StringRef> words;
  EXPECT_TRUE(splitBlockHeader("input amount money {", words));
  EXPECT_EQ(words.size(), 3u);
  EXPECT_EQ(words[0], "input");
  EXPECT_EQ(words[2], "money");

  words.clear();
  EXPECT_FALSE(splitBlockHeader("input amount money", words)); // no '{'
}

TEST(AllowGrammar, TakeQuotedWordAndConsumeKeywordAdvanceInPlace) {
  llvm::StringRef s = "  \"acme\" with \"globex\"";
  std::string word;
  ASSERT_TRUE(takeQuotedWord(s, word));
  EXPECT_EQ(word, "acme");
  ASSERT_TRUE(consumeKeyword(s, "with"));
  ASSERT_TRUE(takeQuotedWord(s, word));
  EXPECT_EQ(word, "globex");
  EXPECT_TRUE(s.trim().empty());
}

TEST(AllowGrammar, WrongConnectiveDoesNotParse) {
  llvm::StringRef s = "\"a\" banana \"b\"";
  std::string word;
  ASSERT_TRUE(takeQuotedWord(s, word));
  EXPECT_FALSE(
      consumeKeyword(s, "with")); // typoed connective fails the grammar
}

TEST(UnquoteVersionToken, QuotedBareAndUnbalanced) {
  llvm::StringRef v;
  EXPECT_TRUE(unquoteVersionToken("\"1.2.3\"", v));
  EXPECT_EQ(v, "1.2.3");
  EXPECT_TRUE(unquoteVersionToken("1.2.3", v)); // bare passes through
  EXPECT_EQ(v, "1.2.3");
  EXPECT_FALSE(unquoteVersionToken("\"1.2.3", v)); // one stray quote
  EXPECT_FALSE(unquoteVersionToken("1.2.3\"", v));
}

} // namespace

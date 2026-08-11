// SPDX-License-Identifier: Apache-2.0
//===- JsonUtilTest.cpp - unit tests for the shared JSON/hash primitives --===//
//
// jsonEscape + sha256Hex (include/Neutrino/JsonUtil.h) are the canonical leaf
// primitives behind the hand-rolled structural renderers and the
// capability-spec identity hash. Byte-exactness matters (fixture stability,
// cross-language hash agreement with the Python validators), so they are
// asserted directly here rather than only through a rendered artifact. See
// docs/testing/TESTING.md.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/JsonUtil.h"

#include "gtest/gtest.h"

using namespace neutrino;

namespace {

TEST(JsonEscape, PlainTextPassesThroughUnchanged) {
  EXPECT_EQ(jsonEscape(""), "");
  EXPECT_EQ(jsonEscape("acme.merchant_balance"), "acme.merchant_balance");
  EXPECT_EQ(jsonEscape("USD 100"), "USD 100");
}

TEST(JsonEscape, MandatoryEscapes) {
  EXPECT_EQ(jsonEscape("\""), "\\\"");
  EXPECT_EQ(jsonEscape("\\"), "\\\\");
  EXPECT_EQ(jsonEscape("a\"b\\c"), "a\\\"b\\\\c");
}

TEST(JsonEscape, ShortFormControlCharacters) {
  EXPECT_EQ(jsonEscape("\b"), "\\b");
  EXPECT_EQ(jsonEscape("\f"), "\\f");
  EXPECT_EQ(jsonEscape("\n"), "\\n");
  EXPECT_EQ(jsonEscape("\r"), "\\r");
  EXPECT_EQ(jsonEscape("\t"), "\\t");
  EXPECT_EQ(jsonEscape("line1\nline2"), "line1\\nline2");
}

TEST(JsonEscape, OtherC0ControlsBecomeUnicodeEscapes) {
  EXPECT_EQ(jsonEscape(llvm::StringRef("\x00", 1)), "\\u0000");
  EXPECT_EQ(jsonEscape("\x01"), "\\u0001");
  EXPECT_EQ(jsonEscape("\x1f"), "\\u001f");
}

TEST(JsonEscape, HighBytesPassThroughVerbatim) {
  // 0x20+ (incl. UTF-8 continuation bytes) is not escaped; only C0 controls,
  // quote, and backslash are.
  EXPECT_EQ(jsonEscape("\x7f"), "\x7f");
  EXPECT_EQ(jsonEscape("café"), "café"); // UTF-8 bytes unchanged
}

TEST(Sha256Hex, KnownVectors) {
  // NIST/RFC-6234 test vectors; lowercase hex, 64 chars.
  EXPECT_EQ(sha256Hex(""),
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
  EXPECT_EQ(sha256Hex("abc"),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
}

TEST(Sha256Hex, ShapeAndSensitivity) {
  std::string h = sha256Hex("neutrino");
  EXPECT_EQ(h.size(), 64u);
  EXPECT_EQ(h.find_first_not_of("0123456789abcdef"), std::string::npos);
  // Distinct inputs -> distinct digests (avalanche on a one-char change).
  EXPECT_NE(sha256Hex("neutrino"), sha256Hex("neutrini"));
  // Embedded NULs are hashed (StringRef carries length, not C-string).
  EXPECT_NE(sha256Hex(llvm::StringRef("a\0b", 3)), sha256Hex("a"));
}

TEST(RequiredJsonAccess, StringPositiveMissingAndWrongType) {
  llvm::json::Object obj;
  obj["procedure"] = "coordinate_payment";
  obj["inputs"] = llvm::json::Array{};

  llvm::Expected<llvm::StringRef> procedure =
      requiredString(obj, "procedure", "capability-spec");
  ASSERT_TRUE(static_cast<bool>(procedure));
  EXPECT_EQ(*procedure, "coordinate_payment");

  llvm::Expected<llvm::StringRef> missing =
      requiredString(obj, "missing", "capability-spec");
  ASSERT_FALSE(static_cast<bool>(missing));
  EXPECT_EQ(llvm::toString(missing.takeError()),
            "capability-spec: missing/invalid missing");

  llvm::Expected<llvm::StringRef> wrongType =
      requiredString(obj, "inputs", "capability-spec");
  ASSERT_FALSE(static_cast<bool>(wrongType));
  EXPECT_EQ(llvm::toString(wrongType.takeError()),
            "capability-spec: missing/invalid inputs");
}

TEST(RequiredJsonAccess, ArrayPositiveMissingAndWrongType) {
  llvm::json::Object obj;
  obj["inputs"] = llvm::json::Array{};
  obj["procedure"] = "coordinate_payment";

  llvm::Expected<const llvm::json::Array *> inputs =
      requiredArray(obj, "inputs", "capability-spec");
  ASSERT_TRUE(static_cast<bool>(inputs));
  EXPECT_TRUE((*inputs)->empty());

  llvm::Expected<const llvm::json::Array *> missing =
      requiredArray(obj, "effects", "capability-spec");
  ASSERT_FALSE(static_cast<bool>(missing));
  EXPECT_EQ(llvm::toString(missing.takeError()),
            "capability-spec: missing/invalid effects");

  llvm::Expected<const llvm::json::Array *> wrongType =
      requiredArray(obj, "procedure", "capability-spec");
  ASSERT_FALSE(static_cast<bool>(wrongType));
  EXPECT_EQ(llvm::toString(wrongType.takeError()),
            "capability-spec: missing/invalid procedure");
}

TEST(RequiredJsonAccess, ObjectPositiveMissingAndWrongType) {
  llvm::json::Object obj;
  obj["lifecycle"] = llvm::json::Object{};
  obj["inputs"] = llvm::json::Array{};

  llvm::Expected<const llvm::json::Object *> lifecycle =
      requiredObject(obj, "lifecycle", "capability-spec");
  ASSERT_TRUE(static_cast<bool>(lifecycle));
  EXPECT_TRUE((*lifecycle)->empty());

  llvm::Expected<const llvm::json::Object *> missing =
      requiredObject(obj, "terminalStates", "capability-spec");
  ASSERT_FALSE(static_cast<bool>(missing));
  EXPECT_EQ(llvm::toString(missing.takeError()),
            "capability-spec: missing/invalid terminalStates");

  llvm::Expected<const llvm::json::Object *> wrongType =
      requiredObject(obj, "inputs", "capability-spec");
  ASSERT_FALSE(static_cast<bool>(wrongType));
  EXPECT_EQ(llvm::toString(wrongType.takeError()),
            "capability-spec: missing/invalid inputs");
}

TEST(RequiredJsonAccess, LifecycleSuccessPositiveMissingAndWrongType) {
  llvm::json::Object spec;
  llvm::json::Object terminalStates;
  terminalStates["success"] = "CLOSED";
  llvm::json::Object lifecycle;
  lifecycle["terminalStates"] = std::move(terminalStates);
  spec["lifecycle"] = std::move(lifecycle);

  llvm::Expected<llvm::StringRef> success =
      requiredLifecycleSuccessTerminal(spec, "projection");
  ASSERT_TRUE(static_cast<bool>(success));
  EXPECT_EQ(*success, "CLOSED");

  llvm::json::Object missingSuccess;
  missingSuccess["lifecycle"] =
      llvm::json::Object{{"terminalStates", llvm::json::Object{}}};
  llvm::Expected<llvm::StringRef> missing =
      requiredLifecycleSuccessTerminal(missingSuccess, "projection");
  ASSERT_FALSE(static_cast<bool>(missing));
  EXPECT_EQ(llvm::toString(missing.takeError()),
            "capability-spec lifecycle has no success terminal state; "
            "projection projects it");

  llvm::json::Object wrongType;
  wrongType["lifecycle"] = llvm::json::Object{{"terminalStates", "CLOSED"}};
  llvm::Expected<llvm::StringRef> terminalStatesWrongType =
      requiredLifecycleSuccessTerminal(wrongType, "projection");
  ASSERT_FALSE(static_cast<bool>(terminalStatesWrongType));
  EXPECT_EQ(llvm::toString(terminalStatesWrongType.takeError()),
            "capability-spec lifecycle: missing/invalid terminalStates");
}

} // namespace

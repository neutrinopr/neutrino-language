// SPDX-License-Identifier: Apache-2.0
//===- SelfEmittedSpecTest.cpp - unit tests for translator-owned ingest ---===//
//
// SelfEmittedSpec ( S3 / ) is the one adapter that ingests the
// translator's OWN emitted capability-spec. It owns the re-parsed buffer for
// the use lifetime and treats a parse/shape failure as an INTERNAL invariant
// (report_fatal_error / abort), never a user diagnostic. These assertions pin
// the ownership/lifetime guarantee and the fail-closed abort on malformed
// self-output. See docs/testing/TESTING.md.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/SelfEmittedSpec.h"

#include "gtest/gtest.h"

#include <string>

using namespace neutrino;

namespace {

// A valid capability-spec-shaped object (only the fields these tests read).
const char *kValidSpec = R"({"procedure":"p","inputs":[],"effects":[]})";

TEST(SelfEmittedSpec, ExposesTheValidatedObject) {
  SelfEmittedSpec spec(SelfEmittedSpec::FromOwnOutput{}, kValidSpec);
  const llvm::json::Object &obj = spec.object();
  EXPECT_EQ(obj.getString("procedure"), llvm::Optional<llvm::StringRef>("p"));
  EXPECT_NE(obj.getArray("effects"), nullptr);
}

// Ownership: the source buffer can be destroyed and the object() reference
// stays valid, because the adapter owns the parsed json::Value (the parse
// copies string contents into it).
TEST(SelfEmittedSpec, OwnsTheBufferPastTheSourceString) {
  const llvm::json::Object *obj = nullptr;
  auto make = [&]() -> SelfEmittedSpec {
    std::string transient = kValidSpec; // freed when this scope ends
    return SelfEmittedSpec(SelfEmittedSpec::FromOwnOutput{}, transient);
  };
  SelfEmittedSpec spec =
      make(); // `transient` is gone here; guaranteed copy elision, no move
  obj = &spec.object();
  EXPECT_EQ(obj->getString("procedure"), llvm::Optional<llvm::StringRef>("p"));
}

// Fail-closed: malformed JSON from our OWN output is an internal invariant — it
// aborts, it is NOT a recoverable diagnostic. (External specs never reach this
// adapter; they keep their diagnostic path.)
TEST(SelfEmittedSpecDeathTest, MalformedJsonAborts) {
  EXPECT_DEATH(
      { SelfEmittedSpec(SelfEmittedSpec::FromOwnOutput{}, "{ not json"); },
      "internal: emitted capability-spec is not valid JSON");
}

// Fail-closed: valid JSON that is not an object (a bare string / array) also
// aborts.
TEST(SelfEmittedSpecDeathTest, NonObjectJsonAborts) {
  EXPECT_DEATH(
      { SelfEmittedSpec(SelfEmittedSpec::FromOwnOutput{}, "[1, 2, 3]"); },
      "internal: emitted capability-spec is not a JSON object");
}

} // namespace

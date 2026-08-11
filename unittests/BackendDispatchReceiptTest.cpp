#include "Neutrino/BackendDispatchReceipt.h"
#include "Neutrino/JsonUtil.h"

#include "llvm/Support/Error.h"
#include "llvm/Support/JSON.h"

#include "gtest/gtest.h"

#include <cstdlib>
#include <string>
#include <utility>

using namespace neutrino;

namespace {

template <typename T> T take(llvm::Expected<T> value) {
  if (!value) {
    ADD_FAILURE() << llvm::toString(value.takeError());
    std::abort();
  }
  return std::move(*value);
}

template <typename T>
void expectError(llvm::Expected<T> value, llvm::StringRef needle) {
  ASSERT_FALSE(static_cast<bool>(value));
  std::string message = llvm::toString(value.takeError());
  EXPECT_NE(message.find(needle.str()), std::string::npos) << message;
}

std::string digest(char value) { return "sha256:" + std::string(64, value); }

backend_invocation::Result invocation() {
  backend_invocation::Result result;
  result.requestId = 73;
  result.coreIdentity = "neutrino-core|test";
  result.targetIdentity = "synthetic";
  result.targetProfileIdentity = "profile:synthetic";
  result.packageManifestDigest = digest('1');
  result.projectionEncoding = "neutrino.finalized-projection/1";
  result.projectionByteLen = 4096;
  result.projectionDigest = digest('2');
  result.receiptDigest = digest('3');
  result.artifacts = {
      {"z.txt", "z\n", "sha256:" + sha256Hex("z\n")},
      {"nested/a.txt", "a\n", "sha256:" + sha256Hex("a\n")},
  };
  return result;
}

std::string reseal(llvm::json::Value value) {
  llvm::json::Object *root = value.getAsObject();
  EXPECT_NE(root, nullptr);
  root->erase("receiptDigest");
  std::string payload = compactJson(value);
  root->insert({"receiptDigest", "sha256:" + sha256Hex(payload)});
  return compactJson(value);
}

TEST(BackendDispatchReceiptTest, DeterministicallyBindsApprovedInvocation) {
  backend_invocation::Result input = invocation();
  std::string first = take(backend_dispatch_receipt::createApproved(input));
  std::string second = take(backend_dispatch_receipt::createApproved(input));
  EXPECT_EQ(first, second);

  backend_dispatch_receipt::VerifiedReceipt receipt =
      take(backend_dispatch_receipt::verify(first));
  EXPECT_EQ(receipt.requestId, input.requestId);
  EXPECT_EQ(receipt.coreIdentity, input.coreIdentity);
  EXPECT_EQ(receipt.targetIdentity, input.targetIdentity);
  EXPECT_EQ(receipt.targetProfileIdentity, input.targetProfileIdentity);
  EXPECT_EQ(receipt.packageManifestDigest, input.packageManifestDigest);
  EXPECT_EQ(receipt.projectionEncoding, input.projectionEncoding);
  EXPECT_EQ(receipt.projectionByteLen, input.projectionByteLen);
  EXPECT_EQ(receipt.projectionDigest, input.projectionDigest);
  EXPECT_EQ(receipt.backendReceiptDigest, input.receiptDigest);
  ASSERT_EQ(receipt.artifacts.size(), 2u);
  EXPECT_EQ(receipt.artifacts[0].path, "nested/a.txt");
  EXPECT_EQ(receipt.artifacts[1].path, "z.txt");
}

TEST(BackendDispatchReceiptTest, TamperWithoutResealingFailsDigest) {
  std::string receipt =
      take(backend_dispatch_receipt::createApproved(invocation()));
  size_t offset = receipt.find("profile:synthetic");
  ASSERT_NE(offset, std::string::npos);
  receipt.replace(offset, std::string("profile:synthetic").size(),
                  "profile:substitute");
  expectError(backend_dispatch_receipt::verify(receipt),
              "receiptDigest does not match");
}

TEST(BackendDispatchReceiptTest, SecurityBindingIsIndependentOfSelfDigest) {
  llvm::json::Value value = take(llvm::json::parse(
      take(backend_dispatch_receipt::createApproved(invocation()))));
  (*value.getAsObject()->getObject("security"))["projectionDigest"] =
      digest('4');
  expectError(backend_dispatch_receipt::verify(reseal(std::move(value))),
              "security projection binding does not match");
}

TEST(BackendDispatchReceiptTest, RequestBindingIsIndependentOfSelfDigest) {
  llvm::json::Value value = take(llvm::json::parse(
      take(backend_dispatch_receipt::createApproved(invocation()))));
  (*value.getAsObject()->getObject("security"))["requestId"] = 74;
  expectError(backend_dispatch_receipt::verify(reseal(std::move(value))),
              "security requestId binding does not match");
}

TEST(BackendDispatchReceiptTest, UnknownFieldsAndNoncanonicalBytesFailClosed) {
  std::string receipt =
      take(backend_dispatch_receipt::createApproved(invocation()));
  llvm::json::Value value = take(llvm::json::parse(receipt));
  value.getAsObject()->insert({"unexpected", true});
  expectError(backend_dispatch_receipt::verify(reseal(std::move(value))),
              "missing or unknown fields");
  expectError(backend_dispatch_receipt::verify(receipt + "\n"),
              "not canonical JSON");
}

TEST(BackendDispatchReceiptTest, CreationRejectsArtifactSubstitution) {
  backend_invocation::Result input = invocation();
  input.artifacts.front().bytes = "substituted\n";
  expectError(backend_dispatch_receipt::createApproved(input),
              "artifact digest does not match bytes");
}

} // namespace

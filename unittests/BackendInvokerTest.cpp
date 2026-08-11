// SPDX-License-Identifier: Apache-2.0
#include "Neutrino/BackendInvoker.h"
#include "Neutrino/BackendPackage.h"
#include "Neutrino/BackendProjection.h"
#include "Neutrino/BackendProjectionCodec.h"
#include "Neutrino/JsonUtil.h"

#include "llvm/ADT/ScopeExit.h"
#include "llvm/Support/Error.h"
#include "llvm/Support/FileSystem.h"
#include "llvm/Support/JSON.h"
#include "llvm/Support/MemoryBuffer.h"
#include "llvm/Support/Path.h"
#include "llvm/Support/raw_ostream.h"

#include "gtest/gtest.h"

#include <chrono>
#include <cstdlib>
#include <fcntl.h>
#include <memory>
#include <string>
#include <unistd.h>
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

std::string digest(llvm::StringRef bytes) {
  return "sha256:" + sha256Hex(bytes);
}

llvm::json::Object targetProfileObject() {
  return llvm::json::Object{
      {"capabilitySpecVersion", "v1"},
      {"executionMode", "simulated"},
      {"fallbackPolicy", "fail_closed"},
      {"kind", "neutrino.target-profile"},
      {"profileId", "target.synthetic.v1"},
      {"profileVersion", 1},
      {"runtimeFamily", "off_chain"},
      {"schemaVersion", 1},
      {"semanticProfile",
       llvm::json::Object{
           {"features",
            llvm::json::Array{"authorization:explicit", "terminal:success"}},
           {"limits",
            llvm::json::Object{
                {"maxAttestations", 4},
                {"maxComputes", 4},
                {"maxEffectGroups", 4},
                {"maxEffects", 8},
                {"maxExpressionDepth", 8},
                {"maxOperationSteps", 32},
            }},
           {"version", 3},
       }},
      {"supportedFeatures", llvm::json::Array{"effect:credit", "effect:debit"}},
      {"target", "synthetic"},
      {"unsupportedConstructs", llvm::json::Array{"value_category:extension"}},
  };
}

std::string sealDescriptor(llvm::StringRef entryBytes) {
  llvm::json::Value value(llvm::json::Object{
      {"apiVersion", 1},
      {"capabilities", llvm::json::Array{"emit", "stream"}},
      {"closure", llvm::json::Array{llvm::json::Object{
                      {"byteLen", static_cast<int64_t>(entryBytes.size())},
                      {"path", "bin/backend"},
                      {"sha256", digest(entryBytes)},
                  }}},
      {"compatibilityBounds",
       llvm::json::Object{
           {"coreProtocol",
            llvm::json::Object{
                {"max", llvm::json::Object{{"major", 1}, {"minor", 0}}},
                {"min", llvm::json::Object{{"major", 1}, {"minor", 0}}},
            }},
           {"projectionSchema",
            llvm::json::Object{
                {"max",
                 static_cast<int64_t>(projection::kProjectionSchemaVersion)},
                {"min",
                 static_cast<int64_t>(projection::kProjectionSchemaVersion)},
            }},
       }},
      {"entry", "bin/backend"},
      {"kind", backend_package::kDescriptorKind},
      {"licenseIdentity", "MIT"},
      {"profileSummary", targetProfileObject()},
      {"protocolMajor", 1},
      {"protocolMinor", 0},
      {"targetIdentity", "synthetic"},
      {"targetProfileIdentity", "target.synthetic.v1"},
  });
  value.getAsObject()->insert({"manifestDigest", digest(compactJson(value))});
  return compactJson(value);
}

void writeFile(llvm::StringRef path, llvm::StringRef bytes,
               llvm::sys::fs::perms permissions) {
  std::error_code error;
  llvm::raw_fd_ostream output(path, error);
  ASSERT_FALSE(error) << error.message();
  output << bytes;
  output.close();
  ASSERT_FALSE(llvm::sys::fs::setPermissions(path, permissions));
}

CoordinationPlan invocationPlan() {
  CoordinationPlan plan;
  plan.procedure = "invocation_fixture";
  plan.workflowKey = "shipment_ref";
  plan.evidenceOnly = true;
  plan.terminal.success = "CLOSED";
  LifecycleTransitionPolicy close;
  close.name = "CLOSE";
  close.from = "OPEN";
  close.to = "CLOSED";
  close.idempotency = "reject";
  plan.lifecycleTransitions.push_back(close);
  AttestationPolicy attestation;
  attestation.input = "input:1";
  attestation.quorum = 2;
  attestation.observerSet = "0";
  attestation.canonicalization = "exact";
  attestation.timeout = "PT48H";
  attestation.fallback = "abort";
  plan.attestations.push_back(attestation);
  return plan;
}

class BackendInvokerTest : public ::testing::Test {
protected:
  void SetUp() override {
    ASSERT_FALSE(llvm::sys::fs::createUniqueDirectory(
        "neutrino-backend-invoker", PackageDirectory));
    llvm::SmallString<256> bin(PackageDirectory);
    llvm::sys::path::append(bin, "bin");
    ASSERT_FALSE(llvm::sys::fs::create_directory(bin));

    llvm::ErrorOr<std::unique_ptr<llvm::MemoryBuffer>> executable =
        llvm::MemoryBuffer::getFile(NEUTRINO_SYNTHETIC_BACKEND_PATH);
    ASSERT_TRUE(static_cast<bool>(executable))
        << executable.getError().message();
    ExecutableBytes = (*executable)->getBuffer().str();

    llvm::SmallString<256> entry(bin);
    llvm::sys::path::append(entry, "backend");
    EntryPath = entry.str().str();
    writeFile(EntryPath, ExecutableBytes,
              llvm::sys::fs::owner_read | llvm::sys::fs::owner_exe);

    llvm::SmallString<256> descriptor(PackageDirectory);
    llvm::sys::path::append(descriptor, backend_package::kDescriptorFileName);
    writeFile(descriptor, sealDescriptor(ExecutableBytes),
              llvm::sys::fs::owner_read);

    Filesystem = backend_package::createNativePackageFilesystem();
    backend_package::Compatibility compatibility;
    Package = std::make_unique<backend_package::VerifiedPackage>(
        take(backend_package::verifyPackage(PackageDirectory, compatibility,
                                            *Filesystem)));
    Graph = take(projection::projectBackendGraph(invocationPlan()));
  }

  void TearDown() override {
    Package.reset();
    Filesystem.reset();
    ASSERT_FALSE(llvm::sys::fs::remove_directories(PackageDirectory));
  }

  backend_invocation::InvocationOptions options(llvm::StringRef mode) const {
    backend_invocation::InvocationOptions result;
    result.requestId = 73;
    result.coreIdentity =
        ("synthetic|" + mode + "|" + Package->descriptor().manifestDigest)
            .str();
    result.outputSpec = {4, 4096, "/core-owned-output"};
    result.timeout = std::chrono::milliseconds(2000);
    result.cancellationGrace = std::chrono::milliseconds(1000);
    return result;
  }

  llvm::SmallString<256> PackageDirectory;
  std::string EntryPath;
  std::string ExecutableBytes;
  std::unique_ptr<backend_package::PackageFilesystem> Filesystem;
  std::unique_ptr<backend_package::VerifiedPackage> Package;
  projection::BackendProjectionGraph Graph;
};

TEST_F(BackendInvokerTest, ReturnsTargetBlindInMemoryArtifacts) {
  backend_invocation::Result result =
      take(backend_invocation::invoke(*Package, Graph, options("success")));
  EXPECT_EQ(result.requestId, 73u);
  EXPECT_EQ(result.coreIdentity, options("success").coreIdentity);
  EXPECT_EQ(result.targetIdentity, "synthetic");
  EXPECT_EQ(result.targetProfileIdentity, "target.synthetic.v1");
  EXPECT_EQ(result.packageManifestDigest, Package->descriptor().manifestDigest);
  EXPECT_EQ(result.projectionEncoding, "neutrino.finalized-projection/1");
  std::string projectionBytes =
      take(projection::encodeFinalizedProjection(Graph));
  EXPECT_EQ(result.projectionByteLen, projectionBytes.size());
  EXPECT_EQ(result.projectionDigest, digest(projectionBytes));
  ASSERT_EQ(result.artifacts.size(), 1u);
  EXPECT_EQ(result.artifacts[0].path, "result.txt");
  EXPECT_EQ(result.artifacts[0].bytes, "synthetic artifact\n");
  EXPECT_EQ(result.artifacts[0].sha256, digest("synthetic artifact\n"));
  EXPECT_EQ(result.receiptDigest, "sha256:" + std::string(64, 'a'));
}

TEST_F(BackendInvokerTest, IncompatibleVersionFailsClosed) {
  expectError(
      backend_invocation::invoke(*Package, Graph, options("incompatible")),
      "E_VERSION");
}

TEST_F(BackendInvokerTest, EarlyExitIsNotAProtocolSuccess) {
  expectError(
      backend_invocation::invoke(*Package, Graph, options("early-exit")),
      "E_PROCESS_EXIT");
}

TEST_F(BackendInvokerTest, TimeoutIsCancelledBeforeProcessTeardown) {
  backend_invocation::InvocationOptions timeout = options("timeout");
  timeout.timeout = std::chrono::milliseconds(2500);
  expectError(backend_invocation::invoke(*Package, Graph, timeout),
              "timed out and was cancelled");
}

TEST_F(BackendInvokerTest, BlockingProjectionWriteHonorsInvocationDeadline) {
  projection::BackendProjectionGraph largeGraph = Graph;
  ASSERT_FALSE(largeGraph.executionIdentities.empty());
  largeGraph.executionIdentities.front().sourceRef.assign(8 * 1024 * 1024, 'x');
  backend_invocation::InvocationOptions timeout = options("write-stall");
  timeout.timeout = std::chrono::milliseconds(2500);
  auto started = std::chrono::steady_clock::now();
  expectError(backend_invocation::invoke(*Package, largeGraph, timeout),
              "backend protocol write timed out");
  auto elapsed = std::chrono::steady_clock::now() - started;
  EXPECT_LT(elapsed, std::chrono::seconds(5));
}

TEST_F(BackendInvokerTest, MalformedResponseOrderingFailsClosed) {
  expectError(
      backend_invocation::invoke(*Package, Graph, options("malformed-order")),
      "lone raw frame");
}

TEST_F(BackendInvokerTest, RequestIdMismatchFailsClosed) {
  expectError(
      backend_invocation::invoke(*Package, Graph, options("request-mismatch")),
      "requestId does not match");
}

TEST_F(BackendInvokerTest, StructuredBackendErrorIsReturnedAfterCleanExit) {
  expectError(
      backend_invocation::invoke(*Package, Graph, options("peer-error")),
      "E_RENDER:invoke:render:synthetic refusal");
}

TEST_F(BackendInvokerTest, ChildCannotObserveUnrelatedCoreDescriptor) {
  char sentinelPath[] = "/tmp/neutrino-invoker-sentinel.XXXXXX";
  int temporary = ::mkstemp(sentinelPath);
  ASSERT_GE(temporary, 0);
  ASSERT_EQ(::unlink(sentinelPath), 0);
  int sentinel = ::fcntl(temporary, F_DUPFD, 20);
  ASSERT_GE(sentinel, 20);
  ASSERT_EQ(::close(temporary), 0);
  auto closeSentinel = llvm::make_scope_exit([&] { (void)::close(sentinel); });
  ASSERT_EQ(::fcntl(sentinel, F_GETFD) & FD_CLOEXEC, 0);

  backend_invocation::Result result = take(backend_invocation::invoke(
      *Package, Graph,
      options(("fd-sentinel-" + llvm::Twine(sentinel)).str())));
  ASSERT_EQ(result.artifacts.size(), 1u);
  EXPECT_EQ(result.artifacts[0].bytes, "synthetic artifact\n");
}

TEST_F(BackendInvokerTest, EntryReplacementAfterDiscoveryCannotChangeLaunch) {
  ASSERT_FALSE(llvm::sys::fs::setPermissions(
      EntryPath, llvm::sys::fs::owner_read | llvm::sys::fs::owner_write));
  writeFile(EntryPath, "not an executable\n",
            llvm::sys::fs::owner_read | llvm::sys::fs::owner_write);
  backend_invocation::Result result =
      take(backend_invocation::invoke(*Package, Graph, options("success")));
  ASSERT_EQ(result.artifacts.size(), 1u);
  EXPECT_EQ(result.artifacts[0].bytes, "synthetic artifact\n");
}

} // namespace

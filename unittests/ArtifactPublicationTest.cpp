// SPDX-License-Identifier: Apache-2.0
#include "Neutrino/ArtifactPublication.h"
#include "Neutrino/JsonUtil.h"

#include "../lib/spec-contract/ArtifactPublicationTestSupport.h"

#include "llvm/ADT/ScopeExit.h"
#include "llvm/Support/Error.h"
#include "llvm/Support/FileSystem.h"
#include "llvm/Support/MemoryBuffer.h"
#include "llvm/Support/Path.h"
#include "llvm/Support/raw_ostream.h"

#include "gtest/gtest.h"

#include <condition_variable>
#include <cstdlib>
#include <fcntl.h>
#include <functional>
#include <initializer_list>
#include <memory>
#include <mutex>
#include <string>
#include <sys/stat.h>
#include <thread>
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

void writeFile(llvm::StringRef path, llvm::StringRef bytes) {
  std::error_code error;
  llvm::raw_fd_ostream output(path, error);
  ASSERT_FALSE(error) << error.message();
  output << bytes;
}

std::string readFile(llvm::StringRef path) {
  llvm::ErrorOr<std::unique_ptr<llvm::MemoryBuffer>> buffer =
      llvm::MemoryBuffer::getFile(path);
  if (!buffer) {
    ADD_FAILURE() << buffer.getError().message();
    return {};
  }
  return (*buffer)->getBuffer().str();
}

backend_invocation::Result
manifest(std::initializer_list<std::pair<llvm::StringRef, llvm::StringRef>>
             artifacts) {
  backend_invocation::Result result;
  result.requestId = 73;
  result.targetIdentity = "synthetic";
  result.receiptDigest = "sha256:" + std::string(64, 'a');
  for (const auto &artifact : artifacts)
    result.artifacts.push_back(
        {artifact.first.str(), artifact.second.str(), digest(artifact.second)});
  return result;
}

class ConcurrentMutation {
public:
  ConcurrentMutation(artifact_publication::TestEvent event,
                     llvm::StringRef path, std::function<void()> mutation)
      : Event(event), Path(path.str()), Mutation(std::move(mutation)),
        Worker([this] {
          std::unique_lock<std::mutex> lock(Mutex);
          Condition.wait(lock, [this] { return Requested || Stopping; });
          if (Stopping)
            return;
          lock.unlock();
          Mutation();
          lock.lock();
          Complete = true;
          Condition.notify_one();
        }) {}

  ~ConcurrentMutation() {
    {
      std::lock_guard<std::mutex> lock(Mutex);
      Stopping = true;
      Condition.notify_one();
    }
    Worker.join();
  }

  artifact_publication::TestHooks hooks() {
    return {&ConcurrentMutation::barrier, this};
  }

private:
  static void barrier(artifact_publication::TestEvent event,
                      llvm::StringRef path, void *context) {
    auto *self = static_cast<ConcurrentMutation *>(context);
    if (event != self->Event || path != self->Path)
      return;
    std::unique_lock<std::mutex> lock(self->Mutex);
    self->Requested = true;
    self->Condition.notify_one();
    self->Condition.wait(lock, [self] { return self->Complete; });
  }

  artifact_publication::TestEvent Event;
  std::string Path;
  std::function<void()> Mutation;
  std::mutex Mutex;
  std::condition_variable Condition;
  bool Requested = false;
  bool Complete = false;
  bool Stopping = false;
  std::thread Worker;
};

class ArtifactPublicationTest : public ::testing::Test {
protected:
  void SetUp() override {
    ASSERT_FALSE(llvm::sys::fs::createUniqueDirectory(
        "neutrino-artifact-publication", Temporary));
    llvm::SmallString<256> resolvedTemporary;
    ASSERT_FALSE(llvm::sys::fs::real_path(Temporary, resolvedTemporary, true));
    Temporary = resolvedTemporary;
    llvm::SmallString<256> output(Temporary);
    llvm::sys::path::append(output, "output");
    Output = output.str().str();
    ASSERT_FALSE(llvm::sys::fs::create_directory(Output));
  }

  void TearDown() override {
    ASSERT_FALSE(llvm::sys::fs::remove_directories(Temporary));
  }

  llvm::SmallString<256> path(llvm::StringRef relative) const {
    llvm::SmallString<256> result(Output);
    llvm::sys::path::append(result, relative);
    return result;
  }

  llvm::SmallString<256> Temporary;
  std::string Output;
};

TEST_F(ArtifactPublicationTest, PublishesVerifiedManifestInPathOrder) {
  backend_invocation::Result input =
      manifest({{"z.txt", "last\n"}, {"nested/a.txt", "first\n"}});
  artifact_publication::Result result =
      take(artifact_publication::publish(input, Output));

  ASSERT_EQ(result.artifacts.size(), 2u);
  EXPECT_EQ(result.artifacts[0].path, "nested/a.txt");
  EXPECT_EQ(result.artifacts[1].path, "z.txt");
  EXPECT_EQ(readFile(path("nested/a.txt")), "first\n");
  EXPECT_EQ(readFile(path("z.txt")), "last\n");
  EXPECT_EQ(result.requestId, input.requestId);
  EXPECT_EQ(result.targetIdentity, input.targetIdentity);
  EXPECT_EQ(result.receiptDigest, input.receiptDigest);
}

TEST_F(ArtifactPublicationTest, PublishesCoreMetadataThroughSameSafePath) {
  artifact_publication::PublishedArtifact result =
      take(artifact_publication::publishCoreArtifact(
          "backend-dispatch-receipt.json", "{\"receipt\":true}", Output));
  EXPECT_EQ(result.path, "backend-dispatch-receipt.json");
  EXPECT_EQ(result.byteLen, 16u);
  EXPECT_EQ(result.sha256, digest("{\"receipt\":true}"));
  EXPECT_EQ(readFile(path(result.path)), "{\"receipt\":true}");

  expectError(artifact_publication::publishCoreArtifact(result.path,
                                                        "replacement", Output),
              "visible paths are retained");
}

TEST_F(ArtifactPublicationTest, PublishesCoreArtifactBatchInPathOrder) {
  std::vector<artifact_publication::CoreArtifact> artifacts{{"z.json", "z\n"},
                                                            {"a.json", "a\n"}};
  auto result =
      take(artifact_publication::publishCoreArtifacts(artifacts, Output));
  ASSERT_EQ(result.size(), 2u);
  EXPECT_EQ(result[0].path, "a.json");
  EXPECT_EQ(result[1].path, "z.json");
}

TEST_F(ArtifactPublicationTest, CoreBatchRejectsUnsafeOrExistingNames) {
  llvm::SmallString<256> outside(Temporary);
  llvm::sys::path::append(outside, "outside.json");
  writeFile(outside, "sentinel\n");
  ASSERT_EQ(::symlink(outside.c_str(), path("a.json").c_str()), 0);
  std::vector<artifact_publication::CoreArtifact> symlinked{
      {"a.json", "replacement\n"}};
  expectError(artifact_publication::publishCoreArtifacts(symlinked, Output),
              "E_PATH");
  EXPECT_EQ(readFile(outside), "sentinel\n");

  writeFile(path("z.json"), "existing\n");
  std::vector<artifact_publication::CoreArtifact> midBatch{
      {"b.json", "visible\n"}, {"z.json", "replacement\n"}};
  expectError(artifact_publication::publishCoreArtifacts(midBatch, Output),
              "visible paths are retained");
  EXPECT_EQ(readFile(path("b.json")), "visible\n");
  EXPECT_EQ(readFile(path("z.json")), "existing\n");
}

TEST_F(ArtifactPublicationTest, DigestSubstitutionWritesNothing) {
  backend_invocation::Result input = manifest({{"result.txt", "original\n"}});
  input.artifacts[0].bytes = "substituted\n";
  expectError(artifact_publication::publish(input, Output),
              "E_ARTIFACT_DIGEST");
  EXPECT_FALSE(llvm::sys::fs::exists(path("result.txt")));
}

TEST_F(ArtifactPublicationTest, DuplicatePathWritesNothing) {
  backend_invocation::Result input =
      manifest({{"result.txt", "one\n"}, {"result.txt", "two\n"}});
  expectError(artifact_publication::publish(input, Output), "duplicated");
  EXPECT_FALSE(llvm::sys::fs::exists(path("result.txt")));
}

TEST_F(ArtifactPublicationTest, ReceiptSubstitutionWritesNothing) {
  backend_invocation::Result input = manifest({{"result.txt", "original\n"}});
  input.receiptDigest = "not-a-digest";
  expectError(artifact_publication::publish(input, Output), "E_PROTOCOL");
  EXPECT_FALSE(llvm::sys::fs::exists(path("result.txt")));
}

TEST_F(ArtifactPublicationTest, SymlinkedComponentCannotEscapeRoot) {
  llvm::SmallString<256> outside(Temporary);
  llvm::sys::path::append(outside, "outside");
  ASSERT_FALSE(llvm::sys::fs::create_directory(outside));
  llvm::SmallString<256> link(path("nested"));
  ASSERT_EQ(::symlink(outside.c_str(), link.c_str()), 0);

  expectError(artifact_publication::publish(
                  manifest({{"nested/escaped.txt", "forbidden\n"}}), Output),
              "E_PATH");
  llvm::SmallString<256> escaped(outside);
  llvm::sys::path::append(escaped, "escaped.txt");
  EXPECT_FALSE(llvm::sys::fs::exists(escaped));
}

TEST_F(ArtifactPublicationTest, SymlinkedFinalFileIsNeverFollowed) {
  llvm::SmallString<256> outside(Temporary);
  llvm::sys::path::append(outside, "sentinel.txt");
  writeFile(outside, "sentinel\n");
  llvm::SmallString<256> link(path("result.txt"));
  ASSERT_EQ(::symlink(outside.c_str(), link.c_str()), 0);

  expectError(artifact_publication::publish(
                  manifest({{"result.txt", "replacement\n"}}), Output),
              "E_PATH");
  EXPECT_EQ(readFile(outside), "sentinel\n");
}

TEST_F(ArtifactPublicationTest, SymlinkedOutputRootIsRejected) {
  llvm::SmallString<256> outside(Temporary);
  llvm::sys::path::append(outside, "outside");
  ASSERT_FALSE(llvm::sys::fs::create_directory(outside));
  ASSERT_FALSE(llvm::sys::fs::remove(Output));
  ASSERT_EQ(::symlink(outside.c_str(), Output.c_str()), 0);

  expectError(artifact_publication::publish(
                  manifest({{"escaped.txt", "forbidden\n"}}), Output),
              "E_PATH");
  llvm::SmallString<256> escaped(outside);
  llvm::sys::path::append(escaped, "escaped.txt");
  EXPECT_FALSE(llvm::sys::fs::exists(escaped));
}

TEST_F(ArtifactPublicationTest, AbsoluteIntermediateRootSymlinkIsRejected) {
  llvm::SmallString<256> outside(Temporary);
  llvm::sys::path::append(outside, "outside");
  ASSERT_FALSE(llvm::sys::fs::create_directory(outside));
  llvm::SmallString<256> escapedRoot(outside);
  llvm::sys::path::append(escapedRoot, "output");
  ASSERT_FALSE(llvm::sys::fs::create_directory(escapedRoot));
  llvm::SmallString<256> link(Temporary);
  llvm::sys::path::append(link, "root-link");
  ASSERT_EQ(::symlink(outside.c_str(), link.c_str()), 0);
  llvm::SmallString<256> linkedOutput(link);
  llvm::sys::path::append(linkedOutput, "output");

  expectError(artifact_publication::publish(
                  manifest({{"escaped.txt", "forbidden\n"}}), linkedOutput),
              "E_PATH");
  llvm::SmallString<256> escaped(escapedRoot);
  llvm::sys::path::append(escaped, "escaped.txt");
  EXPECT_FALSE(llvm::sys::fs::exists(escaped));
}

TEST_F(ArtifactPublicationTest, RelativeIntermediateRootSymlinkIsRejected) {
  int savedWorkingDirectory = ::open(".", O_RDONLY | O_DIRECTORY | O_CLOEXEC);
  ASSERT_GE(savedWorkingDirectory, 0);
  auto restoreWorkingDirectory = llvm::make_scope_exit([&] {
    ASSERT_EQ(::fchdir(savedWorkingDirectory), 0);
    ASSERT_EQ(::close(savedWorkingDirectory), 0);
  });
  ASSERT_EQ(::chdir(Temporary.c_str()), 0);
  ASSERT_EQ(::mkdir("relative-outside", 0755), 0);
  ASSERT_EQ(::mkdir("relative-outside/output", 0755), 0);
  ASSERT_EQ(::symlink("relative-outside", "relative-link"), 0);

  expectError(
      artifact_publication::publish(manifest({{"escaped.txt", "forbidden\n"}}),
                                    "relative-link/output"),
      "E_PATH");
  EXPECT_FALSE(llvm::sys::fs::exists("relative-outside/output/escaped.txt"));
}

TEST_F(ArtifactPublicationTest, ExistingTargetLeavesEarlierArtifactVisible) {
  writeFile(path("z.txt"), "existing\n");
  backend_invocation::Result input =
      manifest({{"a.txt", "new\n"}, {"z.txt", "replacement\n"}});
  expectError(artifact_publication::publish(input, Output),
              "visible paths are retained");
  EXPECT_EQ(readFile(path("a.txt")), "new\n");
  EXPECT_EQ(readFile(path("z.txt")), "existing\n");
}

TEST_F(ArtifactPublicationTest,
       PostValidationReplacementCannotSubstitutePublishedBytes) {
  llvm::SmallString<256> displaced(path("displaced.txt"));
  ConcurrentMutation mutation(
      artifact_publication::TestEvent::ArtifactValidated, "result.txt", [&] {
        ASSERT_EQ(::rename(path("result.txt").c_str(), displaced.c_str()), 0);
        writeFile(path("result.txt"), "foreign\n");
      });

  expectError(
      artifact_publication::publishForTesting(
          manifest({{"result.txt", "verified\n"}}), Output, mutation.hooks()),
      "identity changed");
  EXPECT_EQ(readFile(path("result.txt")), "foreign\n");
  EXPECT_EQ(readFile(displaced), "verified\n");
}

TEST_F(ArtifactPublicationTest,
       LaterFailureDoesNotDeleteConcurrentFileReplacement) {
  writeFile(path("z.txt"), "existing\n");
  llvm::SmallString<256> displaced(path("displaced.txt"));
  ConcurrentMutation mutation(
      artifact_publication::TestEvent::ArtifactValidated, "a.txt", [&] {
        ASSERT_EQ(::rename(path("a.txt").c_str(), displaced.c_str()), 0);
        writeFile(path("a.txt"), "foreign\n");
      });

  expectError(
      artifact_publication::publishForTesting(
          manifest({{"a.txt", "verified\n"}, {"z.txt", "replacement\n"}}),
          Output, mutation.hooks()),
      "E_PATH");
  EXPECT_EQ(readFile(path("a.txt")), "foreign\n");
  EXPECT_EQ(readFile(displaced), "verified\n");
  EXPECT_EQ(readFile(path("z.txt")), "existing\n");
}

TEST_F(ArtifactPublicationTest,
       LaterFailureDoesNotDeleteConcurrentDirectoryReplacement) {
  writeFile(path("z.txt"), "existing\n");
  llvm::SmallString<256> displaced(path("displaced"));
  ConcurrentMutation mutation(
      artifact_publication::TestEvent::ArtifactValidated, "nested/a.txt", [&] {
        ASSERT_EQ(::rename(path("nested").c_str(), displaced.c_str()), 0);
        ASSERT_EQ(::mkdir(path("nested").c_str(), 0755), 0);
        writeFile(path("nested/foreign.txt"), "foreign\n");
      });

  expectError(artifact_publication::publishForTesting(
                  manifest({{"nested/a.txt", "verified\n"},
                            {"z.txt", "replacement\n"}}),
                  Output, mutation.hooks()),
              "E_PATH");
  EXPECT_EQ(readFile(path("nested/foreign.txt")), "foreign\n");
  EXPECT_FALSE(llvm::sys::fs::exists(path("nested/a.txt")));
  EXPECT_TRUE(llvm::sys::fs::exists(displaced));
  EXPECT_EQ(readFile(path("z.txt")), "existing\n");
}

} // namespace

// SPDX-License-Identifier: Apache-2.0
#include "Neutrino/BackendProtocol.h"
#include "Neutrino/BackendStartup.h"
#include "Neutrino/JsonUtil.h"

#include "llvm/ADT/SmallVector.h"
#include "llvm/Support/Error.h"
#include "llvm/Support/JSON.h"

#include <algorithm>
#include <cerrno>
#include <cstdint>
#include <cstdlib>
#include <fcntl.h>
#include <string>
#include <unistd.h>
#include <vector>

using namespace neutrino;
using namespace neutrino::backend_protocol;

namespace {

template <typename T> T take(llvm::Expected<T> value) {
  if (!value)
    std::_Exit(90);
  return std::move(*value);
}

bool readExact(char *bytes, size_t size) {
  size_t offset = 0;
  while (offset < size) {
    ssize_t count = ::read(STDIN_FILENO, bytes + offset, size - offset);
    if (count < 0) {
      if (errno == EINTR)
        continue;
      std::_Exit(91);
    }
    if (count == 0)
      return false;
    offset += static_cast<size_t>(count);
  }
  return true;
}

Frame readFrame() {
  std::string wire(8, '\0');
  if (!readExact(wire.data(), wire.size()))
    std::_Exit(92);
  const auto *raw = reinterpret_cast<const unsigned char *>(wire.data());
  uint32_t payloadLength = (static_cast<uint32_t>(raw[0]) << 24) |
                           (static_cast<uint32_t>(raw[1]) << 16) |
                           (static_cast<uint32_t>(raw[2]) << 8) |
                           static_cast<uint32_t>(raw[3]);
  wire.resize(8 + payloadLength);
  if (!readExact(wire.data() + 8, payloadLength))
    std::_Exit(93);
  std::vector<Frame> frames = take(decodeFrames(wire));
  if (frames.size() != 1)
    std::_Exit(94);
  return std::move(frames.front());
}

void writeFrame(const Frame &frame) {
  std::string wire = take(encodeFrame(frame));
  size_t offset = 0;
  while (offset < wire.size()) {
    ssize_t count =
        ::write(STDOUT_FILENO, wire.data() + offset, wire.size() - offset);
    if (count < 0) {
      if (errno == EINTR)
        continue;
      std::_Exit(95);
    }
    offset += static_cast<size_t>(count);
  }
}

llvm::json::Object parseObject(const Frame &frame) {
  llvm::Expected<llvm::json::Value> value = llvm::json::parse(frame.payload);
  if (!value || !value->getAsObject())
    std::_Exit(96);
  return std::move(*value->getAsObject());
}

std::string requiredString(const llvm::json::Object &object,
                           llvm::StringRef key) {
  llvm::Optional<llvm::StringRef> value = object.getString(key);
  if (!value)
    std::_Exit(97);
  return value->str();
}

uint64_t requiredInteger(const llvm::json::Object &object,
                         llvm::StringRef key) {
  llvm::Optional<int64_t> value = object.getInteger(key);
  if (!value || *value < 0)
    std::_Exit(98);
  return static_cast<uint64_t>(*value);
}

struct Identity {
  std::string mode;
  std::string manifestDigest;
  std::string target = "synthetic";
  std::string artifactBytes = "synthetic artifact\n";
};

Identity parseIdentity(llvm::StringRef coreIdentity,
                       llvm::StringRef packageManifestDigest) {
  llvm::SmallVector<llvm::StringRef, 3> fields;
  coreIdentity.split(fields, '|');
  if (fields.size() == 3 && fields[0] == "synthetic")
    return {fields[1].str(), packageManifestDigest.str()};
  if (!fields.empty() && fields[0] == "neutrino-core") {
    Identity identity;
    if (const char *mode = std::getenv("NEUTRINO_SYNTHETIC_MODE"))
      identity.mode = mode;
    else
      identity.mode = "success";
    identity.manifestDigest = packageManifestDigest.str();
    if (const char *target = std::getenv("NEUTRINO_SYNTHETIC_TARGET_IDENTITY"))
      identity.target = target;
    if (const char *artifact = std::getenv("NEUTRINO_SYNTHETIC_ARTIFACT_BYTES"))
      identity.artifactBytes = artifact;

    return identity;
  }
  std::_Exit(99);
}

} // namespace

#ifndef NEUTRINO_SYNTHETIC_ARTIFACT_PATH
#define NEUTRINO_SYNTHETIC_ARTIFACT_PATH "result.txt"
#endif

int main(int argc, char **argv) {
  llvm::Expected<backend_startup::Binding> startup =
      backend_startup::parseArguments(argc, argv);
  if (!startup) {
    llvm::consumeError(startup.takeError());
    return 86;
  }
  llvm::Expected<std::string> packageManifestDigest =
      backend_startup::loadPackageManifestDigest(*startup);
  if (!packageManifestDigest) {
    llvm::consumeError(packageManifestDigest.takeError());
    return 87;
  }
  if (const char *removePath =
          std::getenv("NEUTRINO_SYNTHETIC_REMOVE_PATH_ON_START"))
    (void)::unlink(removePath);
  if (const char *marker =
          std::getenv("NEUTRINO_SYNTHETIC_INVOCATION_MARKER")) {
    int descriptor =
        ::open(marker, O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0600);
    if (descriptor < 0 || ::write(descriptor, "invoked\n", 8) != 8)
      std::_Exit(89);
    (void)::close(descriptor);
  }
  constexpr llvm::StringLiteral artifactPath = NEUTRINO_SYNTHETIC_ARTIFACT_PATH;
  Frame hello = readFrame();
  Identity identity =
      parseIdentity(requiredString(parseObject(hello), "coreIdentity"),
                    *packageManifestDigest);
  if (identity.mode == "manifest-mismatch") {
    identity.mode = "success";
    identity.manifestDigest = "sha256:" + std::string(64, '0');
  }
  llvm::StringRef modeSuffix(identity.mode);
  if (modeSuffix.consume_front("fd-sentinel-")) {
    char *end = nullptr;
    std::string spelling = modeSuffix.str();
    long descriptor = std::strtol(spelling.c_str(), &end, 10);
    if (!end || *end != '\0' || descriptor < 0)
      return 24;
    errno = 0;
    if (::fcntl(static_cast<int>(descriptor), F_GETFD) != -1 || errno != EBADF)
      return 25;
    identity.mode = "success";
  }
  if (identity.mode == "early-exit")
    return 23;

  std::string defaultProfileTarget = identity.target;
  std::replace(defaultProfileTarget.begin(), defaultProfileTarget.end(), '-',
               '_');
  Capabilities capabilities{
      identity.mode == "incompatible" ? 2u : kProtocolMajor,
      kProtocolMinor,
      1,
      identity.target,
      std::getenv("NEUTRINO_SYNTHETIC_PROFILE_IDENTITY")
          ? std::getenv("NEUTRINO_SYNTHETIC_PROFILE_IDENTITY")
          : "target." + defaultProfileTarget + ".v1",
      static_cast<uint32_t>(projection::kProjectionSchemaVersion),
      static_cast<uint32_t>(projection::kProjectionSchemaVersion),
      identity.manifestDigest,
      {"emit", "stream"},
      "MIT"};
  writeFrame(take(encodeCapabilities(capabilities)));
  if (identity.mode == "incompatible")
    return 0;
  if (identity.mode == "write-stall") {
    while (true)
      ::pause();
  }

  Frame emit = readFrame();
  uint64_t requestId = requiredInteger(parseObject(emit), "requestId");
  (void)readFrame();

  if (identity.mode == "timeout") {
    Frame cancel = readFrame();
    uint64_t cancelledId = requiredInteger(parseObject(cancel), "requestId");
    writeFrame(take(encodeCancelled({cancelledId})));
    (void)readFrame();
    return 0;
  }
  if (identity.mode == "malformed-order") {
    writeFrame({static_cast<uint16_t>(MessageType::ArtifactBytes),
                kMustUnderstand, "orphan"});
    return 0;
  }
  if (identity.mode == "peer-error") {
    writeFrame(take(encodeError(
        {requestId, "E_RENDER", "render", "synthetic refusal", false})));
    (void)readFrame();
    return 0;
  }

  uint64_t responseId =
      identity.mode == "request-mismatch" ? requestId + 1 : requestId;
  const std::string &artifactBytes = identity.artifactBytes;
  ArtifactChunk chunk{responseId, artifactPath.str(), 0, true,
                      static_cast<uint32_t>(artifactBytes.size())};
  for (const Frame &frame : take(encodeArtifactChunk(chunk, artifactBytes)))
    writeFrame(frame);
  if (identity.mode == "request-mismatch")
    return 0;

  Manifest manifest;
  manifest.requestId = requestId;
  manifest.artifacts.push_back({artifactPath.str(),
                                "sha256:" + sha256Hex(artifactBytes),
                                artifactBytes.size()});
  manifest.receiptDigest = "sha256:" + std::string(64, 'a');
  writeFrame(take(encodeManifest(manifest)));
  (void)readFrame();
  return 0;
}

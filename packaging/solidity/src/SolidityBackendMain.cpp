#include "SolidityRecipeProvider.h"

#include "Neutrino/BackendProtocol.h"
#include "Neutrino/BackendStartup.h"
#include "Neutrino/JsonUtil.h"

#include "llvm/Support/Error.h"

#include <cerrno>
#include <cstdint>
#include <cstdlib>
#include <exception>
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

std::string emissionReceipt(const std::vector<SoliditySourceFile> &artifacts) {
  std::string material;
  for (const SoliditySourceFile &artifact : artifacts) {
    material.append(artifact.path);
    material.push_back('\0');
    material.append("sha256:" + sha256Hex(artifact.content));
    material.push_back('\0');
    material.append(std::to_string(artifact.content.size()));
    material.push_back('\n');
  }
  return "sha256:" + sha256Hex(material);
}

} // namespace

int main(int argc, char **argv) {
  llvm::Expected<backend_startup::Binding> startup =
      backend_startup::parseArguments(argc, argv);
  if (!startup) {
    llvm::consumeError(startup.takeError());
    return 96;
  }
  llvm::Expected<std::string> packageManifestDigest =
      backend_startup::loadPackageManifestDigest(*startup);
  if (!packageManifestDigest) {
    llvm::consumeError(packageManifestDigest.takeError());
    return 97;
  }
  Session session;

  Frame hello = readFrame();
  if (llvm::Error error = session.consume(Direction::CoreToBackend, hello)) {
    llvm::consumeError(std::move(error));
    return 2;
  }

  Capabilities capabilities{
      kProtocolMajor,
      kProtocolMinor,
      1,
      "solidity",
      "target.evm.v1",
      static_cast<uint32_t>(projection::kProjectionSchemaVersion),
      static_cast<uint32_t>(projection::kProjectionSchemaVersion),
      *packageManifestDigest,
      {"emit", "stream"},
      "pending:"};
  Frame capabilitiesFrame = take(encodeCapabilities(capabilities));
  if (llvm::Error error =
          session.consume(Direction::BackendToCore, capabilitiesFrame)) {
    llvm::consumeError(std::move(error));
    return 3;
  }
  writeFrame(capabilitiesFrame);

  Frame emit = readFrame();
  if (llvm::Error error = session.consume(Direction::CoreToBackend, emit)) {
    llvm::consumeError(std::move(error));
    return 4;
  }
  Frame projectionBytes = readFrame();
  if (llvm::Error error =
          session.consume(Direction::CoreToBackend, projectionBytes)) {
    llvm::consumeError(std::move(error));
    return 5;
  }
  llvm::Optional<AcceptedEmit> accepted = session.takeAcceptedEmit();
  if (!accepted)
    return 6;

  std::vector<SoliditySourceFile> sources;
  try {
    sources = solidity_model::materializeSoliditySources(accepted->graph);
  } catch (const std::exception &error) {
    Frame failure = take(encodeError({accepted->request.requestId, "E_RENDER",
                                      "render", error.what(), false}));
    if (llvm::Error consume =
            session.consume(Direction::BackendToCore, failure)) {
      llvm::consumeError(std::move(consume));
      return 7;
    }
    writeFrame(failure);
    Frame goodbye = readFrame();
    if (llvm::Error consume =
            session.consume(Direction::CoreToBackend, goodbye)) {
      llvm::consumeError(std::move(consume));
      return 8;
    }
    return 0;
  }

  Manifest manifest;
  manifest.requestId = accepted->request.requestId;
  for (const SoliditySourceFile &source : sources) {
    ArtifactChunk chunk{manifest.requestId, source.path, 0, true,
                        static_cast<uint32_t>(source.content.size())};
    for (const Frame &frame :
         take(encodeArtifactChunk(chunk, source.content))) {
      if (llvm::Error error =
              session.consume(Direction::BackendToCore, frame)) {
        llvm::consumeError(std::move(error));
        return 9;
      }
      writeFrame(frame);
    }
    manifest.artifacts.push_back({source.path,
                                  "sha256:" + sha256Hex(source.content),
                                  source.content.size()});
  }
  manifest.receiptDigest = emissionReceipt(sources);
  Frame manifestFrame = take(encodeManifest(manifest));
  if (llvm::Error error =
          session.consume(Direction::BackendToCore, manifestFrame)) {
    llvm::consumeError(std::move(error));
    return 10;
  }
  writeFrame(manifestFrame);

  Frame goodbye = readFrame();
  if (llvm::Error error = session.consume(Direction::CoreToBackend, goodbye)) {
    llvm::consumeError(std::move(error));
    return 11;
  }
  if (llvm::Error error = session.finish()) {
    llvm::consumeError(std::move(error));
    return 12;
  }
  return 0;
}

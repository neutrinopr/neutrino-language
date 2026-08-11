#ifndef NEUTRINO_BACKEND_PROTOCOL_H
#define NEUTRINO_BACKEND_PROTOCOL_H

#include "Neutrino/BackendProjection.h"

#include "llvm/ADT/Optional.h"
#include "llvm/ADT/StringRef.h"
#include "llvm/Support/Error.h"

#include <cstdint>
#include <map>
#include <string>
#include <vector>

namespace neutrino {
namespace backend_protocol {

constexpr uint32_t kProtocolMajor = 1;
constexpr uint32_t kProtocolMinor = 0;
constexpr uint32_t kMaximumFramePayload = 64u * 1024u * 1024u;
constexpr uint16_t kMustUnderstand = 1u << 0;
constexpr uint16_t kHasTrailingRaw = 1u << 1;

enum class MessageType : uint16_t {
  Hello = 1,
  Capabilities = 2,
  Emit = 3,
  ArtifactChunk = 4,
  ArtifactBytes = 5,
  Manifest = 6,
  Cancel = 7,
  Cancelled = 8,
  Error = 9,
  Goodbye = 10,
  ProjectionBytes = 11,
};

enum class Direction {
  CoreToBackend,
  BackendToCore,
};

enum class SessionState {
  Init,
  AwaitingCapabilities,
  Ready,
  Emitting,
  Cancelling,
  Closed,
  Failed,
};

struct Frame {
  uint16_t messageType = 0;
  uint16_t flags = 0;
  std::string payload;
};

struct Hello {
  uint32_t protocolMajor = kProtocolMajor;
  uint32_t protocolMinorMax = kProtocolMinor;
  std::string coreIdentity;
};

struct Capabilities {
  uint32_t protocolMajor = kProtocolMajor;
  uint32_t protocolMinorSelected = kProtocolMinor;
  uint32_t apiVersion = 0;
  std::string targetIdentity;
  std::string targetProfileIdentity;
  uint32_t projectionSchemaMin = 0;
  uint32_t projectionSchemaMax = 0;
  std::string manifestDigest;
  std::vector<std::string> features;
  std::string licenseIdentity;
};

struct OutputSpec {
  uint32_t maxArtifacts = 0;
  uint64_t maxTotalBytes = 0;
  std::string pathPrefix;
};

struct Emit {
  uint64_t requestId = 0;
  std::string artifactEncoding;
  uint64_t artifactByteLen = 0;
  std::string artifactDigest;
  std::string targetProfileIdentity;
  OutputSpec outputSpec;
};

struct ArtifactChunk {
  uint64_t requestId = 0;
  std::string path;
  uint32_t sequence = 0;
  bool final = false;
  uint32_t byteLen = 0;
};

struct ManifestArtifact {
  std::string path;
  std::string sha256;
  uint64_t byteLen = 0;
};

struct Manifest {
  uint64_t requestId = 0;
  std::vector<ManifestArtifact> artifacts;
  std::string receiptDigest;
};

struct RequestControl {
  uint64_t requestId = 0;
};

struct ErrorMessage {
  uint64_t requestId = 0;
  std::string code;
  std::string stage;
  std::string diagnostic;
  bool retriable = false;
};

struct CompletedArtifact {
  std::string path;
  std::string bytes;
  std::string sha256;
};

struct CompletedEmission {
  uint64_t requestId = 0;
  std::vector<CompletedArtifact> artifacts;
  std::string receiptDigest;
};

struct AcceptedEmit {
  Emit request;
  projection::BackendProjectionGraph graph;
};

llvm::Expected<std::string> encodeFrame(const Frame &frame);
llvm::Expected<std::vector<Frame>> decodeFrames(llvm::StringRef bytes);
llvm::Error validateArtifactPath(llvm::StringRef path);

llvm::Expected<Frame> encodeHello(const Hello &message);
llvm::Expected<Frame> encodeCapabilities(const Capabilities &message);
llvm::Expected<std::vector<Frame>> encodeEmit(const Emit &message,
                                              llvm::StringRef projectionBytes);
llvm::Expected<std::vector<Frame>>
encodeArtifactChunk(const ArtifactChunk &message, llvm::StringRef bytes);
llvm::Expected<Frame> encodeManifest(const Manifest &message);
llvm::Expected<Frame> encodeCancel(const RequestControl &message);
llvm::Expected<Frame> encodeCancelled(const RequestControl &message);
llvm::Expected<Frame> encodeError(const ErrorMessage &message);
llvm::Expected<Frame> encodeGoodbye();

class Session {
public:
  llvm::Error consume(Direction direction, const Frame &frame);
  llvm::Error finish();

  SessionState state() const { return State; }
  llvm::Optional<Capabilities> negotiatedCapabilities() const;
  llvm::Optional<AcceptedEmit> takeAcceptedEmit();
  llvm::Optional<CompletedEmission> takeCompletedEmission();
  llvm::Optional<ErrorMessage> takePeerError();

private:
  enum class PendingRaw {
    None,
    Projection,
    Artifact,
    Skipped,
  };

  llvm::Error consumeKnown(Direction direction, MessageType type,
                           const Frame &frame);
  llvm::Error consumePendingRaw(Direction direction, const Frame &frame);
  void fail() { State = SessionState::Failed; }
  void resetRequest();

  SessionState State = SessionState::Init;
  PendingRaw Pending = PendingRaw::None;
  Direction PendingDirection = Direction::CoreToBackend;
  Hello NegotiationHello;
  Capabilities NegotiatedCapabilities;
  Emit CurrentEmit;
  ArtifactChunk CurrentChunk;
  std::string CurrentPath;
  uint32_t NextSequence = 0;
  std::string CurrentBytes;
  uint64_t TotalArtifactBytes = 0;
  std::map<std::string, CompletedArtifact> Artifacts;
  std::vector<AcceptedEmit> Accepted;
  std::vector<CompletedEmission> Completed;
  std::vector<ErrorMessage> PeerErrors;
};

} // namespace backend_protocol
} // namespace neutrino

#endif // NEUTRINO_BACKEND_PROTOCOL_H

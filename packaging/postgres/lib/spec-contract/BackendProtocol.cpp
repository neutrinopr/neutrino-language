#include "Neutrino/BackendProtocol.h"

#include "Neutrino/BackendProjection.h"
#include "Neutrino/BackendProjectionCodec.h"
#include "Neutrino/JsonUtil.h"

#include "llvm/ADT/STLExtras.h"
#include "llvm/ADT/StringExtras.h"
#include "llvm/Support/JSON.h"

#include <algorithm>
#include <limits>
#include <set>
#include <utility>

namespace neutrino {
namespace backend_protocol {
namespace {

namespace json = llvm::json;
using llvm::StringRef;

constexpr StringRef kArtifactEncoding = "neutrino.finalized-projection/1";
constexpr uint16_t kKnownFlags = kMustUnderstand | kHasTrailingRaw;

llvm::Error protocolFailure(StringRef code, StringRef stage,
                            const llvm::Twine &diagnostic) {
  return llvm::make_error<llvm::StringError>(
      (llvm::Twine(code) + ":" + stage + ":" + diagnostic).str(),
      llvm::inconvertibleErrorCode());
}

llvm::Error protocolError(const llvm::Twine &diagnostic,
                          StringRef stage = "decode") {
  return protocolFailure("E_PROTOCOL", stage, diagnostic);
}

llvm::Error frameError(const Frame &frame) {
  if (frame.payload.size() > kMaximumFramePayload)
    return protocolFailure("E_FRAME_LIMIT", "decode",
                           "frame payload exceeds 64 MiB");
  if ((frame.flags & ~kKnownFlags) != 0)
    return protocolError("frame uses reserved flags");
  return llvm::Error::success();
}

bool isKnownMessageType(uint16_t value) {
  return value >= static_cast<uint16_t>(MessageType::Hello) &&
         value <= static_cast<uint16_t>(MessageType::ProjectionBytes);
}

bool isRawMessage(MessageType type) {
  return type == MessageType::ArtifactBytes ||
         type == MessageType::ProjectionBytes;
}

uint16_t readU16(const unsigned char *bytes) {
  return static_cast<uint16_t>((static_cast<uint16_t>(bytes[0]) << 8) |
                               static_cast<uint16_t>(bytes[1]));
}

uint32_t readU32(const unsigned char *bytes) {
  return (static_cast<uint32_t>(bytes[0]) << 24) |
         (static_cast<uint32_t>(bytes[1]) << 16) |
         (static_cast<uint32_t>(bytes[2]) << 8) |
         static_cast<uint32_t>(bytes[3]);
}

void appendU16(std::string &bytes, uint16_t value) {
  bytes.push_back(static_cast<char>((value >> 8) & 0xff));
  bytes.push_back(static_cast<char>(value & 0xff));
}

void appendU32(std::string &bytes, uint32_t value) {
  bytes.push_back(static_cast<char>((value >> 24) & 0xff));
  bytes.push_back(static_cast<char>((value >> 16) & 0xff));
  bytes.push_back(static_cast<char>((value >> 8) & 0xff));
  bytes.push_back(static_cast<char>(value & 0xff));
}

llvm::Error rejectFloatingPoint(const json::Value &value, StringRef path) {
  if (value.kind() == json::Value::Number && !value.getAsInteger() &&
      !value.getAsUINT64())
    return protocolError(llvm::Twine(path) +
                         ": floating-point values are forbidden");
  if (const json::Array *array = value.getAsArray()) {
    for (size_t index = 0; index < array->size(); ++index)
      if (llvm::Error error = rejectFloatingPoint(
              (*array)[index],
              (llvm::Twine(path) + "[" + llvm::Twine(index) + "]").str()))
        return error;
  }
  if (const json::Object *object = value.getAsObject()) {
    for (const auto &field : *object)
      if (llvm::Error error = rejectFloatingPoint(
              field.second,
              (llvm::Twine(path) + "." + StringRef(field.first)).str()))
        return llvm::Error(std::move(error));
  }
  return llvm::Error::success();
}

llvm::Expected<json::Object> decodeOwnedControlObject(const Frame &frame) {
  llvm::Expected<json::Value> parsed = json::parse(frame.payload);
  if (!parsed)
    return protocolError("control payload is not valid JSON");
  if (llvm::Error error = rejectFloatingPoint(*parsed, "$"))
    return std::move(error);
  if (compactJson(*parsed) != frame.payload)
    return protocolError("control payload is not canonical JSON");
  json::Object *object = parsed->getAsObject();
  if (!object)
    return protocolError("control payload must be an object");
  return std::move(*object);
}

template <typename T>
llvm::Expected<T> requiredUnsigned(const json::Object &object, StringRef name) {
  const json::Value *wire = object.get(name);
  if (!wire)
    return protocolError(llvm::Twine("$.") + name +
                         ": required field is omitted");
  llvm::Optional<uint64_t> value = wire->getAsUINT64();
  if (!value || *value > std::numeric_limits<T>::max())
    return protocolError(llvm::Twine("$.") + name +
                         ": expected unsigned integer");
  return static_cast<T>(*value);
}

llvm::Expected<std::string> requiredString(const json::Object &object,
                                           StringRef name) {
  const json::Value *wire = object.get(name);
  if (!wire)
    return protocolError(llvm::Twine("$.") + name +
                         ": required field is omitted");
  llvm::Optional<StringRef> value = wire->getAsString();
  if (!value)
    return protocolError(llvm::Twine("$.") + name + ": expected string");
  return value->str();
}

llvm::Expected<bool> requiredBoolean(const json::Object &object,
                                     StringRef name) {
  const json::Value *wire = object.get(name);
  if (!wire)
    return protocolError(llvm::Twine("$.") + name +
                         ": required field is omitted");
  llvm::Optional<bool> value = wire->getAsBoolean();
  if (!value)
    return protocolError(llvm::Twine("$.") + name + ": expected bool");
  return *value;
}

llvm::Expected<const json::Object *>
requiredNestedObject(const json::Object &object, StringRef name) {
  const json::Value *wire = object.get(name);
  if (!wire)
    return protocolError(llvm::Twine("$.") + name +
                         ": required field is omitted");
  const json::Object *value = wire->getAsObject();
  if (!value)
    return protocolError(llvm::Twine("$.") + name + ": expected object");
  return value;
}

llvm::Expected<const json::Array *> requiredArray(const json::Object &object,
                                                  StringRef name) {
  const json::Value *wire = object.get(name);
  if (!wire)
    return protocolError(llvm::Twine("$.") + name +
                         ": required field is omitted");
  const json::Array *value = wire->getAsArray();
  if (!value)
    return protocolError(llvm::Twine("$.") + name + ": expected array");
  return value;
}

bool validDigest(StringRef digest) {
  if (!digest.consume_front("sha256:") || digest.size() != 64)
    return false;
  return llvm::all_of(digest, llvm::isHexDigit);
}

llvm::Error validatePath(StringRef path) {
  if (path.empty())
    return protocolFailure("E_PATH", "write", "artifact path is empty");
  if (path.size() > 4096)
    return protocolFailure("E_PATH", "write",
                           "artifact path exceeds 4096 bytes");
  if (path.front() == '/')
    return protocolFailure("E_PATH", "write", "artifact path is absolute");
  if (path.contains('\0'))
    return protocolFailure("E_PATH", "write", "artifact path contains NUL");
  if (path.endswith("/") || path.contains("//"))
    return protocolFailure("E_PATH", "write",
                           "artifact path contains an empty segment");
  while (!path.empty()) {
    std::pair<StringRef, StringRef> split = path.split('/');
    if (split.first.empty() || split.first == "." || split.first == "..")
      return protocolFailure("E_PATH", "write",
                             "artifact path contains an invalid segment");
    path = split.second;
  }
  return llvm::Error::success();
}

llvm::Expected<Frame> controlFrame(MessageType type, json::Object object,
                                   bool trailingRaw = false) {
  Frame frame;
  frame.messageType = static_cast<uint16_t>(type);
  frame.flags = kMustUnderstand | (trailingRaw ? kHasTrailingRaw : 0);
  frame.payload = compactJson(json::Value(std::move(object)));
  if (llvm::Error error = frameError(frame))
    return std::move(error);
  return frame;
}

Frame rawFrame(MessageType type, StringRef payload) {
  Frame frame;
  frame.messageType = static_cast<uint16_t>(type);
  frame.flags = kMustUnderstand;
  frame.payload = payload.str();
  return frame;
}

llvm::Expected<Hello> decodeHello(const Frame &frame) {
  llvm::Expected<json::Object> object = decodeOwnedControlObject(frame);
  if (!object)
    return object.takeError();
  Hello result;
  llvm::Expected<uint32_t> major =
      requiredUnsigned<uint32_t>(*object, "protocolMajor");
  llvm::Expected<uint32_t> minor =
      requiredUnsigned<uint32_t>(*object, "protocolMinorMax");
  llvm::Expected<std::string> identity =
      requiredString(*object, "coreIdentity");
  if (!major)
    return major.takeError();
  if (!minor)
    return minor.takeError();
  if (!identity)
    return identity.takeError();
  result.protocolMajor = *major;
  result.protocolMinorMax = *minor;
  result.coreIdentity = std::move(*identity);
  return result;
}

llvm::Expected<Capabilities> decodeCapabilities(const Frame &frame) {
  llvm::Expected<json::Object> object = decodeOwnedControlObject(frame);
  if (!object)
    return object.takeError();
  Capabilities result;
#define DECODE_CAPABILITY_UINT(Field, Wire)                                    \
  do {                                                                         \
    llvm::Expected<uint32_t> value =                                           \
        requiredUnsigned<uint32_t>(*object, Wire);                             \
    if (!value)                                                                \
      return value.takeError();                                                \
    result.Field = *value;                                                     \
  } while (false)
#define DECODE_CAPABILITY_STRING(Field, Wire)                                  \
  do {                                                                         \
    llvm::Expected<std::string> value = requiredString(*object, Wire);         \
    if (!value)                                                                \
      return value.takeError();                                                \
    result.Field = std::move(*value);                                          \
  } while (false)
  DECODE_CAPABILITY_UINT(protocolMajor, "protocolMajor");
  DECODE_CAPABILITY_UINT(protocolMinorSelected, "protocolMinorSelected");
  DECODE_CAPABILITY_UINT(apiVersion, "apiVersion");
  DECODE_CAPABILITY_STRING(targetIdentity, "targetIdentity");
  DECODE_CAPABILITY_STRING(targetProfileIdentity, "targetProfileIdentity");
  DECODE_CAPABILITY_UINT(projectionSchemaMin, "projectionSchemaMin");
  DECODE_CAPABILITY_UINT(projectionSchemaMax, "projectionSchemaMax");
  DECODE_CAPABILITY_STRING(manifestDigest, "manifestDigest");
  DECODE_CAPABILITY_STRING(licenseIdentity, "licenseIdentity");
#undef DECODE_CAPABILITY_UINT
#undef DECODE_CAPABILITY_STRING
  llvm::Expected<const json::Array *> features =
      requiredArray(*object, "features");
  if (!features)
    return features.takeError();
  for (const json::Value &wire : **features) {
    llvm::Optional<StringRef> feature = wire.getAsString();
    if (!feature)
      return protocolError("$.features: expected string entries");
    result.features.push_back(feature->str());
  }
  return result;
}

llvm::Expected<Emit> decodeEmit(const Frame &frame) {
  llvm::Expected<json::Object> object = decodeOwnedControlObject(frame);
  if (!object)
    return object.takeError();
  Emit result;
  llvm::Expected<uint64_t> requestId =
      requiredUnsigned<uint64_t>(*object, "requestId");
  llvm::Expected<std::string> encoding =
      requiredString(*object, "artifactEncoding");
  llvm::Expected<uint64_t> byteLen =
      requiredUnsigned<uint64_t>(*object, "artifactByteLen");
  llvm::Expected<std::string> digest =
      requiredString(*object, "artifactDigest");
  llvm::Expected<std::string> profile =
      requiredString(*object, "targetProfileIdentity");
  llvm::Expected<const json::Object *> output =
      requiredNestedObject(*object, "outputSpec");
  if (!requestId)
    return requestId.takeError();
  if (!encoding)
    return encoding.takeError();
  if (!byteLen)
    return byteLen.takeError();
  if (!digest)
    return digest.takeError();
  if (!profile)
    return profile.takeError();
  if (!output)
    return output.takeError();
  llvm::Expected<uint32_t> maxArtifacts =
      requiredUnsigned<uint32_t>(**output, "maxArtifacts");
  llvm::Expected<uint64_t> maxBytes =
      requiredUnsigned<uint64_t>(**output, "maxTotalBytes");
  llvm::Expected<std::string> prefix = requiredString(**output, "pathPrefix");
  if (!maxArtifacts)
    return maxArtifacts.takeError();
  if (!maxBytes)
    return maxBytes.takeError();
  if (!prefix)
    return prefix.takeError();
  result.requestId = *requestId;
  result.artifactEncoding = std::move(*encoding);
  result.artifactByteLen = *byteLen;
  result.artifactDigest = std::move(*digest);
  result.targetProfileIdentity = std::move(*profile);
  result.outputSpec = {*maxArtifacts, *maxBytes, std::move(*prefix)};
  return result;
}

llvm::Expected<ArtifactChunk> decodeArtifactChunk(const Frame &frame) {
  llvm::Expected<json::Object> object = decodeOwnedControlObject(frame);
  if (!object)
    return object.takeError();
  ArtifactChunk result;
  llvm::Expected<uint64_t> requestId =
      requiredUnsigned<uint64_t>(*object, "requestId");
  llvm::Expected<std::string> path = requiredString(*object, "path");
  llvm::Expected<uint32_t> sequence =
      requiredUnsigned<uint32_t>(*object, "seq");
  llvm::Expected<bool> final = requiredBoolean(*object, "final");
  llvm::Expected<uint32_t> byteLen =
      requiredUnsigned<uint32_t>(*object, "byteLen");
  if (!requestId)
    return requestId.takeError();
  if (!path)
    return path.takeError();
  if (!sequence)
    return sequence.takeError();
  if (!final)
    return final.takeError();
  if (!byteLen)
    return byteLen.takeError();
  result.requestId = *requestId;
  result.path = std::move(*path);
  result.sequence = *sequence;
  result.final = *final;
  result.byteLen = *byteLen;
  return result;
}

llvm::Expected<Manifest> decodeManifest(const Frame &frame) {
  llvm::Expected<json::Object> object = decodeOwnedControlObject(frame);
  if (!object)
    return object.takeError();
  Manifest result;
  llvm::Expected<uint64_t> requestId =
      requiredUnsigned<uint64_t>(*object, "requestId");
  llvm::Expected<const json::Array *> artifacts =
      requiredArray(*object, "artifacts");
  llvm::Expected<std::string> receipt =
      requiredString(*object, "receiptDigest");
  if (!requestId)
    return requestId.takeError();
  if (!artifacts)
    return artifacts.takeError();
  if (!receipt)
    return receipt.takeError();
  result.requestId = *requestId;
  result.receiptDigest = std::move(*receipt);
  for (const json::Value &wire : **artifacts) {
    const json::Object *entry = wire.getAsObject();
    if (!entry)
      return protocolError("$.artifacts: expected object entries");
    llvm::Expected<std::string> path = requiredString(*entry, "path");
    llvm::Expected<std::string> digest = requiredString(*entry, "sha256");
    llvm::Expected<uint64_t> byteLen =
        requiredUnsigned<uint64_t>(*entry, "byteLen");
    if (!path)
      return path.takeError();
    if (!digest)
      return digest.takeError();
    if (!byteLen)
      return byteLen.takeError();
    result.artifacts.push_back(
        {std::move(*path), std::move(*digest), *byteLen});
  }
  return result;
}

llvm::Expected<RequestControl> decodeRequestControl(const Frame &frame) {
  llvm::Expected<json::Object> object = decodeOwnedControlObject(frame);
  if (!object)
    return object.takeError();
  llvm::Expected<uint64_t> requestId =
      requiredUnsigned<uint64_t>(*object, "requestId");
  if (!requestId)
    return requestId.takeError();
  return RequestControl{*requestId};
}

bool validStage(StringRef stage) {
  return stage == "handshake" || stage == "decode" || stage == "legalize" ||
         stage == "render" || stage == "write";
}

bool validLocalCode(StringRef code) {
  static constexpr StringRef Codes[] = {
      "E_VERSION",          "E_PROJECTION_SCHEMA",
      "E_ARTIFACT_DECODE",  "E_ARTIFACT_DIGEST",
      "E_PROFILE_MISMATCH", "E_LEGALITY",
      "E_UNSUPPORTED",      "E_RENDER",
      "E_OUTPUT_LIMIT",     "E_PATH",
      "E_FRAME_LIMIT",      "E_PROTOCOL",
  };
  return llvm::is_contained(Codes, code);
}

llvm::Expected<ErrorMessage> decodeErrorMessage(const Frame &frame) {
  llvm::Expected<json::Object> object = decodeOwnedControlObject(frame);
  if (!object)
    return object.takeError();
  ErrorMessage result;
  llvm::Expected<uint64_t> requestId =
      requiredUnsigned<uint64_t>(*object, "requestId");
  llvm::Expected<std::string> code = requiredString(*object, "code");
  llvm::Expected<std::string> stage = requiredString(*object, "stage");
  llvm::Expected<std::string> diagnostic =
      requiredString(*object, "diagnostic");
  llvm::Expected<bool> retriable = requiredBoolean(*object, "retriable");
  if (!requestId)
    return requestId.takeError();
  if (!code)
    return code.takeError();
  if (!stage)
    return stage.takeError();
  if (!diagnostic)
    return diagnostic.takeError();
  if (!retriable)
    return retriable.takeError();
  if (code->empty() || !validStage(*stage))
    return protocolError("Error carries an empty code or unknown stage");
  result = {*requestId, std::move(*code), std::move(*stage),
            std::move(*diagnostic), *retriable};
  return result;
}

llvm::Error requireDirection(Direction actual, Direction expected,
                             StringRef message) {
  if (actual != expected)
    return protocolError(llvm::Twine(message) + " has the wrong direction");
  return llvm::Error::success();
}

llvm::Error requireNoTrailingRaw(const Frame &frame, StringRef message) {
  if ((frame.flags & kHasTrailingRaw) != 0)
    return protocolError(llvm::Twine(message) +
                         " unexpectedly declares trailing raw bytes");
  return llvm::Error::success();
}

llvm::Error requireTrailingRaw(const Frame &frame, StringRef message) {
  if ((frame.flags & kHasTrailingRaw) == 0)
    return protocolError(llvm::Twine(message) +
                         " must declare trailing raw bytes");
  return llvm::Error::success();
}

} // namespace

llvm::Error validateArtifactPath(StringRef path) { return validatePath(path); }

llvm::Expected<std::string> encodeFrame(const Frame &frame) {
  if (llvm::Error error = frameError(frame))
    return std::move(error);
  std::string bytes;
  bytes.reserve(8 + frame.payload.size());
  appendU32(bytes, static_cast<uint32_t>(frame.payload.size()));
  appendU16(bytes, frame.messageType);
  appendU16(bytes, frame.flags);
  bytes += frame.payload;
  return bytes;
}

llvm::Expected<std::vector<Frame>> decodeFrames(StringRef bytes) {
  std::vector<Frame> frames;
  size_t offset = 0;
  while (offset < bytes.size()) {
    if (bytes.size() - offset < 8)
      return protocolError("truncated frame header");
    const auto *header =
        reinterpret_cast<const unsigned char *>(bytes.data() + offset);
    const uint32_t payloadLen = readU32(header);
    Frame frame;
    frame.messageType = readU16(header + 4);
    frame.flags = readU16(header + 6);
    if (payloadLen > kMaximumFramePayload)
      return protocolFailure("E_FRAME_LIMIT", "decode",
                             "frame payload exceeds 64 MiB");
    if ((frame.flags & ~kKnownFlags) != 0)
      return protocolError("frame uses reserved flags");
    offset += 8;
    if (bytes.size() - offset < payloadLen)
      return protocolError("truncated frame payload");
    frame.payload = bytes.substr(offset, payloadLen).str();
    offset += payloadLen;
    frames.push_back(std::move(frame));
  }
  return frames;
}

llvm::Expected<Frame> encodeHello(const Hello &message) {
  return controlFrame(
      MessageType::Hello,
      json::Object{{"coreIdentity", message.coreIdentity},
                   {"protocolMajor", message.protocolMajor},
                   {"protocolMinorMax", message.protocolMinorMax}});
}

llvm::Expected<Frame> encodeCapabilities(const Capabilities &message) {
  json::Array features;
  for (const std::string &feature : message.features)
    features.push_back(feature);
  return controlFrame(
      MessageType::Capabilities,
      json::Object{{"apiVersion", message.apiVersion},
                   {"features", std::move(features)},
                   {"licenseIdentity", message.licenseIdentity},
                   {"manifestDigest", message.manifestDigest},
                   {"projectionSchemaMax", message.projectionSchemaMax},
                   {"projectionSchemaMin", message.projectionSchemaMin},
                   {"protocolMajor", message.protocolMajor},
                   {"protocolMinorSelected", message.protocolMinorSelected},
                   {"targetIdentity", message.targetIdentity},
                   {"targetProfileIdentity", message.targetProfileIdentity}});
}

llvm::Expected<std::vector<Frame>> encodeEmit(const Emit &message,
                                              StringRef projectionBytes) {
  if (projectionBytes.size() > kMaximumFramePayload)
    return protocolFailure("E_FRAME_LIMIT", "decode",
                           "projection payload exceeds 64 MiB");
  if (message.artifactEncoding != kArtifactEncoding)
    return protocolFailure("E_ARTIFACT_DECODE", "decode",
                           "unsupported projection artifact encoding");
  if (message.artifactByteLen != projectionBytes.size())
    return protocolFailure("E_ARTIFACT_DIGEST", "decode",
                           "projection byte length does not match header");
  if (!validDigest(message.artifactDigest) ||
      message.artifactDigest != "sha256:" + sha256Hex(projectionBytes))
    return protocolFailure("E_ARTIFACT_DIGEST", "decode",
                           "projection digest does not match header");
  llvm::Expected<projection::BackendProjectionGraph> graph =
      projection::decodeFinalizedProjection(projectionBytes);
  if (!graph)
    return protocolFailure("E_ARTIFACT_DECODE", "decode",
                           llvm::toString(graph.takeError()));
  llvm::Expected<Frame> header = controlFrame(
      MessageType::Emit,
      json::Object{
          {"artifactByteLen", message.artifactByteLen},
          {"artifactDigest", message.artifactDigest},
          {"artifactEncoding", message.artifactEncoding},
          {"outputSpec",
           json::Object{{"maxArtifacts", message.outputSpec.maxArtifacts},
                        {"maxTotalBytes", message.outputSpec.maxTotalBytes},
                        {"pathPrefix", message.outputSpec.pathPrefix}}},
          {"requestId", message.requestId},
          {"targetProfileIdentity", message.targetProfileIdentity}},
      /*trailingRaw=*/true);
  if (!header)
    return header.takeError();
  return std::vector<Frame>{
      std::move(*header),
      rawFrame(MessageType::ProjectionBytes, projectionBytes)};
}

llvm::Expected<std::vector<Frame>>
encodeArtifactChunk(const ArtifactChunk &message, StringRef bytes) {
  if (bytes.size() > kMaximumFramePayload)
    return protocolFailure("E_FRAME_LIMIT", "write",
                           "artifact payload exceeds 64 MiB");
  if (message.byteLen != bytes.size())
    return protocolError("artifact byte length does not match chunk header",
                         "write");
  if (llvm::Error error = validatePath(message.path))
    return std::move(error);
  llvm::Expected<Frame> header =
      controlFrame(MessageType::ArtifactChunk,
                   json::Object{{"byteLen", message.byteLen},
                                {"final", message.final},
                                {"path", message.path},
                                {"requestId", message.requestId},
                                {"seq", message.sequence}},
                   /*trailingRaw=*/true);
  if (!header)
    return header.takeError();
  return std::vector<Frame>{std::move(*header),
                            rawFrame(MessageType::ArtifactBytes, bytes)};
}

llvm::Expected<Frame> encodeManifest(const Manifest &message) {
  json::Array artifacts;
  for (const ManifestArtifact &artifact : message.artifacts)
    artifacts.push_back(json::Object{{"byteLen", artifact.byteLen},
                                     {"path", artifact.path},
                                     {"sha256", artifact.sha256}});
  return controlFrame(MessageType::Manifest,
                      json::Object{{"artifacts", std::move(artifacts)},
                                   {"receiptDigest", message.receiptDigest},
                                   {"requestId", message.requestId}});
}

llvm::Expected<Frame> encodeCancel(const RequestControl &message) {
  return controlFrame(MessageType::Cancel,
                      json::Object{{"requestId", message.requestId}});
}

llvm::Expected<Frame> encodeCancelled(const RequestControl &message) {
  return controlFrame(MessageType::Cancelled,
                      json::Object{{"requestId", message.requestId}});
}

llvm::Expected<Frame> encodeError(const ErrorMessage &message) {
  if (!validLocalCode(message.code) || !validStage(message.stage))
    return protocolError("Error carries an unknown code or stage");
  return controlFrame(MessageType::Error,
                      json::Object{{"code", message.code},
                                   {"diagnostic", message.diagnostic},
                                   {"requestId", message.requestId},
                                   {"retriable", message.retriable},
                                   {"stage", message.stage}});
}

llvm::Expected<Frame> encodeGoodbye() {
  return controlFrame(MessageType::Goodbye, json::Object{});
}

llvm::Error Session::consume(Direction direction, const Frame &frame) {
  if (State == SessionState::Failed)
    return protocolError("session is failed");
  if (State == SessionState::Closed) {
    fail();
    return protocolError("frame follows Goodbye");
  }
  if (llvm::Error error = frameError(frame)) {
    fail();
    return error;
  }
  if (Pending != PendingRaw::None) {
    if (llvm::Error error = consumePendingRaw(direction, frame)) {
      fail();
      return error;
    }
    return llvm::Error::success();
  }

  if (!isKnownMessageType(frame.messageType)) {
    if ((frame.flags & kMustUnderstand) != 0) {
      fail();
      return protocolError("unknown required message type");
    }
    if ((frame.flags & kHasTrailingRaw) != 0) {
      Pending = PendingRaw::Skipped;
      PendingDirection = direction;
    }
    return llvm::Error::success();
  }

  MessageType type = static_cast<MessageType>(frame.messageType);
  if (isRawMessage(type)) {
    fail();
    return protocolError("lone raw frame");
  }
  if (llvm::Error error = consumeKnown(direction, type, frame)) {
    fail();
    return error;
  }
  return llvm::Error::success();
}

llvm::Error Session::consumePendingRaw(Direction direction,
                                       const Frame &frame) {
  if (direction != PendingDirection)
    return protocolError("trailing raw frame has the wrong direction");
  if ((frame.flags & kHasTrailingRaw) != 0)
    return protocolError("trailing raw frame declares another raw frame");
  if (Pending == PendingRaw::Skipped) {
    if (isKnownMessageType(frame.messageType) &&
        !isRawMessage(static_cast<MessageType>(frame.messageType)))
      return protocolError("unknown header is not followed by a raw frame");
    Pending = PendingRaw::None;
    return llvm::Error::success();
  }

  MessageType expected = Pending == PendingRaw::Projection
                             ? MessageType::ProjectionBytes
                             : MessageType::ArtifactBytes;
  if (frame.messageType != static_cast<uint16_t>(expected))
    return protocolError("header is not followed by its required raw frame");

  if (Pending == PendingRaw::Projection) {
    if (frame.payload.size() != CurrentEmit.artifactByteLen)
      return protocolFailure("E_ARTIFACT_DIGEST", "decode",
                             "projection byte length does not match header");
    if (!validDigest(CurrentEmit.artifactDigest) ||
        CurrentEmit.artifactDigest != "sha256:" + sha256Hex(frame.payload))
      return protocolFailure("E_ARTIFACT_DIGEST", "decode",
                             "projection digest does not match header");
    llvm::Expected<projection::BackendProjectionGraph> graph =
        projection::decodeFinalizedProjection(frame.payload);
    if (!graph)
      return protocolFailure("E_ARTIFACT_DECODE", "decode",
                             llvm::toString(graph.takeError()));
    const uint32_t schemaVersion = static_cast<uint32_t>(graph->schemaVersion);
    if (schemaVersion < NegotiatedCapabilities.projectionSchemaMin ||
        schemaVersion > NegotiatedCapabilities.projectionSchemaMax)
      return protocolFailure("E_PROJECTION_SCHEMA", "decode",
                             "projection schema is outside package bounds");
    Accepted.push_back({CurrentEmit, std::move(*graph)});
    Pending = PendingRaw::None;
    State = SessionState::Emitting;
    return llvm::Error::success();
  }

  if (frame.payload.size() != CurrentChunk.byteLen)
    return protocolError("artifact byte length does not match chunk header",
                         "write");
  if (frame.payload.size() > CurrentEmit.outputSpec.maxTotalBytes ||
      TotalArtifactBytes >
          CurrentEmit.outputSpec.maxTotalBytes - frame.payload.size())
    return protocolFailure("E_OUTPUT_LIMIT", "write",
                           "artifact bytes exceed output limit");
  TotalArtifactBytes += frame.payload.size();
  CurrentBytes += frame.payload;
  ++NextSequence;
  if (CurrentChunk.final) {
    if (Artifacts.size() >= CurrentEmit.outputSpec.maxArtifacts)
      return protocolFailure("E_OUTPUT_LIMIT", "write",
                             "artifact count exceeds output limit");
    std::string digest = "sha256:" + sha256Hex(CurrentBytes);
    CompletedArtifact artifact{CurrentPath, std::move(CurrentBytes),
                               std::move(digest)};
    Artifacts.emplace(CurrentPath, std::move(artifact));
    CurrentPath.clear();
    CurrentBytes.clear();
    NextSequence = 0;
  }
  Pending = PendingRaw::None;
  return llvm::Error::success();
}

llvm::Error Session::consumeKnown(Direction direction, MessageType type,
                                  const Frame &frame) {
  if (type == MessageType::Emit || type == MessageType::ArtifactChunk) {
    if (llvm::Error error = requireTrailingRaw(
            frame, type == MessageType::Emit ? "Emit" : "ArtifactChunk"))
      return error;
  } else if (llvm::Error error =
                 requireNoTrailingRaw(frame, "control message")) {
    return error;
  }

  switch (type) {
  case MessageType::Hello: {
    if (State != SessionState::Init)
      return protocolError("Hello is out of order", "handshake");
    if (llvm::Error error =
            requireDirection(direction, Direction::CoreToBackend, "Hello"))
      return error;
    llvm::Expected<Hello> hello = decodeHello(frame);
    if (!hello)
      return hello.takeError();
    if (hello->protocolMajor != kProtocolMajor)
      return protocolFailure("E_VERSION", "handshake",
                             "protocol major does not match");
    NegotiationHello = std::move(*hello);
    State = SessionState::AwaitingCapabilities;
    return llvm::Error::success();
  }
  case MessageType::Capabilities: {
    if (State != SessionState::AwaitingCapabilities)
      return protocolError("Capabilities is out of order", "handshake");
    if (llvm::Error error = requireDirection(
            direction, Direction::BackendToCore, "Capabilities"))
      return error;
    llvm::Expected<Capabilities> capabilities = decodeCapabilities(frame);
    if (!capabilities)
      return capabilities.takeError();
    if (capabilities->protocolMajor != kProtocolMajor ||
        capabilities->protocolMinorSelected >
            NegotiationHello.protocolMinorMax ||
        capabilities->protocolMinorSelected > kProtocolMinor)
      return protocolFailure("E_VERSION", "handshake",
                             "protocol version cannot be negotiated");
    if (capabilities->projectionSchemaMin > capabilities->projectionSchemaMax)
      return protocolFailure("E_VERSION", "handshake",
                             "projection schema bounds are reversed");
    NegotiatedCapabilities = std::move(*capabilities);
    State = SessionState::Ready;
    return llvm::Error::success();
  }
  case MessageType::Emit: {
    if (State != SessionState::Ready)
      return protocolError("Emit is out of order");
    if (llvm::Error error =
            requireDirection(direction, Direction::CoreToBackend, "Emit"))
      return error;
    llvm::Expected<Emit> emit = decodeEmit(frame);
    if (!emit)
      return emit.takeError();
    if (emit->requestId == 0)
      return protocolError("Emit requestId must be nonzero");
    if (emit->artifactEncoding != kArtifactEncoding)
      return protocolFailure("E_ARTIFACT_DECODE", "decode",
                             "unsupported projection artifact encoding");
    if (!validDigest(emit->artifactDigest))
      return protocolFailure("E_ARTIFACT_DIGEST", "decode",
                             "projection digest is malformed");
    if (emit->targetProfileIdentity !=
        NegotiatedCapabilities.targetProfileIdentity)
      return protocolFailure("E_PROFILE_MISMATCH", "decode",
                             "target profile identity does not match");
    CurrentEmit = std::move(*emit);
    Pending = PendingRaw::Projection;
    PendingDirection = direction;
    return llvm::Error::success();
  }
  case MessageType::ArtifactChunk: {
    if (State != SessionState::Emitting)
      return protocolError("ArtifactChunk is out of order", "write");
    if (llvm::Error error = requireDirection(
            direction, Direction::BackendToCore, "ArtifactChunk"))
      return error;
    llvm::Expected<ArtifactChunk> chunk = decodeArtifactChunk(frame);
    if (!chunk)
      return chunk.takeError();
    if (chunk->requestId != CurrentEmit.requestId)
      return protocolError("ArtifactChunk requestId does not match", "write");
    if (llvm::Error error = validatePath(chunk->path))
      return error;
    if (Artifacts.count(chunk->path) != 0)
      return protocolError("artifact path has multiple chunk runs", "write");
    if (CurrentPath.empty()) {
      if (chunk->sequence != 0)
        return protocolError("artifact sequence must start at zero", "write");
      CurrentPath = chunk->path;
    } else if (chunk->path != CurrentPath) {
      return protocolError("artifact chunk runs are interleaved", "write");
    } else if (chunk->sequence != NextSequence) {
      return protocolError("artifact sequence is not contiguous", "write");
    }
    CurrentChunk = std::move(*chunk);
    Pending = PendingRaw::Artifact;
    PendingDirection = direction;
    return llvm::Error::success();
  }
  case MessageType::Manifest: {
    if (State != SessionState::Emitting)
      return protocolError("Manifest is out of order", "write");
    if (llvm::Error error =
            requireDirection(direction, Direction::BackendToCore, "Manifest"))
      return error;
    if (!CurrentPath.empty())
      return protocolError("Manifest precedes final artifact chunk", "write");
    llvm::Expected<Manifest> manifest = decodeManifest(frame);
    if (!manifest)
      return manifest.takeError();
    if (manifest->requestId != CurrentEmit.requestId)
      return protocolError("Manifest requestId does not match", "write");
    if (!validDigest(manifest->receiptDigest))
      return protocolFailure("E_ARTIFACT_DIGEST", "write",
                             "receipt digest is malformed");
    std::set<std::string> manifestPaths;
    for (const ManifestArtifact &entry : manifest->artifacts) {
      if (llvm::Error error = validatePath(entry.path))
        return error;
      if (!manifestPaths.insert(entry.path).second)
        return protocolError("Manifest contains a duplicate path", "write");
      auto assembled = Artifacts.find(entry.path);
      if (assembled == Artifacts.end())
        return protocolError("Manifest path set does not match chunks",
                             "write");
      if (!validDigest(entry.sha256) ||
          entry.sha256 != assembled->second.sha256)
        return protocolFailure("E_ARTIFACT_DIGEST", "write",
                               "artifact digest does not match chunks");
      if (entry.byteLen != assembled->second.bytes.size())
        return protocolError("artifact length does not match chunks", "write");
    }
    if (manifestPaths.size() != Artifacts.size())
      return protocolError("Manifest path set does not match chunks", "write");
    CompletedEmission completed;
    completed.requestId = manifest->requestId;
    completed.receiptDigest = manifest->receiptDigest;
    for (auto &entry : Artifacts)
      completed.artifacts.push_back(std::move(entry.second));
    Completed.push_back(std::move(completed));
    resetRequest();
    State = SessionState::Ready;
    return llvm::Error::success();
  }
  case MessageType::Cancel: {
    if (State != SessionState::Emitting)
      return protocolError("Cancel is out of order", "render");
    if (llvm::Error error =
            requireDirection(direction, Direction::CoreToBackend, "Cancel"))
      return error;
    llvm::Expected<RequestControl> cancel = decodeRequestControl(frame);
    if (!cancel)
      return cancel.takeError();
    if (cancel->requestId != CurrentEmit.requestId)
      return protocolError("Cancel requestId does not match", "render");
    State = SessionState::Cancelling;
    return llvm::Error::success();
  }
  case MessageType::Cancelled: {
    if (State != SessionState::Cancelling)
      return protocolError("Cancelled is out of order", "render");
    if (llvm::Error error =
            requireDirection(direction, Direction::BackendToCore, "Cancelled"))
      return error;
    llvm::Expected<RequestControl> cancelled = decodeRequestControl(frame);
    if (!cancelled)
      return cancelled.takeError();
    if (cancelled->requestId != CurrentEmit.requestId)
      return protocolError("Cancelled requestId does not match", "render");
    resetRequest();
    State = SessionState::Ready;
    return llvm::Error::success();
  }
  case MessageType::Error: {
    if (llvm::Error error =
            requireDirection(direction, Direction::BackendToCore, "Error"))
      return error;
    llvm::Expected<ErrorMessage> message = decodeErrorMessage(frame);
    if (!message)
      return message.takeError();
    if (State == SessionState::AwaitingCapabilities) {
      if (message->requestId != 0)
        return protocolError("pre-request Error uses nonzero requestId",
                             "handshake");
      PeerErrors.push_back(std::move(*message));
      State = SessionState::Failed;
      return llvm::Error::success();
    }
    if (State != SessionState::Emitting)
      return protocolError("Error is out of order");
    if (message->requestId != CurrentEmit.requestId)
      return protocolError("Error requestId does not match");
    PeerErrors.push_back(std::move(*message));
    resetRequest();
    State = SessionState::Ready;
    return llvm::Error::success();
  }
  case MessageType::Goodbye: {
    if (State != SessionState::Ready)
      return protocolError("Goodbye is out of order");
    if (llvm::Error error =
            requireDirection(direction, Direction::CoreToBackend, "Goodbye"))
      return error;
    llvm::Expected<json::Object> object = decodeOwnedControlObject(frame);
    if (!object)
      return object.takeError();
    State = SessionState::Closed;
    return llvm::Error::success();
  }
  case MessageType::ArtifactBytes:
  case MessageType::ProjectionBytes:
    return protocolError("lone raw frame");
  }
  return protocolError("unknown message type");
}

llvm::Error Session::finish() {
  if (State == SessionState::Closed)
    return llvm::Error::success();
  fail();
  return protocolError(Pending != PendingRaw::None
                           ? "stream ended in a header/raw pair"
                           : "stream ended before Goodbye");
}

llvm::Optional<CompletedEmission> Session::takeCompletedEmission() {
  if (Completed.empty())
    return llvm::None;
  llvm::Optional<CompletedEmission> result = std::move(Completed.front());
  Completed.erase(Completed.begin());
  return result;
}

llvm::Optional<Capabilities> Session::negotiatedCapabilities() const {
  if (State == SessionState::Init ||
      State == SessionState::AwaitingCapabilities)
    return llvm::None;
  return NegotiatedCapabilities;
}

llvm::Optional<AcceptedEmit> Session::takeAcceptedEmit() {
  if (Accepted.empty())
    return llvm::None;
  llvm::Optional<AcceptedEmit> result = std::move(Accepted.front());
  Accepted.erase(Accepted.begin());
  return result;
}

llvm::Optional<ErrorMessage> Session::takePeerError() {
  if (PeerErrors.empty())
    return llvm::None;
  llvm::Optional<ErrorMessage> result = std::move(PeerErrors.front());
  PeerErrors.erase(PeerErrors.begin());
  return result;
}

void Session::resetRequest() {
  Pending = PendingRaw::None;
  CurrentEmit = {};
  CurrentChunk = {};
  CurrentPath.clear();
  NextSequence = 0;
  CurrentBytes.clear();
  TotalArtifactBytes = 0;
  Artifacts.clear();
}

} // namespace backend_protocol
} // namespace neutrino

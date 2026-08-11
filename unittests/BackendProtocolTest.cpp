// SPDX-License-Identifier: Apache-2.0
#include "Neutrino/BackendProtocol.h"
#include "Neutrino/BackendProjection.h"
#include "Neutrino/BackendProjectionCodec.h"
#include "Neutrino/CoordinationPlan.h"
#include "Neutrino/JsonUtil.h"

#include "llvm/Support/Error.h"

#include "gtest/gtest.h"

#include <string>
#include <utility>
#include <vector>

using namespace neutrino;
using namespace neutrino::backend_protocol;

namespace {

template <typename T> T take(llvm::Expected<T> value) {
  if (!value) {
    ADD_FAILURE() << llvm::toString(value.takeError());
    return {};
  }
  return std::move(*value);
}

void consumeOk(Session &session, Direction direction, const Frame &frame) {
  llvm::Error error = session.consume(direction, frame);
  ASSERT_FALSE(static_cast<bool>(error)) << llvm::toString(std::move(error));
}

void expectError(llvm::Error error, llvm::StringRef needle) {
  ASSERT_TRUE(static_cast<bool>(error));
  EXPECT_NE(llvm::toString(std::move(error)).find(needle.str()),
            std::string::npos);
}

CoordinationPlan protocolPlan() {
  CoordinationPlan plan;
  plan.procedure = "protocol_fixture";
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

std::string projectionBytes() {
  llvm::Expected<projection::BackendProjectionGraph> graph =
      projection::projectBackendGraph(protocolPlan());
  if (!graph) {
    ADD_FAILURE() << llvm::toString(graph.takeError());
    return {};
  }
  return take(projection::encodeFinalizedProjection(*graph));
}

Hello hello() { return {kProtocolMajor, kProtocolMinor, "core:test"}; }

Capabilities capabilities() {
  return {kProtocolMajor,
          kProtocolMinor,
          1,
          "test-backend",
          "profile:test",
          static_cast<uint32_t>(projection::kProjectionSchemaVersion),
          static_cast<uint32_t>(projection::kProjectionSchemaVersion),
          "sha256:" + std::string(64, '1'),
          {"emit"},
          "MIT"};
}

void handshake(Session &session) {
  consumeOk(session, Direction::CoreToBackend, take(encodeHello(hello())));
  consumeOk(session, Direction::BackendToCore,
            take(encodeCapabilities(capabilities())));
  ASSERT_EQ(session.state(), SessionState::Ready);
}

Emit emitFor(llvm::StringRef bytes, uint64_t requestId = 41) {
  Emit emit;
  emit.requestId = requestId;
  emit.artifactEncoding = "neutrino.finalized-projection/1";
  emit.artifactByteLen = bytes.size();
  emit.artifactDigest = "sha256:" + sha256Hex(bytes);
  emit.targetProfileIdentity = "profile:test";
  emit.outputSpec = {4, 4096, "/tmp/core-owned-output"};
  return emit;
}

void startEmit(Session &session, llvm::StringRef bytes,
               uint64_t requestId = 41) {
  std::vector<Frame> frames =
      take(encodeEmit(emitFor(bytes, requestId), bytes));
  ASSERT_EQ(frames.size(), 2u);
  consumeOk(session, Direction::CoreToBackend, frames[0]);
  ASSERT_EQ(session.state(), SessionState::Ready);
  consumeOk(session, Direction::CoreToBackend, frames[1]);
  ASSERT_EQ(session.state(), SessionState::Emitting);
}

void sendChunk(Session &session, uint64_t requestId, llvm::StringRef path,
               uint32_t sequence, bool final, llvm::StringRef bytes) {
  ArtifactChunk chunk{requestId, path.str(), sequence, final,
                      static_cast<uint32_t>(bytes.size())};
  std::vector<Frame> frames = take(encodeArtifactChunk(chunk, bytes));
  ASSERT_EQ(frames.size(), 2u);
  consumeOk(session, Direction::BackendToCore, frames[0]);
  consumeOk(session, Direction::BackendToCore, frames[1]);
}

Frame raw(MessageType type, llvm::StringRef payload) {
  return {static_cast<uint16_t>(type), kMustUnderstand, payload.str()};
}

} // namespace

TEST(BackendProtocol, FrameEncodingIsBigEndianDeterministicAndBounded) {
  Frame frame{static_cast<uint16_t>(MessageType::Hello), kMustUnderstand,
              "abc"};
  std::string first = take(encodeFrame(frame));
  std::string second = take(encodeFrame(frame));
  EXPECT_EQ(first, second);
  EXPECT_EQ(take(encodeHello(hello())).payload,
            take(encodeHello(hello())).payload);
  ASSERT_EQ(first.size(), 11u);
  EXPECT_EQ(static_cast<unsigned char>(first[0]), 0u);
  EXPECT_EQ(static_cast<unsigned char>(first[3]), 3u);
  EXPECT_EQ(static_cast<unsigned char>(first[5]), 1u);
  EXPECT_EQ(static_cast<unsigned char>(first[7]), kMustUnderstand);
  std::vector<Frame> decoded = take(decodeFrames(first));
  ASSERT_EQ(decoded.size(), 1u);
  EXPECT_EQ(decoded[0].payload, "abc");

  Frame reserved = frame;
  reserved.flags |= 1u << 2;
  llvm::Expected<std::string> reservedResult = encodeFrame(reserved);
  ASSERT_FALSE(static_cast<bool>(reservedResult));
  EXPECT_NE(llvm::toString(reservedResult.takeError()).find("E_PROTOCOL"),
            std::string::npos);
  std::string reservedWire = first;
  reservedWire[7] = static_cast<char>(kMustUnderstand | (1u << 2));
  llvm::Expected<std::vector<Frame>> reservedDecode =
      decodeFrames(reservedWire);
  ASSERT_FALSE(static_cast<bool>(reservedDecode));
  EXPECT_NE(llvm::toString(reservedDecode.takeError()).find("E_PROTOCOL"),
            std::string::npos);

  std::string oversized = {char(0x04), char(0x00), char(0x00), char(0x01),
                           char(0x00), char(0x01), char(0x00), char(0x01)};
  llvm::Expected<std::vector<Frame>> oversizedResult = decodeFrames(oversized);
  ASSERT_FALSE(static_cast<bool>(oversizedResult));
  EXPECT_NE(llvm::toString(oversizedResult.takeError()).find("E_FRAME_LIMIT"),
            std::string::npos);

  expectError(decodeFrames(first.substr(0, first.size() - 1)).takeError(),
              "truncated frame payload");
}

TEST(BackendProtocol, CanonicalControlsAndRequiredFieldsFailClosed) {
  Session whitespace;
  Frame noncanonical = take(encodeHello(hello()));
  noncanonical.payload = " " + noncanonical.payload;
  expectError(whitespace.consume(Direction::CoreToBackend, noncanonical),
              "not canonical JSON");

  Session floating;
  Frame floatHello = take(encodeHello(hello()));
  floatHello.payload = "{\"coreIdentity\":\"core:test\",\"protocolMajor\":1.5,"
                       "\"protocolMinorMax\":0}";
  expectError(floating.consume(Direction::CoreToBackend, floatHello),
              "floating-point values are forbidden");

  Session omitted;
  Frame missing = take(encodeHello(hello()));
  missing.payload = "{\"coreIdentity\":\"core:test\",\"protocolMajor\":1}";
  expectError(omitted.consume(Direction::CoreToBackend, missing),
              "required field is omitted");
}

TEST(BackendProtocol, HandshakeNegotiatesOnlyTheSupportedVersion) {
  Session wrongMajor;
  Hello incompatible = hello();
  incompatible.protocolMajor = 2;
  expectError(wrongMajor.consume(Direction::CoreToBackend,
                                 take(encodeHello(incompatible))),
              "E_VERSION");

  Session wrongMinor;
  consumeOk(wrongMinor, Direction::CoreToBackend, take(encodeHello(hello())));
  Capabilities future = capabilities();
  future.protocolMinorSelected = 1;
  expectError(wrongMinor.consume(Direction::BackendToCore,
                                 take(encodeCapabilities(future))),
              "E_VERSION");
}

TEST(BackendProtocol, UnknownFramesSkipAtomicallyButRequiredAndLoneRawFail) {
  Session skipped;
  handshake(skipped);
  consumeOk(skipped, Direction::BackendToCore, {77, 0, "{}"});
  EXPECT_EQ(skipped.state(), SessionState::Ready);
  consumeOk(skipped, Direction::BackendToCore, {78, kHasTrailingRaw, "{}"});
  consumeOk(skipped, Direction::BackendToCore, {79, 0, "opaque"});
  EXPECT_EQ(skipped.state(), SessionState::Ready);

  Session required;
  handshake(required);
  expectError(
      required.consume(Direction::BackendToCore, {77, kMustUnderstand, "{}"}),
      "unknown required message type");

  Session loneRaw;
  handshake(loneRaw);
  expectError(loneRaw.consume(Direction::CoreToBackend,
                              raw(MessageType::ProjectionBytes, "orphan")),
              "lone raw frame");

  Session truncatedPair;
  handshake(truncatedPair);
  std::string bytes = projectionBytes();
  std::vector<Frame> emit = take(encodeEmit(emitFor(bytes), bytes));
  consumeOk(truncatedPair, Direction::CoreToBackend, emit[0]);
  expectError(truncatedPair.finish(), "header/raw pair");
}

TEST(BackendProtocol, ProjectionPairChecksTypeLengthDigestAndCanonicalBytes) {
  std::string projection = projectionBytes();

  Session digestMismatch;
  handshake(digestMismatch);
  std::vector<Frame> emit = take(encodeEmit(emitFor(projection), projection));
  consumeOk(digestMismatch, Direction::CoreToBackend, emit[0]);
  emit[1].payload.back() ^= 1;
  expectError(digestMismatch.consume(Direction::CoreToBackend, emit[1]),
              "E_ARTIFACT_DIGEST");

  Session wrongRawType;
  handshake(wrongRawType);
  emit = take(encodeEmit(emitFor(projection), projection));
  consumeOk(wrongRawType, Direction::CoreToBackend, emit[0]);
  emit[1].messageType = static_cast<uint16_t>(MessageType::ArtifactBytes);
  expectError(wrongRawType.consume(Direction::CoreToBackend, emit[1]),
              "required raw frame");
}

TEST(BackendProtocol, AcceptedEmitAndPeerErrorsRemainObservable) {
  std::string projection = projectionBytes();
  Session session;
  handshake(session);
  startEmit(session, projection);

  llvm::Optional<AcceptedEmit> accepted = session.takeAcceptedEmit();
  ASSERT_TRUE(accepted.hasValue());
  EXPECT_EQ(accepted->request.requestId, 41u);
  EXPECT_EQ(accepted->request.outputSpec.pathPrefix, "/tmp/core-owned-output");
  llvm::Expected<projection::FinalizedProjectionSequence> sequence =
      projection::consumeFinalizedProjectionSequence(accepted->graph);
  ASSERT_TRUE(static_cast<bool>(sequence))
      << llvm::toString(sequence.takeError());
  EXPECT_FALSE(session.takeAcceptedEmit().hasValue());

  ErrorMessage failure{41, "E_RENDER", "render", "failed", false};
  consumeOk(session, Direction::BackendToCore, take(encodeError(failure)));
  llvm::Optional<ErrorMessage> observed = session.takePeerError();
  ASSERT_TRUE(observed.hasValue());
  EXPECT_EQ(observed->requestId, 41u);
  EXPECT_EQ(observed->code, "E_RENDER");
  EXPECT_EQ(observed->stage, "render");
  EXPECT_FALSE(session.takePeerError().hasValue());
}

TEST(BackendProtocol, CompleteEmissionValidatesProjectionChunksAndManifest) {
  Session session;
  handshake(session);
  std::string projection = projectionBytes();
  startEmit(session, projection);
  sendChunk(session, 41, "src/Foo.sol", 0, false, "ab");
  sendChunk(session, 41, "src/Foo.sol", 1, true, "cd");
  sendChunk(session, 41, "test/Foo.t.sol", 0, true, llvm::StringRef("\0x", 2));

  Manifest manifest;
  manifest.requestId = 41;
  manifest.artifacts = {
      {"src/Foo.sol", "sha256:" + sha256Hex("abcd"), 4},
      {"test/Foo.t.sol", "sha256:" + sha256Hex(llvm::StringRef("\0x", 2)), 2},
  };
  manifest.receiptDigest = "sha256:" + std::string(64, '2');
  consumeOk(session, Direction::BackendToCore, take(encodeManifest(manifest)));
  ASSERT_EQ(session.state(), SessionState::Ready);
  llvm::Optional<CompletedEmission> completed = session.takeCompletedEmission();
  ASSERT_TRUE(completed.hasValue());
  EXPECT_EQ(completed->requestId, 41u);
  ASSERT_EQ(completed->artifacts.size(), 2u);
  EXPECT_EQ(completed->artifacts[0].path, "src/Foo.sol");
  EXPECT_EQ(completed->artifacts[0].bytes, "abcd");
  EXPECT_EQ(completed->artifacts[1].path, "test/Foo.t.sol");
  EXPECT_EQ(completed->artifacts[1].bytes, std::string("\0x", 2));

  consumeOk(session, Direction::CoreToBackend, take(encodeGoodbye()));
  EXPECT_EQ(session.state(), SessionState::Closed);
  llvm::Error finished = session.finish();
  EXPECT_FALSE(static_cast<bool>(finished))
      << llvm::toString(std::move(finished));
}

TEST(BackendProtocol, OrderingRequestIdsAndCancellationAreStrict) {
  Session badOrder;
  handshake(badOrder);
  Manifest empty{41, {}, "sha256:" + std::string(64, '3')};
  expectError(
      badOrder.consume(Direction::BackendToCore, take(encodeManifest(empty))),
      "Manifest is out of order");

  Session badRequest;
  handshake(badRequest);
  std::string projection = projectionBytes();
  startEmit(badRequest, projection);
  ArtifactChunk wrong{42, "out/a", 0, true, 1};
  std::vector<Frame> wrongFrames = take(encodeArtifactChunk(wrong, "x"));
  expectError(badRequest.consume(Direction::BackendToCore, wrongFrames.front()),
              "requestId does not match");

  Session cancelled;
  handshake(cancelled);
  startEmit(cancelled, projection);
  consumeOk(cancelled, Direction::CoreToBackend, take(encodeCancel({41})));
  EXPECT_EQ(cancelled.state(), SessionState::Cancelling);
  consumeOk(cancelled, Direction::BackendToCore, take(encodeCancelled({41})));
  EXPECT_EQ(cancelled.state(), SessionState::Ready);
  consumeOk(cancelled, Direction::CoreToBackend, take(encodeGoodbye()));

  Session backendError;
  handshake(backendError);
  startEmit(backendError, projection);
  ErrorMessage renderFailure{41, "E_RENDER", "render", "failed", false};
  consumeOk(backendError, Direction::BackendToCore,
            take(encodeError(renderFailure)));
  EXPECT_EQ(backendError.state(), SessionState::Ready);
  llvm::Optional<ErrorMessage> observed = backendError.takePeerError();
  ASSERT_TRUE(observed.hasValue());
  EXPECT_EQ(observed->code, "E_RENDER");
}

TEST(BackendProtocol, AdditivePeerErrorCodesArePreserved) {
  ErrorMessage future{41, "E_FUTURE_RENDER", "render", "future", false};
  llvm::Expected<Frame> localEncoding = encodeError(future);
  ASSERT_FALSE(static_cast<bool>(localEncoding));
  EXPECT_NE(llvm::toString(localEncoding.takeError()).find("unknown code"),
            std::string::npos);

  Session session;
  handshake(session);
  startEmit(session, projectionBytes());
  Frame futureWire{
      static_cast<uint16_t>(MessageType::Error),
      kMustUnderstand,
      "{\"code\":\"E_FUTURE_RENDER\",\"diagnostic\":\"future\","
      "\"requestId\":41,\"retriable\":false,\"stage\":\"render\"}",
  };
  consumeOk(session, Direction::BackendToCore, futureWire);
  ASSERT_EQ(session.state(), SessionState::Ready);
  llvm::Optional<ErrorMessage> observed = session.takePeerError();
  ASSERT_TRUE(observed.hasValue());
  EXPECT_EQ(observed->code, "E_FUTURE_RENDER");
  EXPECT_EQ(observed->stage, "render");
}

TEST(BackendProtocol, ChunkPathSequenceAndInterleavingFailClosed) {
  std::string projection = projectionBytes();

  Session badPath;
  handshake(badPath);
  startEmit(badPath, projection);
  Frame pathHeader =
      take(encodeArtifactChunk({41, "out/good", 0, true, 1}, "x"))[0];
  pathHeader.payload =
      "{\"byteLen\":1,\"final\":true,\"path\":\"out/../escape\","
      "\"requestId\":41,\"seq\":0}";
  expectError(badPath.consume(Direction::BackendToCore, pathHeader), "E_PATH");

  Session badSequence;
  handshake(badSequence);
  startEmit(badSequence, projection);
  std::vector<Frame> sequence =
      take(encodeArtifactChunk({41, "out/a", 1, true, 1}, "x"));
  expectError(badSequence.consume(Direction::BackendToCore, sequence[0]),
              "start at zero");

  Session interleaved;
  handshake(interleaved);
  startEmit(interleaved, projection);
  sendChunk(interleaved, 41, "out/a", 0, false, "x");
  std::vector<Frame> other =
      take(encodeArtifactChunk({41, "out/b", 0, true, 1}, "y"));
  expectError(interleaved.consume(Direction::BackendToCore, other[0]),
              "interleaved");

  Session duplicateRun;
  handshake(duplicateRun);
  startEmit(duplicateRun, projection);
  sendChunk(duplicateRun, 41, "out/a", 0, true, "x");
  std::vector<Frame> duplicate =
      take(encodeArtifactChunk({41, "out/a", 0, true, 1}, "y"));
  expectError(duplicateRun.consume(Direction::BackendToCore, duplicate[0]),
              "multiple chunk runs");

  Session outputLimit;
  handshake(outputLimit);
  Emit limited = emitFor(projection);
  limited.outputSpec.maxTotalBytes = 1;
  std::vector<Frame> limitedEmit = take(encodeEmit(limited, projection));
  consumeOk(outputLimit, Direction::CoreToBackend, limitedEmit[0]);
  consumeOk(outputLimit, Direction::CoreToBackend, limitedEmit[1]);
  std::vector<Frame> tooLarge =
      take(encodeArtifactChunk({41, "out/a", 0, true, 2}, "xy"));
  consumeOk(outputLimit, Direction::BackendToCore, tooLarge[0]);
  expectError(outputLimit.consume(Direction::BackendToCore, tooLarge[1]),
              "E_OUTPUT_LIMIT");
}

TEST(BackendProtocol, ManifestSetLengthAndDigestMustMatchAssembly) {
  std::string projection = projectionBytes();

  Session digestMismatch;
  handshake(digestMismatch);
  startEmit(digestMismatch, projection);
  sendChunk(digestMismatch, 41, "out/a", 0, true, "abc");
  Manifest badDigest{
      41,
      {{"out/a", "sha256:" + std::string(64, '0'), 3}},
      "sha256:" + std::string(64, '4'),
  };
  expectError(digestMismatch.consume(Direction::BackendToCore,
                                     take(encodeManifest(badDigest))),
              "E_ARTIFACT_DIGEST");

  Session missing;
  handshake(missing);
  startEmit(missing, projection);
  sendChunk(missing, 41, "out/a", 0, true, "abc");
  Manifest missingPath{41, {}, "sha256:" + std::string(64, '5')};
  expectError(missing.consume(Direction::BackendToCore,
                              take(encodeManifest(missingPath))),
              "path set does not match");

  Session wrongLength;
  handshake(wrongLength);
  startEmit(wrongLength, projection);
  sendChunk(wrongLength, 41, "out/a", 0, true, "abc");
  Manifest badLength{
      41,
      {{"out/a", "sha256:" + sha256Hex("abc"), 4}},
      "sha256:" + std::string(64, '6'),
  };
  expectError(wrongLength.consume(Direction::BackendToCore,
                                  take(encodeManifest(badLength))),
              "length does not match");

  Session unfinished;
  handshake(unfinished);
  startEmit(unfinished, projection);
  sendChunk(unfinished, 41, "out/a", 0, false, "abc");
  Manifest beforeFinal{41, {}, "sha256:" + std::string(64, '7')};
  expectError(unfinished.consume(Direction::BackendToCore,
                                 take(encodeManifest(beforeFinal))),
              "precedes final");
}

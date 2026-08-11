#include "Neutrino/BackendDispatchReceipt.h"

#include "Neutrino/BackendProtocol.h"
#include "Neutrino/JsonUtil.h"

#include "llvm/ADT/STLExtras.h"
#include "llvm/Support/JSON.h"

#include <algorithm>
#include <initializer_list>
#include <set>
#include <string>
#include <utility>

namespace neutrino {
namespace backend_dispatch_receipt {
namespace {

using llvm::StringRef;

llvm::Error receiptError(const llvm::Twine &diagnostic) {
  return llvm::make_error<llvm::StringError>(
      (llvm::Twine("E_RECEIPT:receipt:") + diagnostic).str(),
      llvm::inconvertibleErrorCode());
}

bool validDigest(StringRef digest) {
  if (!digest.consume_front("sha256:") || digest.size() != 64)
    return false;
  return llvm::all_of(digest, [](char value) {
    return (value >= '0' && value <= '9') || (value >= 'a' && value <= 'f');
  });
}

llvm::Error requireClosed(const llvm::json::Object &object, StringRef context,
                          std::initializer_list<StringRef> expectedFields) {
  std::set<StringRef> expected(expectedFields.begin(), expectedFields.end());
  if (object.size() != expected.size())
    return receiptError(context + " has missing or unknown fields");
  for (const auto &entry : object)
    if (!expected.count(entry.first))
      return receiptError(context + " has unknown field '" + entry.first.str() +
                          "'");
  return llvm::Error::success();
}

llvm::Expected<StringRef> stringField(const llvm::json::Object &object,
                                      StringRef field, StringRef context) {
  llvm::Optional<StringRef> value = object.getString(field);
  if (!value || value->empty())
    return receiptError(context + " has missing/invalid " + field);
  return *value;
}

llvm::Expected<uint64_t> uintField(const llvm::json::Object &object,
                                   StringRef field, StringRef context,
                                   bool allowZero = true) {
  llvm::Optional<int64_t> value = object.getInteger(field);
  if (!value || *value < 0 || (!allowZero && *value == 0))
    return receiptError(context + " has missing/invalid " + field);
  return static_cast<uint64_t>(*value);
}

llvm::Expected<StringRef> digestField(const llvm::json::Object &object,
                                      StringRef field, StringRef context) {
  llvm::Expected<StringRef> value = stringField(object, field, context);
  if (!value)
    return value.takeError();
  if (!validDigest(*value))
    return receiptError(context + " has invalid " + field);
  return *value;
}

llvm::json::Object projectionObject(const backend_invocation::Result &input) {
  return llvm::json::Object{
      {"byteLen", static_cast<int64_t>(input.projectionByteLen)},
      {"encoding", input.projectionEncoding},
      {"sha256", input.projectionDigest},
  };
}

llvm::json::Object securityObject(const backend_invocation::Result &input) {
  return llvm::json::Object{
      {"decision", "approved"},
      {"projectionDigest", input.projectionDigest},
      {"requestId", static_cast<int64_t>(input.requestId)},
  };
}

llvm::Expected<llvm::json::Array>
artifactArray(const backend_invocation::Result &input) {
  std::vector<const backend_invocation::Artifact *> ordered;
  ordered.reserve(input.artifacts.size());
  for (const backend_invocation::Artifact &artifact : input.artifacts)
    ordered.push_back(&artifact);
  llvm::sort(ordered, [](const auto *left, const auto *right) {
    return left->path < right->path;
  });

  llvm::json::Array artifacts;
  std::string previous;
  for (const backend_invocation::Artifact *artifact : ordered) {
    if (artifact->path == previous)
      return receiptError("artifact path is duplicated");
    previous = artifact->path;
    if (llvm::Error error =
            backend_protocol::validateArtifactPath(artifact->path))
      return std::move(error);
    if (!validDigest(artifact->sha256) ||
        artifact->sha256 != "sha256:" + sha256Hex(artifact->bytes))
      return receiptError("artifact digest does not match bytes");
    artifacts.push_back(llvm::json::Object{
        {"byteLen", static_cast<int64_t>(artifact->bytes.size())},
        {"path", artifact->path},
        {"sha256", artifact->sha256},
    });
  }
  return artifacts;
}

} // namespace

llvm::Expected<std::string>
createApproved(const backend_invocation::Result &input) {
  if (input.requestId == 0 || input.coreIdentity.empty() ||
      input.targetIdentity.empty() || input.targetProfileIdentity.empty() ||
      !validDigest(input.packageManifestDigest) ||
      input.projectionEncoding != "neutrino.finalized-projection/1" ||
      input.projectionByteLen == 0 || !validDigest(input.projectionDigest) ||
      !validDigest(input.receiptDigest))
    return receiptError("invocation identity is malformed");

  llvm::Expected<llvm::json::Array> artifacts = artifactArray(input);
  if (!artifacts)
    return artifacts.takeError();
  llvm::json::Object root{
      {"artifacts", std::move(*artifacts)},
      {"backendReceiptDigest", input.receiptDigest},
      {"coreIdentity", input.coreIdentity},
      {"kind", kKind},
      {"packageManifestDigest", input.packageManifestDigest},
      {"projection", projectionObject(input)},
      {"requestId", static_cast<int64_t>(input.requestId)},
      {"schemaVersion", static_cast<int64_t>(kSchemaVersion)},
      {"security", securityObject(input)},
      {"targetIdentity", input.targetIdentity},
      {"targetProfileIdentity", input.targetProfileIdentity},
  };
  llvm::json::Value receipt(std::move(root));
  std::string payload = compactJson(receipt);
  receipt.getAsObject()->insert(
      {"receiptDigest", "sha256:" + sha256Hex(payload)});
  std::string bytes = compactJson(receipt);
  llvm::Expected<VerifiedReceipt> checked = verify(bytes);
  if (!checked)
    return checked.takeError();
  return bytes;
}

llvm::Expected<VerifiedReceipt> verify(StringRef bytes) {
  llvm::Expected<llvm::json::Value> parsed = llvm::json::parse(bytes);
  if (!parsed)
    return receiptError("receipt is not valid JSON");
  llvm::json::Object *root = parsed->getAsObject();
  if (!root)
    return receiptError("receipt root is not an object");
  if (llvm::Error error = requireClosed(
          *root, "receipt",
          {"artifacts", "backendReceiptDigest", "coreIdentity", "kind",
           "packageManifestDigest", "projection", "receiptDigest", "requestId",
           "schemaVersion", "security", "targetIdentity",
           "targetProfileIdentity"}))
    return std::move(error);

  llvm::Expected<StringRef> kind = stringField(*root, "kind", "receipt");
  if (!kind)
    return kind.takeError();
  if (*kind != kKind)
    return receiptError("receipt kind is unsupported");
  llvm::Expected<uint64_t> schema =
      uintField(*root, "schemaVersion", "receipt", false);
  if (!schema)
    return schema.takeError();
  if (*schema != kSchemaVersion)
    return receiptError("receipt schemaVersion is unsupported");

  llvm::Expected<StringRef> receiptDigest =
      digestField(*root, "receiptDigest", "receipt");
  if (!receiptDigest)
    return receiptDigest.takeError();
  std::string savedReceiptDigest = receiptDigest->str();
  root->erase("receiptDigest");
  std::string payload = compactJson(*parsed);
  if (savedReceiptDigest != "sha256:" + sha256Hex(payload))
    return receiptError("receiptDigest does not match canonical payload");
  root->insert({"receiptDigest", savedReceiptDigest});
  if (compactJson(*parsed) != bytes)
    return receiptError("receipt bytes are not canonical JSON");

  VerifiedReceipt result;
  llvm::Expected<uint64_t> requestId =
      uintField(*root, "requestId", "receipt", false);
  llvm::Expected<StringRef> core =
      stringField(*root, "coreIdentity", "receipt");
  llvm::Expected<StringRef> target =
      stringField(*root, "targetIdentity", "receipt");
  llvm::Expected<StringRef> profile =
      stringField(*root, "targetProfileIdentity", "receipt");
  llvm::Expected<StringRef> package =
      digestField(*root, "packageManifestDigest", "receipt");
  llvm::Expected<StringRef> backend =
      digestField(*root, "backendReceiptDigest", "receipt");
  if (!requestId)
    return requestId.takeError();
  if (!core)
    return core.takeError();
  if (!target)
    return target.takeError();
  if (!profile)
    return profile.takeError();
  if (!package)
    return package.takeError();
  if (!backend)
    return backend.takeError();
  result.requestId = *requestId;
  result.coreIdentity = core->str();
  result.targetIdentity = target->str();
  result.targetProfileIdentity = profile->str();
  result.packageManifestDigest = package->str();
  result.backendReceiptDigest = backend->str();
  result.receiptDigest = savedReceiptDigest;

  const llvm::json::Object *projection = root->getObject("projection");
  if (!projection)
    return receiptError("receipt has missing/invalid projection");
  if (llvm::Error error = requireClosed(*projection, "projection",
                                        {"byteLen", "encoding", "sha256"}))
    return std::move(error);
  llvm::Expected<uint64_t> projectionByteLen =
      uintField(*projection, "byteLen", "projection", false);
  llvm::Expected<StringRef> projectionEncoding =
      stringField(*projection, "encoding", "projection");
  llvm::Expected<StringRef> projectionDigest =
      digestField(*projection, "sha256", "projection");
  if (!projectionByteLen)
    return projectionByteLen.takeError();
  if (!projectionEncoding)
    return projectionEncoding.takeError();
  if (*projectionEncoding != "neutrino.finalized-projection/1")
    return receiptError("projection encoding is unsupported");
  if (!projectionDigest)
    return projectionDigest.takeError();
  result.projectionByteLen = *projectionByteLen;
  result.projectionEncoding = projectionEncoding->str();
  result.projectionDigest = projectionDigest->str();

  const llvm::json::Object *security = root->getObject("security");
  if (!security)
    return receiptError("receipt has missing/invalid security");
  if (llvm::Error error = requireClosed(
          *security, "security", {"decision", "projectionDigest", "requestId"}))
    return std::move(error);
  llvm::Expected<StringRef> decision =
      stringField(*security, "decision", "security");
  llvm::Expected<uint64_t> securityRequest =
      uintField(*security, "requestId", "security", false);
  llvm::Expected<StringRef> securityProjection =
      digestField(*security, "projectionDigest", "security");
  if (!decision)
    return decision.takeError();
  if (*decision != "approved")
    return receiptError("security decision is not approved");
  if (!securityRequest)
    return securityRequest.takeError();
  if (*securityRequest != result.requestId)
    return receiptError("security requestId binding does not match");
  if (!securityProjection)
    return securityProjection.takeError();
  if (*securityProjection != result.projectionDigest)
    return receiptError("security projection binding does not match");

  const llvm::json::Array *artifacts = root->getArray("artifacts");
  if (!artifacts)
    return receiptError("receipt has missing/invalid artifacts");
  std::string previous;
  for (const llvm::json::Value &value : *artifacts) {
    const llvm::json::Object *artifact = value.getAsObject();
    if (!artifact)
      return receiptError("artifact identity is not an object");
    if (llvm::Error error =
            requireClosed(*artifact, "artifact", {"byteLen", "path", "sha256"}))
      return std::move(error);
    llvm::Expected<StringRef> path = stringField(*artifact, "path", "artifact");
    llvm::Expected<uint64_t> byteLen =
        uintField(*artifact, "byteLen", "artifact");
    llvm::Expected<StringRef> sha =
        digestField(*artifact, "sha256", "artifact");
    if (!path)
      return path.takeError();
    if (llvm::Error error = backend_protocol::validateArtifactPath(*path))
      return std::move(error);
    if (!previous.empty() && previous >= *path)
      return receiptError("artifact identities are not uniquely path-sorted");
    previous = path->str();
    if (!byteLen)
      return byteLen.takeError();
    if (!sha)
      return sha.takeError();
    result.artifacts.push_back({path->str(), *byteLen, sha->str()});
  }
  return result;
}

} // namespace backend_dispatch_receipt
} // namespace neutrino

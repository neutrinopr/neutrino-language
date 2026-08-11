//===- JsonUtil.cpp - shared leaf JSON/identity primitives () --------===//
//
// The single definition of the JSON string escaper and the sha256 hex digest
// used across the structural renderers and the capability-spec hash. Kept
// dependency-light (StringRef + LLVM Support, no MLIR) so the C++ unit layer
// (unittests/) can assert them directly. See include/Neutrino/JsonUtil.h.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/JsonUtil.h"

#include "llvm/ADT/ArrayRef.h"
#include "llvm/ADT/StringExtras.h"
#include "llvm/Support/FormatVariadic.h"
#include "llvm/Support/SHA256.h"

namespace neutrino {

std::string compactJson(const llvm::json::Value &v) {
  return llvm::formatv("{0}", v).str();
}

std::string jsonEscape(llvm::StringRef s) {
  std::string o;
  o.reserve(s.size() + 2);
  for (char ch : s) {
    unsigned char c = static_cast<unsigned char>(ch);
    switch (c) {
    case '"':
      o += "\\\"";
      break;
    case '\\':
      o += "\\\\";
      break;
    case '\b':
      o += "\\b";
      break;
    case '\f':
      o += "\\f";
      break;
    case '\n':
      o += "\\n";
      break;
    case '\r':
      o += "\\r";
      break;
    case '\t':
      o += "\\t";
      break;
    default:
      if (c < 0x20) {
        // Remaining C0 control character: emit as \u00XX (lowercase hex).
        static const char *kHex = "0123456789abcdef";
        o += "\\u00";
        o += kHex[(c >> 4) & 0xF];
        o += kHex[c & 0xF];
      } else {
        o += ch;
      }
    }
  }
  return o;
}

std::string sha256Hex(llvm::StringRef s) {
  auto d = llvm::SHA256::hash(llvm::ArrayRef<uint8_t>(
      reinterpret_cast<const uint8_t *>(s.data()), s.size()));
  return llvm::toHex(d, /*LowerCase=*/true);
}

static std::string missingInvalid(llvm::StringRef context,
                                  llvm::StringRef field) {
  std::string msg = context.str();
  msg += ": missing/invalid ";
  msg += field.str();
  return msg;
}

static llvm::Error requiredError(llvm::StringRef context,
                                 llvm::StringRef field) {
  return llvm::make_error<llvm::StringError>(missingInvalid(context, field),
                                             llvm::inconvertibleErrorCode());
}

llvm::Expected<const llvm::json::Object *>
requiredObject(const llvm::json::Object &obj, llvm::StringRef field,
               llvm::StringRef context) {
  if (const llvm::json::Object *nested = obj.getObject(field))
    return nested;
  return requiredError(context, field);
}

llvm::Expected<const llvm::json::Array *>
requiredArray(const llvm::json::Object &obj, llvm::StringRef field,
              llvm::StringRef context) {
  if (const llvm::json::Array *array = obj.getArray(field))
    return array;
  return requiredError(context, field);
}

llvm::Expected<llvm::StringRef> requiredString(const llvm::json::Object &obj,
                                               llvm::StringRef field,
                                               llvm::StringRef context) {
  if (llvm::Optional<llvm::StringRef> value = obj.getString(field))
    return *value;
  return requiredError(context, field);
}

llvm::Expected<llvm::StringRef>
requiredLifecycleSuccessTerminal(const llvm::json::Object &spec,
                                 llvm::StringRef projection) {
  llvm::Expected<const llvm::json::Object *> lifecycle =
      requiredObject(spec, "lifecycle", "capability-spec");
  if (!lifecycle)
    return lifecycle.takeError();
  llvm::Expected<const llvm::json::Object *> terminalStates = requiredObject(
      **lifecycle, "terminalStates", "capability-spec lifecycle");
  if (!terminalStates)
    return terminalStates.takeError();
  if (llvm::Optional<llvm::StringRef> success =
          (*terminalStates)->getString("success"))
    return *success;
  return llvm::make_error<llvm::StringError>(
      "capability-spec lifecycle has no success terminal state; " +
          projection.str() + " projects it",
      llvm::inconvertibleErrorCode());
}

} // namespace neutrino

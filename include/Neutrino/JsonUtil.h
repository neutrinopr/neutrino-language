#ifndef NEUTRINO_JSON_UTIL_H
#define NEUTRINO_JSON_UTIL_H

#include "llvm/ADT/StringRef.h"
#include "llvm/Support/Error.h"
#include "llvm/Support/JSON.h"

#include <string>

namespace neutrino {

// Leaf JSON/identity primitives shared by the hand-rolled structural renderers
// and the capability-spec hash. Pure and MLIR-free, needing only StringRef and
// LLVM Support, so they can be exercised directly by the C++ unit layer
// (unittests/, ) instead of only indirectly through the CLI. Previously
// each renderer carried its own copy of the escaper and
// CapabilitySpecTarget.cpp its own sha256 wrapper; this is the single
// definition.

// Escape `s` as the CONTENT of a JSON string (no surrounding quotes). Produces
// valid JSON: the mandatory escapes (`"` and `\`), the short forms for the
// common control characters (`\b \f \n \r \t`), and any remaining C0 control
// character (< 0x20) as a `\u00XX` sequence. All other bytes (including UTF-8
// continuation bytes) pass through verbatim. Total and pure.
std::string jsonEscape(llvm::StringRef s);

// Lowercase hex SHA-256 of `s` — the canonical digest used for the
// capability-spec identity (capabilityHash / specHash). Total and pure.
std::string sha256Hex(llvm::StringRef s);

// Required capability-spec accessors for backend-neutral JSON shape checks.
// They return stable `spec.ast`-ready error messages instead of letting
// renderers silently `value_or("")` required contract fields.
llvm::Expected<const llvm::json::Object *>
requiredObject(const llvm::json::Object &obj, llvm::StringRef field,
               llvm::StringRef context);
llvm::Expected<const llvm::json::Array *>
requiredArray(const llvm::json::Object &obj, llvm::StringRef field,
              llvm::StringRef context);
llvm::Expected<llvm::StringRef> requiredString(const llvm::json::Object &obj,
                                               llvm::StringRef field,
                                               llvm::StringRef context);

// Shared lifecycle pin used by backend projections whose local terminal state
// projects the capability spec's success terminal.
llvm::Expected<llvm::StringRef>
requiredLifecycleSuccessTerminal(const llvm::json::Object &spec,
                                 llvm::StringRef projection);

// The compact, sorted-key canonical JSON of `v` — the hash-preimage form.
// llvm's JSON printer sorts object keys; the `{0}` (no-indent) form emits no
// whitespace. This matches Python json.dumps(sort_keys=True,
// separators=(",",":"), ensure_ascii=False) byte-for-byte, so the C++ emitter
// and the stdlib validators agree on every hash. Single definition — the
// capability-spec hash and the agreement identity () share it.
std::string compactJson(const llvm::json::Value &v);

} // namespace neutrino

#endif // NEUTRINO_JSON_UTIL_H

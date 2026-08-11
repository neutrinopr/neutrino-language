#ifndef NEUTRINO_SOLIDITYEMIT_H
#define NEUTRINO_SOLIDITYEMIT_H

/// Shared Solidity-render helpers (): the type/escape/operand primitives
/// the coordination-contract (GenSoliditySpec.cpp) and Foundry-harness
/// (GenSolidityTest.cpp) renderers both use. View.h-free — it consumes only the
/// capability-spec JSON + the  value model, like the renderers it serves.

#include "llvm/ADT/StringRef.h"
#include "llvm/Support/JSON.h"

#include <string>

namespace neutrino {
namespace sol_detail {

/// Solidity type for a spec value type: uint256 for money/decimal and explicit
/// temporal inputs, else string. Temporal values remain caller-supplied; this
/// mapping never substitutes the EVM block clock.
std::string solType(llvm::StringRef ty);

/// A `<solType> <name>` parameter declaration (string params are `calldata`).
std::string param(llvm::StringRef n, llvm::StringRef ty);

/// A Solidity double-quoted string literal (escapes `\` and `"`).
std::string solString(llvm::StringRef t);

/// True iff the text is an (optionally-signed) integer literal.
bool isInt(llvm::StringRef t);

/// The `u_`-prefixed member name for an input reference.
std::string uref(llvm::StringRef name);

/// The upper-cased copy of a string.
std::string upper(llvm::StringRef s);

/// A debit/credit operand from the spec ({kind: ref|literal, value}):
/// contractStr keeps a literal as a Solidity string; contractUint requires an
/// int literal; a ref lowers to its u_ member.
std::string contractStr(const llvm::json::Object &op);
std::string contractUint(const llvm::json::Object &op);

/// A capability-spec sub-object, or a fail-closed `spec.ast` diagnostic.
const llvm::json::Object &obj(const llvm::json::Value *v, const char *what);

} // namespace sol_detail
} // namespace neutrino

#endif // NEUTRINO_SOLIDITYEMIT_H

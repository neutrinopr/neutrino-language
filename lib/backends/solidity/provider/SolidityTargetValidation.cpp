//===- SolidityTargetValidation.cpp - fail-closed target-node policy -----===//
//
// The reusable fail-closed validation policy over the typed Solidity target
// nodes: the single throw site, the per-node lexical/vocabulary contract the
// generated factories route through, the typed-parameter projection, and the
//  construction-level prohibition. No CoordinationPlan/spec/L2 intake.
//
//===----------------------------------------------------------------------===//

#include "SolidityTargetValidation.h"

#include "Neutrino/Expr.h"

#include <algorithm>
#include <cctype>
#include <cstddef>
#include <set>
#include <string>
#include <utility>
#include <vector>

// The generated printer's spelling-table lengths (kCallableKindSpellingCount /
// kCallableModifierSpellingCount) are the COUNT side of the callable-coverage
// asserts below, so the generated handlers must be visible here.
#include "SolidityPrinterHandlers.inc"

namespace neutrino {
namespace solidity_model {

// The single failure site for legalization errors — one throw, so the
// throw-debt ratchet stays honest as fail-closed checks are added. Defined here
// so every fail-closed factory routes through it rather than growing the throw
// count.
[[noreturn]] void specFail(const std::string &msg) {
  throw ExprError("spec.ast", msg);
}

namespace {

// A statement separator (`;` or newline) smuggled into a typed statement-shell
// operand would launder a second raw statement past the  ratchet — the
// `.td` owns the framing punctuation, so the typed factories reject it.
bool hasStatementSeparator(const std::string &s) {
  return s.find_first_of(";\n\r") != std::string::npos;
}

// Every character that terminates a Solidity single-line/NatSpec comment,
// checked over the UTF-8 bytes: LF, VT, FF, CR (ASCII) plus NEL U+0085, LS
// U+2028, and PS U+2029. A comment factory MUST reject all of them — otherwise
// the suffix after the terminator escapes the `///`/`//` framing as live source
// (and NEL/LS/PS also break the byte-valid single-line output contract). Shared
// so the later SPDX/`//` comment slice enforces exactly the same rule.
// (https://docs.soliditylang.org/en/latest/layout-of-source-files.html#comments)
bool hasSolidityLineTerminator(const std::string &s) {
  if (s.find_first_of("\n\v\f\r") != std::string::npos)
    return true;
  return s.find("\xC2\x85") != std::string::npos ||     // NEL  U+0085
         s.find("\xE2\x80\xA8") != std::string::npos || // LS   U+2028
         s.find("\xE2\x80\xA9") != std::string::npos;   // PS   U+2029
}

// Any ASCII control byte (< 0x20, e.g. TAB/LF/VT/FF/CR) or DEL (0x7F). These
// cannot appear literally in a Solidity double-quoted string; a source-unit
// import path has no legitimate use for them either. Combined with
// hasSolidityLineTerminator (which adds the multi-byte NEL/LS/PS terminators),
// this closes the control/terminator surface of a quoted-string operand.
bool hasControlByte(const std::string &s) {
  for (unsigned char c : s)
    if (c < 0x20 || c == 0x7F)
      return true;
  return false;
}

// A Solidity line comment (`//`) or block comment (`/*`) opener. A comment
// delimiter smuggled into a `.td`-framed operand would COMMENT OUT the framing
// that follows it on the same physical line (the closing paren, the modifiers,
// the trailing brace/semicolon) — a single clean line that codetext's
// no-newline check does not catch. So callable/parameter operands reject it.
bool hasCommentDelimiter(const std::string &s) {
  return s.find("//") != std::string::npos || s.find("/*") != std::string::npos;
}

// A Solidity identifier: `[A-Za-z_$][A-Za-z0-9_$]*`. Callable/parameter NAMES
// are identifiers, so validating them as such (not merely "no framing
// punctuation") closes the space/comment/operator surface structurally.
bool isSolidityIdentifier(const std::string &s) {
  if (s.empty())
    return false;
  auto head = [](char c) {
    return std::isalpha((unsigned char)c) || c == '_' || c == '$';
  };
  auto tail = [&](char c) { return head(c) || std::isdigit((unsigned char)c); };
  if (!head(s[0]))
    return false;
  for (char c : s)
    if (!tail(c))
      return false;
  return true;
}

// The escape surface every `.td`-framed callable/parameter TOKEN must be free
// of
// ( review P1.2): the framing punctuation the `.td` owns (`(`/`)`/`{`/`}`/
// `,`/`;`), a comment opener, ANY Solidity line terminator (LF/VT/FF/CR/NEL/LS/
// PS), and any other control byte. A value carrying any of these could break
// out of, or comment past, the generated framing.
bool hasCallableTokenEscape(const std::string &s) {
  return s.find_first_of("(){},;") != std::string::npos ||
         hasCommentDelimiter(s) || hasSolidityLineTerminator(s) ||
         hasControlByte(s);
}

// COVERAGE (): the terminal-sentinel + per-member ordinal assertions tying
// the CallableKind/CallableModifier enums 1:1 to the generated `.td` spelling
// tables. Shared with the compile-negative coverage probe (see the file) so
// "add an enum member without a `.td` spelling → compile error" is PROVEN, not
// merely asserted against a hand-synced side array.
#include "SolidityCallableCoverage.inc"

// DOMAIN guards ( review): a value is in the closed vocabulary iff its
// ordinal is in [0, Count) — this rejects the `Count` terminal sentinel itself
// AND any `static_cast<Enum>(N)` value a caller could forge past the type. The
// factory validates every incoming kind/modifier through these so the finalized
// model never carries an out-of-vocabulary ordinal.
bool isCallableKindInDomain(CallableKind k) {
  int ord = static_cast<int>(k);
  return ord >= 0 && ord < static_cast<int>(CallableKind::Count);
}
bool isCallableModifierInDomain(CallableModifier m) {
  int ord = static_cast<int>(m);
  return ord >= 0 && ord < static_cast<int>(CallableModifier::Count);
}

// A modifier is a VISIBILITY (external/public/internal/private) or a MUTABILITY
// (view/pure/payable) — a callable may carry at most one of each.
bool isVisibilityModifier(CallableModifier m) {
  return m == CallableModifier::External || m == CallableModifier::Public ||
         m == CallableModifier::Internal || m == CallableModifier::Private;
}

// The CLOSED parameter data-location vocabulary.
const std::set<std::string> kParamLocations = {"", "calldata", "memory",
                                               "storage"};

// Validate one already-decided parameter as a CLOSED typed shape (): a
// non-empty type free of the escape surface, a data location from the closed
// vocabulary, and an empty (anonymous) or identifier name. Shared by the event
// and function parameter lists so neither can launder syntax through a param.
void validateParam(const SolParam &p, const char *ctx) {
  if (p.type.empty())
    specFail(std::string(ctx) + ": a parameter must carry a non-empty type");
  if (hasCallableTokenEscape(p.type))
    specFail(std::string(ctx) + ": a parameter type must not carry framing "
                                "punctuation, a comment, a line terminator, or "
                                "a control byte");
  if (kParamLocations.count(p.location) == 0) {
    specFail(std::string(ctx) + ": a parameter data location must be empty or "
                                "one of calldata/memory/storage");
  }
  if (!p.name.empty() && !isSolidityIdentifier(p.name))
    specFail(std::string(ctx) +
             ": a parameter name must be empty or a Solidity identifier");
}
} // namespace

std::vector<std::vector<std::string>>
projectGeneratedParams(const std::vector<SolParam> &params, const char *ctx) {
  std::vector<std::vector<std::string>> group;
  group.reserve(params.size());
  for (const SolParam &param : params) {
    validateParam(param, ctx);
    group.push_back({param.type, param.location, param.name});
  }
  return group;
}

// Validation is reusable C++ policy, separate from the generated per-node ABI
// and storage mapping. The generated builder owns only schema-derived field
// order/cardinality and calls this one seam after projecting those typed
// inputs.
void validateGeneratedSolStmt(
    SolStmt::Kind kind, const std::vector<std::string> &operands,
    const std::vector<SolStmt> &body,
    const std::vector<std::vector<std::string>> &group,
    const std::vector<std::vector<int>> &enumOrdinals) {
  auto operand = [&](std::size_t index) -> const std::string & {
    if (index >= operands.size())
      specFail("SolStmt: generated builder omitted a scalar operand");
    return operands[index];
  };
  // This is validation, not target-node emission/dispatch: keep each closed
  // guard as an early-return predicate so the target-printer authority gate
  // does not misclassify validation-only `case Kind` labels as printer cases.
  if (kind == SolStmt::Kind::LocalDecl) {
    if (hasStatementSeparator(operand(0)) || hasStatementSeparator(operand(1)))
      specFail("SolStmt::localDecl: declaration type/name must not carry a "
               "statement separator (';' or newline) — the .td owns the "
               "'= ;' framing");
    return;
  }
  if (kind == SolStmt::Kind::Assign) {
    if (hasStatementSeparator(operand(0)) || hasStatementSeparator(operand(1)))
      specFail("SolStmt::assign: assignment lhs/rhs must not carry a statement "
               "separator (';' or newline) — the .td owns the '= ;' framing");
    return;
  }
  if (kind == SolStmt::Kind::CompoundAssign) {
    if (operand(1) != "+=" && operand(1) != "-=")
      specFail("SolStmt::compoundAssign: operator must be exactly '+=' or '-=' "
               "(the .td owns the surrounding framing) — got '" +
               operand(1) + "'");
    if (hasStatementSeparator(operand(0)) || hasStatementSeparator(operand(2)))
      specFail("SolStmt::compoundAssign: lhs/rhs must not carry a statement "
               "separator (';' or newline) — the .td owns the ' ;' framing");
    return;
  }
  if (kind == SolStmt::Kind::DocComment) {
    if (hasSolidityLineTerminator(operand(0)))
      specFail("SolStmt::docComment: comment text must be a single line (no "
               "Solidity line terminator: LF/VT/FF/CR/NEL/LS/PS) — the .td "
               "owns the '/// ' framing");
    return;
  }
  if (kind == SolStmt::Kind::SpdxLicense) {
    if (operand(0).empty())
      specFail("SolStmt::spdxLicense: license identifier must be non-empty");
    if (hasSolidityLineTerminator(operand(0)))
      specFail("SolStmt::spdxLicense: license must be a single line (no "
               "Solidity line terminator: LF/VT/FF/CR/NEL/LS/PS) — the .td "
               "owns the '// SPDX-License-Identifier: ' framing");
    return;
  }
  if (kind == SolStmt::Kind::Pragma) {
    if (operand(0).empty())
      specFail("SolStmt::pragma: version pragma must be non-empty");
    if (hasStatementSeparator(operand(0)))
      specFail("SolStmt::pragma: version must not carry a statement separator "
               "(';' or newline) — the .td owns the 'pragma solidity ;' "
               "framing");
    return;
  }
  if (kind == SolStmt::Kind::Import) {
    if (operand(0).empty())
      specFail("SolStmt::importUnit: import path must be non-empty");
    if (operand(0).find('"') != std::string::npos ||
        operand(0).find('\\') != std::string::npos)
      specFail("SolStmt::importUnit: path must not carry a double quote or a "
               "backslash — the .td owns the '\"' framing and a backslash "
               "would escape it out of the quoted-string import");
    if (hasStatementSeparator(operand(0)) ||
        hasSolidityLineTerminator(operand(0)) || hasControlByte(operand(0)))
      specFail("SolStmt::importUnit: path must not carry a statement separator "
               "(';' or newline), a Solidity line terminator "
               "(LF/VT/FF/CR/NEL/LS/PS), or a control byte — the .td owns the "
               "'import \"\";' single-line framing");
    return;
  }
  if (kind == SolStmt::Kind::EnumDecl) {
    if (operand(0).empty() || operand(1).empty())
      specFail("SolStmt::enumDecl: enum name and variants must be non-empty");
    if (operand(0).find_first_of("{};\n\r") != std::string::npos ||
        operand(1).find_first_of("{};\n\r") != std::string::npos)
      specFail("SolStmt::enumDecl: name/variants must not carry the framing "
               "punctuation '{', '}', ';' or a newline — the .td owns the "
               "'enum { }' framing");
    return;
  }
  if (kind == SolStmt::Kind::StorageDecl) {
    if (operand(0).empty() || operand(2).empty())
      specFail("SolStmt::storageDecl: storage type and name must be non-empty");
    if (hasStatementSeparator(operand(0)) ||
        hasStatementSeparator(operand(1)) || hasStatementSeparator(operand(2)))
      specFail("SolStmt::storageDecl: type/modifiers/name must not carry a "
               "statement separator (';' or newline) — the .td owns the "
               "'<type> <modifiers> <name>;' framing");
    return;
  }
  if (kind == SolStmt::Kind::EventDecl) {
    if (operand(0).empty())
      specFail("SolStmt::eventDecl: event name must be non-empty");
    if (operand(0).find_first_of("(),;\n\r") != std::string::npos)
      specFail("SolStmt::eventDecl: event name must not carry framing "
               "punctuation ('(', ')', ',', ';' or newline) — the .td owns "
               "the 'event <name>(<params>);' framing");
    if (hasCommentDelimiter(operand(0)) ||
        hasSolidityLineTerminator(operand(0)) || hasControlByte(operand(0)))
      specFail("SolStmt::eventDecl: event name must not carry a comment, a "
               "Solidity line terminator, or a control byte");
    return;
  }
  if (kind == SolStmt::Kind::FunctionSig) {
    if (enumOrdinals.size() != 2 || enumOrdinals[0].size() != 1)
      specFail("SolStmt::functionSig: generated enum cardinality mismatch");
    CallableKind callableKind =
        static_cast<CallableKind>(enumOrdinals[0].front());
    if (!isCallableKindInDomain(callableKind))
      specFail("SolStmt::functionSig: callable kind is outside the closed "
               "vocabulary (the Count sentinel or an out-of-range cast)");
    if (callableKind == CallableKind::Constructor && !operand(0).empty())
      specFail("SolStmt::functionSig: a constructor has no name");
    if (callableKind == CallableKind::Function &&
        !isSolidityIdentifier(operand(0)))
      specFail("SolStmt::functionSig: a function name must be a Solidity "
               "identifier");
    if (hasCallableTokenEscape(operand(0)) || hasCommentDelimiter(operand(0)))
      specFail("SolStmt::functionSig: a function name must not carry framing "
               "punctuation, a comment, a terminator, or a control byte");
    int previous = -1;
    int visibility = 0;
    int mutability = 0;
    for (int ordinal : enumOrdinals[1]) {
      CallableModifier modifier = static_cast<CallableModifier>(ordinal);
      if (!isCallableModifierInDomain(modifier))
        specFail("SolStmt::functionSig: a modifier is outside the closed "
                 "vocabulary (the Count sentinel or an out-of-range cast)");
      if (ordinal <= previous)
        specFail("SolStmt::functionSig: modifiers must be in canonical order "
                 "with no duplicates");
      previous = ordinal;
      if (isVisibilityModifier(modifier))
        ++visibility;
      else
        ++mutability;
    }
    if (visibility > 1)
      specFail("SolStmt::functionSig: at most one visibility modifier "
               "(external/public/internal/private)");
    if (mutability > 1)
      specFail("SolStmt::functionSig: at most one mutability modifier "
               "(view/pure/payable)");
    return;
  }
  if (kind == SolStmt::Kind::ContractShell) {
    if (!isSolidityIdentifier(operand(0)))
      specFail("SolStmt::contractShell: a contract name must be a Solidity "
               "identifier");
    return;
  }
  if (kind == SolStmt::Kind::InterfaceSignature) {
    if (!isSolidityIdentifier(operand(0)))
      specFail("SolStmt::interfaceSignature: a method name must be a Solidity "
               "identifier");
    if (operand(1).empty())
      specFail("SolStmt::interfaceSignature: a method must declare a return "
               "type");
    if (hasCallableTokenEscape(operand(1)) || hasCommentDelimiter(operand(1)))
      specFail("SolStmt::interfaceSignature: a return type must not carry "
               "framing punctuation, a comment, a terminator, or a control "
               "byte");
    return;
  }
  if (kind == SolStmt::Kind::InterfaceShell) {
    if (!isSolidityIdentifier(operand(0)))
      specFail("SolStmt::interfaceShell: an interface name must be a Solidity "
               "identifier");
    for (const SolStmt &signature : body)
      if (signature.kind != SolStmt::Kind::InterfaceSignature)
        specFail("SolStmt::interfaceShell: an interface body holds only "
                 "interface signatures");
    return;
  }
  (void)group;
}

//  CONSTRUCTION-LEVEL prohibition: every SolStmt ctor routes through here,
// so this is the single, spelling-independent seam that rejects raw statement
// authoring. `Line` and `Block` are the only two kinds whose printer template
// is a bare verbatim `${text}` — arbitrary raw statements — so constructing
// EITHER is forbidden, by whatever spelling produced the enum value
// (`Kind::Line`, `Kind(0)`, a cast, an alias all reduce to the same value and
// are caught). No factory builds them; this guard makes a rogue member that
// tries impossible at runtime.
void SolStmt::ensureAuthorable(Kind k) {
  if (k == Kind::Line || k == Kind::Block)
    specFail("SolStmt: raw Line/Block statement authoring is prohibited ( "
             "endpoint) — build a typed SolidityTargetNodes.td node instead");
}

bool SolStmt::rejectsAtConstructionForTest(Kind k) {
  try {
    (void)SolStmt(k, {});
  } catch (const ExprError &) {
    return true;
  }
  return false;
}

} // namespace solidity_model
} // namespace neutrino

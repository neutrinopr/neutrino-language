//===- SolidityTargetAdapter.h - typed Solidity target-node model --------===//
//
// The Solidity adapter consumes only the verified BackendProjectionGraph.
// Projection traversal materializes typed target idioms; the codetext sink
// performs layout only. No backend entry can read the CoordinationPlan,
// capability spec, L2 input, or any alternate semantic authority. The
// constructs the model owns are TYPED (enum/event/storage/function + typed
// parameters + require/guard/transition/ emit statements); only the leaf target
// expressions stay Solidity-specific strings (already lowered by
// toSolidity/guardToSolidity) — this is NOT a general-purpose Solidity AST.
// Backend-internal seam header: consumes only the typed coordination leaf,
// never View.h.
//
// This is the target-node model (the SolStmt idiom + its generated factories +
// the callable/modifier vocabularies) and the adapter->codetext boundary
// (toNode). The renderer contract lives in SolidityRenderer.h; the fail-closed
// validation policy in SolidityTargetValidation.h.
//
//===----------------------------------------------------------------------===//

#ifndef NEUTRINO_BACKENDS_SOLIDITY_SOLIDITYTARGETADAPTER_H
#define NEUTRINO_BACKENDS_SOLIDITY_SOLIDITYTARGETADAPTER_H

#include "Neutrino/BackendProjection.h"
#include "Neutrino/CodeText.h"

#include <algorithm>
#include <array>
#include <optional>
#include <string>
#include <utility>
#include <vector>

namespace neutrino {
namespace solidity_model {

// One legalized statement. The coordination constructs are TYPED shapes — a
// `Require` is the revert shape, a `Guarded` is the condition shape, a
// `Transition` is the state-write shape (its storage slot + target state), an
// `Emit` is the event-emission shape (its event name + already-lowered args) —
// while framing (`Blank`/`Block`) and any other leaf is a verbatim `Line`. The
// predicate/expression/arg text inside a shape is already lowered
// (target-specific); this is not a Solidity AST.
struct SolParam; // a typed `<type> [<location>] <name>` parameter (defined
                 // below)

// The CLOSED callable-kind + function-modifier vocabularies (): real typed
// enums, NOT strings. Both are GENERATED from SolidityTargetNodes.td (the
// SINGLE declarative source that also drives the ordinal->spelling tables) via
// the SolidityTargetEnums.inc X-macro, so the enum member set and the spelling
// table cannot drift and an added member cannot alias an existing ordinal — the
// members ARE the position-indexed `.td` list. A terminal `Count` sentinel
// closes each. The generated SolidityCallableCoverage.inc reconciles the
// ordinals against a position probe (catching a hand-edited alias/reorder), and
// the regeneration freshness gate catches any edit to the generated source.
//
// CallableModifier order is visibility (external/public/internal/private) then
// mutability (view/pure/payable), matching the model's canonical-order check.
enum class CallableKind {
#define NEU_SOL_ENUM_CallableKind(Sym, Ordinal, Spelling) Sym = Ordinal,
#include "SolidityTargetEnums.inc"
#undef NEU_SOL_ENUM_CallableKind
  Count // terminal sentinel
};
enum class CallableModifier {
#define NEU_SOL_ENUM_CallableModifier(Sym, Ordinal, Spelling) Sym = Ordinal,
#include "SolidityTargetEnums.inc"
#undef NEU_SOL_ENUM_CallableModifier
  Count // terminal sentinel
};

//  G1-S1: the generated (mode, role) -> atom status accessor — the ONLY
// reader of the Solidity status atoms. The legalizer passes the PROJECTED
// `ExecutionMode` and `LifecycleRole` it consumed from the verified
// `BackendProjectionGraph`; this maps that pair to the rail's lexical atom via
// the generated `NEU_SOL_STATUS_ATOM` table. The atom NEVER appears inline in a
// legalizer body, and the table can neither SELECT nor CHANGE a role — an
// unmapped pair fails closed (caught by the byte-goldens).
inline std::string solidityStatusAtom(projection::ExecutionMode mode,
                                      projection::LifecycleRole role) {
  using projection::ExecutionMode;
  using projection::LifecycleRole;
  struct Binding {
    ExecutionMode mode;
    LifecycleRole role;
    const char *atom;
  };
  static constexpr std::array<Binding, 6> bindings = {{
#define NEU_SOL_STATUS_ATOM(ModeSym, RoleSym, Atom)                            \
  {ExecutionMode::ModeSym, LifecycleRole::RoleSym, Atom},
#include "SolidityTargetEnums.inc"
#undef NEU_SOL_STATUS_ATOM
  }};
  const auto binding =
      std::find_if(bindings.begin(), bindings.end(), [&](const Binding &item) {
        return item.mode == mode && item.role == role;
      });
  return binding == bindings.end() ? "<unmapped-status-atom>" : binding->atom;
}

struct SolStmt {
  // The statement kinds are GENERATED from SolidityTargetNodes.td (): the
  // `.td` is the single source of truth, expanded here into the enum (Ordinal
  // fixes each value, kept identical to the pre-pilot enum so the byte-goldens
  // are unchanged). The check_target_node_registry.py gate reconciles this
  // registry with the toNode dispatch (every kind handled, no drift).
  enum class Kind {
#define NEU_SOL_NODE(Sym, Ordinal, Handler, IsLeaf, Feature) Sym = Ordinal,
#include "SolidityTargetNodes.inc"
  };
  // ENCAPSULATED (): the fields are public-READABLE but `const`, and the
  // constructor is private, so a SolStmt is IMMUTABLE and NOT an aggregate.
  // External code therefore cannot author a raw Line/Block by a `{Kind::Line,
  // …}` aggregate-init or by field mutation (`s.kind = …`) — both are compile
  // errors. The ONLY construction paths are the TYPED factories below (fixed
  // shapes with already-lowered field values, not raw pass-through text); there
  // is no raw-authoring seam ( endpoint — it was deleted at zero callers).
  // check_solidity_syntax_authority.py enforces that no raw factory/wrapper/
  // aggregate/direct-CodeText authoring reappears in production legalization.
  const Kind kind;
  // The ordered, already-lowered field values the printer projects by ordinal
  // (arity-generic — a node carries as many operands as its `.td` grammar
  // binds):
  //   Line     [statement]              Require    [predicate, reason]
  //   Guarded  [predicate]              Transition [state, slot]
  //   Emit     [event, args]            Block      [open, close]
  //   LocalDecl[type, name, init]       Assign     [lhs, rhs]
  //   CompoundAssign[lhs, op, rhs]      DocComment [text]
  //   SpdxLicense[license]              Pragma     [version]
  //   Import   [path]                   EnumDecl   [name, variants]
  //   Blank    []
  const std::vector<std::string> operands;
  const std::vector<SolStmt> body; // Guarded/Block children
  // The optional REPEATED-field (list) group the generated printer projects
  // through a node's `.td` ListField ( §7): a list of items, each an
  // ordered value vector. EventDecl carries its parameters here — one item per
  // parameter,
  // `[type, location, name]` — so the per-parameter shape and the `, `
  // separator are TableGen-owned SHAPE, not a handwritten pre-joined string.
  // Empty for a node with no list field.
  const std::vector<std::vector<std::string>> group;
  // The optional ENUM-field ordinal groups the generated printer spells through
  // a node's `.td` EnumFields (): one entry per enum field, each a list of
  // ordinals into that field's `.td` spelling table (a SCALAR enum carries one
  // ordinal, a REPEATED enum carries the ordered list). FunctionSig carries its
  // callable kind (scalar) and its modifier list (repeated) here — the enum
  // VALUES are legalization-decided; the SPELLING is TableGen-owned. Empty for
  // a node with no enum field.
  const std::vector<std::vector<int>> enumOrdinals;
  // An INERT trailing line-comment (): NOT an operand and NOT projected by
  // the printer template — structurally inert layout metadata. When non-empty,
  // the generic renderer aligns this node among its block siblings into a shared
  // trailing `// …` column via codetext's `commentedLine` (which owns the `// `
  // framing and rejects a newline, so the comment can annotate but never
  // re-author grammar). Empty for every node that carries no trailing comment.
  // This lets the storage-slot comment ride the typed node tree instead of being
  // composed by a handwritten renderer.
  const std::string comment;

  // The typed target-node builders and operand accessor are generated from the
  // package's SolidityTargetNodes.td registry. The generated declarations keep
  // callers on typed nodes while removing handwritten construction authority.
#include "SolidityEmitBuilderDecls.inc"

  // A revert `require(<cond>, "<reason>");` ( typed node): a fixed shape,
  // not raw text — `cond` is an already-lowered predicate.
  // A state-write `<slot> = Status.<state>;` (): the slot is carried, not
  // hard-coded, so a future per-(key, policy) ledger () can target a
  // different slot without a new statement kind.
  // An event emission `emit <event>(<args>);` (): `args` already lowered.
  // A local declaration `<type> <name> = <init>;` ( slice 2a): the whole
  // declaration grammar (type, name, `=`, `;`) is owned by
  // SolidityTargetNodes.td. `type` and `name` are validated (defined
  // out-of-line in SolidityTargetValidation.cpp) to carry NO statement
  // separator (`;`/newline) — the
  // `.td` owns the `= ;` framing, so a separator smuggled into type/name would
  // launder a raw statement past the  ratchet, so it fails closed. `init`
  // is the reviewed expression-renderer boundary (already lowered by toSolidity
  // — the statement shell is what is retired here, not all expression
  // authority).

  // A plain/indexed assignment `<lhs> = <rhs>;` ( slice 2b): the `=`/`;`
  // framing is owned by SolidityTargetNodes.td. BOTH `lhs` and `rhs` are
  // validated (defined out-of-line in SolidityTargetValidation.cpp) to carry NO
  // statement separator (`;`/newline) — either would launder a second raw
  // statement past the  ratchet through this typed shell — so it fails
  // closed. Both operands are already-lowered target text (a storage slot /
  // indexed slot on the left, a lowered expression on the right); compound
  // `+=`/`-=` updates are the CompoundAssign typed node below.

  // A compound update `<lhs> <op> <rhs>;` ( slice 2c): the spacing + `;`
  // framing is owned by SolidityTargetNodes.td. `op` must be exactly `+=` or
  // `-=` (a CLOSED operator vocabulary the factory validates — not free
  // grammar), and BOTH `lhs` and `rhs` are validated (out-of-line in
  // SolidityTargetValidation.cpp) to carry NO statement separator
  // (`;`/newline); any violation fails closed, so neither the operator nor an
  // operand can launder a second statement past the  ratchet. lhs/rhs are
  // already-lowered target text.

  // A NatSpec doc-comment source-unit record `/// <text>` ( slice 1): the
  // `///` marker + separating space is owned by SolidityTargetNodes.td. `text`
  // is the already-decided comment content and must be a SINGLE line — the
  // factory (out-of-line in SolidityTargetValidation.cpp) rejects ANY Solidity
  // line terminator (LF/VT/FF/CR/NEL/LS/PS, via hasSolidityLineTerminator), any
  // of which would end the `///` comment and leave the suffix as live source
  // past the framing.

  // An SPDX license source-unit record `// SPDX-License-Identifier: <license>`
  // ( slice 2): the whole directive prefix is owned by
  // SolidityTargetNodes.td. `license` is the already-decided SPDX
  // identifier/expression; the factory (out-of-line in
  // SolidityTargetValidation.cpp) requires it to be NON-EMPTY and to carry NO
  // Solidity line terminator (LF/VT/FF/CR/NEL/LS/PS, via
  // hasSolidityLineTerminator), any of which would end the `//` comment and
  // leave the suffix as live source. A space is allowed (SPDX license
  // EXPRESSIONS such as `MIT OR Apache-2.0`).

  // A version-pragma source-unit record `pragma solidity <version>;` (
  // slice 3): the whole `pragma solidity ` prefix and the trailing `;` are
  // owned by SolidityTargetNodes.td. `version` is the already-decided version
  // constraint (e.g. `^0.8.20`); the factory (out-of-line in
  // SolidityTargetValidation.cpp) requires it NON-EMPTY and carrying NO
  // statement separator (';' or newline, via hasStatementSeparator), either of
  // which would launder a second statement past the `;` framing the node owns.

  // An import-directive source-unit record `import "<path>";` ( slice 4):
  // the `import "` prefix (with its opening quote) and the closing `";` are
  // owned by SolidityTargetNodes.td. `path` is the already-decided import path
  // and a CLOSED quoted-string operand — the factory (out-of-line in
  // SolidityTargetValidation.cpp) is the whole safety boundary for the Solidity
  // string literal, so it requires it NON-EMPTY and rejects every byte that
  // could change or break the framing: a double quote (`"`), a backslash (`\`
  // escapes the closing quote / forms an escape sequence), a statement
  // separator (';' or newline), any Solidity line terminator
  // (LF/VT/FF/CR/NEL/LS/PS), and any ASCII control byte / DEL.

  // A status-enum type declaration `enum <name> { <variants> }` (): the
  // whole `enum … { … }` construct framing is owned by SolidityTargetNodes.td.
  // `name` and `variants` are already-decided operands (the variant list is
  // comma-joined during legalization, a formatting of the decided SolEnum). The
  // factory (out-of-line in SolidityTargetValidation.cpp) rejects the framing
  // punctuation (`{`/`}`/`;`/newline) in either operand, so a caller cannot
  // break out of the `enum { }` framing.

  // A storage-slot / state-variable declaration `<type> <modifiers> <name>;`
  // (): the whole framing is owned by SolidityTargetNodes.td. `type`,
  // `modifiers`, `name` are already-decided operands; the factory (out-of-line
  // in SolidityTargetValidation.cpp) rejects the framing punctuation
  // (`;`/newline) in any of them. The optional trailing `// …` comment is NOT
  // carried here — its column alignment stays a generic printer concern.

  // An event declaration `event <name>(<params>);` ( §7): the whole
  // `event (...) ;` framing AND the per-parameter shape + `, ` separator are
  // owned by SolidityTargetNodes.td (the `${params}` REPEATED-field
  // projection). The model boundary is TYPED: `params` is a `SolParam` list,
  // and the factory (out-of-line) requires each parameter to carry a NON-EMPTY
  // `type` (an anonymous, location-less param is legal — `location`/`name` may
  // be empty), then projects EXACTLY `[type, location, name]` per parameter
  // into the node's repeated group. So the group is always well-formed 3-slot
  // items — a malformed (empty / wrong-arity) item is unrepresentable through
  // this boundary. `name` is a scalar operand; both it and every parameter
  // field reject the framing punctuation that would break out of the parens or
  // the statement. `params` may be empty (a no-arg event).

  // A callable signature + brace container `<keyword> <name>(<params>)
  // <modifiers> { <body> }` (): a BLOCK node whose `body` children nest
  // between the generated braces. The callable GRAMMAR is a CLOSED TYPED model
  // (): `kind` is a `CallableKind` enum and `modifiers` a canonical list of
  // `CallableModifier` enums — NOT strings — so a new callable/modifier grammar
  // cannot be introduced in C++; the enum-value -> target SPELLING and the
  // repeated-modifier separator/order live in SolidityTargetNodes.td. `name` is
  // empty for a constructor and a Solidity identifier for a function
  // (fail-closed cardinality). `params` is the TYPED `SolParam` list. The
  // factory (out-of-line) enforces the semantic rules the table must not
  // (constructor-name cardinality, no duplicate/conflicting visibility or
  // mutability, canonical modifier order) and the escape surface on every
  // token; it projects the enum ordinals the generated printer spells. This is
  // the sole `<type> [<location>] <name>` parameter authority (it retires
  // SolFunction::signature and SolParam::render).

  //  slice 2: the contract CONTAINER shell `contract <name> { … }`. A typed
  // BLOCK node carrying only the contract name; its children (the contract
  // body) are the already-composed codetext nodes the printer passes to the
  // generated Block renderer. Validates the name as a Solidity identifier free
  // of the escape surface. The `contract <name> {` framing is now `.td`-owned.

  //  slice 3a: a quorum-guard interface METHOD SIGNATURE —
  // `function <name>(<params>) external view returns (<returns>);`. Validates
  // the method name (identifier), each parameter, and the return TYPE against
  // the escape surface. This is the consumer ABI the coordination binds to, NOT
  // the security-reviewed guard body (ThresholdQuorumAcceptance.sol.inc).
  // Typing the signatures (3a) and the shell (3b) drove  to zero. `returns`
  // here is a fixed interface-declaration return type, not the effectful-body
  // returns the  ruling kept out of the model.

  //  slice 3b: the quorum-guard interface SHELL `interface <name> { … }` —
  // a typed BLOCK whose children are the (already-typed) InterfaceSignature
  // methods (rendered recursively between the generated braces). Validates the
  // name as a Solidity identifier; the children must be interface signatures.
  // This was the last raw seam site; typing it drove  to zero (after which
  // the raw seam was deleted).

  //  endpoint — the CONSTRUCTION-LEVEL prohibition. `Line`/`Block` are the
  // only two kinds whose printer template is a bare verbatim `${text}` (every
  // other kind has a fixed structured template that cannot emit an arbitrary
  // statement), i.e. they are raw statement authoring. The SINGLE canonical
  // constructor (below) is the ONE point every SolStmt flows through — the ctor
  // is private, and the other overloads DELEGATE to the canonical one, so there
  // is exactly ONE place that binds `kind`, and it routes through
  // ensureAuthorable, which REJECTS Line/Block by their enum VALUE. That is
  // spelling-INDEPENDENT: `Kind::Line`, `Kind(0)`, a `static_cast`, a C-style
  // cast, an alias — all evaluate to the same value and are caught. A source
  // scanner could not guarantee this (it can't enumerate every cast); this
  // runtime seam is the trust anchor, and check_solidity_syntax_authority.py is
  // defense-in-depth. ensureAuthorable is public so the predicate is
  // unit-tested, and the non-authoring witness below exercises the ACTUAL
  // construction seam without granting private-constructor authority.
  static void ensureAuthorable(Kind k);

  // Non-authoring test witness for the ACTUAL canonical constructor path. It
  // accepts only a kind and returns only whether construction rejected it: no
  // SolStmt, operands, children, groups, enum ordinals, or private-constructor
  // authority can escape.
  static bool rejectsAtConstructionForTest(Kind k);

private:
  // THE canonical constructor: the sole initializer that binds the members. It
  // guards FIRST (`ensureAuthorable` before `kind` is bound), so no
  // operand/child is retained for a forbidden kind. Every other ctor delegates
  // here.
  SolStmt(Kind k, std::vector<std::string> ops, std::vector<SolStmt> b,
          std::vector<std::vector<std::string>> g,
          std::vector<std::vector<int>> e, std::string cm = "")
      : kind((ensureAuthorable(k), k)), operands(std::move(ops)),
        body(std::move(b)), group(std::move(g)), enumOrdinals(std::move(e)),
        comment(std::move(cm)) {}
  // Delegating overloads — they CANNOT bind `kind` themselves, so they cannot
  // bypass the guard by construction. The 4-arg carries `group` AFTER `body`
  // (never a defaulted 3rd overload) so an empty `{}` third argument stays
  // UNAMBIGUOUSLY the `body` — otherwise the SolStmt encapsulation
  // compile-negative probes (aggregate/private-ctor) would see "ambiguous"
  // instead of the private-ctor diagnostic they assert.
  SolStmt(Kind k, std::vector<std::string> ops, std::vector<SolStmt> b = {})
      : SolStmt(k, std::move(ops), std::move(b), {}, {}) {}
  SolStmt(Kind k, std::vector<std::string> ops, std::vector<SolStmt> b,
          std::vector<std::vector<std::string>> g)
      : SolStmt(k, std::move(ops), std::move(b), std::move(g), {}) {}
};

// The GENERATED node-metadata table (), the second consumer of the
// registry: one row per SolStmt::Kind, in ordinal order, carrying the
// printer-handler label + the leaf/feature metadata from the SAME single source
// as the enum. The check_target_node_registry.py gate reconciles these rows
// against the toNode dispatch; a completeness self-test walks the table.
struct SolNodeInfo {
  SolStmt::Kind kind;
  const char *name;
  const char *printerHandler;
  bool isLeaf;
  const char *requiredFeature;
};
inline constexpr SolNodeInfo kSolNodeRegistry[] = {
#define NEU_SOL_NODE(Sym, Ordinal, Handler, IsLeaf, Feature)                   \
  {SolStmt::Kind::Sym, #Sym, Handler, IsLeaf, Feature},
#include "SolidityTargetNodes.inc"
};
inline constexpr int kSolNodeCount =
    sizeof(kSolNodeRegistry) / sizeof(kSolNodeRegistry[0]);

// One `<type> [<location>] [<name>]` parameter of an event or a function. The
// type is a lowered Solidity type; the data location ("calldata") and the name
// are separated so legalization (and 's per-(key, policy) surface) can
// inspect/extend them without string surgery. An anonymous parameter (an
// evidence accept()'s non-key arg) has an empty name.
struct SolParam {
  std::string type;
  std::string location; // "calldata" | "" (none)
  std::string name;     // "" = anonymous
  // NOTE: the `<type> [<location>] <name>` per-parameter SHAPE is
  // TableGen-owned (the  §7 repeated-field projection). There is
  // deliberately NO `render()` here — legalization decides type/location/name;
  // the generated printer joins them. Both the event list and the function
  // signature project this struct.
};

// One legalized statement -> one codetext node. The TYPED shapes expand to
// their fixed Solidity syntax; framing nests; a Line is verbatim. No shape
// carries a decision — the layout is fixed. This is the adapter's sole
// codetext boundary; the renderer (SolidityRenderer.h) composes documents from
// these nodes.
codetext::Node toNode(const SolStmt &s);

} // namespace solidity_model
} // namespace neutrino

#endif // NEUTRINO_BACKENDS_SOLIDITY_SOLIDITYTARGETADAPTER_H

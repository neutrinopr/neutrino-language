#ifndef NEUTRINO_TARGETPRINTER_H
#define NEUTRINO_TARGETPRINTER_H

// Shared target-printer substrate (). This is a tiny MLIR-free driver for
// generated printer records over already-legalized target models. It owns only
// pattern substitution and codetext node construction; target syntax and field
// projections come from generated tables.

#include "Neutrino/CodeText.h"

#include <optional>
#include <vector>

#include <cstddef>
#include <string>

namespace neutrino {
namespace target_printer {

// Line/CommentedLine/Blank/Lines/FramedLines are terminal (leaf) layouts;
// Block and FlatBlock nest children. `CommentedLine` expands the same typed
// declaration pattern as `Line`, then delegates precomputed padding and the
// trailing comment body to codetext's structurally inert comment framing.
// `Lines` renders a FLAT fixed multi-line statement (Syntax split on `\n` into
// N sibling lines). `FramedLines` () renders a fixed HEADER, then ONE
// item-line template repeated once per model tuple, then a fixed FOOTER — all
// flat siblings at the current indent. The two express different cardinality
// operators: `Lines` = one fixed closed sequence; `FramedLines` = fixed prefix
// + repetition of a single item template over a tuple group + an optional fixed
// suffix. The item COUNT is model data; the item SHAPE is fixed (no
// operand-value-driven line selection). `Block` and `FlatBlock` both frame
// typed CHILDREN with an `open`/`close` (CloseSyntax); they differ only in
// indentation — `Block` nests its children one level deeper, `FlatBlock`
// () keeps them at the frame's own indent (the flat  guard
// `IF … THEN … END IF;` whose legs stay flush with the frame).
enum class LayoutKind {
  Line,
  CommentedLine,
  Blank,
  Block,
  FlatBlock,
  Lines,
  FramedLines
};

// Layout data computed from sibling declarations before rendering. The
// declaration remains a typed handler expansion; only alignment and the inert
// comment body travel beside it.
struct CommentedLineData {
  unsigned padding;
  std::string comment;
};

struct FieldBinding {
  const char *name;
  // The ordinal of the model operand this `${name}` placeholder projects. Field
  // projection is arity-generic: a node may bind any number of operands, so the
  // driver is not limited to a fixed text/aux pair.
  unsigned index;
  // OPTIONAL-scalar separator (): a non-null `prefix` is emitted ONLY when
  // the projected value is non-empty — so an absent optional framing field
  // (e.g. a constructor's empty `name`, a function with no `modifiers`)
  // contributes nothing, INCLUDING its leading separator, instead of a stray
  // space. The prefix is TableGen-owned SHAPE; the value stays
  // legalization-decided. `prefix` null (the common case) means the value is
  // projected verbatim.
  const char *prefix;
};

struct Handler {
  int ordinal;
  const char *target;
  const char *node;
  const char *handler;
  LayoutKind layout;
  // The registry's leaf/nesting contract, threaded through so the driver can
  // enforce it: a leaf handler must never be handed children (they would be
  // silently dropped), and a nesting handler (Block/FlatBlock) must be
  // non-leaf. The generator statically guarantees `isLeaf == (layout is not a
  // nesting layout)`; `render` fails closed if a caller violates it.
  bool isLeaf;
  const char *syntax;
  // Block/FlatBlock layout: the close pattern (else "").
  const char *closeSyntax;
  const FieldBinding *fields;
  std::size_t fieldCount;
  // Optional REPEATED-FIELD (list) projection ( §7). When `listField` is
  // non-null, the `${listField}` placeholder in `syntax` expands to the model's
  // repeated group (a list of items, each item an ordered value vector): each
  // item is the `listInner`-join of its NON-EMPTY values (so an absent optional
  // component leaves no double delimiter), and the items are joined by
  // `listOuter`. Both delimiters are TableGen-owned SHAPE — the values are the
  // legalization-decided operands. A node has at most one list field; the
  // driver reads the group via `ResolveGroupsFn`. `listField` null ⇒ no list.
  const char *listField;
  const char *listInner; // between an item's values (e.g. " ")
  const char *listOuter; // between items (e.g. ", ")
  // Optional ENUM-FIELD projections (): a `${name}` placeholder whose value
  // is a CLOSED enum spelled from a `.td`-owned ordinal->spelling table (NOT a
  // free operand). The model carries only the ordinal(s); the driver spells
  // them, failing closed on an out-of-range ordinal. A node may declare
  // several.
  const struct EnumField *enumFields;
  std::size_t enumFieldCount;
  // FRAMED-LINES layout (): a fixed repeated-line block. `syntax` is the
  // fixed HEADER template and `closeSyntax` an optional fixed FOOTER template
  // (both split on `\n` into flat sibling lines, emitted verbatim — no
  // projection). Between them, `itemSyntax` is projected ONCE PER model tuple:
  // each
  // `${name}` spells the tuple's value at the `itemFields[name].index` (dense
  // per-item arity). The tuples come from the reused `ResolveGroupsFn`
  // (line-wise projection, NOT the inline listInner/listOuter join).
  // `itemSyntax` null ⇒ not a framed-lines node. The layout only lays out N
  // tuples + fixed frame; it makes no decision.
  const char *itemSyntax;
  const FieldBinding *itemFields;
  std::size_t itemFieldCount;
  // FRAMED-LINES empty-case placeholder (): a fixed line emitted between
  // the HEADER and FOOTER ONLY when the model supplies ZERO item tuples (split
  // on
  // `\n`, verbatim — no projection). `nullptr` ⇒ an empty group renders
  // header+footer only. This lets a repeated section own its own "nothing here"
  // sentinel so no raw string is appended outside the node.
  const char *emptyItemSyntax;
};

// One closed enum-field projection: the `${name}` placeholder spells the
// model's ordinal(s) from the `.td`-declared `spellings` table. A SCALAR field
// spells one ordinal; a REPEATED field spells the ordered list joined by
// `inner`. A non-null `prefix` is emitted (like FieldBinding's) only when the
// rendered value is non-empty. `groupIndex` selects the node's enum-ordinal
// group. The `spellings`/ `spellingCount` and `inner`/`prefix` are
// TableGen-owned SHAPE; the ordinals are legalization-decided VALUES.
struct EnumField {
  const char *name;
  const char *const *spellings; // ordinal -> literal target spelling
  std::size_t spellingCount;
  bool repeated;
  const char *inner;  // between repeated spellings (e.g. " ")
  const char *prefix; // optional-scalar leading separator, or nullptr
  unsigned groupIndex;
};

using ResolveFieldFn = std::string (*)(const void *model, unsigned index);

// Projects a node's REPEATED-field group: a list of items, each an ordered
// value vector (e.g. a parameter's `[type, location, name]`). Only consulted
// for a handler whose `listField` is non-null.
using ResolveGroupsFn =
    const std::vector<std::vector<std::string>> &(*)(const void *model);

// Projects a node's ENUM-field ordinal groups: one ordinal list per enum field.
// Only consulted for a handler with `enumFieldCount > 0`.
using ResolveEnumsFn =
    const std::vector<std::vector<int>> &(*)(const void *model);

// `operandCount` is the number of SCALAR operands the concrete model carries;
// it MUST equal `handler.fieldCount` (every projected scalar field backed by
// exactly one operand, no missing/extra) or render fails closed — the repeated
// `listField`, if any, is NOT a scalar operand and is not counted here.
// `children` are the already-rendered nested nodes for a Block-layout handler
// (empty for leaves). `resolveGroups` supplies the repeated group when the
// handler has a `listField` (may be null otherwise).
codetext::Node
render(const Handler &handler, const void *model, ResolveFieldFn resolveField,
       std::size_t operandCount, std::vector<codetext::Node> children = {},
       ResolveGroupsFn resolveGroups = nullptr,
       ResolveEnumsFn resolveEnums = nullptr,
       std::optional<CommentedLineData> commentedLine = std::nullopt);

} // namespace target_printer
} // namespace neutrino

#endif // NEUTRINO_TARGETPRINTER_H

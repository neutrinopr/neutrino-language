//===- TargetPrinter.cpp - generated target-printer driver ----------------===//
//
// Shared TableGen printer substrate (). This file is deliberately
// target-agnostic: no Solidity/PostgreSQL node switches, no capability-spec
// reads, and no semantic decisions. Generated records provide syntax/layout and
// field projections over already-legalized target models.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/TargetPrinter.h"

#include "llvm/Support/ErrorHandling.h"

#include <string>

using namespace llvm;

namespace neutrino {
namespace target_printer {

namespace {

[[noreturn]] void fail(const Handler &handler, const std::string &msg) {
  std::string full = "target-printer handler " + std::string(handler.target) +
                     "." + handler.node + ": " + msg;
  report_fatal_error(StringRef(full), /*gen_crash_diag=*/false);
}

const FieldBinding *findField(const Handler &handler, StringRef name) {
  for (std::size_t i = 0; i < handler.fieldCount; ++i)
    if (name == handler.fields[i].name)
      return &handler.fields[i];
  return nullptr;
}

// Expand a handler's REPEATED-field group into its inline text: each item is
// the `listInner`-join of its NON-EMPTY ordered values, and the items are
// joined by `listOuter`. Both delimiters are handler SHAPE; the values come
// from the model.
std::string expandGroup(const Handler &handler, const void *model,
                        ResolveGroupsFn resolveGroups) {
  if (!resolveGroups)
    fail(handler, "syntax references a list field but no group resolver was "
                  "supplied");
  const std::vector<std::vector<std::string>> &items = resolveGroups(model);
  std::string inner = handler.listInner ? handler.listInner : "";
  std::string outer = handler.listOuter ? handler.listOuter : "";
  std::string out;
  for (std::size_t i = 0; i < items.size(); ++i) {
    if (i)
      out += outer;
    std::string item;
    bool first = true;
    for (const std::string &value : items[i]) {
      if (value.empty()) // an absent optional component leaves no delimiter
        continue;
      if (!first)
        item += inner;
      item += value;
      first = false;
    }
    out += item;
  }
  return out;
}

// Split a raw template on `\n` into flat sibling lines, appended verbatim to
// `out` (for a framed-lines fixed HEADER/FOOTER — pure literal shape, no
// projection). An empty template contributes NO line.
void splitOnNewlines(StringRef tmpl, std::vector<std::string> &out) {
  if (tmpl.empty())
    return;
  std::size_t start = 0;
  while (true) {
    std::size_t nl = tmpl.find('\n', start);
    StringRef line = (nl == StringRef::npos) ? tmpl.substr(start)
                                             : tmpl.substr(start, nl - start);
    out.push_back(line.str());
    if (nl == StringRef::npos)
      break;
    start = nl + 1;
  }
}

// Project ONE framed-lines item-line template over ONE model tuple: `${name}`
// spells the tuple's value at `itemFields[name].index` (dense per-item arity).
// A value carrying an embedded `\n`/`\r` fails closed — framed-lines owns the
// structural line boundaries, so a tuple value may never manufacture an extra
// line. Items are PURE dense-tuple projection: no scalar/list/enum fields, no
// predicates or value switches (that stays legalization's decision upstream).
std::string expandItemLine(const Handler &handler, StringRef pattern,
                           const std::vector<std::string> &tuple) {
  std::string out;
  std::size_t pos = 0;
  while (pos < pattern.size()) {
    std::size_t open = pattern.find("${", pos);
    if (open == StringRef::npos) {
      out += pattern.substr(pos).str();
      break;
    }
    out += pattern.substr(pos, open - pos).str();
    std::size_t close = pattern.find("}", open + 2);
    if (close == StringRef::npos)
      fail(handler, "unterminated field placeholder in item syntax");
    StringRef name = pattern.substr(open + 2, close - open - 2);
    const FieldBinding *f = nullptr;
    for (std::size_t i = 0; i < handler.itemFieldCount; ++i)
      if (name == handler.itemFields[i].name) {
        f = &handler.itemFields[i];
        break;
      }
    if (!f)
      fail(handler,
           "item syntax references undeclared item field '" + name.str() + "'");
    if (f->index >= tuple.size())
      fail(handler, "item field '" + name.str() + "' index " +
                        std::to_string(f->index) +
                        " out of range for a tuple of arity " +
                        std::to_string(tuple.size()));
    const std::string &value = tuple[f->index];
    if (value.find('\n') != std::string::npos ||
        value.find('\r') != std::string::npos)
      fail(handler,
           "item field '" + name.str() +
               "' value contains a newline; a framed-lines item may not "
               "manufacture additional lines");
    if (!value.empty()) {
      if (f->prefix)
        out += f->prefix;
      out += value;
    }
    pos = close + 1;
  }
  return out;
}

const EnumField *findEnumField(const Handler &handler, StringRef name) {
  for (std::size_t i = 0; i < handler.enumFieldCount; ++i)
    if (name == handler.enumFields[i].name)
      return &handler.enumFields[i];
  return nullptr;
}

// Expand an ENUM field into its inline text: SPELL each model ordinal from the
// field's `.td` spelling table (fail closed on an out-of-range ordinal — never
// silently blank), joining a REPEATED field's spellings by `inner`. A non-null
// `prefix` is emitted only when the rendered text is non-empty. The spellings
// and delimiters are handler SHAPE; the ordinals come from the model.
std::string expandEnum(const Handler &handler, const EnumField &ef,
                       const void *model, ResolveEnumsFn resolveEnums) {
  if (!resolveEnums)
    fail(handler, "syntax references an enum field but no enum resolver was "
                  "supplied");
  const std::vector<std::vector<int>> &groups = resolveEnums(model);
  if (ef.groupIndex >= groups.size())
    fail(handler, "enum field '" + std::string(ef.name) +
                      "' group index out of range for the model");
  const std::vector<int> &ordinals = groups[ef.groupIndex];
  // A SCALAR enum field spells EXACTLY one ordinal: zero would silently drop a
  // REQUIRED keyword (e.g. an empty `${keyword}`), more than one would
  // concatenate two spellings. Fail closed on either.
  if (!ef.repeated && ordinals.size() != 1)
    fail(handler, "scalar enum field '" + std::string(ef.name) +
                      "' must carry exactly one ordinal, got " +
                      std::to_string(ordinals.size()));
  std::string inner = ef.inner ? ef.inner : "";
  std::string out;
  for (std::size_t i = 0; i < ordinals.size(); ++i) {
    int ord = ordinals[i];
    if (ord < 0 || static_cast<std::size_t>(ord) >= ef.spellingCount)
      fail(handler, "enum field '" + std::string(ef.name) + "' ordinal " +
                        std::to_string(ord) +
                        " has no spelling (out of the closed vocabulary)");
    if (i)
      out += inner;
    out += ef.spellings[ord];
  }
  return out;
}

// Expand `${field}` / `${listField}` / `${enumField}` placeholders in
// `pattern`. When `rejectNewlineValues` is set (the Lines layout), a resolved
// value containing `\n`/`\r` is a boundary error, not a laundered line:
// structural line boundaries must come ONLY from the fixed `\n`s in the .td
// Syntax, so a projected scalar value or repeated-group expansion may never
// manufacture an additional line.
std::string expandTemplate(const Handler &handler, StringRef pattern,
                           const void *model, ResolveFieldFn resolveField,
                           ResolveGroupsFn resolveGroups,
                           ResolveEnumsFn resolveEnums,
                           bool rejectNewlineValues) {
  std::string out;
  std::size_t pos = 0;
  while (pos < pattern.size()) {
    std::size_t open = pattern.find("${", pos);
    if (open == StringRef::npos) {
      out += pattern.substr(pos).str();
      break;
    }
    out += pattern.substr(pos, open - pos).str();
    std::size_t close = pattern.find("}", open + 2);
    if (close == StringRef::npos)
      fail(handler, "unterminated field placeholder in syntax pattern");
    StringRef name = pattern.substr(open + 2, close - open - 2);
    if (handler.listField && name == handler.listField) {
      std::string group = expandGroup(handler, model, resolveGroups);
      if (rejectNewlineValues && (group.find('\n') != std::string::npos ||
                                  group.find('\r') != std::string::npos))
        fail(handler, "list field '" + name.str() +
                          "' expanded to a value containing a newline; a Lines "
                          "layout's structural line boundaries come only from "
                          "the fixed .td Syntax, so a field value may not "
                          "manufacture additional lines");
      out += group;
      pos = close + 1;
      continue;
    }
    if (const EnumField *ef = findEnumField(handler, name)) {
      std::string enumText = expandEnum(handler, *ef, model, resolveEnums);
      // An OPTIONAL-scalar enum (a modifier list) drops its prefix when empty.
      if (!enumText.empty()) {
        if (ef->prefix)
          out += ef->prefix;
        out += enumText;
      }
      pos = close + 1;
      continue;
    }
    const FieldBinding *field = findField(handler, name);
    if (!field)
      fail(handler, "syntax references undeclared field '" + name.str() + "'");
    std::string value = resolveField(model, field->index);
    if (rejectNewlineValues && (value.find('\n') != std::string::npos ||
                                value.find('\r') != std::string::npos))
      fail(handler,
           "field '" + name.str() +
               "' resolved to a value containing a newline; a Lines "
               "layout's structural line boundaries come only from the "
               "fixed .td Syntax, so a field value may not manufacture "
               "additional lines");
    // An OPTIONAL-scalar field: a non-null prefix is emitted with the value
    // only when the value is non-empty, so an absent field drops its separator
    // too.
    if (!value.empty()) {
      if (field->prefix)
        out += field->prefix;
      out += value;
    }
    pos = close + 1;
  }
  return out;
}

std::string expandPattern(const Handler &handler, const void *model,
                          ResolveFieldFn resolveField,
                          ResolveGroupsFn resolveGroups,
                          ResolveEnumsFn resolveEnums) {
  return expandTemplate(handler, StringRef(handler.syntax), model, resolveField,
                        resolveGroups, resolveEnums,
                        /*rejectNewlineValues=*/false);
}

} // namespace

// Expand the Block-layout close pattern (handler.closeSyntax) the same way as
// the open pattern.
static std::string expandClose(const Handler &handler, const void *model,
                               ResolveFieldFn resolveField) {
  StringRef pattern(handler.closeSyntax ? handler.closeSyntax : "");
  std::string out;
  std::size_t i = 0;
  while (i < pattern.size()) {
    std::size_t open = pattern.find("${", i);
    if (open == StringRef::npos) {
      out += pattern.substr(i).str();
      break;
    }
    out += pattern.substr(i, open - i).str();
    std::size_t close = pattern.find('}', open + 2);
    if (close == StringRef::npos)
      fail(handler, "unterminated field placeholder in close pattern");
    StringRef name = pattern.substr(open + 2, close - (open + 2));
    const FieldBinding *field = findField(handler, name);
    if (!field)
      fail(handler,
           "close syntax references undeclared field '" + name.str() + "'");
    std::string value = resolveField(model, field->index);
    if (!value.empty()) {
      if (field->prefix)
        out += field->prefix;
      out += value;
    }
    i = close + 1;
  }
  return out;
}

codetext::Node render(const Handler &handler, const void *model,
                      ResolveFieldFn resolveField, std::size_t operandCount,
                      std::vector<codetext::Node> children,
                      ResolveGroupsFn resolveGroups,
                      ResolveEnumsFn resolveEnums,
                      std::optional<CommentedLineData> commentedLine) {
  // ARITY, fail-closed: the model must carry exactly one operand per projected
  // field — a missing operand would resolve out of range and an extra operand
  // would be silently dropped, either rendering malformed or meaning-changed
  // code. A factory that builds the wrong operand count is a boundary error,
  // not a silent mis-render.
  if (operandCount != handler.fieldCount)
    fail(handler, "operand count " + std::to_string(operandCount) +
                      " does not match the handler's projected field count " +
                      std::to_string(handler.fieldCount));
  // ENUM-GROUP ARITY, fail-closed (analogous to operand arity): the model must
  // carry EXACTLY one ordinal group per declared enum field. A missing group
  // would drop a required enum projection; an EXTRA group is model data the
  // handler silently ignores. When a resolver is supplied we can check both
  // directions up front; a null resolver with declared enum fields is caught at
  // projection time ("no enum resolver").
  if (resolveEnums) {
    const std::vector<std::vector<int>> &enumGroups = resolveEnums(model);
    if (enumGroups.size() != handler.enumFieldCount)
      fail(handler, "model carries " + std::to_string(enumGroups.size()) +
                        " enum ordinal group(s) but the handler declares " +
                        std::to_string(handler.enumFieldCount));
  }
  // Enforce the registry's leaf/nesting contract, fail-closed. The generator
  // guarantees `isLeaf == (layout is not a nesting layout)`, but re-check here
  // so a malformed handler table or a caller that hands children to a leaf can
  // never silently drop a subtree.
  bool nesting = handler.layout == LayoutKind::Block ||
                 handler.layout == LayoutKind::FlatBlock;
  if (handler.isLeaf == nesting)
    fail(handler, nesting ? "nesting-layout handler is marked leaf"
                          : "non-nesting handler is marked non-leaf");
  if (handler.isLeaf && !children.empty())
    fail(handler, "leaf handler was handed children (they would be dropped)");
  if (handler.layout != LayoutKind::CommentedLine && commentedLine)
    fail(handler, "trailing-comment layout data was handed to a non-commented "
                  "handler");
  switch (handler.layout) {
  case LayoutKind::Line:
    return codetext::line(expandPattern(handler, model, resolveField,
                                        resolveGroups, resolveEnums));
  case LayoutKind::CommentedLine: {
    // A commented-line handler renders the SAME typed declaration as a `Line`;
    // the trailing aligned comment is layout data supplied per-node by the
    // generic traversal policy. When no comment data is supplied (a declaration
    // of this kind that simply carries no trailing comment), it renders as a
    // plain line — so ONE handler kind serves both the commented and the bare
    // declaration without a stray `// ` (the codetext comment framing is only
    // introduced when there is a body to frame).
    codetext::Node decl = codetext::line(expandPattern(
        handler, model, resolveField, resolveGroups, resolveEnums));
    if (!commentedLine || commentedLine->comment.empty())
      return decl;
    return codetext::commentedLine(std::move(decl), commentedLine->padding,
                                   std::move(commentedLine->comment));
  }
  case LayoutKind::Blank:
    return codetext::blank();
  case LayoutKind::Block:
    return codetext::block(expandPattern(handler, model, resolveField,
                                         resolveGroups, resolveEnums),
                           expandClose(handler, model, resolveField),
                           std::move(children));
  case LayoutKind::FlatBlock:
    // Same frame as Block (open pattern + close pattern + typed children), but
    // the children render at the frame's own indent — the flat  guard.
    return codetext::flatBlock(expandPattern(handler, model, resolveField,
                                             resolveGroups, resolveEnums),
                               expandClose(handler, model, resolveField),
                               std::move(children));
  case LayoutKind::Lines: {
    // Structural line boundaries come ONLY from the fixed `\n`s in the .td
    // Syntax: split the RAW template on `\n` FIRST, then project fields into
    // each line SEPARATELY — rejecting any resolved value that itself contains
    // `\n`/`\r` (see expandTemplate). A field therefore can never manufacture
    // an extra structural line, and because the split precedes projection each
    // element is a clean single line — codetext's no-embedded-newline invariant
    // holds by construction.
    StringRef tmpl(handler.syntax);
    std::vector<std::string> pieces;
    std::size_t start = 0;
    while (true) {
      std::size_t nl = tmpl.find('\n', start);
      StringRef lineTmpl = (nl == StringRef::npos)
                               ? tmpl.substr(start)
                               : tmpl.substr(start, nl - start);
      pieces.push_back(expandTemplate(handler, lineTmpl, model, resolveField,
                                      resolveGroups, resolveEnums,
                                      /*rejectNewlineValues=*/true));
      if (nl == StringRef::npos)
        break;
      start = nl + 1;
    }
    return codetext::lineGroup(std::move(pieces));
  }
  case LayoutKind::FramedLines: {
    // A fixed HEADER, then ONE item-line template repeated once per model
    // tuple, then an optional fixed FOOTER — all flat siblings at the current
    // indent. The
    // layout only lays out the tuples + fixed frame; which/how-many tuples and
    // their values are legalization's decision, supplied via the group
    // resolver.
    if (!handler.itemSyntax)
      fail(handler, "framed-lines handler has no item syntax");
    if (!resolveGroups)
      fail(handler, "framed-lines handler has no group resolver for its item "
                    "tuples");
    const std::vector<std::vector<std::string>> &tuples = resolveGroups(model);
    std::vector<std::string> pieces;
    // Fixed HEADER (verbatim, split on `\n`).
    splitOnNewlines(StringRef(handler.syntax), pieces);
    // Empty-case placeholder (): when the model supplies NO tuples, a
    // non-null `emptyItemSyntax` is the section's own "nothing here" line
    // (split on `\n`, verbatim) — so the node fully owns its empty rendering
    // and no raw string is appended outside it. With tuples present it
    // contributes nothing.
    if (tuples.empty() && handler.emptyItemSyntax)
      splitOnNewlines(StringRef(handler.emptyItemSyntax), pieces);
    // ONE item-line per tuple. Split itemSyntax on `\n` FIRST, then project
    // each line over the tuple (rejecting newline values) so every element is a
    // clean single line. Preserve tuple order exactly as legalization supplied
    // it.
    StringRef item(handler.itemSyntax);
    for (const std::vector<std::string> &tuple : tuples) {
      // Exact item arity, fail-closed: a missing value would resolve out of
      // range, an extra value is silently unused — either is a boundary error.
      if (tuple.size() != handler.itemFieldCount)
        fail(handler,
             "framed-lines item tuple has arity " +
                 std::to_string(tuple.size()) + " but the handler declares " +
                 std::to_string(handler.itemFieldCount) + " item field(s)");
      std::size_t start = 0;
      while (true) {
        std::size_t nl = item.find('\n', start);
        StringRef lineTmpl = (nl == StringRef::npos)
                                 ? item.substr(start)
                                 : item.substr(start, nl - start);
        pieces.push_back(expandItemLine(handler, lineTmpl, tuple));
        if (nl == StringRef::npos)
          break;
        start = nl + 1;
      }
    }
    // Fixed FOOTER (verbatim, split on `\n`).
    splitOnNewlines(StringRef(handler.closeSyntax ? handler.closeSyntax : ""),
                    pieces);
    return codetext::lineGroup(std::move(pieces));
  }
  }
  fail(handler, "unknown layout kind");
}

} // namespace target_printer
} // namespace neutrino

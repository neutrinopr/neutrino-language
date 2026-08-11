//===- CodeText.cpp - the language-neutral structured code emitter --------===//
//
// M5 codetext S1 (); type-safe representation + raw_ostream printer ().
// The printer for the block/line/blank document model: it owns indentation and
// the structural newlines; the leaf text is verbatim. See Neutrino/CodeText.h.
// Generic mechanics only — no target semantics.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/CodeText.h"

#include "llvm/Support/ErrorHandling.h"
#include "llvm/Support/raw_ostream.h"

#include <algorithm>

using namespace llvm;

namespace neutrino {
namespace codetext {

Node line(std::string text) { return Line{std::move(text)}; }

Node lineGroup(std::vector<std::string> lines) {
  return LineGroup{std::move(lines)};
}

Node blank() { return Blank{}; }

Node block(std::string open, std::string close, std::vector<Node> children) {
  return Block{std::move(open), std::move(close), std::move(children)};
}

Node flatBlock(std::string open, std::string close,
               std::vector<Node> children) {
  return FlatBlock{std::move(open), std::move(close), std::move(children)};
}

void alignTrailingComments(std::vector<Node> &siblings) {
  // The shared comment column is two past the widest COMMENTED declaration —
  // uncommented siblings never widen it (they carry no trailing comment). A
  // list with no commented sibling keeps its column at zero and is left as-is.
  std::size_t column = 0;
  for (const Node &n : siblings)
    if (const CommentLine *c = std::get_if<CommentLine>(&n.value()))
      column = std::max(column, c->child.text.size());
  if (column == 0)
    return;
  column += 2;
  for (Node &n : siblings) {
    const CommentLine *c = std::get_if<CommentLine>(&n.value());
    if (!c)
      continue;
    // Capture before rebuilding (the reassignment invalidates `c`).
    std::string text = c->child.text;
    std::string body = c->body;
    unsigned pad = static_cast<unsigned>(column - text.size());
    n = commentedLine(line(std::move(text)), pad, std::move(body));
  }
}

Node commentedLine(Node child, unsigned pad, std::string commentBody) {
  // The child MUST be a single-line leaf: its verbatim text is what carries the
  // syntax, so a Block/Blank/nested CommentLine child is a caller bug.
  const Line *l = std::get_if<Line>(&child.value());
  if (!l)
    report_fatal_error(
        "codetext::commentedLine: child must be a single-line node");
  return CommentLine{*l, pad, std::move(commentBody)};
}

namespace {

bool hasNewline(const std::string &s) {
  return s.find('\n') != std::string::npos || s.find('\r') != std::string::npos;
}

// The first invariant violation in `node` (or its descendants), or "" if valid.
// With the type-safe node representation the only runtime rule left is the
// no-embedded-newline one (a Line's text / a Block's delimiters must each be a
// single physical line — the printer owns the structural newlines). A Blank has
// nothing to check.
std::string nodeError(const Node &node) {
  const std::variant<Line, Blank, Block, FlatBlock, CommentLine, LineGroup> &v =
      node.value();
  if (const Line *l = std::get_if<Line>(&v)) {
    if (hasNewline(l->text))
      return "a Line's text must be a single line (no newline) — the printer "
             "owns structural newlines";
    return "";
  }
  if (const LineGroup *g = std::get_if<LineGroup>(&v)) {
    // Each element is a flat sibling line at the current indent; the printer
    // owns the structural newline between them, so an embedded newline in any
    // element is rejected exactly like a Line.
    for (const std::string &ln : g->lines)
      if (hasNewline(ln))
        return "a LineGroup element must be a single line (no newline) — the "
               "printer owns structural newlines";
    return "";
  }
  if (const CommentLine *c = std::get_if<CommentLine>(&v)) {
    if (hasNewline(c->child.text) || hasNewline(c->body))
      return "a CommentLine's child text and comment body must each be a "
             "single line (no newline) — the printer owns structural newlines, "
             "and a newline would break the body out of the `//` comment";
    return "";
  }
  if (const Block *b = std::get_if<Block>(&v)) {
    if (hasNewline(b->open) || hasNewline(b->close))
      return "a Block delimiter must be a single line (no newline)";
    for (const Node &child : b->children)
      if (std::string err = nodeError(child); !err.empty())
        return err;
    return "";
  }
  if (const FlatBlock *fb = std::get_if<FlatBlock>(&v)) {
    if (hasNewline(fb->open) || hasNewline(fb->close))
      return "a FlatBlock delimiter must be a single line (no newline)";
    for (const Node &child : fb->children)
      if (std::string err = nodeError(child); !err.empty())
        return err;
    return "";
  }
  return ""; // Blank.
}

void appendIndent(raw_ostream &os, StringRef unit, unsigned depth) {
  for (unsigned i = 0; i < depth; ++i)
    os << unit;
}

void printNode(const Node &node, StringRef unit, unsigned depth,
               raw_ostream &os);

void printNodes(const std::vector<Node> &nodes, StringRef unit, unsigned depth,
                raw_ostream &os) {
  for (const Node &n : nodes)
    printNode(n, unit, depth, os);
}

void printNode(const Node &node, StringRef unit, unsigned depth,
               raw_ostream &os) {
  const std::variant<Line, Blank, Block, FlatBlock, CommentLine, LineGroup> &v =
      node.value();
  if (std::holds_alternative<Blank>(v)) {
    // A blank line carries no indentation — a bare structural separator.
    os << '\n';
    return;
  }
  if (const Line *l = std::get_if<Line>(&v)) {
    appendIndent(os, unit, depth);
    os << l->text << '\n';
    return;
  }
  if (const LineGroup *g = std::get_if<LineGroup>(&v)) {
    // N flat sibling lines, each at THIS indent (no deeper nesting, no
    // framing).
    for (const std::string &ln : g->lines) {
      appendIndent(os, unit, depth);
      os << ln << '\n';
    }
    return;
  }
  if (const CommentLine *c = std::get_if<CommentLine>(&v)) {
    // The child's verbatim syntax, then `pad` alignment spaces, then the
    // codetext-OWNED `// ` framing and the (structurally inert) comment body.
    appendIndent(os, unit, depth);
    os << c->child.text << std::string(c->pad, ' ') << "// " << c->body << '\n';
    return;
  }
  if (const FlatBlock *fb = std::get_if<FlatBlock>(&v)) {
    // Like a Block, but the children render at THIS indent (not depth + 1) — a
    // flat frame whose body sits at the same depth as `open`/`close`. Same
    // empty-delimiter omission. A nested Block child still indents its own
    // children (printNode owns that), so only this frame adds no depth.
    if (!fb->open.empty()) {
      appendIndent(os, unit, depth);
      os << fb->open << '\n';
    }
    printNodes(fb->children, unit, depth, os);
    if (!fb->close.empty()) {
      appendIndent(os, unit, depth);
      os << fb->close << '\n';
    }
    return;
  }
  const Block &b = std::get<Block>(v);
  // open at this indent; body one level deeper; close back at this indent. An
  // EMPTY delimiter is OMITTED (no line) — a block can have a header but no
  // closing bracket (e.g. PL/pgSQL `DECLARE` + indented decls:
  // block("DECLARE", "", …)), or be a bare indented group (both empty). The
  // children are still indented one level, so the printer keeps owning the
  // indentation.
  if (!b.open.empty()) {
    appendIndent(os, unit, depth);
    os << b.open << '\n';
  }
  printNodes(b.children, unit, depth + 1, os);
  if (!b.close.empty()) {
    appendIndent(os, unit, depth);
    os << b.close << '\n';
  }
}

} // namespace

std::string Document::validate() const {
  for (const Node &n : nodes_)
    if (std::string err = nodeError(n); !err.empty())
      return err;
  return "";
}

void Document::print(raw_ostream &os, StringRef indentUnit) const {
  // Fail closed: a structural violation is a caller bug that would emit wrong
  // or silently-truncated code, so abort with the reason rather than print it.
  if (std::string err = validate(); !err.empty()) {
    std::string msg = "codetext: malformed document — " + err;
    report_fatal_error(StringRef(msg), /*gen_crash_diag=*/false);
  }
  printNodes(nodes_, indentUnit, 0, os);
}

std::string Document::print(StringRef indentUnit) const {
  std::string out;
  raw_string_ostream os(out);
  print(os, indentUnit);
  os.flush();
  return out;
}

} // namespace codetext
} // namespace neutrino

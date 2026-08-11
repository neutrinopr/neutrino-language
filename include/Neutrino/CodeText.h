#ifndef NEUTRINO_CODETEXT_H
#define NEUTRINO_CODETEXT_H

// The language-neutral structured code emitter substrate (M5 codetext S1,
// ; type-safe representation ). A tiny block/line/blank document model
// whose printer owns indentation and the structural newlines — so a backend
// renderer describes the SHAPE of its output (nesting + delimiters) and never
// hand-manages indentation or `\n`.
//
// This is generic emission MECHANICS only, not target semantics: block
// delimiters are caller-provided (Solidity/JS `{`…`}`, SQL `BEGIN`…`END`,
// anything), and the leaf text of a `Line` is produced verbatim by the existing
// per-target lowerers. It deliberately carries NO target-expression AST — the
// expression/statement text stays a leaf string ( scope). It is a
// bottom-of- the-graph leaf (`NeutrinoCodeText`, links only llvm Support) so
// any backend module can depend on it without a backend-to-backend edge.
#include "llvm/ADT/StringRef.h"

#include <string>
#include <utility>
#include <variant>
#include <vector>

namespace llvm {
class raw_ostream;
} // namespace llvm

namespace neutrino {
namespace codetext {

// One node of a structured document is EXACTLY ONE of six shapes (): a
// `Line`, a `Blank`, a `Block`, a `FlatBlock` (a framed body whose children
// stay at the CURRENT indent), a `CommentLine` (a line + an aligned trailing
// comment), or a `LineGroup` (N sibling lines at the SAME indent). The
// representation makes invalid states unrepresentable — a `Line` cannot carry
// children or delimiters, a `Blank` cannot carry text — so the "printer owns
// layout" contract is enforced by the type system, not rediscovered at runtime
// by a `validate()` field-consistency scan (only the no-embedded-newline rule,
// which the type system can't express, stays a runtime check).
class Node;

// A single line of verbatim text (printed at the current indentation).
Node line(std::string text);

// A FLAT group of N sibling lines, each printed at the CURRENT indent (NOT one
// level deeper like `block`, and with NO open/close framing). This is the
// substrate for the target-printer `Lines` layout (): a single generated
// node renders a fixed multi-line statement as N flat siblings. Each element is
// exactly a `Line` at the current indent — the caller SPLITS its text on `\n`
// BEFORE calling, so no element ever carries an embedded newline (the printer
// still owns every structural newline; an embedded `\n`/`\r` in any element is
// rejected exactly like a `Line`).
Node lineGroup(std::vector<std::string> lines);

// A generated/leaf line followed by an aligned trailing LINE COMMENT. `child`
// owns the line's SYNTAX (rendered verbatim); `pad` is the count of alignment
// spaces between the line and the comment; `commentBody` is the annotation
// text. codetext OWNS the `// ` comment framing — the body is ALWAYS emitted
// behind codetext's own `// ` on a single physical line (a newline in the body
// is rejected), so it is STRUCTURALLY INERT: this composition can attach a
// comment to a typed node but CANNOT reintroduce target grammar after it (there
// is no caller-supplied raw suffix — a code-bearing `commentBody` renders as an
// inert comment, not live source). `child` must be a single-line leaf (a
// `line(...)`); a non-Line/multi-line child, or a newline in `commentBody`, is
// a caller bug caught at construction / by `print`.
Node commentedLine(Node child, unsigned pad, std::string commentBody);

// GENERIC trailing-comment column alignment (): re-pad every `CommentLine`
// among a sibling node list so each `// ` begins at ONE shared column — two
// past the widest commented declaration in the list. Non-comment siblings and
// their order are untouched; a list with no `CommentLine` is unchanged. This is
// a target-BLIND document-layout policy (it reads only codetext node shapes and
// widths, no backend construct knowledge), so a recursive renderer can align a
// block's commented children by handing them here rather than computing the
// column itself. Idempotent (re-aligning an aligned list is a no-op modulo the
// same column).
void alignTrailingComments(std::vector<Node> &siblings);

// An empty line — a structural separator; never carries indentation.
Node blank();

// A block: `open` on its own line at the current indent, `children` indented
// one level deeper, then `close` on its own line back at the current indent.
// The delimiters are whatever the target uses (`"{"`/`"}"`, `"function f()
// {"`/`"}"`, `"BEGIN"`/`"END;"`, …) — the model is language-neutral. An EMPTY
// `open` or `close` is OMITTED (no line), so a block can be a header with no
// closing bracket (PL/pgSQL `block("DECLARE", "", decls)`) or a bare indented
// group (`block("", "", …)`); the children are still indented one level.
Node block(std::string open, std::string close,
           std::vector<Node> children = {});

// A FLAT-FRAMED block: `open` on its own line at the current indent, `children`
// at the SAME indent (NOT one level deeper like `block`), then `close` on its
// own line at the current indent. Same empty-delimiter omission as `block`. The
// children are still typed `Node`s (a nested `Block` among them indents ITS own
// children normally) — the only difference from `block` is that this frame adds
// no indent to its direct children. The substrate for the target-printer
// `FlatBlock` layout (): the flat  guard `IF <cond> THEN … END IF;`
// whose then-branch legs sit at the guard's own indent.
Node flatBlock(std::string open, std::string close,
               std::vector<Node> children = {});

// A single line of verbatim text, printed at the current indentation.
struct Line {
  std::string text;

private:
  explicit Line(std::string t) : text(std::move(t)) {}
  friend Node line(std::string text);
  friend Node commentedLine(Node child, unsigned pad, std::string commentBody);
};

// A `child` line (its verbatim, unaltered syntax), `pad` alignment spaces, and
// a trailing line comment. codetext OWNS the `// ` framing and renders `body`
// strictly behind it on one physical line, so `body` is structurally a comment
// — it keeps the child authoritative AND cannot re-author the line as raw
// target grammar (there is no free-form suffix; a code-bearing `body` is
// inert).
struct CommentLine {
  Line child;
  unsigned pad;
  std::string body;

private:
  CommentLine(Line c, unsigned p, std::string b)
      : child(std::move(c)), pad(p), body(std::move(b)) {}
  friend Node commentedLine(Node child, unsigned pad, std::string commentBody);
};

// An empty line — a bare structural separator; never indented, never carries
// text.
struct Blank {
private:
  Blank() = default;
  friend Node blank();
};

// A block: `open` on its own line at the current indent, `children` indented
// one level deeper, then `close` on its own line back at the current indent. An
// EMPTY `open` or `close` is OMITTED (no line), so a block can be a header with
// no closing bracket (PL/pgSQL `block("DECLARE", "", decls)`) or a bare
// indented group (both empty); the children are still indented one level.
struct Block {
  std::string open;
  std::string close;
  std::vector<Node> children; // the indented body, in order.

  // Append a child (returns *this so a Block can be built fluently). Defined
  // out-of-line, once `Node` is complete.
  Block &add(Node child);

private:
  Block(std::string o, std::string c, std::vector<Node> body)
      : open(std::move(o)), close(std::move(c)), children(std::move(body)) {}
  friend Node block(std::string open, std::string close,
                    std::vector<Node> children);
};

// A flat-framed block: `open` at the current indent, `children` at the SAME
// indent (NOT one level deeper like a `Block`), then `close` at the current
// indent. Identical to `Block` except the direct children are not indented one
// level — the frame lines sit at the same depth as the body. Same
// empty-delimiter omission. A nested `Block` child still indents its own
// children normally; only THIS frame adds no depth.
struct FlatBlock {
  std::string open;
  std::string close;
  std::vector<Node> children; // the body, at the SAME indent as the frame.

  // Append a child (returns *this so a FlatBlock can be built fluently).
  // Defined out-of-line, once `Node` is complete.
  FlatBlock &add(Node child);

private:
  FlatBlock(std::string o, std::string c, std::vector<Node> body)
      : open(std::move(o)), close(std::move(c)), children(std::move(body)) {}
  friend Node flatBlock(std::string open, std::string close,
                        std::vector<Node> children);
};

// A FLAT group of sibling lines, each printed at the CURRENT indent (NOT one
// level deeper like a `Block`, and with NO open/close framing). Every element
// is a single physical line — the printer owns the structural newline between
// them — so an embedded `\n`/`\r` in any element is rejected exactly like a
// `Line`. The target-printer `Lines` layout () builds this after splitting
// its projected multi-line template on `\n`.
struct LineGroup {
  std::vector<std::string> lines;

private:
  explicit LineGroup(std::vector<std::string> l) : lines(std::move(l)) {}
  friend Node lineGroup(std::vector<std::string> lines);
};

// The tagged union of the five node shapes. Implicitly constructible from any
// one of them, so a factory return or a `Block` value drops straight into a
// `std::vector<Node>` / `Document::add`.
class Node {
public:
  Node(Line node) : value_(std::move(node)) {}
  Node(Blank node) : value_(std::move(node)) {}
  Node(Block node) : value_(std::move(node)) {}
  Node(FlatBlock node) : value_(std::move(node)) {}
  Node(CommentLine node) : value_(std::move(node)) {}
  Node(LineGroup node) : value_(std::move(node)) {}

  const std::variant<Line, Blank, Block, FlatBlock, CommentLine, LineGroup> &
  value() const {
    return value_;
  }

private:
  std::variant<Line, Blank, Block, FlatBlock, CommentLine, LineGroup> value_;
};

inline Block &Block::add(Node child) {
  children.push_back(std::move(child));
  return *this;
}

inline FlatBlock &FlatBlock::add(Node child) {
  children.push_back(std::move(child));
  return *this;
}

// A document root: an ordered sequence of top-level nodes. `print` renders the
// whole tree, owning ALL indentation and structural newlines; every line
// (including the last) is newline-terminated.
class Document {
public:
  // Append a top-level node (returns *this for chaining).
  Document &add(Node node) {
    nodes_.push_back(std::move(node));
    return *this;
  }

  bool empty() const { return nodes_.empty(); }

  // The first structural-invariant violation in the document, or "" when it is
  // well-formed. With the type-safe node representation the ONLY runtime
  // invariant left is: no embedded newline (`\n`/`\r`) in any Line text or
  // Block delimiter — the printer owns ALL structural newlines, so a
  // `line("a\nb")` (which would print an UNindented second physical line) is
  // rejected. (The old "only a Block carries children / only a Line carries
  // text" checks are gone — those states can no longer be constructed.) `print`
  // ENFORCES this (a violation is a caller bug that aborts via
  // report_fatal_error); it is exposed so callers/tests can detect misuse
  // without provoking the abort.
  std::string validate() const;

  // Render the document to an `llvm::raw_ostream`. `indentUnit` is one level of
  // indentation (two spaces by default); nested blocks repeat it per depth.
  // Fails closed: a structural violation (see `validate`) aborts rather than
  // emitting malformed code.
  void print(llvm::raw_ostream &os, llvm::StringRef indentUnit = "  ") const;

  // The convenience `std::string` form — the same rendering, collected through
  // an `llvm::raw_string_ostream`.
  std::string print(llvm::StringRef indentUnit = "  ") const;

private:
  std::vector<Node> nodes_;
};

} // namespace codetext
} // namespace neutrino

#endif // NEUTRINO_CODETEXT_H

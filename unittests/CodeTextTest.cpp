// SPDX-License-Identifier: Apache-2.0
//===- CodeTextTest.cpp - unit tests for the structured code emitter ------===//
//
// The language-neutral block/line/blank document model (include/Neutrino/
// CodeText.h, M5 codetext S1 ): the printer owns indentation + structural
// newlines. These assert the layout mechanics directly — nested blocks print
// with stable indentation and the caller-provided close delimiters —
// independent of any backend renderer. See docs/backends/CODETEXT.md.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/CodeText.h"
#include "Neutrino/TargetPrinter.h"

#include "llvm/Support/raw_ostream.h"

#include "gtest/gtest.h"

using namespace neutrino::codetext;
namespace tp = neutrino::target_printer;

namespace {

TEST(CodeText, EmptyDocumentPrintsNothing) {
  Document doc;
  EXPECT_TRUE(doc.empty());
  EXPECT_EQ(doc.print(), "");
}

TEST(CodeText, LinesAndBlankAtRoot) {
  Document doc;
  doc.add(line("a")).add(blank()).add(line("b"));
  // Every line is newline-terminated; a blank line carries no indentation.
  EXPECT_EQ(doc.print(), "a\n\nb\n");
}

TEST(CodeText, BlockIndentsChildrenAndClosesWithDelimiter) {
  Document doc;
  doc.add(block("{", "}", {line("body")}));
  EXPECT_EQ(doc.print(), "{\n  body\n}\n");
}

TEST(CodeText, EmptyBlockStillPrintsBothDelimiters) {
  Document doc;
  doc.add(block("{", "}"));
  EXPECT_EQ(doc.print(), "{\n}\n");
}

TEST(CodeText, EmptyDelimiterIsOmitted) {
  // A block with an empty close is a header + indented body with no closing
  // bracket (e.g. PL/pgSQL `DECLARE` + decls) — the close line is omitted, the
  // children stay indented.
  Document decl;
  decl.add(block("DECLARE", "", {line("x int;")}));
  EXPECT_EQ(decl.print(), "DECLARE\n  x int;\n");

  // Empty open: an indented body then a close (no opening line).
  Document tail;
  tail.add(block("", "END;", {line("y := 1;")}));
  EXPECT_EQ(tail.print(), "  y := 1;\nEND;\n");

  // Both empty: a bare indented group.
  Document bare;
  bare.add(block("", "", {line("z;")}));
  EXPECT_EQ(bare.print(), "  z;\n");

  // Adjacent header-only + block reproduces DECLARE…decls…BEGIN…body…END; with
  // no stray blank between the sections (the SQL emitter's shape, ).
  Document fn;
  fn.add(block("DECLARE", "", {line("n int;")}));
  fn.add(block("BEGIN", "END;", {line("n := 1;")}));
  EXPECT_EQ(fn.print(), "DECLARE\n  n int;\nBEGIN\n  n := 1;\nEND;\n");
}

TEST(CodeText, NestedBlocksHaveStableIndentation) {
  Document doc;
  doc.add(block(
      "outer {", "}",
      {line("x"), block("inner {", "}", {line("y"), line("z")}), line("w")}));
  EXPECT_EQ(doc.print(), "outer {\n"
                         "  x\n"
                         "  inner {\n"
                         "    y\n"
                         "    z\n"
                         "  }\n"
                         "  w\n"
                         "}\n");
}

TEST(CodeText, FlatBlockKeepsChildrenAtTheFrameIndent) {
  // : the flat  guard — `open`/`close` frame the children, but the
  // children stay at the frame's OWN indent (NOT one level deeper like a Block).
  Document doc;
  doc.add(flatBlock("IF cond THEN", "END IF;", {line("leg1"), line("leg2")}));
  EXPECT_EQ(doc.print(), "IF cond THEN\n"
                         "leg1\n"
                         "leg2\n"
                         "END IF;\n");
}

TEST(CodeText, FlatBlockVsBlockDifferOnlyInChildIndent) {
  // The SAME delimiters + children: a Block indents the body one level; a
  // FlatBlock keeps it flush with the frame — the one difference between them.
  Document nested;
  nested.add(block("IF c THEN", "END IF;", {line("x")}));
  EXPECT_EQ(nested.print(), "IF c THEN\n  x\nEND IF;\n");

  Document flat;
  flat.add(flatBlock("IF c THEN", "END IF;", {line("x")}));
  EXPECT_EQ(flat.print(), "IF c THEN\nx\nEND IF;\n");
}

TEST(CodeText, FlatBlockNestedBlockChildStillSelfIndents) {
  // A Block among a FlatBlock's flat children still indents ITS own children —
  // only the flat frame adds no depth (the  guard wrapping a nested If).
  Document doc;
  doc.add(flatBlock(
      "IF v = 0 THEN", "END IF;",
      {block("IF (a) < 0 THEN", "END IF;", {line("RAISE;")}), line("leg")}));
  EXPECT_EQ(doc.print(), "IF v = 0 THEN\n"
                         "IF (a) < 0 THEN\n"
                         "  RAISE;\n"
                         "END IF;\n"
                         "leg\n"
                         "END IF;\n");
}

TEST(CodeText, FlatBlockNestedInsideBlockIndentsAsAUnit) {
  // A FlatBlock is itself a child: a parent Block indents the WHOLE flat frame
  // (open, its flush children, close) one level — the flat frame composes.
  Document doc;
  doc.add(block("BEGIN", "END;",
                {flatBlock("IF c THEN", "END IF;", {line("leg")})}));
  EXPECT_EQ(doc.print(), "BEGIN\n"
                         "  IF c THEN\n"
                         "  leg\n"
                         "  END IF;\n"
                         "END;\n");
}

TEST(CodeText, FlatBlockEmptyDelimiterIsOmitted) {
  // Same empty-delimiter omission as Block: an empty open/close prints no line.
  Document head;
  head.add(flatBlock("IF c THEN", "", {line("leg")}));
  EXPECT_EQ(head.print(), "IF c THEN\nleg\n");
}

TEST(CodeText, DeepNestingRepeatsTheIndentUnitPerLevel) {
  Document doc;
  doc.add(block("a {", "}",
                {block("b {", "}", {block("c {", "}", {line("deep")})})}));
  EXPECT_EQ(doc.print(), "a {\n"
                         "  b {\n"
                         "    c {\n"
                         "      deep\n"
                         "    }\n"
                         "  }\n"
                         "}\n");
}

TEST(CodeText, IndentUnitIsConfigurable) {
  Document doc;
  doc.add(block("{", "}", {line("body")}));
  // A four-space unit; the printer owns the width, the model is unchanged.
  EXPECT_EQ(doc.print("    "), "{\n    body\n}\n");
  // A tab unit.
  EXPECT_EQ(doc.print("\t"), "{\n\tbody\n}\n");
}

TEST(CodeText, DelimitersAreCallerProvidedLanguageNeutral) {
  // The SAME mechanics render a Solidity-style brace block …
  Document sol;
  sol.add(block("function f() {", "}", {line("return x;")}));
  EXPECT_EQ(sol.print(), "function f() {\n  return x;\n}\n");

  // … and a SQL-style BEGIN/END block — only the delimiters differ.
  Document sql;
  sql.add(block("BEGIN", "END;", {line("RETURN NEW;")}));
  EXPECT_EQ(sql.print(), "BEGIN\n  RETURN NEW;\nEND;\n");
}

TEST(CodeText, BlockFactoryBuildsNestedBodies) {
  // Blocks are created through the restricted public factory, then dropped into
  // the document as nodes.
  Document doc;
  doc.add(block("{", "}", {line("one"), line("two")}));
  EXPECT_EQ(doc.print(), "{\n  one\n  two\n}\n");
}

TEST(CodeText, PrintsDirectlyToRawOstream) {
  // : a document renders straight to an llvm::raw_ostream, and the string
  // convenience form (implemented over raw_string_ostream) is byte-identical.
  Document doc;
  doc.add(line("// SPDX-License-Identifier: MIT"))
      .add(blank())
      .add(block("contract C {", "}",
                 {line("uint256 x;"),
                  block("function f() {", "}", {line("x = 1;")})}));

  std::string viaOstream;
  llvm::raw_string_ostream os(viaOstream);
  doc.print(os);
  os.flush();

  EXPECT_EQ(viaOstream, doc.print());
  EXPECT_EQ(viaOstream, "// SPDX-License-Identifier: MIT\n"
                        "\n"
                        "contract C {\n"
                        "  uint256 x;\n"
                        "  function f() {\n"
                        "    x = 1;\n"
                        "  }\n"
                        "}\n");
}

TEST(CodeText, RawOstreamHonorsTheIndentUnit) {
  // The raw_ostream entry point takes the same configurable indent unit.
  Document doc;
  doc.add(block("{", "}", {line("body")}));
  std::string out;
  llvm::raw_string_ostream os(out);
  doc.print(os, "\t");
  os.flush();
  EXPECT_EQ(out, "{\n\tbody\n}\n");
}

TEST(CodeText, LeafTextIsVerbatim) {
  // The model owns layout, not semantics: leaf text (produced by a target
  // lowerer) is emitted verbatim, including its own inner spacing /
  // punctuation.
  Document doc;
  doc.add(line("a + b * (c - d)"));
  EXPECT_EQ(doc.print(), "a + b * (c - d)\n");
}

// ---- commentedLine: aligned trailing comment over a verbatim child ()
// ----

TEST(CodeText, CommentedLineFramesTheBodyAndAlignsWithPadding) {
  // The child leaf carries the SYNTAX (verbatim); `pad` spaces align the
  // comment column; codetext OWNS the `// ` framing and renders the body behind
  // it. Used to hang a column-aligned comment off a typed declaration node.
  Document doc;
  doc.add(commentedLine(line("uint256 public total;"), 2, "running sum"));
  EXPECT_EQ(doc.print(), "uint256 public total;  // running sum\n");
}

TEST(CodeText, CommentedLineChildIsVerbatimAndBodyCannotBecomeCode) {
  // The child's bytes are emitted unchanged, then padding, then a
  // codetext-owned
  // `// ` and the body. The body is STRUCTURALLY a comment: even a code-bearing
  // string lands behind `// ` on one physical line, so it is inert — the
  // composition cannot re-author live target grammar after the typed node.
  const std::string decl = "mapping(bytes32 => Status) public statusOf;";
  Document annotated;
  annotated.add(commentedLine(line(decl), 1, "per account"));
  EXPECT_EQ(annotated.print(), decl + " // per account\n");

  // A malicious "comment" carrying Solidity source is rendered as an inert
  // comment, NOT appended as live code — proof there is no raw-suffix escape.
  Document tamper;
  tamper.add(
      commentedLine(line(decl), 1, "; selfdestruct(); uint256 injected"));
  EXPECT_EQ(tamper.print(), decl + " // ; selfdestruct(); uint256 injected\n");
}

TEST(CodeText, CommentedLineIsIndentedAsOneLineInsideABlock) {
  // The printer owns indentation: a commentedLine nested in a block is indented
  // once, with the child, padding, and comment on that single physical line.
  Document doc;
  doc.add(block("contract C {", "}",
                {commentedLine(line("uint256 x;"), 2, "slot 0")}));
  EXPECT_EQ(doc.print(), "contract C {\n  uint256 x;  // slot 0\n}\n");
}

TEST(CodeText, EmbeddedNewlineInCommentedLineBodyIsRejected) {
  // The printer owns structural newlines for the body too — a newline would
  // both emit an unindented second physical line AND break the body out of the
  // `//` comment into live code position, so it is rejected.
  Document bodyNl;
  bodyNl.add(commentedLine(line("uint256 x;"), 2, "\nstealFunds();"));
  EXPECT_NE(bodyNl.validate(), "");
}

// ---- structural invariants (fail-closed;  review) ----

TEST(CodeText, WellFormedDocumentValidatesClean) {
  Document doc;
  doc.add(line("a")).add(blank()).add(block("{", "}", {line("b")}));
  EXPECT_EQ(doc.validate(), "");
}

TEST(CodeText, EmbeddedNewlineInLineIsRejected) {
  // The printer owns structural newlines: a `line("a\nb")` would emit an
  // UNindented second physical line, so it is a detected invariant violation,
  // not silent.
  Document doc;
  doc.add(line("a\nb"));
  EXPECT_NE(doc.validate(), "");
  Document cr;
  cr.add(line("a\rb"));
  EXPECT_NE(cr.validate(), "");
}

TEST(CodeText, EmbeddedNewlineInBlockDelimiterIsRejected) {
  Document open;
  open.add(block("if (...) {\nraw", "}", {line("x")}));
  EXPECT_NE(open.validate(), "");
  Document close;
  close.add(block("{", "}\nraw", {line("x")}));
  EXPECT_NE(close.validate(), "");
}

// NOTE (): the old "a stray child on a Line" and "text on a Block" runtime
// checks are gone — those states are now UNREPRESENTABLE. A `Line` has only
// `text`, a `Blank` has no fields, and only a `Block` has `children`, so
// `line("if (...)").add(line("body"))` or setting `.text` on a Block simply
// does not compile. The invariant moved from `validate()` to the type system,
// which is the whole point of the type-safe representation. What remains a
// runtime check — the no-embedded-newline rule, which the types cannot express
// — is covered by the tests below.

TEST(CodeText, NestedViolationIsDetected) {
  Document doc;
  doc.add(block("{", "}", {line("ok"), block("{", "}", {line("deep\nbad")})}));
  EXPECT_NE(doc.validate(), "");
}

TEST(CodeText, CommentInjectionValueIsClosedByConstruction) {
  //  / oracle-JS S3 (): the observer renders its header comment as
  // line("// … '" + untrusted id + "' …"). Expressing the comment as a codetext
  // node closes the comment-injection class BY CONSTRUCTION — a value carrying
  // a newline can no longer break out of the `//` comment into code position,
  // because the emitter rejects an embedded newline (structural safety), not
  // (only) the identifier sanitizer.
  std::string injected = "obs\n  stealFunds();";
  Document doc;
  doc.add(line("// Neutrino oracle observer — observer '" + injected + "'"));
  EXPECT_NE(doc.validate(), "");
  // A carriage return (another line-break vector) is caught too.
  Document cr;
  cr.add(line("// set '" + std::string("x\r  evil()") + "'"));
  EXPECT_NE(cr.validate(), "");
}

TEST(CodeTextDeathTest, CommentedLineRejectsANonLineChild) {
  // The child MUST be a single-line leaf — its verbatim text is the syntax the
  // comment hangs off. A Block (or Blank) child is a caller bug caught at
  // construction, so an annotation can never wrap a nested structure.
  EXPECT_DEATH((void)commentedLine(block("{", "}", {line("x")}), 1, "c"),
               "child must be a single-line node");
  EXPECT_DEATH((void)commentedLine(blank(), 1, "c"),
               "child must be a single-line node");
}

TEST(CodeTextDeathTest, PrintAbortsOnAMalformedDocument) {
  // print() enforces the invariants — it fails closed rather than emit wrong
  // code.
  Document doc;
  doc.add(line("a\nb"));
  EXPECT_DEATH((void)doc.print(), "codetext: malformed document");
}

// The shared target-printer driver (/) enforces the registry's
// leaf/nesting contract at render time, failing closed rather than silently
// mis-rendering. These live here (the NeutrinoCodeText unit that owns the
// driver), not in a backend test, so no extraction boundary is crossed.
static const tp::Handler kLeafBlank{
    /*ordinal=*/0,   "t", "N", "h",     tp::LayoutKind::Blank,
    /*isLeaf=*/true, "",  "",  nullptr, 0};
static const tp::Handler kBlockMarkedLeaf{
    /*ordinal=*/0,   "t", "N", "h",     tp::LayoutKind::Block,
    /*isLeaf=*/true, "o", "c", nullptr, 0};
static const tp::Handler kFlatBlockMarkedLeaf{
    /*ordinal=*/0,   "t", "N", "h",     tp::LayoutKind::FlatBlock,
    /*isLeaf=*/true, "o", "c", nullptr, 0};

TEST(TargetPrinterDeathTest, LeafHandedChildrenAbortsInsteadOfDropping) {
  std::vector<Node> children;
  children.push_back(blank());
  EXPECT_DEATH(
      (void)tp::render(kLeafBlank, nullptr, nullptr, 0, std::move(children)),
      "leaf handler was handed children");
}

TEST(TargetPrinterDeathTest, InconsistentLeafLayoutAborts) {
  // A nesting-layout handler marked leaf is a malformed handler table — the
  // driver rejects it rather than nesting into a "leaf". Both nesting layouts
  // (Block and FlatBlock, ) are exercised so the fail-closed contract is
  // non-vacuous for each variant.
  EXPECT_DEATH((void)tp::render(kBlockMarkedLeaf, nullptr, nullptr, 0, {}),
               "nesting-layout handler is marked leaf");
  EXPECT_DEATH((void)tp::render(kFlatBlockMarkedLeaf, nullptr, nullptr, 0, {}),
               "nesting-layout handler is marked leaf");
}

TEST(TargetPrinter, WellFormedLeafRendersWithoutChildren) {
  // Positive control: the fail-closed checks are specific, not always-fatal —
  // a valid leaf with no children renders normally.
  Document doc;
  doc.add(tp::render(kLeafBlank, nullptr, nullptr, 0, {}));
  EXPECT_EQ(doc.print(), "\n");
}

// A 3-field local-declaration shape (`${type} ${name} = ${rhs};`) over a model
// of ordered operands — the arity-generic projection ( slice 2a).
// resolveField returns the operand at the ordinal index.
static const tp::FieldBinding kDeclFields[] = {
    {"type", 0}, {"name", 1}, {"rhs", 2}};
static const std::vector<std::string> kDeclOps = {"bytes32", "x", "y"};
static std::string declResolve(const void *m, unsigned i) {
  return (*static_cast<const std::vector<std::string> *>(m))[i];
}
static tp::Handler declHandler(const char *syntax) {
  return {7,
          "solidity",
          "LocalDecl",
          "local-decl",
          tp::LayoutKind::Line,
          /*isLeaf=*/true,
          syntax,
          "",
          kDeclFields,
          3};
}

TEST(TargetPrinter, ArityGenericProjectionRendersAllOperands) {
  // The .td syntax record is LOAD-BEARING: the SAME operands rendered through
  // the committed grammar vs a MUTATED one produce DIFFERENT text — so mutating
  // `${type} ${name} = ${rhs};` in SolidityTargetNodes.td changes the rendered
  // (and therefore golden) declaration. The committed form is the exact byte
  // shape the production goldens carry.
  tp::Handler committed = declHandler("${type} ${name} = ${rhs};");
  tp::Handler mutated = declHandler("${type} ${name} := ${rhs};");
  Document a, b;
  a.add(tp::render(committed, &kDeclOps, declResolve, kDeclOps.size()));
  b.add(tp::render(mutated, &kDeclOps, declResolve, kDeclOps.size()));
  EXPECT_EQ(a.print(), "bytes32 x = y;\n");
  EXPECT_EQ(b.print(), "bytes32 x := y;\n");
  EXPECT_NE(a.print(), b.print());
}

TEST(TargetPrinter, CommentedLineRendersTypedDeclarationWithComputedPadding) {
  tp::Handler handler = declHandler("${type} ${name} = ${rhs};");
  handler.layout = tp::LayoutKind::CommentedLine;

  const std::string declaration = "bytes32 x = y;";
  const unsigned commentColumn = 20;
  const unsigned padding = commentColumn - declaration.size();
  Document doc;
  doc.add(tp::render(handler, &kDeclOps, declResolve, kDeclOps.size(), {},
                     nullptr, nullptr,
                     tp::CommentedLineData{padding, "cached digest"}));

  EXPECT_EQ(doc.print(), "bytes32 x = y;      // cached digest\n");
}

TEST(TargetPrinterDeathTest, MissingOperandAborts) {
  // Fewer operands than projected fields would resolve out of range — fail
  // closed.
  tp::Handler h = declHandler("${type} ${name} = ${rhs};");
  EXPECT_DEATH((void)tp::render(h, &kDeclOps, declResolve, 2),
               "operand count 2 does not match");
}

TEST(TargetPrinterDeathTest, ExtraOperandAborts) {
  // More operands than projected fields would be silently dropped — fail
  // closed.
  tp::Handler h = declHandler("${type} ${name} = ${rhs};");
  EXPECT_DEATH((void)tp::render(h, &kDeclOps, declResolve, 4),
               "operand count 4 does not match");
}

// A REPEATED-field (list) projection over a `${name}(${params})` shape (
// §7, the event/parameter-list facility). One scalar field (`name`) plus a list
// field (`params`): each item is the inner-join of its non-empty values, and
// the items are joined by the outer delimiter — BOTH delimiters are handler
// SHAPE.
struct EventLikeModel {
  std::vector<std::string> operands; // scalar: [name]
  std::vector<std::vector<std::string>>
      group; // one [type, location, name]/param
};
static const tp::FieldBinding kEventFields[] = {{"name", 0}};
static std::string eventResolve(const void *m, unsigned i) {
  return static_cast<const EventLikeModel *>(m)->operands[i];
}
static const std::vector<std::vector<std::string>> &eventGroups(const void *m) {
  return static_cast<const EventLikeModel *>(m)->group;
}
static tp::Handler eventHandler(const char *inner, const char *outer) {
  return {16,
          "solidity",
          "EventDecl",
          "event-decl",
          tp::LayoutKind::Line,
          /*isLeaf=*/true,
          "event ${name}(${params});",
          "",
          kEventFields,
          1,
          /*listField=*/"params",
          /*listInner=*/inner,
          /*listOuter=*/outer};
}

TEST(TargetPrinter, RepeatedFieldProjectionJoinsItemsAndOmitsEmptyValues) {
  // The multi-parameter list renders each item as `type [location] name` (empty
  // location omitted — no double space) and joins items with `, `, all from the
  // handler's delimiters — never a pre-joined operand string.
  EventLikeModel m{{"SenderDebitDebited"},
                   {{"string", "", "party"},
                    {"uint256", "", "amount"},
                    {"bytes", "calldata", "data"}}};
  tp::Handler h = eventHandler(" ", ", ");
  Document doc;
  doc.add(tp::render(h, &m, eventResolve, m.operands.size(), {}, eventGroups));
  EXPECT_EQ(doc.print(), "event SenderDebitDebited(string party, uint256 "
                         "amount, bytes calldata data);\n");
}

TEST(TargetPrinter, RepeatedFieldDelimitersAreLoadBearingShape) {
  // Both delimiters are handler SHAPE: the SAME group rendered with a mutated
  // inner or outer delimiter produces DIFFERENT text — proving the
  // per-parameter shape and the separator are TableGen-owned, not handwritten
  // C++.
  EventLikeModel m{{"E"}, {{"string", "", "a"}, {"uint256", "", "b"}}};
  Document committed, mutOuter, mutInner;
  committed.add(tp::render(eventHandler(" ", ", "), &m, eventResolve,
                           m.operands.size(), {}, eventGroups));
  mutOuter.add(tp::render(eventHandler(" ", " | "), &m, eventResolve,
                          m.operands.size(), {}, eventGroups));
  mutInner.add(tp::render(eventHandler("_", ", "), &m, eventResolve,
                          m.operands.size(), {}, eventGroups));
  EXPECT_EQ(committed.print(), "event E(string a, uint256 b);\n");
  EXPECT_EQ(mutOuter.print(), "event E(string a | uint256 b);\n");
  EXPECT_EQ(mutInner.print(), "event E(string_a, uint256_b);\n");
  EXPECT_NE(committed.print(), mutOuter.print());
  EXPECT_NE(committed.print(), mutInner.print());
}

TEST(TargetPrinter, RepeatedFieldEmptyGroupRendersEmptyParens) {
  // A no-argument event: the list projects to nothing between the parens.
  EventLikeModel m{{"Ping"}, {}};
  Document doc;
  doc.add(tp::render(eventHandler(" ", ", "), &m, eventResolve,
                     m.operands.size(), {}, eventGroups));
  EXPECT_EQ(doc.print(), "event Ping();\n");
}

TEST(TargetPrinterDeathTest, ListFieldWithoutGroupResolverAborts) {
  // A handler whose syntax references a list field but no group resolver was
  // supplied is a malformed call — fail closed rather than emit `event N();`.
  EventLikeModel m{{"E"}, {}};
  tp::Handler h = eventHandler(" ", ", ");
  EXPECT_DEATH(
      (void)tp::render(h, &m, eventResolve, m.operands.size(), {}, nullptr),
      "list field but no group resolver");
}

// ---- Enum-field projection: a callable signature () ----

// A FunctionSig-like BLOCK node exercising BOTH enum projections at once: a
// SCALAR enum (`${keyword}` -> "function"/"constructor") and a REPEATED enum
// (`${modifiers}` -> the ordered visibility/mutability list), alongside the
// optional-scalar name prefix and the repeated parameter list. The model
// carries only ORDINALS; the spellings + delimiters are handler SHAPE.
struct FnLikeModel {
  std::vector<std::string> operands; // scalar: [name]
  std::vector<std::vector<std::string>>
      group; // one [type, location, name]/param
  std::vector<std::vector<int>> enumOrdinals; // [ [kind], [modifiers...] ]
};
static const char *const kKindSpellings[] = {"function", "constructor"};
static const char *const kModSpellings[] = {
    "external", "public", "internal", "private", "view", "pure", "payable"};
static const tp::FieldBinding kFnFields[] = {{"name", 0, " "}};
static std::string fnResolve(const void *m, unsigned i) {
  return static_cast<const FnLikeModel *>(m)->operands[i];
}
static const std::vector<std::vector<std::string>> &fnGroups(const void *m) {
  return static_cast<const FnLikeModel *>(m)->group;
}
static const std::vector<std::vector<int>> &fnEnums(const void *m) {
  return static_cast<const FnLikeModel *>(m)->enumOrdinals;
}
// The enum descriptors are parameterized so a test can mutate ONE facet (the
// keyword spelling, the modifier inner separator, the modifier prefix) and
// prove it is load-bearing SHAPE.
static tp::Handler fnHandler(const char *const *kindSpellings,
                             const char *modInner, const char *modPrefix) {
  static tp::EnumField enums[2];
  enums[0] = {"keyword",          kindSpellings,      2,
              /*repeated=*/false,
              /*inner=*/nullptr,  /*prefix=*/nullptr, /*groupIndex=*/0};
  enums[1] = {"modifiers",        kModSpellings,        7,
              /*repeated=*/true,
              /*inner=*/modInner, /*prefix=*/modPrefix, /*groupIndex=*/1};
  return {17,
          "solidity",
          "FunctionSig",
          "function-sig",
          tp::LayoutKind::Block,
          /*isLeaf=*/false,
          "${keyword}${name}(${params})${modifiers} {",
          "}",
          kFnFields,
          1,
          /*listField=*/"params",
          /*listInner=*/" ",
          /*listOuter=*/", ",
          /*enumFields=*/enums,
          /*enumFieldCount=*/2};
}

TEST(TargetPrinter, EnumFieldScalarAndRepeatedProjectionRenderTheCallableLine) {
  // A visibility+mutability function: the scalar keyword ordinal 0 spells
  // "function", the modifier ordinals [0,4] spell "external view" joined by the
  // inner " " and prefixed by " ", the name carries its leading-space prefix,
  // and the parameter list renders — all from ordinals + handler SHAPE.
  FnLikeModel m{
      {"attest"}, {{"string", "calldata", "u_transfer_id"}}, {{0}, {0, 4}}};
  Document doc;
  doc.add(tp::render(fnHandler(kKindSpellings, " ", " "), &m, fnResolve,
                     m.operands.size(), {}, fnGroups, fnEnums));
  EXPECT_EQ(
      doc.print(),
      "function attest(string calldata u_transfer_id) external view {\n}\n");
}

TEST(TargetPrinter, EnumScalarConstructorOrdinalSelectsTheOtherSpelling) {
  // The OTHER scalar ordinal (1 -> "constructor") with no modifiers: the empty
  // repeated enum drops its optional-scalar prefix (no trailing space before
  // the brace), and the empty name prefix drops too — proving both
  // optional-scalars.
  FnLikeModel m{{""}, {{"address", "", "g"}}, {{1}, {}}};
  Document doc;
  doc.add(tp::render(fnHandler(kKindSpellings, " ", " "), &m, fnResolve,
                     m.operands.size(), {}, fnGroups, fnEnums));
  EXPECT_EQ(doc.print(), "constructor(address g) {\n}\n");
}

TEST(TargetPrinter, EnumSpellingIsLoadBearingShape) {
  // The ordinal->spelling table is handler SHAPE: the SAME ordinals spelled
  // from a MUTATED keyword table produce DIFFERENT text — proving the spelling
  // is TableGen-owned, not baked into the model.
  static const char *const kMutKind[] = {"functionx", "constructor"};
  FnLikeModel m{{"attest"}, {}, {{0}, {0}}};
  Document committed, mutated;
  committed.add(tp::render(fnHandler(kKindSpellings, " ", " "), &m, fnResolve,
                           m.operands.size(), {}, fnGroups, fnEnums));
  mutated.add(tp::render(fnHandler(kMutKind, " ", " "), &m, fnResolve,
                         m.operands.size(), {}, fnGroups, fnEnums));
  EXPECT_EQ(committed.print(), "function attest() external {\n}\n");
  EXPECT_EQ(mutated.print(), "functionx attest() external {\n}\n");
  EXPECT_NE(committed.print(), mutated.print());
}

TEST(TargetPrinter, RepeatedEnumSeparatorAndPrefixAreLoadBearingShape) {
  // The repeated enum's inner separator AND its optional-scalar prefix are
  // handler SHAPE: mutating either re-renders the modifier list differently for
  // the SAME ordinals [0,4] (external, view).
  FnLikeModel m{{"attest"}, {}, {{0}, {0, 4}}};
  Document committed, mutInner, mutPrefix;
  committed.add(tp::render(fnHandler(kKindSpellings, " ", " "), &m, fnResolve,
                           m.operands.size(), {}, fnGroups, fnEnums));
  mutInner.add(tp::render(fnHandler(kKindSpellings, "|", " "), &m, fnResolve,
                          m.operands.size(), {}, fnGroups, fnEnums));
  mutPrefix.add(tp::render(fnHandler(kKindSpellings, " ", "  "), &m, fnResolve,
                           m.operands.size(), {}, fnGroups, fnEnums));
  EXPECT_EQ(committed.print(), "function attest() external view {\n}\n");
  EXPECT_EQ(mutInner.print(), "function attest() external|view {\n}\n");
  EXPECT_EQ(mutPrefix.print(), "function attest()  external view {\n}\n");
  EXPECT_NE(committed.print(), mutInner.print());
  EXPECT_NE(committed.print(), mutPrefix.print());
}

TEST(TargetPrinterDeathTest, EnumOrdinalOutOfRangeAborts) {
  // An ordinal with no spelling in the closed vocabulary is a boundary error —
  // fail closed rather than silently blank the keyword.
  FnLikeModel m{{"attest"}, {}, {{9}, {0}}};
  tp::Handler h = fnHandler(kKindSpellings, " ", " ");
  EXPECT_DEATH((void)tp::render(h, &m, fnResolve, m.operands.size(), {},
                                fnGroups, fnEnums),
               "has no spelling");
}

TEST(TargetPrinterDeathTest, ScalarEnumWithMultipleOrdinalsAborts) {
  // A scalar enum field (keyword) whose model group carries >1 ordinal is
  // malformed — fail closed rather than concatenate two keywords.
  FnLikeModel m{{"attest"}, {}, {{0, 1}, {0}}};
  tp::Handler h = fnHandler(kKindSpellings, " ", " ");
  EXPECT_DEATH((void)tp::render(h, &m, fnResolve, m.operands.size(), {},
                                fnGroups, fnEnums),
               "must carry exactly one ordinal");
}

TEST(TargetPrinterDeathTest, EmptyScalarEnumGroupAborts) {
  // A scalar enum field with an EMPTY ordinal group would silently drop the
  // required keyword (render an empty `${keyword}`) — fail closed on zero, not
  // just on >1.
  FnLikeModel m{{"attest"}, {}, {{}, {0}}}; // empty scalar keyword group
  tp::Handler h = fnHandler(kKindSpellings, " ", " ");
  EXPECT_DEATH((void)tp::render(h, &m, fnResolve, m.operands.size(), {},
                                fnGroups, fnEnums),
               "must carry exactly one ordinal");
}

TEST(TargetPrinterDeathTest, EnumFieldWithoutEnumResolverAborts) {
  // A handler whose syntax references an enum field but no enum resolver was
  // supplied is a malformed call — fail closed.
  FnLikeModel m{{"attest"}, {}, {{0}, {0}}};
  tp::Handler h = fnHandler(kKindSpellings, " ", " ");
  EXPECT_DEATH((void)tp::render(h, &m, fnResolve, m.operands.size(), {},
                                fnGroups, nullptr),
               "no enum resolver");
}

TEST(TargetPrinterDeathTest, MissingEnumGroupAborts) {
  // The model must carry EXACTLY one ordinal group per declared enum field; a
  // model missing the modifier group (only the keyword group present) is a
  // boundary error caught by the render-entry enum-group arity check.
  FnLikeModel m{{"attest"}, {}, {{0}}}; // no group 1 for ${modifiers}
  tp::Handler h = fnHandler(kKindSpellings, " ", " ");
  EXPECT_DEATH((void)tp::render(h, &m, fnResolve, m.operands.size(), {},
                                fnGroups, fnEnums),
               "enum ordinal group.*but the handler declares 2");
}

TEST(TargetPrinterDeathTest, ExtraEnumGroupAborts) {
  // The REVERSE direction: a model carrying MORE ordinal groups than the
  // handler declares is silently-ignored data — fail closed rather than drop
  // it.
  FnLikeModel m{{"attest"}, {}, {{0}, {0}, {0}}}; // 3 groups vs 2 declared
  tp::Handler h = fnHandler(kKindSpellings, " ", " ");
  EXPECT_DEATH((void)tp::render(h, &m, fnResolve, m.operands.size(), {},
                                fnGroups, fnEnums),
               "3 enum ordinal group.*but the handler declares 2");
}

// ---- Lines layout: a FLAT multi-line statement () ----

// A 3-line Lines node whose MIDDLE line interpolates one operand. The whole
// newline-joined template is projected once and split into flat sibling lines.
static const tp::FieldBinding kLinesFields[] = {{"middle", 0}};
static const std::vector<std::string> kLinesOps = {"PROJECTED"};
static std::string linesResolve(const void *m, unsigned i) {
  return (*static_cast<const std::vector<std::string> *>(m))[i];
}
static tp::Handler linesHandler(const char *syntax) {
  return {0,
          "linesfixture",
          "MultiLine",
          "multi-line",
          tp::LayoutKind::Lines,
          /*isLeaf=*/true,
          syntax,
          "",
          kLinesFields,
          1};
}

TEST(TargetPrinter, LinesRendersFlatSiblingsAtTheCurrentIndent) {
  // (a) three FLAT sibling lines at the SAME indent — nested in a block, all
  // three carry ONE indent, NOT the progressive nesting Block would produce;
  // (b) the ${middle} on the MIDDLE line projects its value.
  tp::Handler h = linesHandler("first line\nmiddle ${middle} line\nthird line");
  Document doc;
  doc.add(tp::render(h, &kLinesOps, linesResolve, kLinesOps.size()));
  EXPECT_EQ(doc.print(), "first line\nmiddle PROJECTED line\nthird line\n");

  Document nested;
  nested.add(
      block("wrap {", "}",
            {tp::render(h, &kLinesOps, linesResolve, kLinesOps.size())}));
  EXPECT_EQ(nested.print(), "wrap {\n"
                            "  first line\n"
                            "  middle PROJECTED line\n"
                            "  third line\n"
                            "}\n");
}

TEST(TargetPrinter, LinesPreservesTheNoEmbeddedNewlineInvariant) {
  // (c) codetext invariant: the driver SPLITS the projected template before
  // constructing any line, so no emitted line carries an embedded newline —
  // the document validates clean and print() does not abort.
  tp::Handler h = linesHandler("first line\nmiddle ${middle} line\nthird line");
  Document doc;
  doc.add(tp::render(h, &kLinesOps, linesResolve, kLinesOps.size()));
  EXPECT_EQ(doc.validate(), "");
}

TEST(TargetPrinter, LinesSyntaxMutationChangesOutput) {
  // (d) the Syntax is LOAD-BEARING: removing a line (or changing a placeholder)
  // changes the rendered bytes.
  tp::Handler committed =
      linesHandler("first line\nmiddle ${middle} line\nthird line");
  tp::Handler dropped = linesHandler("first line\nmiddle ${middle} line");
  Document a, b;
  a.add(tp::render(committed, &kLinesOps, linesResolve, kLinesOps.size()));
  b.add(tp::render(dropped, &kLinesOps, linesResolve, kLinesOps.size()));
  EXPECT_EQ(a.print(), "first line\nmiddle PROJECTED line\nthird line\n");
  EXPECT_EQ(b.print(), "first line\nmiddle PROJECTED line\n");
  EXPECT_NE(a.print(), b.print());
}

TEST(TargetPrinterDeathTest, LinesRejectsANewlineBearingFieldValue) {
  // BOUNDARY (): structural line boundaries come ONLY from the fixed `\n`s
  // in the .td Syntax. A field value carrying its own `\n` must FAIL the render
  // rather than be laundered into an extra clean sibling line — the driver
  // splits the template before projection and rejects a multi-line value.
  tp::Handler h = linesHandler("first line\nmiddle ${middle} line\nthird line");
  const std::vector<std::string> injected = {"PROJECTED\nDROP TABLE postings;"};
  EXPECT_DEATH((void)tp::render(h, &injected, linesResolve, injected.size()),
               "may not manufacture additional lines");
  // A `\r`-bearing value is rejected the same way (the `\r` policy is pinned).
  const std::vector<std::string> cr = {"PROJECTED\rphantom"};
  EXPECT_DEATH((void)tp::render(h, &cr, linesResolve, cr.size()),
               "may not manufacture additional lines");
}

// The codetext lineGroup node prints its elements flat at the current indent
// and rejects an embedded newline exactly like a Line.
TEST(CodeText, LineGroupPrintsFlatAndRejectsEmbeddedNewline) {
  Document flat;
  flat.add(lineGroup({"a", "b", "c"}));
  EXPECT_EQ(flat.print(), "a\nb\nc\n");

  Document nested;
  nested.add(block("{", "}", {lineGroup({"a", "b"})}));
  EXPECT_EQ(nested.print(), "{\n  a\n  b\n}\n");

  Document bad;
  bad.add(lineGroup({"ok", "two\nlines"}));
  EXPECT_NE(bad.validate(), "");
}

TEST(TargetPrinter, OptionalScalarPrefixOnlyAppliesToNonEmptyValue) {
  // Directly: a Line node with one required + one optional-prefix field. The
  // prefix is emitted with a present value and dropped for an empty one.
  static const tp::FieldBinding kFields[] = {{"kw", 0, nullptr},
                                             {"mod", 1, " "}};
  tp::Handler h{9,
                "t",
                "N",
                "h",
                tp::LayoutKind::Line,
                true,
                "${kw}${mod};",
                "",
                kFields,
                2,
                nullptr,
                nullptr,
                nullptr};
  std::vector<std::string> present = {"return x", "public"};
  std::vector<std::string> absent = {"return x", ""};
  Document a, b;
  a.add(tp::render(h, &present, declResolve, present.size()));
  b.add(tp::render(h, &absent, declResolve, absent.size()));
  EXPECT_EQ(a.print(), "return x public;\n");
  EXPECT_EQ(b.print(), "return x;\n");
}

// ---- FramedLines layout: fixed header + repeated item line + fixed footer
// () ----

// The item tuples (one [input, set, quorum] per policy) come from a group
// resolver, exactly like the repeated-field channel — but projected LINE-wise.
struct FramedModel {
  std::vector<std::vector<std::string>> group;
};
static const std::vector<std::vector<std::string>> &
framedGroups(const void *m) {
  return static_cast<const FramedModel *>(m)->group;
}
static std::string framedNoScalar(const void *, unsigned) { return ""; }
static const tp::FieldBinding kFramedItemFields[] = {
    {"input", 0, nullptr}, {"set", 1, nullptr}, {"quorum", 2, nullptr}};
static tp::Handler framedHandler() {
  tp::Handler h{
      0, "t", "PolicyCase", "policy-case", tp::LayoutKind::FramedLines,
      /*isLeaf=*/true,
      /*syntax(header)=*/"CASE p_policy",
      /*closeSyntax(footer)=*/
      "  ELSE RAISE EXCEPTION 'unknown policy %', p_policy;\nEND CASE;",
      /*fields=*/nullptr,
      /*fieldCount=*/0,
      /*listField=*/nullptr, nullptr, nullptr,
      /*enumFields=*/nullptr,
      /*enumFieldCount=*/0,
      /*itemSyntax=*/
      "  WHEN ${input} THEN v_set := ${set}; v_m := ${quorum};",
      /*itemFields=*/kFramedItemFields,
      /*itemFieldCount=*/3};
  return h;
}

TEST(TargetPrinter, FramedLinesRendersHeaderNItemsFooterFlat) {
  // (a) N item lines between a fixed header/footer, all FLAT siblings at one
  // indent (nested in a block: header/items/footer share ONE level, not
  // progressive nesting); (b) per-item projection of each tuple in order.
  FramedModel m{{{"'p_hi'", "'set_hi'", "2"}, {"'p_lo'", "'set_lo'", "1"}}};
  tp::Handler h = framedHandler();
  Document doc;
  doc.add(tp::render(h, &m, framedNoScalar, 0, {}, framedGroups));
  EXPECT_EQ(doc.print(),
            "CASE p_policy\n"
            "  WHEN 'p_hi' THEN v_set := 'set_hi'; v_m := 2;\n"
            "  WHEN 'p_lo' THEN v_set := 'set_lo'; v_m := 1;\n"
            "  ELSE RAISE EXCEPTION 'unknown policy %', p_policy;\n"
            "END CASE;\n");

  Document nested;
  nested.add(block("wrap {", "}",
                   {tp::render(h, &m, framedNoScalar, 0, {}, framedGroups)}));
  EXPECT_EQ(nested.print(),
            "wrap {\n"
            "  CASE p_policy\n"
            "    WHEN 'p_hi' THEN v_set := 'set_hi'; v_m := 2;\n"
            "    WHEN 'p_lo' THEN v_set := 'set_lo'; v_m := 1;\n"
            "    ELSE RAISE EXCEPTION 'unknown policy %', p_policy;\n"
            "  END CASE;\n"
            "}\n");
}

TEST(TargetPrinter, FramedLinesRendersOneItem) {
  FramedModel m{{{"'only'", "'s'", "1"}}};
  Document doc;
  doc.add(tp::render(framedHandler(), &m, framedNoScalar, 0, {}, framedGroups));
  EXPECT_EQ(doc.print(),
            "CASE p_policy\n"
            "  WHEN 'only' THEN v_set := 's'; v_m := 1;\n"
            "  ELSE RAISE EXCEPTION 'unknown policy %', p_policy;\n"
            "END CASE;\n");
}

TEST(TargetPrinter, FramedLinesZeroItemsRendersHeaderFooterOnly) {
  // A generic framed-lines node with zero tuples renders header+footer with no
  // item lines — the LAYOUT does not require items (semantic cardinality is the
  // upstream factory's job, not the layout's decision).
  FramedModel m{{}};
  Document doc;
  doc.add(tp::render(framedHandler(), &m, framedNoScalar, 0, {}, framedGroups));
  EXPECT_EQ(doc.print(),
            "CASE p_policy\n"
            "  ELSE RAISE EXCEPTION 'unknown policy %', p_policy;\n"
            "END CASE;\n");
}

TEST(TargetPrinter, FramedLinesItemTupleIsLoadBearing) {
  // The tuple values drive the emitted item bytes: two different groups produce
  // different output — the item is a real per-tuple projection, not a constant.
  FramedModel a{{{"'x'", "'sx'", "1"}}};
  FramedModel b{{{"'y'", "'sy'", "9"}}};
  Document da, db;
  da.add(tp::render(framedHandler(), &a, framedNoScalar, 0, {}, framedGroups));
  db.add(tp::render(framedHandler(), &b, framedNoScalar, 0, {}, framedGroups));
  EXPECT_NE(da.print(), db.print());
}

TEST(TargetPrinterDeathTest, FramedLinesRejectsWrongTupleArity) {
  // Exact per-item arity, fail-closed: a tuple with the wrong number of values
  // aborts rather than silently dropping/ignoring a slot.
  FramedModel m{{{"'p'", "'s'"}}}; // arity 2, handler declares 3
  EXPECT_DEATH((void)tp::render(framedHandler(), &m, framedNoScalar, 0, {},
                                framedGroups),
               "item tuple has arity");
}

TEST(TargetPrinterDeathTest, FramedLinesRejectsNewlineBearingItemValue) {
  // A tuple value carrying its own `\n` may not manufacture an extra line — the
  // item owns no structural newline. Fail closed.
  FramedModel m{{{"'p'\nDROP TABLE x;", "'s'", "1"}}};
  EXPECT_DEATH((void)tp::render(framedHandler(), &m, framedNoScalar, 0, {},
                                framedGroups),
               "may not manufacture additional lines");
}

TEST(TargetPrinterDeathTest, FramedLinesRejectsMissingGroupResolver) {
  FramedModel m{{{"'p'", "'s'", "1"}}};
  EXPECT_DEATH(
      (void)tp::render(framedHandler(), &m, framedNoScalar, 0, {}, nullptr),
      "no group resolver");
}

} // namespace

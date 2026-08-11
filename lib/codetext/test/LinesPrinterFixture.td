//===- LinesPrinterFixture.td - TEST-ONLY Lines-layout substrate fixture --===//
//
// TEST-ONLY fixture (). Proves the shared target-printer `Lines` layout end
// to end: a single generated node renders a FLAT multi-line statement — N lines
// at the SAME indent, each line may interpolate `${field}`.
//
// It is NOT a production backend: it lives under lib/codetext/test/ with a
// non-`*TargetNodes.td` name, so neither the backend-discovery glob
// (lib/backends/**/*TargetNodes.td) used by check_target_node_registry.py nor the
// idiom-gate discovery (lib/backends/**) picks it up. It therefore pollutes no
// production inventory, coverage, or registry; only the fixture render test
// (lib/codetext/test) consumes it.
//
//===----------------------------------------------------------------------===//

include "TargetPrinter.td"

def LinesStmtModel
    : TargetPrinterModel<"linesfixture", "LinesStmt", "LINESFIX", 1>;

// The closed projection-table wrapper — IDENTICAL in shape to the production
// SolNode/PgNode wrappers, so the idiom gate validates the fixture as a closed
// literal idiom (no extra fields, no control constructs).
class LinesFixtureNode<int ord, string handler, bit leaf, string feature,
                       string layout = "", string syntax = "",
                       list<PrinterField> fields = [], bit generated = 0,
                       string closeSyntax = "", string listField = "",
                       string listInner = "", string listOuter = "",
                       list<EnumField> enumFields = []>
    : TargetPrinterNode<"linesfixture", "LinesStmt", ord, handler, leaf, feature,
                        layout, syntax, fields, generated, closeSyntax,
                        "LINESFIX", listField, listInner, listOuter, enumFields>;

def FMiddle : PrinterField<"middle", 0>;

// A FIXED three-line statement. WHICH lines exist is FIXED here; only the
// `${middle}` VALUE varies at render time. There is NO operand-driven /
// conditional line selection (that would be a decision, rejected by the gate's
// ban on TableGen bang operators) — the whole newline-joined template is ONE
// closed literal idiom, projected once and split into flat sibling lines.
def MultiLine : LinesFixtureNode<0, "multi-line", /*leaf=*/1, "fixture", "lines",
                        "first line\nmiddle ${middle} line\nthird line",
                        [FMiddle], /*generated=*/1>;

//===- FramedLinesFixture.td - TEST-ONLY framed-lines substrate fixture ---===//
//
// TEST-ONLY fixture (). Proves the shared target-printer `framed-lines`
// layout end to end through the REAL generator: a single generated node renders
// a fixed HEADER, one item-line template repeated ONCE PER model tuple, and a
// fixed FOOTER — all flat siblings at the current indent.
//
// It is NOT a production backend: it lives under lib/codetext/test/ with a
// non-`*TargetNodes.td` name, so neither the backend-discovery glob
// (lib/backends/**/*TargetNodes.td) used by check_target_node_registry.py nor the
// idiom-gate discovery (lib/backends/**) picks it up. It pollutes no production
// inventory, coverage, or registry; only the fixture render pair consumes it.
//
//===----------------------------------------------------------------------===//

include "TargetPrinter.td"

def FramedStmtModel
    : TargetPrinterModel<"framedfixture", "FramedStmt", "FRAMEDFIX", 1>;

// The closed projection-table wrapper — IDENTICAL in shape to the production
// SolNode/PgNode wrappers (extended with the framed-lines ItemSyntax/ItemFields
// tail), so the idiom gate validates the fixture as a closed literal idiom.
class FramedLinesFixtureNode<int ord, string handler, bit leaf, string feature,
                             string layout = "", string syntax = "",
                             list<PrinterField> fields = [], bit generated = 0,
                             string closeSyntax = "", string listField = "",
                             string listInner = "", string listOuter = "",
                             list<EnumField> enumFields = [],
                             string itemSyntax = "",
                             list<PrinterField> itemFields = []>
    : TargetPrinterNode<"framedfixture", "FramedStmt", ord, handler, leaf,
                        feature, layout, syntax, fields, generated, closeSyntax,
                        "FRAMEDFIX", listField, listInner, listOuter, enumFields,
                        itemSyntax, itemFields>;

// The per-item tuple fields: each `${name}` spells the tuple value at its index.
def FInput  : PrinterField<"input",  0>;
def FSet    : PrinterField<"set",    1>;
def FQuorum : PrinterField<"quorum", 2>;

// A FIXED-shape framed block: a literal `CASE p_policy` header, the SAME
// `WHEN … THEN …;` item line repeated once per tuple (dense [input, set,
// quorum]), and a literal `ELSE …; / END CASE;` footer. WHICH item lines exist
// is model data (the tuple count); the item SHAPE and the header/footer are
// fixed literals — there is NO operand-value-driven line selection (that would
// be a decision, rejected by the gate's ban on TableGen bang operators).
def PolicyCase : FramedLinesFixtureNode<
    0, "policy-case", /*leaf=*/1, "fixture", "framed-lines",
    /*header=*/"CASE p_policy",
    /*fields=*/[], /*generated=*/1,
    /*footer=*/"  ELSE RAISE EXCEPTION 'unknown policy %', p_policy;\nEND CASE;",
    /*listField=*/"", /*listInner=*/"", /*listOuter=*/"", /*enumFields=*/[],
    /*itemSyntax=*/"  WHEN ${input} THEN v_set := ${set}; v_m := ${quorum};",
    /*itemFields=*/[FInput, FSet, FQuorum]>;

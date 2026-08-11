//===- TargetPrinter.td - shared target-printer schema --------------------===//
//
// Shared TableGen printer schema (). Records describe syntax/layout and
// field projection for already-legalized target-model nodes. They do not read a
// capability spec, infer target semantics, or decide workflow/policy/balance/
// replay/lifecycle/profile legality.
//
//===----------------------------------------------------------------------===//

// Declares a closed target-model carrier even before its first node kind lands.
// This lets one backend registry govern disjoint model axes (for example,
// procedure statements and schema declarations) without inventing a second
// target table or allowing one carrier's kinds to inhabit the other.
// Exactly one model per backend is Primary, anchoring reconciliation
// independently of wrapper or model-name ordering.
class TargetPrinterModel<string target, string model, string abbrev,
                         bit primary> {
  string Target = target;
  string Model = model;
  string Abbrev = abbrev;
  bit Primary = primary;
}

// A printer field binds a `${name}` placeholder to the model operand at ordinal
// `index`. Projection is ARITY-GENERIC: a node may project any number of
// operands (0, 1, 2, …), not a fixed text/aux pair — so multi-field statement
// grammars (e.g. `${type} ${name} = ${rhs};`) are expressible.
class PrinterField<string name, int index, string prefix = ""> {
  string Name = name;
  int Index = index;
  // OPTIONAL-scalar separator (): emitted before the value ONLY when the
  // value is non-empty (an absent optional framing field drops its separator).
  // Empty (the common case) projects the value verbatim. TableGen-owned SHAPE.
  string Prefix = prefix;
}

// A CLOSED enum declared for a backend model (): the SINGLE declarative
// source for BOTH the C++ enum and its ordinal -> target spelling table.
// `symbols` are the C++ member identifiers (ordinal = position); `spellings`
// are the target text per ordinal (1:1 with `symbols`). The generator emits the
// `enum class <cppType>` (with a terminal `Count` sentinel) AND the spelling
// table from this one list, so the enum member set and the spelling table
// cannot drift and an added member cannot alias an existing ordinal (the
// generated enum is position-indexed, and a hand-edit is caught by the
// regeneration freshness gate
// + the generated position asserts).
class EnumSpelling<string cppType, list<string> symbols,
                   list<string> spellings> {
  string CppType = cppType;
  list<string> Symbols = symbols;
  list<string> Spellings = spellings;
}

// An ENUM-FIELD projection (): the `${Name}` placeholder spells the model's
// ordinal(s) from `Spelling`. `Repeated=0` spells one ordinal (a scalar enum);
// `Repeated=1` spells the ordered list joined by `Inner`. A non-empty `Prefix`
// is emitted (optional-scalar) only when the rendered text is non-empty. The
// spelling table, `Inner`, and `Prefix` are TableGen-owned SHAPE; the model
// carries only legalization-decided ordinals.
class EnumField<string name, EnumSpelling spelling, bit repeated = 0,
                string inner = "", string prefix = ""> {
  string Name = name;
  EnumSpelling Spelling = spelling;
  bit Repeated = repeated;
  string Inner = inner;
  string Prefix = prefix;
}

// A STANDALONE (mode, role) -> lexical-atom idiom row ( G1-S1): the backend
// substrate for the status-authority lowering table. `mode` and `role` name the
// CLOSED projection `ExecutionMode` / `LifecycleRole` ENUM SYMBOLS the
// legalizer reads from the verified `BackendProjectionGraph`; `atom` is the
// target's lexical spelling ONLY (e.g.
// "None"/"Accepted"/"Reconciled"/"reconciled"/ "attested"), never a fragment or
// a condition. The generator emits one `NEU_<Abbrev>_STATUS_ATOM(ModeSym,
// RoleSym, Atom)` X-macro per backend; the generated `<backend>StatusAtom(mode,
// role)` accessor is the SOLE reader. The legalizer passes the PROJECTED (mode,
// role) it consumed from the projection — so the table maps that pair to an
// atom but can neither SELECT nor CHANGE a role. The generator validates every
// row: `mode`/`role` are valid closed symbols, `atom` is non-empty, and no
// (mode, role) key is duplicated.
class LifecycleAtom<string mode, string role, string atom> {
  string Mode = mode;
  string Role = role;
  string Atom = atom;
}

class TargetPrinterNode<
    string target, string model, int ordinal, string handler, bit leaf,
    string feature, string layout, string syntax, list<PrinterField> fields,
    bit generated, string closeSyntax = "", string abbrev = "",
    string listField = "", string listInner = "", string listOuter = "",
    list<EnumField> enumFields = [], string itemSyntax = "",
    list<PrinterField> itemFields = [], string emptyItemSyntax = ""> {
  string Target = target;
  string Model = model;
  int Ordinal = ordinal;
  string PrinterHandler = handler;
  bit IsLeaf = leaf;
  string RequiredFeature = feature;
  string Layout = layout;
  string Syntax = syntax;
  // For a `block` layout: the closing delimiter (children nest between Syntax
  // and CloseSyntax). Empty for non-nesting layouts.
  string CloseSyntax = closeSyntax;
  list<PrinterField> Fields = fields;
  // Optional REPEATED-field (list) projection ( §7). When `ListField` is
  // non-empty, the `${ListField}` placeholder in `Syntax` expands to the
  // model's repeated group: each item is the `ListInner`-join of its NON-EMPTY
  // ordered values, and the items are joined by `ListOuter`. Both delimiters
  // are TableGen-owned SHAPE (e.g. a parameter list: inner " ", outer ", ");
  // the values stay legalization-decided. Empty ⇒ the node has no list field.
  string ListField = listField;
  string ListInner = listInner;
  string ListOuter = listOuter;
  // Optional ENUM-FIELD projections (): closed enum placeholders spelled
  // from
  // `.td`-owned ordinal->spelling tables (see EnumField). The model carries
  // only ordinals; the vocabulary + spelling live here. Empty ⇒ no enum field.
  list<EnumField> EnumFields = enumFields;
  // FRAMED-LINES layout (): `Syntax` is the fixed HEADER template and
  // `CloseSyntax` an optional fixed FOOTER template (both literal shape, no
  // projection).
  // `ItemSyntax` is projected ONCE PER model tuple between them; each `${name}`
  // spells the tuple value at `ItemFields[name].Index` (dense per-item arity).
  // Item-field Prefix has the usual optional-scalar meaning.
  // The tuples come from the reused repeated-group resolver (line-wise, not the
  // inline ListInner/ListOuter join). Empty ItemSyntax ⇒ not a framed-lines
  // node.
  string ItemSyntax = itemSyntax;
  list<PrinterField> ItemFields = itemFields;
  // FRAMED-LINES empty-case placeholder (): a fixed line emitted between
  // the HEADER and FOOTER ONLY when the model supplies ZERO item tuples (split
  // on
  // `\n`, verbatim, no projection) — so a repeated section that owns its own
  // "nothing here" sentinel needs no raw-string append outside the node. Empty
  // ⇒ an empty group renders header+footer only (the pre- behavior).
  string EmptyItemSyntax = emptyItemSyntax;
  bit GeneratedHandler = generated;
  // Backend abbreviation, uppercase — the generator derives the committed
  // registry X-macro name `NEU_<Abbrev>_NODE` from it (Solidity: SOL, so the
  // emitted macro stays `NEU_SOL_NODE`). All records in one `.td` share it.
  string Abbrev = abbrev;
}

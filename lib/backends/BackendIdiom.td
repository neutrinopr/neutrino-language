//===- BackendIdiom.td - declarative backend-idiom recipe meta-model -------===//
//
// The -ratified closed recipe meta-model (docs/process/
// M6_DECLARATIVE_IDIOM_RECIPE_BOUNDARY.md), realized as TableGen (). A
// backend package's `<Target>IdiomRecipes.td` includes this schema and declares
// `def X : TargetIdiomRecipe<...>` rows.
//
// Recipes describe target SHAPE and idiom COMPOSITION only. They may NOT encode
// a shared semantic decision, read source/domain/spec/MLIR, branch on a raw
// semantic operand, or select an implementation by anything but the exact
// finalized key. All semantics are already finalized in the
// BackendProjectionGraph (§2/§3.2). This file defines the closed vocabulary; it
// contains no backend recipe rows and no semantic decision.
//
//===----------------------------------------------------------------------===//

// ---- §3.2/§3.5 finalized-type field schema ---------------------------------
//
// A finalized projection value type and its typed fields. The generator uses
// this to resolve every `Direct`/`Hook` field path to a typed accessor and
// reject reads of undeclared fields (§3.5 "bindings cannot read undeclared
// fields; stringly named runtime field lookup is forbidden"). It names only
// finalized value types — never a target node, leaf, or renderer type.
class FinalizedField<string name, string valueType> {
  string Name = name;
  string ValueType = valueType; // a finalized value type spelling
}
class FinalizedType<string name, list<FinalizedField> fields = []> {
  string Name = name;
  list<FinalizedField> Fields = fields;
}

// ---- §3.2 typed input slots ------------------------------------------------
//
// A slot binds to a finalized projection node/edge/typed-field only. `many`
// iterates by a projection-owned semantic ordinal (never invented/reversed/
// target-sorted). `max` is a string so it can carry the closed value
// "unbounded" alongside a numeric bound. `finalizedType` names a `FinalizedType`
// so the generator can resolve `slot.field` accessors and type-check bindings.
class InputSlot<string name, string finalizedType, string cardinality,
                int min = 0, string max = "0", string orderKey = "",
                string parentSlot = ""> {
  string Name = name;
  string FinalizedType = finalizedType; // a finalized projection value type
  string Cardinality = cardinality;     // "one" | "optional" | "many"
  int Min = min;
  string Max = max;      // numeric bound or "unbounded"
  string OrderKey = orderKey; // projection-owned ordinal; "many" only
  // Optional explicit association owner. A related slot is traversable only
  // while its parent slot item is active; the provider follows the already
  // finalized typed edge and performs no filtering/name recovery.
  string ParentSlot = parentSlot;
}
class One<string name, string finalizedType>
    : InputSlot<name, finalizedType, "one", 1, "1">;
class Optional<string name, string finalizedType>
    : InputSlot<name, finalizedType, "optional", 0, "1">;
class Many<string name, string finalizedType, int min, string max,
           string orderKey>
    : InputSlot<name, finalizedType, "many", min, max, orderKey>;
class RelatedMany<string name, string finalizedType, int min, string max,
                  string orderKey, string parentSlot>
    : InputSlot<name, finalizedType, "many", min, max, orderKey, parentSlot>;
// ---- optional-slot presence vocabulary (closed) ----------------------------
// A RelatedOptional whose 0/1 presence is a pure function of a typed field on
// its already-finalized parent posting. The ordinal names WHICH typed predicate
// decides presence. The GENERATED recipe module resolves the extent from the
// finalized parent (a mechanical typed read, never a CoordinationPlan/semantic
// inference); the provider only follows the parent edge and dispatches to that
// generated resolution — no handwritten presence read lives in the provider.
// `PresenceNone` (0) means the provider supplies presence itself (kept so
// PostgreSQL's RelatedOptionals need no annotation and stay behaviorally
// unchanged). The ordinals MUST stay in lock step with the generator.
class PostingPresence<int ordinal> { int Ordinal = ordinal; }
def PresenceNone   : PostingPresence<0>;
def PresenceMemo   : PostingPresence<1>; // present iff parent.memo.has_value()
def PresenceGuard  : PostingPresence<2>; // present iff parent.comparisonGuard != nullptr
def PresenceDirect : PostingPresence<3>; // present iff parent has NO comparison guard

class RelatedOptional<string name, string finalizedType, string parentSlot,
                      PostingPresence presence = PresenceNone>
    : InputSlot<name, finalizedType, "optional", 0, "1", "", parentSlot> {
  int Presence = presence.Ordinal;
}

// ---- §3.3 closed result cardinality ----------------------------------------
// Distinct names from the slot classes One/Optional/Many (TableGen has no
// arity overloading): a recipe's declared result cardinality uses these.
class ResultCardinality<string spelling> { string Spelling = spelling; }
def CardinalityOne      : ResultCardinality<"one">;
def CardinalityOptional : ResultCardinality<"optional">;
// `CardinalityMany<min,max>` carries the interval; `max` may be "unbounded".
class CardinalityMany<int min, string max> : ResultCardinality<"many"> {
  int Min = min;
  string Max = max;
}

// ---- §3.4/§3.6 target-node field schema ------------------------------------
//
// Declares each emittable target node and its ordered typed fields. The
// generator validates every `Emit` binding against the named field here — the
// field must exist, its kind must match the binding (`value`=Direct,
// `leaf`=Hook, `nodes`=Nested), its type must match (value type / hook leaf
// output / child node category), and a `nodes` field's cardinality must contain
// the nested body's proven result. The matching field descriptor is handed to
// the builder adapter so it performs the §3.6 recheck. It names only target
// node/leaf/value types — never a domain/source/spec type.
class TargetField<string name, string kind, string type,
                  string cardinality = "one", int min = 1, string max = "1"> {
  string Name = name;
  string Kind = kind;             // "value" | "leaf" | "nodes"
  string Type = type;            // value type | leaf type | child RESULT CATEGORY
  string Cardinality = cardinality;
  int Min = min;
  string Max = max;
}
// A concrete emittable node. `category` is its §3.3 result category — several
// nodes may share one, and a recipe/field result is checked by category (while
// `Emit` still targets the concrete node). `TargetIdiomRecipe.resultType` and a
// `nodes` field's `type` both name a category, not a concrete node.
class TargetNode<string name, string category, list<TargetField> fields = [],
                 string builderKind = "", list<string> builderArgs = []> {
  string Name = name;
  string Category = category;
  list<TargetField> Fields = fields;
  string BuilderKind = builderKind;
  list<string> BuilderArgs = builderArgs;
}

// ---- §3.4 closed body grammar ----------------------------------------------
//
// RecipeBody ::= Sequence<RecipeOp...>
// RecipeOp   ::= Emit | ForEach | OptionalOp | Call
// Binding    ::= Direct | Hook | Nested
//
// There is NO general expression language: no boolean/comparison/arithmetic,
// no if/switch/ternary/predicate, no sort/group/filter/break, no target or
// operand-value selection, no fallback. `OptionalOp` tests only presence of a
// named optional slot; `ForEach` preserves the slot's verified order; `Call`
// invokes an exact recipe in the same package (the call graph is acyclic).

// Forward declaration: bindings and ops reference a nested RecipeBody.
class RecipeBody;

// A binding fills exactly one named field. In an `Emit` the field is the target
// node's field (validated against the node's declared field schema); in a `Call`
// the field is the callee slot it binds. `input` is the finalized slot/field
// path projected into it. The generator resolves both against the schema and
// rejects an unknown/undeclared field or a type/cardinality mismatch (§3.5).
class Binding<string bindKind, string slotField> {
  string BindKind = bindKind;
  string Field = slotField; // target node field (Emit) or callee slot (Call)
}
// A direct typed slot/field projection into `slotField`.
class Direct<string slotField, string input> : Binding<"Direct", slotField> {
  string Input = input;
}
// A registered §5 leaf hook applied to `input`, filling `slotField`.
class Hook<string slotField, string hookId, string input>
    : Binding<"Hook", slotField> {
  string HookId = hookId;
  string Input = input;
}
// A nested recipe body whose whole RecipeResult is consumed as one target-node
// field `slotField` (§3.3 nested-field rule).
class Nested<string slotField, RecipeBody body> : Binding<"Nested", slotField> {
  RecipeBody Body = body;
}

class RecipeOp<string opKind> { string OpKind = opKind; }
// Construct exactly one registered typed target node from its bindings.
class Emit<string node, list<Binding> bindings> : RecipeOp<"Emit"> {
  string Node = node;
  list<Binding> Bindings = bindings;
}
// Iterate a `many` slot in its projection-owned order, evaluating the body per
// item; the result multiplies the body cardinality by the slot bounds.
class ForEach<string slot, RecipeBody body> : RecipeOp<"ForEach"> {
  string Slot = slot;
  RecipeBody Body = body;
}
// Evaluate the body iff the named optional slot is present (presence already
// finalized). Named `OptionalOp` to avoid colliding with the `Optional` slot/
// result-cardinality defs.
class OptionalOp<string slot, RecipeBody body> : RecipeOp<"Optional"> {
  string Slot = slot;
  RecipeBody Body = body;
}
// Invoke an exact recipe (by recipeId) in the same backend package.
class Call<string recipeId, list<Binding> bindings> : RecipeOp<"Call"> {
  string RecipeId = recipeId;
  list<Binding> Bindings = bindings;
}

// An ordered operation list. `Sequence` preserves declared order; an empty
// sequence is forbidden (the generator rejects it).
class Sequence<list<RecipeOp> ops> : RecipeBody { list<RecipeOp> Ops = ops; }

// ---- §3.1 the recipe -------------------------------------------------------
//
// The resolution key is the exact tuple (Target, FinalizedKind, Mode, Role);
// `Mode`/`Role` admit the closed value "NotApplicable" (a real value, not a
// wildcard). `FinalizedKind` has no wildcard and no "NotApplicable". Priority,
// wildcard, partial-match, default, and catch-all rows are forbidden.
class TargetIdiomRecipe<string recipeId, string target, string finalizedKind,
                        string mode, string role, list<InputSlot> inputs,
                        string resultType, ResultCardinality resultCardinality,
                        RecipeBody body, int schemaVersion = 1> {
  string RecipeId = recipeId;         // unique within one backend package
  int SchemaVersion = schemaVersion;  // exact supported version
  string Target = target;             // MUST equal the owning provider's target
  string FinalizedKind = finalizedKind;
  string Mode = mode;                 // closed mode or "NotApplicable"
  string Role = role;                 // closed role or "NotApplicable"
  list<InputSlot> Inputs = inputs;
  string ResultType = resultType;     // backend target-node category ID
  ResultCardinality ResultCardinality = resultCardinality;
  RecipeBody Body = body;
}

// ---- §5 closed handwritten leaf-hook contract ------------------------------
//
// Hook permission is default-deny. A backend package registers AT MOST ONE
// implementation per applicable closed hook kind, each with an exact
// (input -> output) finalized-value signature. Closed-enum lexical spellings
// stay in `.td` (see LifecycleAtom in TargetPrinter.td), NOT a hook. A hook is
// pure, receives the smallest typed value, and may not inspect mode/role/guard/
// replay/balance/lifecycle/grouping/domain/source/target/recipe/.
class LeafHookKind<string kind, string input, string output> {
  string Kind = kind;     // "<target>.<suffix>"
  string Input = input;   // finalized value type
  string Output = output; // target leaf type
}
def HookIdentifierEscape : LeafHookKind<"identifier.escape",
    "TargetIdentifierAtom", "EscapedIdentifier">;
def HookStringEscape     : LeafHookKind<"string.escape",
    "TypedStringLiteral", "EscapedStringLiteral">;
def HookTypeSpell        : LeafHookKind<"type.spell",
    "FinalizedTargetType", "TargetTypeToken">;
def HookLiteralFormat    : LeafHookKind<"literal.format",
    "FinalizedTypedLiteral", "TargetLiteralToken">;
def HookOperandFormat    : LeafHookKind<"operand.format",
    "FinalizedTypedOperand", "TargetOperand">;
def HookExpressionLeaf   : LeafHookKind<"expression.leaf",
    "FinalizedExpressionLeaf", "TargetExpression">;

// A backend registers a concrete hook by binding one closed kind to its exact
// generated RegisteredHookId. `impl` is the package-local pure function symbol.
class RegisterLeafHook<string hookId, LeafHookKind kind, string impl> {
  string HookId = hookId;
  LeafHookKind Kind = kind;
  string Impl = impl;
}

# Expression Model (M5 WP1b, )

How `.neu` **compute expressions** are represented, typed, and shared across
backends — and the **extension process** a new expression construct must follow
before it can ship. This is the L1 companion to [`VALUE_MODEL.md`](VALUE_MODEL.md)
(the value types) and is binding under [`M5_DECISIONS_ADR.md`](../process/M5_DECISIONS_ADR.md)
decisions **D3** (L1 = typed values + expressions in the kernel), **D5** (typed
value model; new types via the extension process) and **D8** (kernel boundary).

## What a compute expression is today

A `compute` binds a name to an arithmetic expression over inputs and prior
computes:

```hcl
compute subsidy = principal * subsidy_pct / 100
compute fee     = round(amount * rate / 100, 2)
```

Current semantics (unchanged by this work — this section documents the status
quo the ADR asked us to write down first):

- **Domain:** integer **minor units** (money) and scaled integers (decimal).
  There are no floats anywhere in the evaluated pipeline.
- **Money is non-negative (M5 release-review, ).** A `money` value is an
  unsigned settlement **amount**, never a signed balance. A negative money input
  or a money-typed compute **result** (e.g. `net = gross_position - fee` driven
  below zero) is an invalid money shape and **fails closed at scenario
  validation** (`scenario.invalid`, exit 3) **before any backend renders** —
  rather than a non-compiling `uint256 constant EXPECT_NET = -30` (Solidity) or
  an inverted PostgreSQL transfer. This is enforced in `validateScenario`
  (grounded in the value model, not a renderer-local patch). Ledger **net
  deltas** are directional and legitimately signed, so they are *not* covered; a
  capability that needs a signed balance must model it as such, not carry it
  through a `money` amount.
- **Operators:** `+`, `-`, `*`, `/`. `/` is **integer division** (truncating);
  operands are non-negative. Standard precedence (`*` `/` over `+` `-`), left
  associative, parentheses group.
- **Functions:** `round(x)` / `round(x, k)` is the **identity** today
  (`round(x, k) == x`) — a declared rounding intent that the minor-units domain
  already satisfies. It is the *only* function in the vocabulary. It takes **one
  or two arguments only**; the rounded value `x` must be **numeric**
  (money/decimal), and the optional scale `k` must be a **constant integer
  literal** (e.g. `round(x, 2)`) — it selects the rounding precision, not a
  runtime value. Any other arity, a non-numeric `x`, or a computed/variable scale
  is rejected (`expr.unsupported` / `expr.type`) rather than silently reduced to
  `x`.
- **One meaning, three renderings:** the same expression lowers to Solidity and
  SQL and evaluates in C++ (`neutrino-equiv`) so every backend computes an
  identical value. That identity is the property the extension process protects.

## Typed AST — parse once, share everywhere

Before this change each renderer re-parsed the raw `expr` string independently
(`GenSolidity`, `GenPostgres`, and `neutrino-equiv` each called `parseExpr(c.expr)`).
Three parsers of the same text is three chances to diverge.

Now the expression is parsed **once** and typed when the semantic view is built
(`viewOf`, [`lib/View.cpp`](../../lib/View.cpp)), and the resulting AST is shared:

- [`ExprNode`](../../include/Neutrino/Expr.h) is the typed AST (`Num` / `Var` /
  `Bin` / `Call`). Every node carries a `ValueCategory dtype` — the same dtype
  surface WP1a () defines in [`ValueModel.h`](../../include/Neutrino/ValueModel.h).
- `ComputeView.ast` (a `shared_ptr<ExprNode>`) holds that AST. `GenSolidity`,
  `GenPostgres`, and `neutrino-equiv` render / evaluate `*c.ast` directly — no
  renderer re-parses `c.expr`. This is decision **D3**: L1 owns the typed
  expression; targets consume it.

`typeExpr(node, env)` infers each node's dtype (`env` maps each in-scope value
name to its declared `ValueCategory`):

| node | dtype rule |
| --- | --- |
| numeric literal | `Decimal` (integer in the minor-units domain) |
| variable | its declared category; an unknown/`Extension` name is unconstrained (D5) |
| `a op b` | numeric **join**: `Money` if either side is money, else `Decimal` |
| `round(x[, k])` | the dtype of `x` (identity today) |

Typing is **fail-closed** on two conditions, each reported with a **stable,
machine-readable diagnostic `code`** (the code is the discriminator — never scrape
it from the message text):

- **`expr.unsupported`** — a function other than `round`, or a `round` call with
  the wrong arity (only `round(x)` / `round(x, k)` are admitted). This is the
  extension gate (below): a new construct cannot be rendered until it has been
  admitted through the process.
- **`expr.type`** — a **governed non-numeric** value (party / currency /
  evidence / string) where a number is required: as an arithmetic operand, as the
  argument of `round`, or as a non-literal `round` scale. An `Extension`-typed
  value is *not* constrained (the input-type vocabulary is intentionally open,
  [`NEU_LANGUAGE_SPEC.md`](NEU_LANGUAGE_SPEC.md)), preserving today's behavior.

`neutrino-gen` surfaces the failure as exit code **4**, with the specific `code`
(`expr.unsupported` / `expr.type`) on the `diagnostics.json` entry — `expr.invalid`
is the fallback family code for a legacy/internal `ExprError` (see self-test check
`[10b]`). This is stricter than before only for expressions that never had a
coherent meaning; every existing sample types cleanly and emits byte-identical
output.

A **syntactically malformed** expression falls into the same net: the frontend's
compute-dependency scan only recognizes identifiers, so it accepts bad syntax and
stores the raw string on `ComputeOp`; the *single* `parseExpr` in `viewOf` then
rejects it with the fallback code `expr.invalid` (exit 4, no artifacts). Because
the parse is now centralized, a malformed expression can no longer partially
render in one backend before another rejects it — it fails once, before any target
runs.

### Well-formedness gates every target, analysis targets included

Expressions are typed in `viewOf`, **before** target dispatch, so an
ill-formed expression fails **every** target with exit 4 — including the
otherwise-ungated analysis targets (`security`, `coverage`, `capability`). This
is deliberate: expression well-formedness is **L1 well-formedness**, so it gates
like a parse error or IR-verification failure (which already fail all targets
pre-dispatch), *not* like a security violation (which is what the analysis
targets exist to diagnose, and so is never gated). You cannot meaningfully
analyze a capability whose L1 cannot be formed. Before this work these targets
never parsed expressions and would succeed on such a source; that is the one
behavioral change for analysis targets, called out in Compatibility below.

## Conditional guards (`when`) — a predicate, not a value (M5 WP7, )

A **guard** is a boolean predicate that conditionally gates an effect: a leg
carries an optional `when = <predicate>` and posts **iff** the predicate holds.
A predicate is a single **comparison** `<lhs> <op> <rhs>` with `op` one of
`<  <=  >  >=  ==  !=` and NUMERIC (money/decimal) operands.

The comparison is a distinct AST node (`cmp`) and is **deliberately not a value**:
it is valid ONLY at the top of a `when` guard, never as a compute value or an
arithmetic operand. This keeps the value model closed — there is **no Boolean
value type**. The "predicate only in a guard" rule is enforced mechanically on
both sides: `parseExpr` / `typeExpr` (value context) reject a `cmp`
(`expr.type`), and `parseGuard` / `typeGuard` (guard context) require the top
node to be a `cmp` with numeric operands. So a comparison in a compute fails to
parse, and a hand-authored spec that smuggles a `cmp` into a value slot (or an
ill-typed guard) is rejected with `expr.type` before any SQL/Solidity is
rendered — the renderers re-type the ingested guard, they do not trust it.

One meaning, three renderings: `evalGuard` decides whether a guarded leg fires
in the reference evaluator; `guardToSql` lowers it to a PL/pgSQL `IF <p> THEN …
END IF`; `guardToSolidity` to `if (<p>) { … }` (`==`→SQL `=`, `!=`→SQL `<>`).
A guarded leg's event is not part of the guaranteed choreography (the renderers
emit it inside the guard), and the balanced invariant holds because guarded legs
must guard **complete debit/credit pairs** — now **enforced, not assumed** ().

**Guarded balance is fail-closed ().** `assert balanced` was originally
guard-blind: it matched the debit/credit `(amount, currency)` multisets while
ignoring `when`, so a *conditionally* unbalanced capability compiled — e.g. a
debit `when C` whose matching credit is unconditional balances "on paper" but
leaves value unconserved on the `¬C` partition. The kernel verifier
(`ProcedureOp::verify`) now keys the balance multiset on **`(guard, amount,
currency)`**: a leg balances only against a counterpart carrying the **identical
guard** (an unguarded leg has the empty guard, so a one-sided guard is a
mismatch). A capability whose guarded legs are not balanced under the same guard
is **refused** with a source-linked `[kernel.balance.unbalanced]` (exit 4), never
compiled. This is **conservative and sound**: it accepts exactly the
identical-guard-pairing shape (the only statically provable one) and refuses
anything beyond it (e.g. `when C` balanced by `when ¬C`, or predicate algebra
across legs) rather than accept it unproven — a deliberate M5 boundary
(/); richer guarded-balance proofs are future work. Genuinely
balanced guarded capabilities (matching guards on the paired legs — e.g.
`core_document_escrow`) still compile unchanged.

A guarded procedure carries
the `guard:conditional` target-requirement (both the PostgreSQL and Solidity
profiles support it) and emits **`schemaVersion 2`** — a guard changes *when* a
leg posts, so a v1 consumer must refuse it rather than silently post
unconditionally; an unguarded spec stays `schemaVersion 1` and byte-identical.
Every guard variable must resolve to a declared input/compute (the renderer and
the spec validator both reject an undeclared guard var, so `--from-spec` fails
closed independently of the source parser). Gate sample: `core_document_escrow`
releases escrow to the seller `when amount >= agreed_amount` (a genuinely
numeric L1 condition; the document-verification VERDICT stays L2/L3/M4) — its
event chain is scenario-aware (the release events appear only on the branch that
fires). See self-test `[92]`.

## Extension process — how a new expression construct ships

Per **D5**, the expression vocabulary does not grow speculatively. A new
construct (a new function, operator, or value-producing form — e.g. `min`,
`max`, `floor`, a timestamp difference) is admitted **only when a gate sample
demands it**, and only as a *complete set* landed together:

1. **A gate sample that needs it.** A real domain sample (not a synthetic test)
   whose coordination genuinely requires the construct. No sample, no construct.
2. **Solidity lowering.** `toSolidity` renders it to code the Foundry suite
   compiles and runs.
3. **SQL lowering.** `toSql` renders it to PL/pgSQL the postgres harness runs.
4. **Reference evaluator.** `evalExpr` computes it in C++ over integer minor
   units — the single source of truth for the intended value.
5. **`typeExpr` rule.** A dtype rule for the construct, so it is typed (not
   rejected as `[expr.unsupported]`) and participates in the numeric join.
6. **Equivalence fixture.** A `neutrino-equiv` fixture proving all three
   renderings agree on the reference value across the sample's scenarios — the
   property that makes "one meaning, three renderings" true for the new form.
7. **Docs.** This file's vocabulary table + `VALUE_MODEL.md` if a new value type
   rides along.

A construct missing any of 2–6 must **not** parse-and-render silently: until its
`typeExpr` rule exists it is rejected with code `expr.unsupported`, so a
half-shipped feature fails closed rather than diverging between backends. New
**value types**
that a construct introduces follow the same admission through this process (D5) —
that is the "expression/extension process" the ADR points `VALUE_MODEL.md` at.

## Compatibility

- Existing sources are unaffected: every sample compute is numeric arithmetic
  over `money`/`decimal` (plus identity `round`), which types cleanly and renders
  identically — the equivalence suite and the committed slot/backend fixtures are
  byte-for-byte unchanged.
- The only new *rejections* are expressions that never had a single coherent
  cross-backend meaning (an unknown function; a bad `round` arity/scale;
  arithmetic over a governed non-numeric value). They are caught once, at view
  build, with an `expr.unsupported` / `expr.type` diagnostic code — not silently
  rendered three different ways.
- **Analysis targets** (`security`, `coverage`, `capability`) now also fail
  (exit 4) on such a source, where before they succeeded — because typing happens
  in `viewOf`, before dispatch (see "Well-formedness gates every target" above).
  This is the intended semantics (ill-formed L1 is not analyzable), not an
  accident of placement; only ill-formed expressions are affected, and no
  existing sample is.
- No external contract changes: the spec/slot JSON and generated Solidity/SQL are
  unchanged for all existing inputs (D1).

## Pipeline impact

- **Solidity / PostgreSQL:** identical codegen; they now render the shared
  `ComputeView.ast` instead of re-parsing `c.expr`.
- **Equivalence (`neutrino-equiv`):** evaluates the same shared AST; the typed
  gate runs before rendering so an ill-typed expression fails fast and uniformly.
- **Frontend / IR:** unchanged — expressions are still stored as text on
  `ComputeOp`; typing happens in the kernel (`viewOf`) where the value model
  lives, keeping the dialect thin (D8).

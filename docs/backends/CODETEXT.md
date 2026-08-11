# codetext — the structured code emitter substrate (M5 codetext S1, )

`neutrino::codetext` ([`include/Neutrino/CodeText.h`](../../include/Neutrino/CodeText.h)) is a small,
language-neutral document model for emitting generated code. Its printer owns **indentation** and the
**structural newlines**, so a backend renderer describes the *shape* of its output — nesting and
delimiters — instead of hand-managing spaces and `\n`.

This is generic emission **mechanics only, not target semantics**. It is the foundation for the
emitter migrations (Solidity/SQL/JS), each of which describes its output with these blocks while keeping
its own delimiters and its own leaf text.

The **Solidity** coordination + Foundry-test renderer is the first consumer (S2, ): its
contract/function/`if` framing is described with `block()`/`line()` (byte-identical output, proved by
the committed Solidity goldens), and the no-hand-framing gate (`check_renderer_includes.py`) forbids a
migrated renderer from re-introducing a hand-assembled structural newline (`"…\n"`).

The **oracle-JS observer** renderer (S3, ) is migrated too: its observer + aggregator framing is
codetext blocks/lines (byte-identical goldens), which also **closes the  comment-injection class by
construction** — the header comments interpolate untrusted identifiers, but they are `line()` nodes, and
`line()` rejects an embedded newline, so a value can no longer break out of a `//` comment into code
position (structural safety, not only the `safeIdent` sanitizer, which stays as defense-in-depth).

The **PostgreSQL** `SqlEmitter` (S4, ) is consolidated onto the same printer: its `IF … THEN … END
IF;`, `BEGIN … END;`, and `DECLARE` framing are codetext blocks, so the four-space indentation is the
printer's (no local `pad()`/line-joining) — byte-identical PL/pgSQL goldens. A block with an **empty
delimiter** is omitted (a header with no closing bracket), which is how `DECLARE` + indented decls
(`block("DECLARE", "", decls)`) renders without a stray blank before `BEGIN`.

## Model

| Node | Meaning |
|------|---------|
| `line(text)` | one line of verbatim text, printed at the current indentation |
| `blank()` | an empty line — a bare structural separator, never indented |
| `block(open, close, children)` | `open` on its own line at the current indent, `children` indented one level deeper, `close` on its own line back at the current indent |
| `Document` | the root: an ordered sequence of top-level nodes; `print(indentUnit = "  ")` renders the tree to a `std::string`, or `print(llvm::raw_ostream &, indentUnit = "  ")` straight to a stream |

A node is a type-safe `std::variant<Line, Blank, Block>` (): a `Line` holds only `text`, a `Blank`
holds nothing, and only a `Block` holds `open`/`close`/`children`. Invalid shapes — a `Line` with
children, a `Block` with leaf text — are *unrepresentable*, so the "printer owns layout" contract is a
compile-time guarantee, not a runtime `validate()` scan. The `print` overloads render identically; the
`std::string` form is implemented over an `llvm::raw_string_ostream`.

**Delimiters are caller-provided**, so the same mechanics render any target:

```cpp
using namespace neutrino::codetext;
Document doc;
doc.add(block("function f() {", "}", { line("return x;") }));
doc.print();
// function f() {
//   return x;
// }
```

```cpp
Document sql;
sql.add(block("BEGIN", "END;", { line("RETURN NEW;") }));
sql.print();
// BEGIN
//   RETURN NEW;
// END;
```

Blocks nest with stable per-level indentation; `print("    ")` or `print("\t")` swaps the indent unit
without changing the model. Every line — including the last — is newline-terminated. An empty block
still prints both delimiter lines.

## Fail-closed invariants

Because the printer owns layout, misuse that would silently emit wrong or partial code is **prevented**,
not tolerated. Two layers:

- **structural shape — a compile-time guarantee ().** Only a `Block` carries `children`, only a
  `Line` carries `text`; the `std::variant` representation makes a stray child on a `Line` or leaf text
  on a `Block` a *type error*, not a runtime discovery. There is nothing to check at runtime because the
  bad state cannot be built.
- **no embedded `\n`/`\r`** in a `line` text or a block delimiter — the printer owns *all* structural
  newlines, so a `line("a\nb")` (which would print an un-indented second physical line) is refused. This
  one the type system can't express, so it stays a runtime invariant: `Document::validate()` returns the
  first violation (`""` when well-formed) and `print()` enforces it (a violation aborts via
  `report_fatal_error` rather than emitting malformed code).

`validate()` is exposed so callers/tests can detect the newline misuse without provoking the abort.

## Scope (what it deliberately is NOT)

- **No target-expression AST.** The text of a `line` is a *leaf string* produced by the existing
  per-target lowerers; codetext never parses or rewrites it (that stays /later slices).
- **No target semantics.** It knows nothing about Solidity, SQL, or JS — only lines, blanks, and
  delimited blocks.

## Placement

`NeutrinoCodeText` is a **bottom-of-the-graph leaf** ([`lib/codetext/`](../../lib/codetext)) that links
only llvm Support — not `NeutrinoSpecContract`, not the MLIR dialect, not any backend. So any backend or
policy module can depend on it **without** a backend-to-backend edge, and it is trivially extractable
with the backends (the  source-topology / future backend-repo goals). It is exercised standalone by
the gtest unit tier ([`unittests/CodeTextTest.cpp`](../../unittests/CodeTextTest.cpp)) — no backend needed —
which also proves the leaf has no hidden dependency.

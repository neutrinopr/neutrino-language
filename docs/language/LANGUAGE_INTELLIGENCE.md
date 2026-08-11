# Language Intelligence (`neutrino-lang`)

The console `.neu` editor gets its grammar, completion data, red-squiggle
diagnostics, outline, hovers, and capability preview **from the translator**,
never from a separate frontend parser (Phase 27 / issue
[](internal-tracker)). Two slices
are **implemented** — static **language metadata** and **parser diagnostics** —
and the remaining commands (`preview`, `symbols`, `hover`, `completions`,
`dialect`) are **specified** below as a stable, versioned contract.

Tool: [`scripts/generators/neutrino_lang.py`](../../scripts/generators/neutrino_lang.py). Every output carries
a `schemaVersion` (stable contract). Diagnostics come from the real
`neutrino-translate` front-end; this tool only runs it and structures its output —
no parser logic is reimplemented.

## The renderer/compiler boundary (binding rule)

The console is a **renderer**, not a parser. Every datum the editor shows is
sourced from the compiler — never recomputed in the browser or in this tool by
re-parsing `.neu`. Concretely, each command's data has exactly one provenance:

| Command | Provenance | Status |
|---|---|---|
| `metadata` | static language constants (grammar that the drift test pins to `examples/`) | implemented |
| `diagnostics` | the real `neutrino-translate` front-end (run + structure stderr) | implemented |
| `preview` | `neutrino-gen` artifacts (`slot` capability.lock/model + `security`) | implemented |
| `dialect` | the committed `neutrino.domain-dialect` artifacts, via `validate_domain_dialect.py` | implemented |
| `symbols` | the **C++ front-end's** source ranges (`neutrino-emit --kind=symbols` + the `symbols` wrapper) | implemented |
| `hover` | `symbols` ranges + static construct docs (`dialect` docs via ) | implemented |
| `completions` | static from `metadata` + in-scope `%references` from `symbols` (semantic dialect terms via  dialect) | implemented |

**Hard constraint:** `symbols` and `hover` need real source ranges. Those MUST
come from the C++ front-end, **not** from re-parsing `.neu` with regex in this
Python tool or in the console. This is now satisfied at the compiler layer: the
front-end attaches op source ranges (1-based line; a block op spans header..closing
brace) and `neutrino-emit --kind=symbols` emits the outline as deterministic JSON
(see [`Emit.h`](../../include/Neutrino/Emit.h)). The ranges are hidden in the default
textual MLIR, so artifacts/hashes are unchanged. The Python `symbols`/`hover`
consumers (below) structure this output; they remain renderers over the front-end's
ranges, never a second grammar.

## `metadata`

```sh
neutrino_lang.py metadata
```

Static language metadata for editor grammar/completion:

- `canonicalExtension` (`.neu`) + `legacyExtensions` (empty — `.neu` is the only extension);
- `lineComments` (`//`, `#`), `blockComment` (none), `blockDelimiters`;
- `keywords` (+ `keywordCategories`: statement / field / connector);
- `valueTypes` (`money`/`decimal`/`party`/`currency`/`evidence`/`string`);
- `operators` (`+ - * /`) + `functions` (`round`);
- `literalClasses` (string / `%`reference / number);
- `snippets` (LSP snippet bodies).

**Source of truth (M5 D10 Python Boundary Policy):** the grammar facts above —
`keywords`, `keywordCategories`, `valueTypes`, `operators`, `functions`, and the
file-level facts — are the **compiler's**, emitted by `neutrino-translate
--language-metadata` (`lib/LanguageMetadata.cpp`; value types from the typed value
model, `ValueModel`/) as deterministic JSON committed at
[`language-metadata.json`](../language-metadata.json). `neutrino_lang.py metadata` **reads
that committed file** (no toolchain required at read time) and adds only the
editor-presentation layer (`literalClasses`, `snippets` — whose type choices derive
from the emitted `valueTypes`, and `rangeConvention`); it holds **no grammar list of
its own**. See [`M5_DECISIONS_ADR.md` §D10](../process/M5_DECISIONS_ADR.md).

**Versioning scope:** `schemaVersion` governs the **compiler-owned fields only** (the
grammar facts above); it comes from the committed `language-metadata.json`. The
presentation layer Python adds (`literalClasses`, `snippets`, `rangeConvention`) is
**not** covered by `schemaVersion` today. A consumer that caches this output must key
its cache on the presentation layer separately (or a `presentationVersion` must be
added before that becomes a concern).

Two drift tests keep this honest (self-test [37]): the committed
`language-metadata.json` is **regenerated from the compiler and byte-matched**, and the
Python `metadata` output must not diverge from the compiler-emitted grammar fields. A
third guard asserts every leading token + field name used across the committed
`examples/` is covered by the metadata, so the editor grammar can't silently fall
behind the language.

**Evolving the language metadata (contributors):** when you add or remove a keyword,
operator, or function, update the compiler-owned tables in `lib/LanguageMetadata.cpp`.
**Value types are different** — their governed set and spellings are owned by
`ValueModel` (`governedCategories()` + `categoryName()`), and `LanguageMetadata.cpp`
renders from there, so a new value category is added in `ValueModel` alone (no
value-type list to touch in `LanguageMetadata.cpp`). After any such change, regenerate
and commit the artifact:

```sh
make language-metadata   # rewrites docs/language-metadata.json from the compiler
git add docs/language-metadata.json
```

Self-test [37] regenerates and byte-matches this file in CI, so a forgotten
regeneration fails the build — the committed JSON can never silently go stale. Do **not**
hand-edit `docs/language-metadata.json`; it is a generated artifact.

## Static syntax highlighting: the generated TextMate grammar ()

The `.neu` **TextMate grammar** — the static-highlighting surface for VS Code, GitHub /
Linguist, and the console editor — is likewise **generated from the compiler**, never
hand-maintained. `scripts/generators/generate_tmgrammar.py` reads the committed
[`language-metadata.json`](../language-metadata.json) and emits
[`neutrino.tmLanguage.json`](../neutrino.tmLanguage.json): the keyword/type/operator/function
vocabulary and the comment/string delimiters all come from the compiler; the script owns
only presentation (each token category → a TextMate scope, and the regex assembly). There
is **no hand-written second grammar and no surface-specific fork** — every downstream
highlighter consumes this one artifact.

**Downstream consumption.** A surface points its language contribution at
`docs/neutrino.tmLanguage.json` (scope `source.neutrino`, file type `.neu`): a VS Code
extension references it from `contributes.grammars`; a GitHub/Linguist entry maps `.neu`
to it; the console loads it directly. None of them re-implement `.neu` syntax — they embed
or fetch the generated file. Because it derives from `LanguageMetadata`, adding a keyword
in the compiler flows into every surface on the next regeneration.

**Scopes** (stable contract for themes): `keyword.control` (statement keywords),
`variable.other.property` (field keywords), `keyword.operator.word` (connectors),
`storage.type` (value types), `support.function` (`round`),
`keyword.operator.arithmetic`/`.comparison` (operators), `string.quoted.double`,
`variable.other.reference` (`%`-references), `constant.numeric`, and
`comment.line.double-slash`/`.number-sign` — all suffixed `.neutrino`.

**Regenerate + drift gate.** After any grammar-metadata change:

```sh
make grammar             # rewrites docs/neutrino.tmLanguage.json from the compiler metadata
git add docs/neutrino.tmLanguage.json
```

The fast-tier check `[fast/21]` (`scripts/generators/generate_tmgrammar.py --check`, also a labeled
CTest) regenerates and **byte-matches** the committed grammar, asserts every compiler token
has a rule, and asserts the fixture
[`test/grammar/neutrino_grammar_fixture.neu`](../../test/grammar/neutrino_grammar_fixture.neu)
exercises every category — so a stale artifact, an unmapped token kind/category, or an
empty fixture all fail closed. Do **not** hand-edit `docs/neutrino.tmLanguage.json`.

### GitHub / Linguist assets ()

The same generated grammar is **packaged** — not re-authored — as GitHub/Linguist assets
under [`linguist/`](../../linguist): `neutrino.tmLanguage.json` (a byte copy of the generated
grammar) and `languages.yml` (the Linguist language entry, derived from the compiler's `.neu`
extension + the `source.neutrino` scope). `make linguist` regenerates them; `[fast/22]`
byte-matches the packaged grammar against the generated one and re-derives `languages.yml`, so
the package can never drift or become a hand-edited fork. The root `.gitattributes` routes
`*.neu` to the `Neutrino` language and marks the generated grammar files `linguist-generated`.
GitHub-web highlighting additionally requires the language to be merged upstream into
`github-linguist` — a tracked follow-up gated on external adoption, **not** an M5 criterion;
[`linguist/README.md`](../../linguist/README.md) documents the assets, consumption, and that
follow-up (including the provisional `language_id` and the usage-threshold risk).

## Live editor substrate: the compiler-backed LSP ()

Where the grammar above is *static* highlighting, [`scripts/generators/neutrino_lsp.py`](../../scripts/generators/neutrino_lsp.py)
is the **live** editor substrate — **one** compiler-backed LSP surface VS Code and the
console share. It **delegates to the compiler and maps its output**; it never re-parses
`.neu` or re-derives validation (M5  T2):

- **Diagnostics** come from `neutrino_lang.py diagnostics` (which runs `neutrino-translate`
  and maps its coded parser diagnostics + ranges). The server only converts them to LSP
  `Diagnostic`s (1-based → 0-based, severity, the compiler's **stable `code`**).
- **Semantic tokens** come from `neutrino_lang.py symbols` (`neutrino-emit --kind=symbols`).
  The **compiler** decides each token's identity, role, and line; the server maps the roles
  onto LSP token types — `input → parameter`, `compute → variable`, `debit`/`credit → event`,
  `procedure → function` — and locates the compiler-named identifier on its line for the span.

Scope (T2) is **diagnostics + semantic tokens only** — hover / go-to-def / completion /
rename are deliberately out of scope. It is **fail-closed**: a missing compiler binary, a
compiler failure, or malformed diagnostics/symbol JSON surface an explicit LSP error
(`window/showMessage` / a JSON-RPC error), never a silent empty result.

**Invocation.**

```sh
# stdio LSP server (a VS Code extension / the console spawns this, speaking LSP over stdio)
NEUTRINO_TRANSLATE=out/tools/neutrino-translate/neutrino-translate \
NEUTRINO_EMIT=out/tools/neutrino-emit/neutrino-emit \
  python3 scripts/generators/neutrino_lsp.py

# batch (scripting / CI / quick checks) — the SAME mapping the server uses
python3 scripts/generators/neutrino_lsp.py --diagnostics FILE.neu       # -> mapped LSP diagnostics JSON
python3 scripts/generators/neutrino_lsp.py --semantic-tokens FILE.neu   # -> semantic tokens + legend
```

**Consumers.** A VS Code extension registers this as the `.neu` language server (spawn the
stdio process; it advertises `textDocumentSync` + `semanticTokensProvider` on `initialize`).
The console runs the same server (or the batch modes) so both surfaces get identical,
compiler-authoritative diagnostics and tokens — no surface re-implements `.neu`. Self-test
`[98]` is the smoke gate: an invalid fixture yields a coded LSP diagnostic, a valid fixture
yields tokens distinguishing input vs compute, a missing binary fails closed, and a real
stdio `initialize → didOpen → publishDiagnostics` round-trip is exercised.

> Token spans currently come from locating the compiler-named identifier on its
> compiler-reported line (`--kind=symbols` ranges are line-granular). Emitting precise
> identifier columns from the compiler, and surfacing `%`-reference/unresolved-reference
> tokens, are follow-ups for when `emitSymbols` grows column-precise ranges.

## `diagnostics`

```sh
neutrino_lang.py diagnostics path/to/file.neu --translate <neutrino-translate>
# or set NEUTRINO_TRANSLATE
```

Runs the front-end and emits structured parser diagnostics:

```json
{ "schemaVersion": 1, "file": "...", "ok": false,
  "diagnostics": [ { "code": "parse.missing_field", "severity": "error",
                     "message": "...", "range": {"start": {"line": 6, "column": 1},
                                                  "end": {"line": 6, "column": 1}} } ] }
```

`ok` is true only when the file parses with no error diagnostics. Stable codes:
`parse.missing_field`, `parse.duplicate_name`, `parse.bad_value`,
`parse.unresolved_reference`, `parse.unexpected_statement`, and a `parse.error`
fallback. If the front-end **fails to run** (non-zero exit with no parseable
diagnostic — a crash, an unexpected error format, an I/O failure) a single
`translate.failed` error diagnostic is synthesized, so `ok:false` **never** comes
back with an empty `diagnostics` list (no silent failures for the editor). Ranges
are 1-based and currently line-level (`columnsAvailable: false`) until the front-end
emits columns.

## `preview` (capability preview) — implemented

```sh
neutrino_lang.py preview path/to/file.neu --gen <neutrino-gen> --scenario s.json
# or set NEUTRINO_GEN
```

A source-first inspection of what the capability *is*, assembled purely from real
compiler output (no recomputation here). The tool runs `neutrino-gen
--target=security` and `--target=slot --allow-insecure`, then structures their
artifacts:

```json
{
  "schemaVersion": 1,
  "file": "<hydrated-curated-pack>/source/example.neu",
  "ok": true,
  "capability": {
    "procedure": "core_sponsored_offer",
    "version": "0.1.0",
    "capabilityHash": "085786f7…",
    "ir": { "inputs": 5, "computes": 0, "participants": 0, "legs": 2 },
    "security": { "status": "advisory", "findings": [ { "category": "value", "status": "pass", "findings": ["…"] } ] },
    "backends": [ { "target": "solidity", "available": true, "gated": true },
                  { "target": "postgres", "available": true, "gated": true } ],
    "assurance": { "labels": [ { "participant": "Sponsor", "minAssurance": "A2", "earnedAt": "realization" } ] }
  }
}
```

- **`capabilityHash`** comes from the slot `capability.lock` (the wire-contract
  hash = the Fabric `EnvelopeHeader.schema_hash` bridge); **`ir`** counts come from
  the slot `capability.json` model.
- **`security`** mirrors the Capability Security Pass report verbatim (category +
  status + finding text), so the editor shows the *same* verdict the gate enforces.
  `status` is the worst category status (`violation` > `advisory` > `pass`).
- **`backends`** remains exactly empty because the hashed slot capability is
  target-neutral; package availability belongs to separate catalog
  introspection and is not reconstructed in this preview.
- **`assurance`** is preview metadata assembled from the security and slot
  binding-policy surfaces. Capability-model v1 carries no static A1 or other
  assurance claim; late-binding `minAssurance` labels are earned downstream at
  realization and are never claimed as satisfied here.
- `--scenario` is **required** — `neutrino-gen` validates it against the procedure.
  (A scenario-less capability-identity preview would need a non-gated, scenario-free
  hash path in the translator; that is a later slice.) Preview runs the gated `slot`
  target with `--allow-insecure` so inspection works even for an insecure
  capability; the security findings still report the violation. `ok:false` always
  carries a `diagnostics` array (same shape as the `diagnostics` command, sourced
  from `neutrino-gen`'s own `diagnostics.json`), never an empty silent failure.

## `dialect` (registry / status / provenance) — implemented

```sh
neutrino_lang.py dialect path/to/domain-dialect.json [--validate <validate_domain_dialect.py>]
```

```json
{ "schemaVersion": 1, "dialect": "...", "ok": true,
  "domain": "sponsored_finance", "version": "0.1.0",
  "domainDialectHash": "e594005b…",
  "registry": {
    "terms": [ { "name": "sponsor", "kind": "term", "layer": "L2", "role": "sponsor",
                 "aliases": ["brand", "funder"], "status": "accepted",
                 "provenance": [ {"ref": "edge:sponsor-term-001", "source": "iso20022/pacs.008.schema",
                                  "status": "accepted", "reviewer": "domain-review"} ] } ],
    "templates": [ { "name": "core_sponsored_offer", "kind": "template", "layer": "L2",
                     "expandsTo": "procedure", "status": "accepted", "provenance": [ … ] } ] } }
```

Surfaces the reviewed `neutrino.domain-dialect` registry so the editor can offer
domain terms/templates **and** show their trust state. The artifact is first
validated by the translator-owned `validate_domain_dialect.py` (schema + provenance
+ `domainDialectHash`); only a verified artifact is rendered. Each entry's `status`
is the artifact's own review state (`accepted` / `proposed` / `rejected`), rolled up
across its provenance edges as the **worst** (rejected > proposed > accepted), and
its `provenance` is resolved from the `mappingGraph` edges its `provenanceRefs` cite
(source / status / reviewer) — never inferred. **Fail-closed:** a missing, stale
(hash-mismatched), or malformed artifact returns `ok:false` with the validator's
diagnostics and an empty registry. No domain parsing here — the wrapper reads the
validator's **normalized** output, not the source, so a valid JSON *or* YAML-authored
dialect (the validator accepts both) renders identically. (Wiring these
`status`-labelled terms into `completions` and the domain-term docs into `hover` is a
later affordance.)

## `symbols` (document outline) — front-end emit landed

The document outline (procedure → participants, inputs, computes, debit/credit
legs, allow policies) with **real source ranges**, emitted by the C++ front-end:

```sh
neutrino-emit --kind=symbols path/to/file.neu
```

```json
{ "kind": "neutrino.document-symbols", "schemaVersion": 1,
  "symbols": [ { "name": "core_flexible_binding", "kind": "procedure",
                 "range": {"start": {"line": 23, "column": 1}, "end": {"line": 49, "column": 1}},
                 "children": [ { "name": "Sponsor", "kind": "participant",
                                 "range": {"start": {"line": 24, "column": 1}, "end": {"line": 30, "column": 1}} } ] } ] }
```

Ranges come from the front-end's op locations: a block op (procedure/participant/
debit/credit/allow-block) spans header line .. closing-brace line; a leaf op
(input/compute/allow/assert) is a single line. `column` is 1 (the lexer is
line-oriented). Invoke on `.neu` source; ranges are relative to the
parsed file.

The `neutrino_lang.py symbols` wrapper renders this into the versioned envelope
(mirroring `diagnostics`), so the console consumes one shape:

```sh
neutrino_lang.py symbols path/to/file.neu --emit <neutrino-emit>   # or set NEUTRINO_EMIT
```

```json
{ "schemaVersion": 1, "file": "...", "ok": true, "symbols": [ /* as above */ ] }
```

`ok` is true only when the source lowers; otherwise `ok:false` with `symbols: []`
and the front-end's structured parser `diagnostics` (same codes as the
`diagnostics` command — never a silent empty outline). The wrapper is a pure
renderer over `neutrino-emit --kind=symbols`; it does not parse `.neu` itself.

## `hover` (symbol docs) — implemented

```sh
neutrino_lang.py hover path/to/file.neu --line L [--column C] --emit <neutrino-emit>
# or set NEUTRINO_EMIT
```

```json
{ "schemaVersion": 1, "file": "...", "ok": true,
  "position": {"line": 24, "column": 1},
  "hover": { "kind": "participant", "name": "Sponsor",
             "range": {"start": {"line": 24, "column": 1}, "end": {"line": 30, "column": 1}},
             "contents": "Declared participant: an actor/organization authorized …" } }
```

Resolves the **deepest** outline symbol whose range contains the position (a child
wins over its enclosing procedure) from the front-end's `symbols` ranges, then
composes a static, translator-owned doc for that construct kind. No new parse — it
reuses the front-end ranges, never scanning `.neu`. `hover` is `null` when no symbol
covers the position (valid — e.g. a blank/comment line). `ok:false` (with `hover:
null` + structured `diagnostics`) only when the source does not lower or the emitter
artifact is missing/malformed. Domain-term docs are layered in by the `dialect`
slice (). Ranges are line-level (`column` 1).

## `completions` — implemented

```sh
neutrino_lang.py completions                                  # scope=static
neutrino_lang.py completions path/to/file.neu --emit <neutrino-emit>   # + in-scope %refs
```

Static (no file) → the language's grammar affordances from `metadata`:

```json
{ "schemaVersion": 1, "scope": "static", "ok": true,
  "completions": [ {"label": "procedure", "kind": "keyword", "category": "statement"},
                   {"label": "money", "kind": "type"},
                   {"label": "participant", "kind": "snippet", "insertText": "participant ${1:Name} { … }"} ] }
```

With a file → the static items **plus** the source's in-scope `%references` (declared
inputs + computes) resolved from the front-end `symbols` outline:

```json
{ "schemaVersion": 1, "file": "...", "ok": true,
  "completions": [ /* static */, {"label": "%contribution", "kind": "reference", "detail": "input"} ] }
```

Each item carries an LSP-style `kind`. The static affordances and the
source-specific `%references` are explicitly distinguished by `scope: static` vs a
`file` field. A file that does not lower fails closed (`ok:false` + diagnostics).
Semantic **dialect-term** completions (carrying the `status` label) layer in with
the `dialect` command (still part of ). No DSL parsing here — composition over
`metadata` + `symbols`.

## LSP adapter (later)

A thin LSP server can wrap these commands once `symbols`/`hover` land. It stays a
translator-owned process; the console talks to it (or a small backend endpoint),
never running parser logic in the browser.

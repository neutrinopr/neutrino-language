# M3 Native Build Gate ()

Every artifact an M3 sample **claims as generated code** must compile/validate with its
**native** target toolchain — not merely be emitted by the Neutrino translator — so M4 never
receives deterministic-but-unbuildable artifacts. Artifacts that are intentionally not code
are explicitly classified and excluded from native compilation. The gate
([`scripts/gates/native_build_gate.py`](../../scripts/gates/native_build_gate.py)) reads the sample
portfolio matrix ([`examples/m3-sample-portfolio.json`](../../examples/m3-sample-portfolio.json),
), so the classification and the build gate share one source of truth.

This gate **builds/validates** generated code; it never **runs** executable instances — that
is the M3/M4 boundary (M4 runtime execution lives in `neutrino-build-tools` / `neutrino-network`).

## Per-target native validation rule

| Generated output | Native validation |
|---|---|
| Solidity / EVM (`.sol`) | `solc` (wired in this gate, `--run`) — and Foundry / `make validate` for full projects |
| PostgreSQL / SQL (`.sql`) | translator-repo SQL parser / migration validation (`make validate`) |
| JVM / Kotlin / Java (`.kt`/`.java`) | Gradle / JVM compile or wrapper contract check |
| Rust / WASM (`.rs`/`.wasm`) | Cargo / WASM build |
| JSON sidecars/manifests | JSON/domain/layer validators + deterministic fixture comparison (`json-schema-validated`) |
| `.neu` source | `neutrino-translate` → IR + `neutrino-gen` (`native-validated`) |

## Classifications (, shared with )

- **`native-validated`** — built/validated by its native target toolchain (or, for `.neu`,
  the translator/generator).
- **`json-schema-validated`** — JSON/schema validated only.
- **`metadata-only`** — descriptive, not code.
- **`future-profile-deferred`** — declared but not emitted/built in M3.

## What the gate enforces (fail-closed)

1. **No mislabelled buildable code.** A committed artifact whose extension is a native target
   language (`.sol`/`.sql`/`.kt`/`.java`/`.rs`/`.wasm`) **must** be `native-validated` — it can
   never be hidden as `json-schema-validated` / `metadata-only` / `future-profile-deferred`.
2. **Native build for claimed code (`--run`).** For each committed native-target artifact the
   gate runs its native toolchain (`solc` for `.sol`); a missing toolchain or a compile failure
   fails the gate. A target without a wired gate cannot be claimed as committed native code —
   wire the gate or mark it `future-profile-deferred`.
3. **Honest non-code classification.** `.neu` → `native-validated`, JSON → `json-schema-validated`.

It also emits a machine-readable **release-note build summary** (kind
`neutrino.m3-native-build-summary`, `--summary-out`) so release notes can state precisely which
sample artifacts are native-compiled, translator/JSON-validated, metadata-only, or deferred.

## Verification matrix — strategy  samples (today)

The three samples are L1 `.neu` + JSON L2/L3 sidecars; none commit native target code yet, so
their Solidity/PostgreSQL profiles are `future-profile-deferred` (explicitly, not silently).

| Sample | Artifact | Class | Native command / status |
|---|---|---|---|
| /, ,  | `…/source/*.neu` | native-validated | `neutrino-translate` + `neutrino-gen --target=slot` (self-tests `[63]`/`[66]`/`[68]`) |
| " | `*.l2.json`, `*.l3.binding.json` | json-schema-validated | `validate_l2_domain_semantics.py` / `validate_l2_branch_compat.py` / `validate_binding_manifest.py` |
| " | generated `slot` | json-schema-validated | `neutrino-gen --target=slot`, validated against `binding-topology` |
| " | generated `solidity` / `postgres` | future-profile-deferred | not emitted for these samples; would build via `solc` (this gate `--run`) / `make validate` when committed |

## How to run / add a sample

- `make native-build-gate` — runs the gate; with `solc` present it `--run`-compiles any
  committed native-target code. Self-test `[69]` runs the fail-closed honesty checks in CI
  (no toolchain needed); the fast tier runs it too (`[fast/6]`).
- A new sample that commits generated target code must classify it `native-validated`, ensure
  a native gate is wired for that target, and the gate will compile it — otherwise mark the
  profile `future-profile-deferred`. References:  (portfolio), , .

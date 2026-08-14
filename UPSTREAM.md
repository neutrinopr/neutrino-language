# Upstream contributions

Work on this compiler surfaces friction in the toolchains it builds on. Where that
friction reflects a genuine upstream gap, we contribute the fix upstream rather than
carry a private workaround. This file tracks those contributions and the local
compensations they retire.

| upstream change | status | local compensation it retires |
|---|---|---|
| [llvm/llvm-project#216360](https://github.com/llvm/llvm-project/pull/216360) — `[mlir] Highlight FileLineColRange diagnostics`: `SourceMgrDiagnosticHandler` maps proper `FileLineColRange` locations to `SMRange` highlighting, with byte-compatible fallback for point locations | under review | the manual range derivation in `lib/View.cpp` (used for capability source maps), once the change lands in a release this project adopts |

Contributions carry no project-specific vocabulary; motivation cites this repository.

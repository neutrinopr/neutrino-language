# Extraction manifest — NeutrinoBackendOracle (`lib/backends/oracle`)

M5 extraction Track A (/): the self-contained oracle-observer backend unit, ready for an M6 git-subtree split with
no further reorganization. It links ONLY the shared bottom leaves (below) — no ProcedureView, no sibling
backend — so the target graph itself proves the boundary (the link-smoke).

The lists below are machine-checked against the CMake/link graph by
[`scripts/gates/check_extraction_manifests.py`](../../../scripts/gates/check_extraction_manifests.py): declared Sources ==
the module's CMake sources + its link-smoke, Leaf dependencies == its `LINK_LIBS PUBLIC`, and every
declared public header exists. A drift between this manifest and `CMakeLists.txt` fails CI.

## Sources owned
- GenOracleObserverSpec.cpp
- test/oracle_observer_smoke.cpp

## Shared leaf dependencies
- NeutrinoSpecContract
- NeutrinoCodeText

## Public headers
- Neutrino/GenOracleObserverSpec.h

## Conformance slice
- `oracle-observer-smoke` — the leaf-only link-smoke (`test/`)
- `test/ir/oracle/oracle_delivery.neu` — the byte-golden observers + aggregator
- `test/ir/oracle/observer_guard_parity.test` — the observer↔guard parity gate ()

## Non-ownership (explicit)
- Does NOT own the registry ENTRY (the oracle registry entry in `NeutrinoEmit`) — it stays in `NeutrinoEmit` (it needs the spec producer +
  `realize()`), the aggregator that folds the view→spec→renderer call.
- Does NOT own the `include/Neutrino/` directory — it EXPOSES only its own headers (above); the shared
  contract/adapter headers are the leaves'.
- Does NOT own domain byte-goldens (`examples/domains/*/generated/`) — the shared conformance corpus.
- Does NOT own cross-cutting gates (`scripts/check_*`, the lit non-vacuous manifest, the root CMake).

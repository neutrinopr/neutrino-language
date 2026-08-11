# Extraction manifest — NeutrinoCapabilityProfile (`lib/policy/capability-profile`)

M5 extraction Track A (/): the self-contained per-backend capability model unit, ready for an M6 git-subtree split with
no further reorganization. It links ONLY the shared bottom leaves (below) — no ProcedureView, no sibling
backend — so the target graph itself proves the boundary (the link-smoke).

The lists below are machine-checked against the CMake/link graph by
[`scripts/gates/check_extraction_manifests.py`](../../../scripts/gates/check_extraction_manifests.py): declared Sources ==
the module's CMake sources + its link-smoke, Leaf dependencies == its `LINK_LIBS PUBLIC`, and every
declared public header exists. A drift between this manifest and `CMakeLists.txt` fails CI.

## Sources owned
- GenCapabilityModelSpec.cpp
- test/capability_profile_smoke.cpp

## Shared leaf dependencies
- NeutrinoSpecContract

## Public headers
- Neutrino/GenCapabilityModelSpec.h

## Conformance slice
- `capability-profile-smoke` — the leaf-only link-smoke (`test/`)
- `backend-capability-model-v1.schema.json` — closed nested v1 model contract
- `capability_claims.test` — independent catalog/schema/byte-binding mutations

## Non-ownership (explicit)
- Does NOT own target dispatch or package discovery. `neutrino-gen` passes the
  already verified, target-sorted catalog profiles through the driver-serialized
  target seam.
- Does NOT own the `include/Neutrino/` directory — it EXPOSES only its own headers (above); the shared
  contract/adapter headers are the leaves'.
- Does NOT own domain byte-goldens (`examples/domains/*/generated/`) — the shared conformance corpus.
- Does NOT own cross-cutting gates (`scripts/check_*`, the lit non-vacuous manifest, the root CMake).

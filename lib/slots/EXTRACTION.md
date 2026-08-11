# Extraction manifest — retained public-core slots (`lib/slots`)

The target-neutral slot artifact model and its registry adapter are retained
public core. `NeutrinoSlotSpec` consumes only the frozen capability-spec
contract. `NeutrinoSlotCore` converts the verified in-memory view to that
contract and delegates without adding target-specific decisions.

No build-profile source decorates the descriptor. The former full-profile
bundled-backend-claims overlay was REMOVED by  S0-C2R: backend availability
is package/target discovery, not agreement content, and folding it into the
hashed capability descriptor made the capability identity depend on the
producer's build profile. Slot descriptor generation is now profile-independent.

The lists below are machine-checked against the source and component build graph
by
[`scripts/gates/check_extraction_manifests.py`](../../scripts/gates/check_extraction_manifests.py).
A drift between this manifest and `CMakeLists.txt` fails CI.

## Sources owned
- GenSlotSpec.cpp
- SlotTarget.cpp
- test/slot_spec_smoke.cpp

## Shared leaf dependencies
- NeutrinoAnalysis
- NeutrinoSpecContract

## Public headers
- Neutrino/GenSlot.h
- Neutrino/GenSlotSpec.h

## Components
- NeutrinoSlotSpec
- NeutrinoSlotCore

## Component NeutrinoSlotSpec sources owned
- GenSlotSpec.cpp
- test/slot_spec_smoke.cpp

## Component NeutrinoSlotSpec dependencies
- NeutrinoSpecContract

## Component NeutrinoSlotSpec public headers
- Neutrino/GenSlotSpec.h

## Component NeutrinoSlotSpec integration headers
- none

## Component NeutrinoSlotCore sources owned
- SlotTarget.cpp

## Component NeutrinoSlotCore dependencies
- NeutrinoAnalysis
- NeutrinoSlotSpec

## Component NeutrinoSlotCore public headers
- Neutrino/GenSlot.h

## Component NeutrinoSlotCore integration headers
- Neutrino/GenSpec.h

## Conformance slice
- `slot-spec-smoke` — standalone target-neutral slot rendering from the
  synthetic core capability-spec
- `core-only-export-check` — proves the retained unit exports without backend,
  oracle, or production-domain paths
- `test/ir/pipeline/slot.test` — full-profile slot artifact behavior

## Non-ownership (explicit)
- Does NOT own capability-spec production or the generic target registry.
- Does NOT own bundled backend implementations, backend packages, the oracle,
  or production-domain inputs.
- Does NOT own backend availability. The former `full/SlotBackendClaims.*` overlay
  is DELETED ( S0-C2R); backend availability is package/target discovery and
  is not emitted into the capability descriptor at all.
- Does NOT own shared headers outside the two public slot headers above.
- Does NOT own cross-cutting gates, root build orchestration, or committed
  domain byte-goldens.

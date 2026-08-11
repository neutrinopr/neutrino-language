# Extraction manifest — retained public-core views (`lib/views`)

The target-neutral participant-view model and its registry adapter are retained
public core. `generateParticipantViewsFromSpec` consumes only the frozen
capability-spec JSON. The direct smoke links only `NeutrinoViewsSpec`, so a
dependency on the adapter, registry, production domains, oracle, or a backend
fails at link time.

The lists below are machine-checked against the CMake/link graph by
[`scripts/gates/check_extraction_manifests.py`](../../scripts/gates/check_extraction_manifests.py): declared Sources ==
the module's CMake sources + its link-smoke, Leaf dependencies == its `LINK_LIBS PUBLIC`, and every
declared public header exists. A drift between this manifest and `CMakeLists.txt` fails CI.

## Sources owned
- GenViewsSpec.cpp
- ViewsTarget.cpp
- test/views_spec_smoke.cpp

## Shared leaf dependencies
- NeutrinoAnalysis
- NeutrinoSpecContract

## Public headers
- Neutrino/GenViews.h
- Neutrino/GenViewsSpec.h

## Components
- NeutrinoViewsSpec
- NeutrinoViewsCore

## Component NeutrinoViewsSpec sources owned
- GenViewsSpec.cpp
- test/views_spec_smoke.cpp

## Component NeutrinoViewsSpec dependencies
- NeutrinoSpecContract

## Component NeutrinoViewsSpec public headers
- Neutrino/GenViewsSpec.h

## Component NeutrinoViewsSpec integration headers
- none

## Component NeutrinoViewsCore sources owned
- ViewsTarget.cpp

## Component NeutrinoViewsCore dependencies
- NeutrinoAnalysis
- NeutrinoViewsSpec

## Component NeutrinoViewsCore public headers
- Neutrino/GenViews.h

## Component NeutrinoViewsCore integration headers
- Neutrino/GenSpec.h

## Conformance slice
- `views-spec-smoke` — standalone target-neutral participant-view rendering
  from the synthetic core capability-spec
- `core-only-export-check` — proves the retained unit exports without backend,
  oracle, or production-domain paths
- `test/ir/pipeline/participant_views.test`, `test/ir/pipeline/views.test` — the spec-derived views gates
- `examples/domains/*/generated/views/*.json` — the committed per-participant view byte-goldens

## Non-ownership (explicit)
- Does NOT own capability-spec production or the generic target registry.
- Does NOT own backend/package availability, lowering, rendering, or dispatch.
- Does NOT own the `include/Neutrino/` directory — it exposes only the two
  public views headers above.
- Does NOT own domain byte-goldens (`examples/domains/*/generated/`) — the shared conformance corpus.
- Does NOT own cross-cutting gates (`scripts/gates/check_*`, the lit non-vacuous manifest, the root CMake).

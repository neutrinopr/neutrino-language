# Extraction manifest — retained public-core coverage (`lib/coverage`)

The target-neutral coverage model and its registry adapter are retained public
core. `coverageReportFromSpec` consumes only the frozen capability-spec and the
shared value-model contract. The direct smoke links only
`NeutrinoCoverageSpec`, so a dependency on the registry adapter, a production
backend, the oracle, or a production domain fails at link time.

The full-profile compatibility source appends bundled-backend maturity claims
only when `NEUTRINO_CORE_ONLY` is disabled. It is physically absent from the
core-only export and does not change the target-neutral coverage model.

The lists below are machine-checked against the source and build graph by
[`scripts/gates/check_extraction_manifests.py`](../../scripts/gates/check_extraction_manifests.py).
A drift between this manifest and `CMakeLists.txt` fails CI.

## Sources owned
- CoverageTarget.cpp
- GenCoverageSpec.cpp
- full/CoverageBackendMaturity.cpp
- test/coverage_spec_smoke.cpp

## Shared leaf dependencies
- NeutrinoAnalysis
- NeutrinoSpecContract

## Public headers
- Neutrino/GenCoverage.h
- Neutrino/GenCoverageSpec.h

## Components
- NeutrinoCoverageSpec
- NeutrinoCoverageCore

## Component NeutrinoCoverageSpec sources owned
- GenCoverageSpec.cpp
- test/coverage_spec_smoke.cpp

## Component NeutrinoCoverageSpec dependencies
- NeutrinoSpecContract

## Component NeutrinoCoverageSpec public headers
- Neutrino/GenCoverageSpec.h

## Component NeutrinoCoverageSpec integration headers
- none

## Component NeutrinoCoverageCore sources owned
- CoverageTarget.cpp
- full/CoverageBackendMaturity.cpp

## Component NeutrinoCoverageCore dependencies
- NeutrinoAnalysis
- NeutrinoCoverageSpec

## Component NeutrinoCoverageCore public headers
- Neutrino/GenCoverage.h

## Component NeutrinoCoverageCore integration headers
- Neutrino/GenSpec.h

## Conformance slice
- `coverage-spec-smoke` — standalone target-neutral coverage rendering from the
  synthetic core capability-spec
- `core-only-export-check` — proves the retained unit exports without backend,
  oracle, or production-domain paths
- `golden-coverage-*` — committed full-profile coverage-report byte evidence

## Non-ownership (explicit)
- Does NOT own capability-spec production or the generic target registry.
- Does NOT own bundled backend implementations, backend packages, the oracle,
  or production-domain inputs.
- Does NOT expose `full/CoverageBackendMaturity.h`; that compatibility adapter
  remains private to the non-core build.
- Does NOT own shared headers outside the two public coverage headers above.
- Does NOT own cross-cutting gates, root build orchestration, or committed
  domain byte-goldens.

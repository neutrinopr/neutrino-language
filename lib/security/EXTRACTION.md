# Extraction manifest — retained public-core security (`lib/security`)

The target-neutral security policy and its registry adapter are retained public
core. `NeutrinoSecurityPolicy` consumes only the frozen capability-spec and
owns the pre-dispatch refusal decision. `NeutrinoSecurityCore` converts the
verified in-memory view to that contract and delegates to the policy without
adding backend authority.

The direct smoke links only `NeutrinoSecurityPolicy`, so a dependency on the
registry adapter, a production backend, the oracle, or a production domain
fails at link time.

The lists below are machine-checked against the source and component build graph
by
[`scripts/gates/check_extraction_manifests.py`](../../scripts/gates/check_extraction_manifests.py).
A drift between this manifest and `CMakeLists.txt` fails CI.

## Sources owned
- GenSecuritySpec.cpp
- SecurityAdmission.cpp
- SecurityTarget.cpp
- test/security_policy_smoke.cpp

## Shared leaf dependencies
- NeutrinoAnalysis
- NeutrinoSpecContract

## Public headers
- Neutrino/GenSecurity.h
- Neutrino/GenSecuritySpec.h

## Components
- NeutrinoSecurityPolicy
- NeutrinoSecurityCore

## Component NeutrinoSecurityPolicy sources owned
- GenSecuritySpec.cpp
- SecurityAdmission.cpp
- test/security_policy_smoke.cpp

## Component NeutrinoSecurityPolicy dependencies
- NeutrinoSpecContract

## Component NeutrinoSecurityPolicy public headers
- Neutrino/GenSecuritySpec.h

## Component NeutrinoSecurityPolicy integration headers
- none

## Component NeutrinoSecurityCore sources owned
- SecurityTarget.cpp

## Component NeutrinoSecurityCore dependencies
- NeutrinoAnalysis
- NeutrinoSecurityPolicy

## Component NeutrinoSecurityCore public headers
- Neutrino/GenSecurity.h

## Component NeutrinoSecurityCore integration headers
- Neutrino/GenSpec.h
- Neutrino/Validate.h

## Conformance slice
- `security-policy-smoke` — standalone hard-violation refusal from the
  synthetic core capability-spec
- `core-only-export-check` — proves the retained unit exports without backend,
  oracle, or production-domain paths
- `golden-security-*` — committed full-profile security-report byte evidence

## Non-ownership (explicit)
- Does NOT own capability-spec production or the generic target registry.
- Does NOT own bundled backend implementations, backend packages, the oracle,
  or production-domain inputs.
- Does NOT own shared headers outside the two public security headers above.
- Does NOT own cross-cutting gates, root build orchestration, or committed
  domain byte-goldens.

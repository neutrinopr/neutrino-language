# scripts/ — tooling boundary map ( /  S1)

Sidecar **validators** (Python, enforcing the `docs/` contracts against committed artifacts) and CI
**helpers** (shell). The C++ tools stay file-based and deterministic; these gate the schema-first
sidecars the tools don't own.

The layout makes the **base-language vs domain-scaling boundary physical** (): core compiler
contracts live at the root of `scripts/`, while domain-dialect / L2 / corpus / rail / sample tooling
lives in explicit subtrees, so domain/corpus logic can't be mistaken for generic compiler logic.
This map is the allowlist the  boundary scanner consumes.

## Layout

The base-compiler root is organized by **role** (), while the **base-vs-domain** boundary (/)
stays the top-level axis: domain/corpus/rail/sample tooling lives in its own subtrees.

| Location | Owns | Examples |
| --- | --- | --- |
| `scripts/` (root) | **build / release / quality infra + data** — the non-role toolchain scripts and the `architecture_boundaries.json` gate config | `mutation_test.py`, `property_test.py`, `run_*.sh`, `make_release.sh`, `smoke_test.sh`, `validate-slot-fixtures.sh`, `architecture_boundaries.json` (`cpp_policy_baseline.json` co-located with its consumer in `gates/`) |
| `scripts/gates/` | **structural gates** (`check_*` + `native_build_gate`) — the boundary/policy/pin scanners that fail CI on a violation | `check_capability_claims.py`, `check_spec_legality.py`, `check_artifact_pins.py`, `check_compatibility.py`, `check_renderer_includes.py`, `check_cpp_policy.py` (+ `cpp_policy_baseline.json`), `check_architecture_boundaries.py`, `check_extraction_manifests.py`, `native_build_gate.py` |
| `scripts/validators/` | **semantic validators** (`validate_*`) — the stdlib-Python contract/schema validators that own the *meaning* of a committed artifact | `validate_capability_spec.py`, `validate_target_profile.py`, `validate_test_realization.py`, `validate_participant_view.py`, `validate_binding_manifest.py`, `validate_binding_topology.py`, `validate_compatibility_manifest.py`, `validate_cross_rail_catalog.py`, `validate_backends.py`, `validate_sovereign_envelope.py`, `validate_observation_binding.py` |
| `scripts/generators/` | **generators** — produce/refresh a committed artifact + the language-intelligence tools | `generate_tmgrammar.py`, `generate_linguist_assets.py`, `neutrino_lang.py`, `neutrino_lsp.py`, `fork_capability.py`, `make_release_manifest.py` |
| `scripts/domain/` | **domain-dialect + L2 domain-semantics tooling** | `validate_domain_dialect.py`, `expand_dialect.py`, `domain_diagnostics.py`, `validate_l2_domain_semantics.py`, `validate_l2_branch_compat.py` |
| `scripts/corpus/` | **corpus / observation-set / proposal / classification tooling** | `validate_domain_observation_set.py`, `validate_domain_proposal.py`, `generate_proposal_from_observations.py`, `generate_proposal_selftest.py`, `validate_solidity_classification.py` |
| `scripts/rails/` | **rail / lower-layer translation tooling** | `translate_rail.py`, `validate_translation_map.py`, `cross_rail_dry_run.py` |
| `scripts/samples/` | **sample / release gates (domain-scaling coverage)** | `validate_sample_portfolio.py`, `spec_feature_matrix.py`, `make_core_feature_example_matrix.py`, `check_m5_scorecard.py` |

### Committed fixtures (`examples/`)

The corresponding fixture trees are **documented here, not moved** — relocating them would churn paths
embedded in committed goldens/manifests and risk changing artifact bytes (out of scope for this slice,
which is behavior/bytes-preserving). Their ownership mirrors the script boundary:

| Fixture tree | Owned by |
| --- | --- |
| `examples/domain-dialects/`, `examples/l2-domain-semantics/` | `scripts/domain/` |
| `examples/domain-observation-set/`, `examples/domain-proposals/`, `examples/solidity-classification/` | `scripts/corpus/` |
| `examples/translation-maps/` | `scripts/rails/` |
| `examples/m3-sample-portfolio.json`, `examples/m5-scorecard/`, `examples/target-profiles/` | `scripts/samples/` (+ core) |

## Transitional wrappers (remove after )

Every moved script keeps a **thin transitional wrapper at its old root path** so existing entry
points don't break during M5 — both `python3 scripts/<name>.py …` (forwarded, run as `__main__`) and
`import <name>` (API re-exported). The wrappers carry a `TRANSITIONAL wrapper ( …)` header and
hold **no logic**; edit the real file under the subtree. The wrappers are the *only* domain/corpus/
rail/sample entries remaining in the root listing, and they are explicitly marked, so the
**`arch-root-scripts`** scanner (below) allowlists them by that header while flagging any *new*
unmarked script at the root as a boundary violation. Make/CMake/CTest/CI entry points are unchanged
(they resolve through the wrappers). Retiring the wrappers is just deleting the files — they pass
`arch-root-scripts` via the marker, not via `root_scripts.allowed`, so no allowlist edit is needed.

## Architecture boundary scanners ()

The boundary above is **enforced**, not just documented, by `check_architecture_boundaries.py`
(reviewed config: `architecture_boundaries.json`), registered as two source-only CTest tests that
also run in the fast tier:

- **`arch-backend-isolation`** — the controlled backend identifiers (`solidity`/`postgres`) may
  appear, in **code**, only in the backend renderers / target registry / expression-lowering AST /
  manifest / CLI tools (the config's `allowed_path_globs`); anywhere else in the C++ surface
  (`include/`+`lib/`+`tools/`) is a core-coupling violation.
- **`arch-domain-isolation`** — sample/domain names (**discovered** from `examples/domains/<name>/`)
  may appear nowhere in the C++ surface — the core is domain-agnostic.
- **`arch-root-scripts`** — enforces THIS boundary map: the flat `scripts/` root may hold only the
  core scripts in the config's `root_scripts.allowed` list and the marked transitional wrappers
  (any file with the `TRANSITIONAL wrapper ( …)` marker). A new unmarked `*.py` at the root — i.e.
  domain-scaling tooling that belongs in a subtree — fails; a genuinely-core new root script must be
  added to `allowed` on review.

The two C++ scanners **strip comments** before scanning (they govern code coupling, not prose that
documents a lowering — using the ONE hardened char/string/raw-string-aware stripper shared with the
C++ policy gate, ``), and **discover** the file set via `git ls-files` (no hand-maintained list).
All three **fail closed** on a missing/malformed config, an empty token/vocabulary/allowlist, or a
scan below its configured file floor, and each is proven non-vacuous by its own `--selftest` negative
fixtures (`check_architecture_boundaries.py --rule <r> --selftest`: a misplaced token/script + a
malformed config both fail — ). Run them with `ctest -L domain-scaling` (or `-L policy` alongside
`cpp-policy`).

## Verify

```
make test-fast       # no-build validator smoke gate (per-family CTest under `ctest -L fast`)
make validate        # backend validation (solc/Slither/libpg_query)
make acceptance      # full + backend + mutation + property + security + cross-rail
```

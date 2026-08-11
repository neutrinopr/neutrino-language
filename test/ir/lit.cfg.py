# Lit configuration for the neutrino IR regression suite ( /  S5-F1).
#
# The LLVM-idiomatic driver for MLIR regression tests: lit runs the `// RUN:` lines in each
# test/ir/*.{mlir,neu} fixture, with FileCheck for positive output and `-verify-diagnostics`
# (`// expected-error {{…}}`) for verifier/frontend error assertions. Tool paths are injected by
# CMake through the generated lit.site.cfg.py (which loads this file).
import os
import re
import shutil
import json
import tempfile

import lit.formats

# The oracle observer is JavaScript; a `.test` can execute it under node (the
# runtime-API leg of the  vector). Gate such tests with `REQUIRES: node` so
# they RUN wherever node is available (CI linux/macos runners, dev) and SKIP
# gracefully in a minimal env rather than failing.
if shutil.which("node"):
    config.available_features.add("node")

config.name = "neutrino-ir"
config.test_format = lit.formats.ShTest(execute_external=True)
# macOS SIP strips DYLD_* before a child process starts, so the Forge library path
# travels in the NEUTRAL `FORGE_DYLD_LIBRARY_PATH` and neutrino-equiv re-materialises
# it at the Forge process boundary (see tools/neutrino-equiv/neutrino-equiv.cpp and
# cmake/NeutrinoForgeToolchain.cmake). lit sanitises the environment, so without this
# forward a `.test` that runs neutrino-equiv gets Forge-present-but-unlinkable and
# reports a rail FAILURE rather than the `--allow-skips` skip (). This only
# FORWARDS what the caller exported: `scripts/gates/check_forge_toolchain.py
# --print-library-path` remains the single derivation authority — nothing is
# re-derived here.
if "FORGE_DYLD_LIBRARY_PATH" in os.environ:
    config.environment["FORGE_DYLD_LIBRARY_PATH"] = os.environ["FORGE_DYLD_LIBRARY_PATH"]
# `.mlir`/`.neu` fixtures carry their own RUN/CHECK; `.test` files are RUN-only drivers for checks
# that exercise a COMMITTED example source (referenced via %examples) rather than an inline fixture —
# e.g. a whole-domain security/lowering worked example ( S5h).
config.suffixes = [".mlir", ".neu", ".test"]
# `Inputs/` dirs hold fixtures a test references via %S/Inputs/... (e.g. the
# reordered-equivalent parity input); they are data, not tests.
config.excludes = ["Inputs"]
config.test_source_root = os.path.dirname(__file__)
# test_exec_root is set by lit.site.cfg.py (the build tree); fall back to source if run directly.
if not getattr(config, "test_exec_root", None):
    config.test_exec_root = config.test_source_root

# Source-root and tool substitutions used by the `// RUN:` lines (tool paths are
# set in lit.site.cfg.py by CMake). `%test` must be registered before lit appends
# its built-in `%t`: without the longer spelling, `%test/ir/...` is corrupted
# into the per-test temporary path followed by the literal suffix `est/ir/...`.
# `%not` is the LLVM `not` tool, which inverts the exit code so a RUN line can
# assert a tool REJECTS its input.
for name, path in (
    ("%test", os.path.dirname(config.test_source_root)),
    ("%neutrino-translate", config.neutrino_translate),
    ("%neutrino-opt", config.neutrino_opt),
    ("%neutrino-emit", config.neutrino_emit),
    ("%neutrino-gen", config.neutrino_gen),
    ("%neutrino-equiv", config.neutrino_equiv),
    ("%neutrino-bundle", config.neutrino_bundle),
    ("%not", config.not_tool),
    ("%FileCheck", config.filecheck),
    # %examples = the committed examples/ tree, so a `.test` driver can point a whole-domain check at
    # its committed source / scenario / golden without copying them into the test dir ( S5h).
    ("%examples", config.examples_root),
    # %scripts = the committed scripts/ tree, so a driver can invoke a Python validator/checker.
    ("%scripts", config.scripts_root),
    # %docs = the committed docs/ tree (language metadata, schemas) for drift/consumption checks.
    ("%docs", config.docs_root),
):
    config.substitutions.append((name, path))

# The curated release corpus is pack-only. Expose ordinal substitutions derived
# from the frozen manifest so tests consume hydrated payloads without embedding
# external domain identities or reconstructing pack coordinates.
_repo_root = os.path.dirname(config.examples_root)
with open(os.path.join(_repo_root, "docs", "m6-curated-example-corpus.json"),
          encoding="utf-8") as _stream:
    _corpus = json.load(_stream)
_curated_root = os.path.join(config.test_exec_root, "curated-packs")
os.makedirs(_curated_root, exist_ok=True)
for _index, _member in enumerate(_corpus["examples"]):
    _pack = _corpus["packs"][_member]["packPath"]
    _root = _pack if os.path.isabs(_pack) else os.path.join(_repo_root, _pack)
    _sources = sorted(
        os.path.join(_root, "source", _name)
        for _name in os.listdir(os.path.join(_root, "source"))
        if _name.endswith(".neu")
    )
    _scenario_dir = os.path.join(_root, "scenario")
    _scenarios = (
        sorted(os.path.join(_scenario_dir, _name)
               for _name in os.listdir(_scenario_dir)
               if _name.endswith(".json"))
        if os.path.isdir(_scenario_dir) else []
    )
    if len(_sources) != 1 or len(_scenarios) > 1:
        lit_config.fatal(
            f"curated pack ordinal {_index} has invalid source/scenario cardinality")
    config.substitutions.append((f"%curated{_index}-source", _sources[0]))
    if _scenarios:
        config.substitutions.append((f"%curated{_index}-scenario", _scenarios[0]))
    config.substitutions.append((f"%curated{_index}", _root))
    _ordinal_root = os.path.join(_curated_root, f"{_index:02d}")
    if os.path.lexists(_ordinal_root):
        os.unlink(_ordinal_root)
    os.symlink(_root, _ordinal_root)
config.substitutions.append(("%curated-pack-root", _curated_root))

# Non-vacuous manifest ( /  review): each frontend-negative test can't pass vacuously (%not
# + a coded CHECK), but the *set* could silently shrink — deleting/renaming a `neg_*.neu` would just
# leave lit running fewer tests, still green. Pin the expected fixtures (the retired
# frontend_negatives.sh had an `n >= 7` floor); a missing/renamed one FAILS the whole lit suite at
# config time. Adding a new `neg_*.neu` is auto-discovered (more coverage) and only needs a manifest
# bump. Enforced everywhere lit runs (`ctest -R lit`, `make ir-test`, CI).
_expected_frontend_negatives = {
    "neg_bad_compute", "neg_bad_value", "neg_duplicate_input", "neg_missing_field",
    "neg_unexpected_stmt", "neg_value_type_launder", "neg_value_type_mismatch",
    # attestation policy (oracle S1, ): non-evidence target + malformed field, fail closed.
    "neg_attest_non_evidence", "neg_attest_bad_fallback",
    # observer-set trust metadata (oracle S6, ): declared-but-unsupported assurance/independence.
    "neg_attest_bad_assurance", "neg_attest_bad_independence",
    # accepted() guard predicate ( slice 1): non-evidence arg + value-context use.
    "neg_accepted_non_evidence", "neg_accepted_as_value",
}
_present = {
    os.path.splitext(f)[0]
    for f in os.listdir(config.test_source_root)
    if f.startswith("neg_") and f.endswith(".neu")
}
_missing = _expected_frontend_negatives - _present
if _missing:
    lit_config.fatal(
        "frontend-negative fixtures missing from test/ir/ (non-vacuous manifest, ): "
        + ", ".join(sorted(_missing))
        + " — a negative was deleted/renamed; restore it or update the manifest in lit.cfg.py.")

# Non-vacuous manifest ( / ): the security worked-example + gate fixtures migrated out of
# run_cpp_tests.sh must not silently shrink either — each is individually non-vacuous, but a
# deleted/renamed `.neu`/`.test` would just leave lit running one fewer subtest, a silent coverage
# drop of a formerly-always-run numbered section. Pin the set (extends as more security sections
# migrate); a missing one FAILS the whole lit suite at config time.
_expected_security_fixtures = {
    # [23]-[27] inline gate fixtures
    "bound.neu", "unbound.neu", "org_advisory.neu", "org_violation.neu",
    "policy_ok.neu", "policy_bad.neu", "malformed_allow.neu", "gate_violation.neu",
    # [29]/[30] frozen mutated-source negatives
    "agreement_wrong_allow.neu", "agreement_malformed.neu",
    "role_violation.neu", "multi_pair_unmatched.neu",
    # committed-source worked examples ([28] secured, [29] agreement, [30] role/multi-pair)
    "secured_example.test", "agreement_sugar.test", "role_policy.test", "multi_pair_role.test",
    # [100] authority-binding surfacing is binding-faithful ( slice 4): rebinding a leg is detected
    "authority_binding.test",
}
_sec_dir = os.path.join(config.test_source_root, "security")
_present_sec = set(os.listdir(_sec_dir)) if os.path.isdir(_sec_dir) else set()
_missing_sec = _expected_security_fixtures - _present_sec
if _missing_sec:
    lit_config.fatal(
        "security fixtures missing from test/ir/security/ (non-vacuous manifest, ): "
        + ", ".join(sorted(_missing_sec))
        + " — a migrated section's fixture was deleted/renamed; restore it or update the manifest.")

# Non-vacuous manifest ( /  S5i): the backend --from-spec ingestion drivers migrated out of
# run_cpp_tests.sh must not silently shrink either. Pin the .test drivers (extends as more backend
# sections migrate); a missing one FAILS the whole lit suite at config time.
_expected_backend_fixtures = {
    "solidity_from_spec.test",  # [86]
    "postgres_from_spec.test",  # [88]
    "validation_report.test",   # [31]
    "postgres_goldens.test",    # [81]
    "solidity_2state.test",     # [85]
}
_be_dir = os.path.join(config.test_source_root, "backend")
_present_be = set(os.listdir(_be_dir)) if os.path.isdir(_be_dir) else set()
_missing_be = _expected_backend_fixtures - _present_be
if _missing_be:
    lit_config.fatal(
        "backend fixtures missing from test/ir/backend/ (non-vacuous manifest, ): "
        + ", ".join(sorted(_missing_be))
        + " — a migrated section's fixture was deleted/renamed; restore it or update the manifest.")

# Non-vacuous manifest ( /  S5i): the spec-legality render-gate drivers.
_expected_legality_fixtures = {
    "solidity_legality.test",  # [84]
    "postgres_legality.test",  # [87]
}
_leg_dir = os.path.join(config.test_source_root, "legality")
_present_leg = set(os.listdir(_leg_dir)) if os.path.isdir(_leg_dir) else set()
_missing_leg = _expected_legality_fixtures - _present_leg
if _missing_leg:
    lit_config.fatal(
        "legality fixtures missing from test/ir/legality/ (non-vacuous manifest, ): "
        + ", ".join(sorted(_missing_leg))
        + " — a migrated section's fixture was deleted/renamed; restore it or update the manifest.")

# Non-vacuous manifest ( /  S5i): the neutrino-equiv report driver.
_expected_equiv_fixtures = {
    "equiv_report.test",              # [12]
    "equiv_structural.test",          # [90]
    "equiv_structural_failclosed.test",  # [91]
}
_eq_dir = os.path.join(config.test_source_root, "equiv")
_present_eq = set(os.listdir(_eq_dir)) if os.path.isdir(_eq_dir) else set()
_missing_eq = _expected_equiv_fixtures - _present_eq
if _missing_eq:
    lit_config.fatal(
        "equiv fixtures missing from test/ir/equiv/ (non-vacuous manifest, ): "
        + ", ".join(sorted(_missing_eq))
        + " — a migrated section's fixture was deleted/renamed; restore it or update the manifest.")

# Non-vacuous manifest: the explicit-instance-key + evidence-only fixtures.
_expected_evidence_fixtures = {
    "shipment_evidence_anchor.neu",       # the source-authored evidence-only sample
    "neg_instance_key_undeclared.neu",    # undeclared instance key
    "neg_instance_key_nonstring.neu",     # non-string instance key
    "neg_instance_key_duplicate.neu",     # duplicate instance-key declaration
    "neg_instance_key_literal_effect.neu",  # effect keyed on a literal, not the declared key
}
_ev_dir = os.path.join(config.test_source_root, "evidence")
_present_ev = set(os.listdir(_ev_dir)) if os.path.isdir(_ev_dir) else set()
_missing_ev = _expected_evidence_fixtures - _present_ev
if _missing_ev:
    lit_config.fatal(
        "evidence fixtures missing from test/ir/evidence/ (non-vacuous manifest): "
        + ", ".join(sorted(_missing_ev))
        + " — a fixture was deleted/renamed; restore it or update the manifest.")

# Non-vacuous manifest: the  bounded-dynamic-realization experiment driver.
_expected_experiment_fixtures = {"bounded_realization.test"}
_ex_dir = os.path.join(config.test_source_root, "experiment")
_present_ex = set(os.listdir(_ex_dir)) if os.path.isdir(_ex_dir) else set()
_missing_ex = _expected_experiment_fixtures - _present_ex
if _missing_ex:
    lit_config.fatal(
        "experiment fixtures missing from test/ir/experiment/ (non-vacuous manifest): "
        + ", ".join(sorted(_missing_ex))
        + " — a fixture was deleted/renamed; restore it or update the manifest.")

# Non-vacuous manifest: the portable agreement-identity () driver + golden vector.
_expected_agreement_fixtures = {
    "agreement_identity.test",
    "check_agreement_identity.py",
    "agreement_hash_vector.json",
}
_ag_dir = os.path.join(config.test_source_root, "agreement")
_present_ag = set(os.listdir(_ag_dir)) if os.path.isdir(_ag_dir) else set()
_missing_ag = _expected_agreement_fixtures - _present_ag
if _missing_ag:
    lit_config.fatal(
        "agreement fixtures missing from test/ir/agreement/ (non-vacuous manifest): "
        + ", ".join(sorted(_missing_ag))
        + " — a fixture was deleted/renamed; restore it or update the manifest.")

# Non-vacuous manifest ( /  S5j): the language-intelligence drivers.
_expected_lang_fixtures = {
    "language_metadata.test",  # [37]
    "document_symbols.test",   # [45]
    "preview.test",            # [44]
    "hover.test",              # [46]
    "completions.test",        # [47]
    "dialect.test",            # [48]
}
_lang_dir = os.path.join(config.test_source_root, "lang")
_present_lang = set(os.listdir(_lang_dir)) if os.path.isdir(_lang_dir) else set()
_missing_lang = _expected_lang_fixtures - _present_lang
if _missing_lang:
    lit_config.fatal(
        "lang fixtures missing from test/ir/lang/ (non-vacuous manifest, ): "
        + ", ".join(sorted(_missing_lang))
        + " — a migrated section's fixture was deleted/renamed; restore it or update the manifest.")

# Non-vacuous manifest (M5 oracle S4, ): the worked oracle-observer example (byte-golden + the
# structural sign-only-canonical-claim + fail-closed N<M). A deleted/renamed fixture must FAIL config,
# not silently drop the only oracle-backend acceptance test.
_expected_oracle_fixtures = {
    "oracle_delivery.neu",  #
    # oracle S6 (): the security surfacing of the oracle trust boundary — the observer set's
    # assurance/independence declared and flagged. Weak (A1/correlated) + undeclared → advisory;
    # strong (A3/independent) → surfaced-not-flagged. A deleted one must FAIL config, not shrink.
    "security_weak_observers.neu", "security_independent_observers.neu",
    "security_undeclared_observers.neu",
    # oracle S3 (): the quorum lifecycle — quorum-pending/met/timeout states + the declared
    # abort/escalate timeout fallback, fail-closed (the post departs only from QUORUM_MET).
    "lifecycle_quorum_abort.neu", "lifecycle_quorum_escalate.neu",
    # oracle S2c (): the Solidity quorum-guard lowering fails CLOSED on a canonicalization mode with
    # no reviewed on-chain guard (numeric `median` is deferred) — the byte-golden positive lives in
    # oracle_delivery.neu; this pins the render-gate negative. A deleted one must FAIL config, not shrink.
    "neg_quorum_guard_median.neu",
    # oracle (/): the quorum lowering fails CLOSED on a spec with >1 attestation policy on BOTH
    # rails (lowering only the first would leave the others ungated — fail-open) — pins the fail-close.
    # (BACKEND render is still single-policy until  slice 3; the coordination plan + reference evaluator support
    # per-policy accepted() already — accepted_multi_policy.neu.)
    "neg_multi_policy.neu",
    # accepted() guard predicate ( slice 1): the typed per-policy multi-policy quorum-acceptance
    # guard normalizes + evaluates (SUPPRESS on unaccepted); backend realization is a later slice.
    "accepted_multi_policy.neu",
    # oracle S5 (): the observation-binding contract — validator + backend portability + fail-closed.
    "observation_binding.test",
    # oracle S7 (): the observer↔guard parity gate — EIP-712 scheme/threshold/observer-set/claim
    # agreement, non-vacuous (naked observer + tampered descriptors fail).
    "observer_guard_parity.test",
    # oracle (): the coordination↔guard claimId parity gate — proves both rails key acceptance on
    # the same spec workflow key (claimId ≡ workflowKey), non-vacuous (drifted derivation/check fails).
    "coordination_guard_parity.test",
    # : the execution-claim cross-implementation vector (C++ recompute == guard-persisted ==
    # vector JSON) and the EXECUTABLE observer runtime-API leg (co-signs + fails closed, run under node).
    "execution_claim_vector.test", "observer_runtime_api.test",
}
_oracle_dir = os.path.join(config.test_source_root, "oracle")
_present_oracle = set(os.listdir(_oracle_dir)) if os.path.isdir(_oracle_dir) else set()
_missing_oracle = _expected_oracle_fixtures - _present_oracle
if _missing_oracle:
    lit_config.fatal(
        "oracle fixtures missing from test/ir/oracle/ (non-vacuous manifest, ): "
        + ", ".join(sorted(_missing_oracle))
        + " — the oracle-observer worked example was deleted/renamed; restore it or update the manifest.")

# Non-vacuous manifest (M5 token S1/S2/S3/S5): the token-line acceptance drivers — each proves a
# feature-by-balanced-composition property (no new primitive), so the *set* must not silently shrink.
_expected_token_fixtures = {
    "core_compliance_guard.test",  #  (S1): compliance-approval allow/deny/malformed
    "freeze_guard.test",  #  (S2): account-freeze suppression
    "core_memo.test",  # effect memo preserved across both backends by a synthetic fixture
    "token_supply.test",  #  (S5): mint/burn balanced on token.supply, both rails, unauthorized
    "unguarded_supply.neu",  #  (S5): regression — an unguarded supply leg is an advisory, not fail-closed
}
_token_dir = os.path.join(config.test_source_root, "token")
_present_token = set(os.listdir(_token_dir)) if os.path.isdir(_token_dir) else set()
_missing_token = _expected_token_fixtures - _present_token
if _missing_token:
    lit_config.fatal(
        "token fixtures missing from test/ir/token/ (non-vacuous manifest, //): "
        + ", ".join(sorted(_missing_token))
        + " — a token-line acceptance/regression driver was deleted/renamed; restore it or update the manifest.")

# Non-vacuous manifest ( /  S5j): the compiler-backed LSP driver ([98], neutrino_lsp.py).
_expected_lsp_fixtures = {
    "lsp.test",  # [98]
}
_lsp_dir = os.path.join(config.test_source_root, "lsp")
_present_lsp = set(os.listdir(_lsp_dir)) if os.path.isdir(_lsp_dir) else set()
_missing_lsp = _expected_lsp_fixtures - _present_lsp
if _missing_lsp:
    lit_config.fatal(
        "lsp fixtures missing from test/ir/lsp/ (non-vacuous manifest, ): "
        + ", ".join(sorted(_missing_lsp))
        + " — a migrated section's fixture was deleted/renamed; restore it or update the manifest.")

# Non-vacuous manifest ( /  S5k): the D0-D4 domain-layer + diagnostic-taxonomy drivers.
_expected_domain_fixtures = {
    "canonical_extension.test",   # [34]
    "domain_dialect.test",        # [35]
    "domain_proposal.test",       # [36]
    "diagnostic_taxonomy.test",   # [78]
    "binding_topology.test",      # [38]
    "dialect_expansion.test",     # [39]
    "domain_origin.test",         # [40]
    "translation_map.test",       # [41]
    "binding_manifest.test",      # [42]
}
_domain_dir = os.path.join(config.test_source_root, "domain")
_present_domain = set(os.listdir(_domain_dir)) if os.path.isdir(_domain_dir) else set()
_missing_domain = _expected_domain_fixtures - _present_domain
if _missing_domain:
    lit_config.fatal(
        "domain fixtures missing from test/ir/domain/ (non-vacuous manifest, ): "
        + ", ".join(sorted(_missing_domain))
        + " — a migrated section's fixture was deleted/renamed; restore it or update the manifest.")

# Non-vacuous manifest ( /  S5l): the M3 domain-sample + conformance/L2/L3 drivers.
_expected_samples_fixtures = {
    "m2_promotion.test",        # [50]
    "conformance.test",         # [56]
    "language_boundary.test",   # [57]
    "l2_validator.test",        # [58]
    "l3_evolution.test",        # [59]
    "l2_core_dual_offer.test",  # [60]
    "sample_siwf.test",              # [63]
    # [66] escrow. Migration provenance (): between  (PR ) and this reconciliation this
    # row read "sample_core_document_escrow.test" — a filename that has never existed in this tree.
    #  repointed the [66] section from an externalized escrow domain onto the synthetic,
    # test-only core_document_escrow and swept the retired domain slug through this manifest string,
    # but left the *fixture* and its driver under their original filenames. The manifest therefore
    # pinned a phantom and fataled lit at config time, skipping all 195 tests. No coverage moved:
    # the fixture below still RUNs check_sample_conditional_escrow.py, which drives
    # core_document_escrow (its SAMPLE constant) over test/ir/samples/Inputs/core_document_escrow/
    # and asserts the same L1/L2/L3 + branch-compat set it always has. Pin the fixture identity, not
    # the domain the fixture happens to drive — and keep the retired slug itself out of core source,
    # which is why this comment names the fixture rather than the domain it replaced ( reachback).
    "sample_conditional_escrow.test",  # [66] (drives core_document_escrow since )
    "sample_clinical.test",          # [68]
    "sample_pay_for_compute.test",   # [70]
    "sample_promo_campaign.test",    # [74]
    "registry_routing.test",         # [62]
    "branch_compat.test",            # [64]
    "lifecycle_decision.test",       # [65]
    "sample_portfolio.test",         # [67]
    "native_build_gate.test",        # [69]
    "cookbook.test",                 # [71]
}
_samples_dir = os.path.join(config.test_source_root, "samples")
_present_samples = set(os.listdir(_samples_dir)) if os.path.isdir(_samples_dir) else set()
_missing_samples = _expected_samples_fixtures - _present_samples
if _missing_samples:
    lit_config.fatal(
        "samples fixtures missing from test/ir/samples/ (non-vacuous manifest, ): "
        + ", ".join(sorted(_missing_samples))
        + " — a migrated section's fixture was deleted/renamed; restore it or update the manifest.")

# Non-vacuous manifest ( /  S5m): the compatibility / version / release-surface drivers.
_expected_compat_fixtures = {
    "cross_rail_catalog.test",   # [51]
    "layout_hygiene.test",       # [53]
    "compat_checker.test",       # [54]
    "compat_manifest.test",      # [72]
    "sovereign_envelope.test",   # [73]
    "target_registry_def.test",  # [97]
    "version_surface.test",      # [52]
    "artifact_pins.test",        # [52b]
    "release.test",              # [55]
}
_compat_dir = os.path.join(config.test_source_root, "compat")
_present_compat = set(os.listdir(_compat_dir)) if os.path.isdir(_compat_dir) else set()
_missing_compat = _expected_compat_fixtures - _present_compat
if _missing_compat:
    lit_config.fatal(
        "compat fixtures missing from test/ir/compat/ (non-vacuous manifest, ): "
        + ", ".join(sorted(_missing_compat))
        + " — a migrated section's fixture was deleted/renamed; restore it or update the manifest.")

# Non-vacuous manifest ( /  S5n): the core pipeline (emit/gen/scenario/bundle/value/expr) drivers.
_expected_pipeline_fixtures = {
    "emit_projection.test",     # [4]
    "gen_manifest.test",        # [5]
    "invalid_scenario.test",    # [6]
    "escaping.test",            # [7]
    "bundle.test",              # [9]
    "value_model.test",         # [10]
    "expression_model.test",    # [10b]
    "views.test",                 # [33]
    "capability_claims.test",     # [15]
    "coverage_spec_derived.test",  # [16b]
    "dsl_versioning.test",        # [19]
    "capability_fork.test",       # [20]
    "participants.test",          # [21]
    "security_spec_derived.test",  # [22b]
    "characterization.test",      # [43]
    "multi_slot_binding.test",    # [49]
    "classification.test",        # [75]
    "observation_set.test",       # [75b]
    "corpus_proposal.test",       # [75c]
    "m5_scorecard.test",          # [75d]
    "capability_spec.test",       # [76]
    "test_realization.test",      # [79]
    "slot_from_spec.test",        # [80]
    "participant_views.test",     # [82]
    "target_profiles.test",       # [77]
    "renderer_include_lock.test",  # [89]
    "conditional_guards.test",    # [92]
    "money_refuse.test",          # [94]
    "computed_expect.test",       # [305]
    "cpp_policy_ratchet.test",    # [95]
}
_pipeline_dir = os.path.join(config.test_source_root, "pipeline")
_present_pipeline = set(os.listdir(_pipeline_dir)) if os.path.isdir(_pipeline_dir) else set()
_missing_pipeline = _expected_pipeline_fixtures - _present_pipeline
if _missing_pipeline:
    lit_config.fatal(
        "pipeline fixtures missing from test/ir/pipeline/ (non-vacuous manifest, ): "
        + ", ".join(sorted(_missing_pipeline))
        + " — a migrated section's fixture was deleted/renamed; restore it or update the manifest.")

# Independent L1 obligation reference vectors. The driver, positive production
# fixture, verifier matrix, and repository-owned vector must remain a complete
# set; deleting any member must fail configuration rather than shrink coverage.
_expected_obligation_reference_fixtures = {
    "obligation_reference_vectors.test",
    "obligation_plan.mlir",
    "obligation_verifier.mlir",
}
_missing_obligation_reference = (
    _expected_obligation_reference_fixtures - set(os.listdir(config.test_source_root))
)
_obligation_vector = os.path.join(
    config.test_source_root, "Inputs", "obligation_reference_vectors.json"
)
if _missing_obligation_reference or not os.path.isfile(_obligation_vector):
    missing = sorted(_missing_obligation_reference)
    if not os.path.isfile(_obligation_vector):
        missing.append("Inputs/obligation_reference_vectors.json")
    lit_config.fatal(
        "obligation reference-vector surface is incomplete: "
        + ", ".join(missing)
        + " — restore the independent gate surface instead of shrinking it.")

# Registration binding (). Every manifest above guards a *set of filenames*, which is only half
# of a fixture's identity: a `.test` that survives the manifest can still stop executing anything.
# Its `// RUN:` line can be dropped, or the `%S/check_*.py` driver it names can be renamed out from
# under it while the fixture keeps the old name — both leave every manifest green.  proved the
# mirror-image drift is real (a domain rename swept a manifest string but not the fixture filename,
# ), so bind each collected `.test` to its *executable* identity as well: it must carry a RUN
# line, and every driver it path-qualifies with `%S/` must resolve on disk. `Inputs/` is data, not
# tests, and is skipped exactly as lit skips it (config.excludes).
_RUN_LINE_RE = re.compile(r"^//\s*RUN:", re.M)
_RUN_DRIVER_RE = re.compile(r"%S/([A-Za-z0-9_.@/+-]+\.py)")
# Substitution binding (). A `DEFINE:` directive CREATES a substitution; lit refuses a second
# `DEFINE:` of the same name and raises inside `adjust_substitutions` — *before any RUN line runs*.
# That makes the test UNRESOLVED rather than FAILED, so it reports no assertion outcome at all and
# is easy to misread as a mere failure. `backend/solidity_from_spec.test` carried `%{cer}` twice
# (identical value), which is why it was the single unresolved row of the  terminal attempt.
# A later *change* of value is spelled `REDEFINE:`; a duplicate binding is simply drift.
_DEFINE_RE = re.compile(r"^//\s*DEFINE:\s*(%\{[A-Za-z0-9_.+-]+\})\s*=", re.M)


def _registration_errors(root):
    """Report every `.test` under `root` that is not bound to a real, executable driver identity."""
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in config.excludes]
        for name in sorted(filenames):
            if not name.endswith(".test"):
                continue
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, root)
            with open(path, encoding="utf-8", errors="replace") as stream:
                text = stream.read()
            if not _RUN_LINE_RE.search(text):
                found.append(f"{rel}: carries no `// RUN:` line, so it asserts nothing")
                continue
            for driver in sorted(set(_RUN_DRIVER_RE.findall(text))):
                if not os.path.isfile(os.path.join(dirpath, driver)):
                    found.append(
                        f"{rel}: RUN line names driver {driver}, which does not exist "
                        "(fixture and driver identities have drifted apart)")
            _defined = _DEFINE_RE.findall(text)
            for _name in sorted({d for d in _defined if _defined.count(d) > 1}):
                found.append(
                    f"{rel}: substitution {_name} is DEFINE-d {_defined.count(_name)} times — lit "
                    "raises in adjust_substitutions before any RUN line executes, so the fixture "
                    "reports UNRESOLVED and asserts nothing; drop the duplicate, or use REDEFINE: "
                    "if a later value change is actually intended")
    return found


# Self-probe (): a guard nobody has watched fail is decorative, so prove this one bites before
# trusting its verdict on the real tree. Build a throwaway fixture/driver pair and replay the three
# drift classes this reconciliation is about — a renamed driver, a stripped RUN line, and (the
# case itself) a fixture that a manifest names but the directory does not hold. Each mutation must
# be reported; if a later edit weakens `_registration_errors`, the probe goes silent and lit fails
# HERE rather than shipping a gate that no longer bites.
_probe_work = tempfile.mkdtemp(prefix="neutrino-lit-registration-probe.")
try:
    _probe_test = os.path.join(_probe_work, "probe.test")
    _probe_driver = os.path.join(_probe_work, "check_probe.py")
    with open(_probe_test, "w", encoding="utf-8") as _stream:
        _stream.write("// RUN: python3 %S/check_probe.py %scripts\n")
    with open(_probe_driver, "w", encoding="utf-8") as _stream:
        _stream.write("# probe driver\n")
    # Data under an excluded dir must never be mistaken for a test (else the probe below is vacuous
    # for the wrong reason).
    os.makedirs(os.path.join(_probe_work, "Inputs"), exist_ok=True)
    with open(os.path.join(_probe_work, "Inputs", "data.test"), "w", encoding="utf-8") as _stream:
        _stream.write("not a test\n")

    _probe_failures = []
    if _registration_errors(_probe_work):
        _probe_failures.append(
            "a well-formed fixture/driver pair is reported as unbound (false positive)")

    os.rename(_probe_driver, os.path.join(_probe_work, "check_renamed.py"))
    if not any("check_probe.py" in _err for _err in _registration_errors(_probe_work)):
        _probe_failures.append("a driver renamed out from under its fixture is not reported")
    os.rename(os.path.join(_probe_work, "check_renamed.py"), _probe_driver)

    # : a duplicate DEFINE must be reported HERE, not discovered as an UNRESOLVED row after a
    # terminal run. A single DEFINE, and a DEFINE followed by REDEFINE, must both stay clean — the
    # guard forbids duplicate *binding*, not rebinding.
    with open(_probe_test, "w", encoding="utf-8") as _stream:
        _stream.write("// DEFINE: %{dup} = a\n"
                      "// DEFINE: %{dup} = a\n"
                      "// RUN: python3 %S/check_probe.py %scripts\n")
    if not any("%{dup}" in _err and "DEFINE-d 2 times" in _err
               for _err in _registration_errors(_probe_work)):
        _probe_failures.append(
            "a substitution DEFINE-d twice is not reported () — the fixture would go "
            "UNRESOLVED at run time instead of failing closed here")
    with open(_probe_test, "w", encoding="utf-8") as _stream:
        _stream.write("// DEFINE: %{dup} = a\n"
                      "// REDEFINE: %{dup} = b\n"
                      "// RUN: python3 %S/check_probe.py %scripts\n")
    if any("%{dup}" in _err for _err in _registration_errors(_probe_work)):
        _probe_failures.append(
            "DEFINE followed by REDEFINE is reported as a duplicate ( false positive) — "
            "rebinding a substitution is legal and must stay legal")

    with open(_probe_test, "w", encoding="utf-8") as _stream:
        _stream.write("// a fixture that asserts nothing\n")
    if not any("no `// RUN:`" in _err for _err in _registration_errors(_probe_work)):
        _probe_failures.append("a fixture with no RUN line is not reported")

    # The  row itself: the escrow fixture must stay *required*, not merely present. Deleting the
    # [66] row from `_expected_samples_fixtures` — the "make it green by dropping the name" move this
    # reconciliation exists to forbid — makes this probe fail closed.
    if not (_expected_samples_fixtures - (_present_samples - {"sample_conditional_escrow.test"})):
        _probe_failures.append(
            "removing sample_conditional_escrow.test from test/ir/samples/ is not reported by the "
            "samples manifest — the [66] escrow row () is no longer required")
finally:
    shutil.rmtree(_probe_work, ignore_errors=True)
if _probe_failures:
    lit_config.fatal(
        "lit fixture-registration guard is not biting (): "
        + "; ".join(_probe_failures)
        + " — restore the guard instead of running a suite it can no longer police.")

_registration_drift = _registration_errors(config.test_source_root)
if _registration_drift:
    lit_config.fatal(
        "lit fixtures are not bound to an executable driver identity (): "
        + "; ".join(_registration_drift)
        + " — restore the RUN line / driver, or rename fixture and driver together.")

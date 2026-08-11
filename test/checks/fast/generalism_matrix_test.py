"""[fast]  generalism matrix runner: the CONTRACT-ANCHORED verdict classifier, execution
identity grouping, adapter model, and envelope construction are correct and -contract-shaped
(minus the still-pending evidence seam) — build-free (pure logic). The binary-driven 32-cell
realization + live compile adapters + full validation run in the build/e2e tiers; here we prove the
ORCHESTRATION LOGIC without neutrino-gen or a live toolchain."""

import importlib.util
import json
import os
import unittest

from _fastcase import FastCase, REPO


def _load(relpath, name):
    p = os.path.join(REPO, relpath)
    spec = importlib.util.spec_from_file_location(name, p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_H = "a" * 64
_PROV = {
    "translator": {"name": "neutrino-translator", "version": "0.2.0", "revision": "abc123",
                   "imageDigest": "sha256:" + "0" * 64},
    "backends": [{"name": "solidity", "version": "m6", "revision": "abc123"},
                 {"name": "postgres", "version": "m6", "revision": "abc123"}],
    "tools": [{"name": "neutrino-gen", "version": "0.2.0", "revision": "abc123"}],
    "runtimes": [],
    "commands": [{"name": "neutrino-gen", "argv": ["neutrino-gen", "--target=solidity", "s.neu"]}],
    "configurationHash": "a" * 64,
}


_SP = {"id": "semantic.realization.v3", "version": "0.1.0"}


def _obs(**kw):
    """A realized-.neu observation: FAITHFUL-shaped by default; override to probe a branch."""
    base = dict(spec_exit=0, spec_hash=_H, spec_version="1.0.0", spec_codes=[], waist_hash=_H,
                trace_exit=0, trace=None, ref_codes=[],
                sol_exit=0, sol_hash=_H, sol_codes=[], pg_exit=0, pg_hash=_H, pg_codes=[],
                eq_valid=True, eq_exit=0, eq_ok=True, eq_trace_ok=True, eq_executed_cases=1,
                eq_backends={"solidity": "pass", "postgres": "pass"},
                eq_stages={"solidity": "", "postgres": ""},
                target_profiles=[("solidity", "target.evm.v1", 3)], timed_out=False)
    base.update(kw)
    return base


class GeneralismMatrix(FastCase):
    def _runner(self):
        return _load("scripts/generators/run_generalism_matrix.py", "gmatrix")

    def _validator(self):
        return _load("scripts/validators/validate_generalism_result.py", "gval")

    # ---- exit-code -> outcome ----
    def test_outcome_mapping(self):
        r = self._runner()
        self.assertEqual(r._outcome(0), "accepted")
        for e in (3, 4, 5, 6):
            self.assertEqual(r._outcome(e), "refused")
        for e in (2, 139, -11):
            self.assertEqual(r._outcome(e), "broken")
        self.assertEqual(r._outcome(None), "broken")
        self.assertEqual(r._outcome(0, timed_out=True), "broken")

    # ---- P1.3: contract-anchored refusal ----
    def test_reference_accepts_targets_security_refuse_is_BROKEN(self):
        # cell02: reference accepts (0), both targets security-refuse (5). A reference-vs-target
        # divergence is BROKEN, NOT a governed refusal (the P1.3 correction).
        r = self._runner()
        v, cause, sem = r.verdict_neu({"id": "x", "witness": "ledger"},
                                      _obs(sol_exit=5, pg_exit=5, sol_codes=["security.gate"],
                                           pg_codes=["security.gate"]), None)
        self.assertEqual(v, "BROKEN")
        self.assertEqual(cause, "internal_error")
        self.assertEqual(sem["referenceDecision"], "accepted")

    def test_predicted_waist_refusal_with_consistent_code_is_REFUSED(self):
        r = self._runner()
        codes = ["kernel.balance.not_balanceable"]
        obs = _obs(trace_exit=4, sol_exit=4, pg_exit=4, ref_codes=codes, sol_codes=codes, pg_codes=codes,
                   sol_hash=None, pg_hash=None)
        v, cause, _sem = r.verdict_neu({"id": "x", "witness": "refusal"}, obs, None)
        self.assertEqual((v, cause), ("REFUSED", "governed_refusal"))

    def test_unpredicted_refusal_everywhere_is_BROKEN(self):
        # a cell expected to realize, refused at 4/6 by everything -> unpredicted -> BROKEN.
        r = self._runner()
        codes = ["kernel.balance.not_balanceable"]
        obs = _obs(trace_exit=4, sol_exit=4, pg_exit=4, ref_codes=codes, sol_codes=codes, pg_codes=codes)
        v, cause, _ = r.verdict_neu({"id": "x", "witness": "ledger"}, obs, None)
        self.assertEqual((v, cause), ("BROKEN", "internal_error"))

    def test_refusal_at_exit_5_is_not_contract_honest(self):
        r = self._runner()
        obs = _obs(trace_exit=5, sol_exit=5, pg_exit=5, ref_codes=["s"], sol_codes=["s"], pg_codes=["s"])
        v, cause, _ = r.verdict_neu({"id": "x", "witness": "refusal", "refusalCode": "s"}, obs, None)
        self.assertEqual((v, cause), ("BROKEN", "substrate_protocol_limit"))

    def test_inconsistent_refusal_codes_is_BROKEN(self):
        r = self._runner()
        obs = _obs(trace_exit=4, sol_exit=4, pg_exit=4,
                   ref_codes=["a"], sol_codes=["b"], pg_codes=["c"])
        v, cause, _ = r.verdict_neu({"id": "x", "witness": "refusal"}, obs, None)
        self.assertEqual((v, cause), ("BROKEN", "internal_error"))

    def test_wrong_declared_refusal_code_is_BROKEN(self):
        r = self._runner()
        codes = ["actual.code"]
        obs = _obs(trace_exit=4, sol_exit=4, pg_exit=4, ref_codes=codes, sol_codes=codes, pg_codes=codes)
        v, cause, _ = r.verdict_neu({"id": "x", "witness": "refusal", "refusalCode": "expected.code"},
                                    obs, None)
        self.assertEqual((v, cause), ("BROKEN", "internal_error"))

    def test_cross_backend_disagreement_is_BROKEN(self):
        r = self._runner()
        v, cause, sem = r.verdict_neu({"id": "x", "witness": "ledger"},
                                      _obs(pg_exit=6, pg_codes=["x"]), None)
        self.assertEqual((v, cause), ("BROKEN", "internal_error"))
        self.assertFalse(sem["decisionEquivalent"])

    # ---- P1.2: fail-closed, non-vacuous differential ----
    def test_missing_equivalence_report_is_BROKEN_not_faithful(self):
        r = self._runner()
        v, cause, _ = r.verdict_neu({"id": "x", "witness": "ledger"}, _obs(eq_valid=False), None)
        self.assertEqual(v, "BROKEN")

    def test_trace_not_ok_is_BROKEN(self):
        r = self._runner()
        v, _c, _ = r.verdict_neu({"id": "x", "witness": "ledger"}, _obs(eq_trace_ok=False), None)
        self.assertEqual(v, "BROKEN")

    def test_zero_executed_cases_is_BROKEN(self):
        r = self._runner()
        v, _c, _ = r.verdict_neu({"id": "x", "witness": "ledger"}, _obs(eq_executed_cases=0), None)
        self.assertEqual(v, "BROKEN")

    def test_nonzero_equiv_process_exit_is_BROKEN(self):
        # Blocker 2: a valid-looking report from a wrapper that then exits nonzero must NOT be FAITHFUL.
        r = self._runner()
        v, cause, sem = r.verdict_neu({"id": "x", "witness": "ledger"}, _obs(eq_exit=2), None)
        self.assertEqual((v, cause), ("BROKEN", "internal_error"))
        self.assertEqual(sem["differentialExit"], 2)

    # ---- P1.4: real compile adapters, fail-closed ----
    def test_compile_stage_failure_is_compile_failure(self):
        r = self._runner()
        v, cause, _ = r.verdict_neu({"id": "x", "witness": "ledger"},
                                    _obs(eq_backends={"solidity": "fail", "postgres": "pass"},
                                         eq_stages={"solidity": "compile", "postgres": ""}), None)
        self.assertEqual((v, cause), ("BROKEN", "compile_failure"))

    def test_runtime_stage_failure_is_distinct_cause(self):
        # Blocker 3: a backend that COMPILED then failed at execution maps to a distinct cause.
        r = self._runner()
        v, cause, sem = r.verdict_neu({"id": "x", "witness": "ledger"},
                                      _obs(eq_backends={"solidity": "fail", "postgres": "pass"},
                                           eq_stages={"solidity": "runtime", "postgres": ""}), None)
        self.assertEqual((v, cause), ("BROKEN", "substrate_protocol_limit"))
        self.assertEqual(sem["solidityStage"], "runtime")

    def test_skipped_compile_adapter_cannot_be_faithful(self):
        # the vacuity fix: without a live compile proof, FAITHFUL is not claimed.
        r = self._runner()
        v, cause, _ = r.verdict_neu({"id": "x", "witness": "ledger"},
                                    _obs(eq_backends={"solidity": "skip", "postgres": "skip"}), None)
        self.assertEqual((v, cause), ("BROKEN", "missing_required_tool"))

    def test_timeout_is_BROKEN_runtime_timeout(self):
        r = self._runner()
        v, cause, _ = r.verdict_neu({"id": "x", "witness": "ledger"}, _obs(timed_out=True), None)
        self.assertEqual((v, cause), ("BROKEN", "runtime_timeout"))

    # ---- FAITHFUL / SILENT ----
    def test_faithful_requires_full_proof(self):
        r = self._runner()
        self.assertEqual(r.verdict_neu({"id": "x", "witness": "ledger"}, _obs(), None)[:2],
                         ("FAITHFUL", "success"))

    def test_predicted_refusal_not_firing_is_SILENT(self):
        r = self._runner()
        self.assertEqual(r.verdict_neu({"id": "x", "witness": "refusal", "refusalCode": "k"}, _obs(), None)[:2],
                         ("SILENT", "semantic_mismatch"))

    def test_invisible_mutation_is_SILENT(self):
        r = self._runner()
        obs = _obs()
        v, cause, sem = r.verdict_neu({"id": "x", "witness": "ledger"}, obs, dict(obs))
        self.assertEqual((v, cause), ("SILENT", "semantic_mismatch"))
        self.assertFalse(sem["controlDivergent"])

    def test_diverging_control_is_FAITHFUL(self):
        r = self._runner()
        v, _c, sem = r.verdict_neu({"id": "x", "witness": "ledger"}, _obs(), _obs(sol_hash="b" * 64))
        self.assertEqual(v, "FAITHFUL")
        self.assertTrue(sem["controlDivergent"])

    # ---- verdict_binding ----
    def test_binding_enforced_faithful(self):
        r = self._runner()
        cell = {"id": "b", "covers": [["assurance", "A3"]], "locator": {"value": "A3"},
                "refusalCode": "kernel.attest.invalid_assurance"}
        obs = {"spec_path": "s", "spec_hash": _H, "valid_exit": 0, "located": True, "invalid_exit": 1,
               "invalid_codes": ["kernel.attest.invalid_assurance"],
               "refusalCode": "kernel.attest.invalid_assurance", "timed_out": False}
        v, cause, sem = r.verdict_binding(cell, obs)
        self.assertEqual((v, cause), ("FAITHFUL", "success"))
        self.assertTrue(sem["enforced"])

    def test_binding_unenforced_silent(self):
        r = self._runner()
        cell = {"id": "b", "covers": [["assurance", "A3"]], "locator": {"value": "A3"},
                "refusalCode": "kernel.attest.invalid_assurance"}
        obs = {"spec_path": "s", "spec_hash": _H, "valid_exit": 0, "located": True, "invalid_exit": 0,
               "invalid_codes": [], "refusalCode": "kernel.attest.invalid_assurance", "timed_out": False}
        self.assertEqual(r.verdict_binding(cell, obs)[:2], ("SILENT", "semantic_mismatch"))

    def test_binding_timeout_is_broken(self):
        r = self._runner()
        cell = {"id": "b", "covers": [["assurance", "A3"]], "locator": {"value": "A3"}, "refusalCode": "k"}
        obs = {"spec_path": "s", "spec_hash": _H, "valid_exit": 0, "located": True, "invalid_exit": 1,
               "invalid_codes": ["k"], "refusalCode": "k", "timed_out": True}
        self.assertEqual(r.verdict_binding(cell, obs)[:2], ("BROKEN", "runtime_timeout"))

    def test_every_generated_binding_witness_is_runner_supported(self):
        # : fast CI must fail before the main matrix crashes if gen_generalism_cells adds a new
        # binding witness class that run_generalism_matrix cannot realize.
        r = self._runner()
        m = json.load(open(os.path.join(REPO, "test", "generalism", "generalism-cells.manifest.json"),
                           encoding="utf-8"))
        self.assertEqual(r.binding_witness_contract_violations(m), [])
        bad = dict(m)
        bad["cells"] = list(m["cells"]) + [{"id": "bind:new", "kind": "binding", "witness": "new_kind"}]
        self.assertTrue(r.binding_witness_contract_violations(bad))

    def test_binding_consume_verdict_faithful_on_valid_delta(self):
        r = self._runner()
        cell = {"id": "bind:bind_min_assurance:A3", "covers": [["bind_min_assurance", "A3"]]}
        obs = {
            "spec_path": "s", "spec_hash": _H, "spec_version": "0.1.0",
            "participant": "EscrowAgent", "specField": "bindMinAssurance", "topologyField": "minAssurance",
            "cellValue": "A3", "controlValue": "A2",
            "cellTopologyValue": "A3", "controlTopologyValue": "A2",
            "expectedCellTopologyValue": "A3", "expectedControlTopologyValue": "A2",
            "cell_spec_exit": 0, "control_spec_exit": 0,
            "cellReport": {"ok": False, "diagnostics": [{"code": "NEU-2001"}]},
            "controlReport": {"ok": True, "diagnostics": []},
            "tamperedReport": {"ok": True, "diagnostics": []},
            "expected": {"ok": False, "code": "NEU-2001"},
            "controlExpected": {"ok": True},
            "producerError": None, "timed_out": False,
        }
        v, cause, sem = r.verdict_binding_consume(cell, obs)
        self.assertEqual((v, cause), ("FAITHFUL", "success"))
        self.assertTrue(sem["enforced"])

    def test_binding_consume_collapsed_adjacent_tier_is_broken(self):
        r = self._runner()
        cell = {"id": "bind:bind_min_assurance:A3", "covers": [["bind_min_assurance", "A3"]]}
        obs = {
            "spec_path": "s", "spec_hash": _H, "spec_version": "0.1.0",
            "participant": "EscrowAgent", "specField": "bindMinAssurance", "topologyField": "minAssurance",
            "cellValue": "A3", "controlValue": "A2",
            "cellTopologyValue": "A3", "controlTopologyValue": "A2",
            "expectedCellTopologyValue": "A3", "expectedControlTopologyValue": "A2",
            "cell_spec_exit": 0, "control_spec_exit": 0,
            # Broken consumer aliases A3 to A2, so the cell incorrectly passes.
            "cellReport": {"ok": True, "diagnostics": []},
            "controlReport": {"ok": True, "diagnostics": []},
            "tamperedReport": {"ok": True, "diagnostics": []},
            "expected": {"ok": False, "code": "NEU-2001"},
            "controlExpected": {"ok": True},
            "producerError": None, "timed_out": False,
        }
        self.assertEqual(r.verdict_binding_consume(cell, obs)[:2], ("BROKEN", "internal_error"))

    def test_observer_set_consume_verdict_faithful_on_valid_delta(self):
        r = self._runner()
        cell = {"id": "bind:assurance:A4", "covers": [["assurance", "A4"]]}
        obs = {
            "spec_path": "s", "spec_hash": _H, "spec_version": "0.1.0",
            "observerSet": "customs_oracles", "specField": "assurance", "bindingField": "assurance",
            "cellValue": "A4", "controlValue": "A3",
            "cellSpecValue": "A4", "controlSpecValue": "A3",
            "cellBindingValue": "A4", "tamperedBindingValue": "A3",
            "cell_spec_exit": 0, "control_spec_exit": 0,
            "cellReport": {"ok": True, "diagnostics": []},
            "controlReport": {"ok": False, "diagnostics": [{"code": "binding.observer_assurance_mismatch"}]},
            "tamperedReport": {"ok": False, "diagnostics": [{"code": "binding.observer_assurance_mismatch"}]},
            "mismatchCode": "binding.observer_assurance_mismatch",
            "producerError": None, "timed_out": False,
        }
        v, cause, sem = r.verdict_binding_consume(cell, obs)
        self.assertEqual((v, cause), ("FAITHFUL", "success"))
        self.assertTrue(sem["enforced"])

    def test_observer_set_consume_ignored_binding_tamper_is_silent(self):
        r = self._runner()
        cell = {"id": "bind:independence:correlated", "covers": [["independence", "correlated"]]}
        obs = {
            "spec_path": "s", "spec_hash": _H, "spec_version": "0.1.0",
            "observerSet": "customs_oracles", "specField": "independence", "bindingField": "independence",
            "cellValue": "correlated", "controlValue": "independent",
            "cellSpecValue": "correlated", "controlSpecValue": "independent",
            "cellBindingValue": "correlated", "tamperedBindingValue": "independent",
            "cell_spec_exit": 0, "control_spec_exit": 0,
            "cellReport": {"ok": True, "diagnostics": []},
            "controlReport": {"ok": False, "diagnostics": [{"code": "binding.observer_independence_mismatch"}]},
            # Broken consumer ignores the binding-side tamper and still accepts.
            "tamperedReport": {"ok": True, "diagnostics": []},
            "mismatchCode": "binding.observer_independence_mismatch",
            "producerError": None, "timed_out": False,
        }
        self.assertEqual(r.verdict_binding_consume(cell, obs)[:2], ("SILENT", "semantic_mismatch"))

    def test_observer_set_consume_wrong_tamper_code_is_broken(self):
        r = self._runner()
        cell = {"id": "bind:assurance:A4", "covers": [["assurance", "A4"]]}
        obs = {
            "spec_path": "s", "spec_hash": _H, "spec_version": "0.1.0",
            "observerSet": "customs_oracles", "specField": "assurance", "bindingField": "assurance",
            "cellValue": "A4", "controlValue": "A3",
            "cellSpecValue": "A4", "controlSpecValue": "A3",
            "cellBindingValue": "A4", "tamperedBindingValue": "A3",
            "cell_spec_exit": 0, "control_spec_exit": 0,
            "cellReport": {"ok": True, "diagnostics": []},
            "controlReport": {"ok": False, "diagnostics": [{"code": "binding.observer_assurance_mismatch"}]},
            "tamperedReport": {"ok": False, "diagnostics": [{"code": "binding.schema"}]},
            "mismatchCode": "binding.observer_assurance_mismatch",
            "producerError": None, "timed_out": False,
        }
        self.assertEqual(r.verdict_binding_consume(cell, obs)[:2], ("BROKEN", "internal_error"))

    def test_terminal_kind_consume_verdict_faithful_on_valid_delta(self):
        r = self._runner()
        cell = {"id": "bind:terminal_kind:contested", "covers": [["terminal_kind", "contested"]]}
        obs = {
            "spec_path": "s", "spec_hash": _H, "spec_version": "0.1.0",
            "state": "CONTESTED", "terminalStateField": "contested",
            "tamperState": "CLOSED",
            "terminalStateRef": "CONTESTED", "tamperedTerminalStateRef": "CLOSED",
            "specField": "terminalKind",
            "cellValue": "contested", "controlValue": "success",
            "cellSpecValue": "contested", "controlSpecValue": "success",
            "tamperedSpecValue": "contested",
            "cell_spec_exit": 0, "cell_spec_codes": [],
            "control_spec_exit": 1, "control_spec_codes": ["spec.bad_terminal_state"],
            "tampered_spec_exit": 1, "tampered_spec_codes": ["spec.bad_terminal_state"],
            "cellIdentityRebuilt": True, "controlIdentityRebuilt": True,
            "tamperedIdentityRebuilt": True,
            "controlSpecHash": "1" * 64, "tamperedSpecHash": "2" * 64,
            "mismatchCode": "spec.bad_terminal_state",
            "producerError": None, "timed_out": False,
        }
        v, cause, sem = r.verdict_binding_consume(cell, obs)
        self.assertEqual((v, cause), ("FAITHFUL", "success"))
        self.assertTrue(sem["enforced"])

    def test_terminal_kind_consume_wrong_mismatch_code_is_broken(self):
        r = self._runner()
        cell = {"id": "bind:terminal_kind:success", "covers": [["terminal_kind", "success"]]}
        obs = {
            "spec_path": "s", "spec_hash": _H, "spec_version": "0.1.0",
            "state": "CLOSED", "terminalStateField": "success",
            "tamperState": "REJECTED",
            "terminalStateRef": "CLOSED", "tamperedTerminalStateRef": "REJECTED",
            "specField": "terminalKind",
            "cellValue": "success", "controlValue": "aborted",
            "cellSpecValue": "success", "controlSpecValue": "aborted",
            "tamperedSpecValue": "success",
            "cell_spec_exit": 0, "cell_spec_codes": [],
            "control_spec_exit": 1, "control_spec_codes": ["spec.schema"],
            "tampered_spec_exit": 1, "tampered_spec_codes": ["spec.bad_terminal_state"],
            "cellIdentityRebuilt": True, "controlIdentityRebuilt": True,
            "tamperedIdentityRebuilt": True,
            "controlSpecHash": "1" * 64, "tamperedSpecHash": "2" * 64,
            "mismatchCode": "spec.bad_terminal_state",
            "producerError": None, "timed_out": False,
        }
        self.assertEqual(r.verdict_binding_consume(cell, obs)[:2], ("BROKEN", "internal_error"))

    def test_terminal_kind_consume_hash_mismatch_is_broken(self):
        r = self._runner()
        cell = {"id": "bind:terminal_kind:aborted", "covers": [["terminal_kind", "aborted"]]}
        obs = {
            "spec_path": "s", "spec_hash": _H, "spec_version": "0.1.0",
            "state": "REJECTED", "terminalStateField": "aborted",
            "tamperState": "CLOSED",
            "terminalStateRef": "REJECTED", "tamperedTerminalStateRef": "CLOSED",
            "specField": "terminalKind",
            "cellValue": "aborted", "controlValue": "success",
            "cellSpecValue": "aborted", "controlSpecValue": "success",
            "tamperedSpecValue": "aborted",
            "cell_spec_exit": 0, "cell_spec_codes": [],
            "control_spec_exit": 1,
            "control_spec_codes": ["spec.bad_terminal_state", "spec.hash_mismatch"],
            "tampered_spec_exit": 1, "tampered_spec_codes": ["spec.bad_terminal_state"],
            "cellIdentityRebuilt": True, "controlIdentityRebuilt": False,
            "tamperedIdentityRebuilt": True,
            "controlSpecHash": "1" * 64, "tamperedSpecHash": "2" * 64,
            "mismatchCode": "spec.bad_terminal_state",
            "producerError": None, "timed_out": False,
        }
        self.assertEqual(r.verdict_binding_consume(cell, obs)[:2], ("BROKEN", "internal_error"))

    def test_transition_idempotency_consume_verdict_faithful_on_coordination_plan_delta(self):
        r = self._runner()
        cell = {"id": "bind:idempotency:noop_on_identical",
                "covers": [["idempotency", "noop_on_identical"]]}
        obs = {
            "spec_path": "s", "spec_hash": _H, "spec_version": "0.1.0",
            "transition": "COMMIT", "specField": "idempotency",
            "cellValue": "noop_on_identical", "controlValue": "reject",
            "cellSpecValue": "noop_on_identical", "controlSpecValue": "reject",
            "cellCoordinationPlanValue": "noop_on_identical", "controlCoordinationPlanValue": "reject",
            "cell_spec_exit": 0, "cell_spec_codes": [],
            "control_spec_exit": 0, "control_spec_codes": [],
            "cellIdentityRebuilt": True, "controlIdentityRebuilt": True,
            "cellCoordinationPlanHash": "1" * 64, "controlCoordinationPlanHash": "2" * 64,
            "producerError": None, "timed_out": False,
        }
        v, cause, sem = r.verdict_binding_consume(cell, obs)
        self.assertEqual((v, cause), ("FAITHFUL", "success"))
        self.assertNotIn("enforced", sem)

    def test_transition_idempotency_consume_same_coordination_plan_hash_is_silent(self):
        r = self._runner()
        cell = {"id": "bind:idempotency:reject", "covers": [["idempotency", "reject"]]}
        obs = {
            "spec_path": "s", "spec_hash": _H, "spec_version": "0.1.0",
            "transition": "COMMIT", "specField": "idempotency",
            "cellValue": "reject", "controlValue": "noop_on_identical",
            "cellSpecValue": "reject", "controlSpecValue": "noop_on_identical",
            "cellCoordinationPlanValue": "reject", "controlCoordinationPlanValue": "noop_on_identical",
            "cell_spec_exit": 0, "cell_spec_codes": [],
            "control_spec_exit": 0, "control_spec_codes": [],
            "cellIdentityRebuilt": True, "controlIdentityRebuilt": True,
            "cellCoordinationPlanHash": "1" * 64, "controlCoordinationPlanHash": "1" * 64,
            "producerError": None, "timed_out": False,
        }
        self.assertEqual(r.verdict_binding_consume(cell, obs)[:2], ("SILENT", "semantic_mismatch"))

    def test_transition_idempotency_consume_stale_identity_is_broken(self):
        r = self._runner()
        cell = {"id": "bind:idempotency:reject", "covers": [["idempotency", "reject"]]}
        obs = {
            "spec_path": "s", "spec_hash": _H, "spec_version": "0.1.0",
            "transition": "COMMIT", "specField": "idempotency",
            "cellValue": "reject", "controlValue": "noop_on_identical",
            "cellSpecValue": "reject", "controlSpecValue": "noop_on_identical",
            "cellCoordinationPlanValue": "reject", "controlCoordinationPlanValue": "noop_on_identical",
            "cell_spec_exit": 0, "cell_spec_codes": [],
            "control_spec_exit": 0, "control_spec_codes": [],
            "cellIdentityRebuilt": False, "controlIdentityRebuilt": True,
            "cellCoordinationPlanHash": "1" * 64, "controlCoordinationPlanHash": "2" * 64,
            "producerError": None, "timed_out": False,
        }
        self.assertEqual(r.verdict_binding_consume(cell, obs)[:2], ("BROKEN", "internal_error"))

    def test_transition_effect_consume_verdict_faithful_on_coordination_plan_delta(self):
        r = self._runner()
        cell = {"id": "bind:transition_effect:reserve",
                "covers": [["transition_effect", "reserve"]]}
        obs = {
            "spec_path": "s", "spec_hash": _H, "spec_version": "0.1.0",
            "transition": "COMMIT", "specField": "effects",
            "cellValue": ["reserve"], "controlValue": ["post"],
            "cellSpecValue": ["reserve"], "controlSpecValue": ["post"],
            "cellCoordinationPlanValue": ["reserve"], "controlCoordinationPlanValue": ["post"],
            "cell_spec_exit": 0, "cell_spec_codes": [],
            "control_spec_exit": 0, "control_spec_codes": [],
            "cellIdentityRebuilt": True, "controlIdentityRebuilt": True,
            "cellCoordinationPlanHash": "1" * 64,
            "controlCoordinationPlanHash": "2" * 64,
            "producerError": None, "timed_out": False,
        }
        self.assertEqual(r.verdict_binding_consume(cell, obs)[:2], ("FAITHFUL", "success"))

    def test_transition_guard_consume_verdict_requires_both_independent_tampers(self):
        r = self._runner()
        cell = {"id": "bind:transition_guard:participant",
                "covers": [["transition_guard", "participant"]]}
        obs = {
            "spec_path": "s", "spec_hash": _H, "spec_version": "0.1.0",
            "transition": "COMMIT", "guardDetail": "generalism-guard-kind",
            "specField": "guards", "cellValue": "participant", "controlValue": "sequence",
            "cellSpecValue": "participant", "controlSpecValue": "sequence",
            "producerTamperedSpecValue": None,
            "cellCoordinationPlanValue": "participant",
            "controlCoordinationPlanValue": "sequence",
            "consumerTamperedCoordinationPlanValue": None,
            "cell_spec_exit": 0, "cell_spec_codes": [],
            "control_spec_exit": 0, "control_spec_codes": [],
            "producer_tamper_exit": 1, "producer_tamper_codes": ["spec.schema"],
            "cellIdentityRebuilt": True, "controlIdentityRebuilt": True,
            "producerTamperedIdentityRebuilt": True,
            "cellCoordinationPlanHash": "1" * 64,
            "controlCoordinationPlanHash": "2" * 64,
            "consumerTamperedCoordinationPlanHash": "3" * 64,
            "producerError": None, "timed_out": False,
        }
        self.assertEqual(r.verdict_binding_consume(cell, obs)[:2], ("FAITHFUL", "success"))
        ignored = dict(obs, consumerTamperedCoordinationPlanValue="participant")
        self.assertEqual(r.verdict_binding_consume(cell, ignored)[:2],
                         ("SILENT", "semantic_mismatch"))

    def test_transition_evidence_consume_verdict_requires_style_tampers_and_preserves_chained(self):
        r = self._runner()
        cell = {"id": "bind:evidence_style:single_hash",
                "covers": [["evidence_style", "single_hash"]]}
        obs = {
            "spec_path": "s", "spec_hash": _H, "spec_version": "0.1.0",
            "transition": "COMMIT", "specField": "evidence", "evidenceChained": True,
            "cellValue": "single_hash", "controlValue": "batched_root",
            "cellSpecValue": "single_hash", "controlSpecValue": "batched_root",
            "producerTamperedSpecValue": None,
            "cellSpecChained": True, "controlSpecChained": True,
            "cellCoordinationPlanValue": "single_hash",
            "controlCoordinationPlanValue": "batched_root",
            "consumerTamperedCoordinationPlanValue": None,
            "cellCoordinationPlanChained": True,
            "controlCoordinationPlanChained": True,
            "consumerTamperedCoordinationPlanChained": True,
            "cell_spec_exit": 0, "cell_spec_codes": [],
            "control_spec_exit": 0, "control_spec_codes": [],
            "producer_tamper_exit": 1, "producer_tamper_codes": ["spec.schema"],
            "cellIdentityRebuilt": True, "controlIdentityRebuilt": True,
            "producerTamperedIdentityRebuilt": True,
            "cellCoordinationPlanHash": "1" * 64,
            "controlCoordinationPlanHash": "2" * 64,
            "consumerTamperedCoordinationPlanHash": "3" * 64,
            "producerError": None, "timed_out": False,
        }
        self.assertEqual(r.verdict_binding_consume(cell, obs)[:2], ("FAITHFUL", "success"))
        ignored = dict(obs, consumerTamperedCoordinationPlanValue="single_hash")
        self.assertEqual(r.verdict_binding_consume(cell, ignored)[:2],
                         ("SILENT", "semantic_mismatch"))
        conflated = dict(obs, controlCoordinationPlanChained=False)
        self.assertEqual(r.verdict_binding_consume(cell, conflated)[:2],
                         ("SILENT", "semantic_mismatch"))

    # ---- adapters ----
    def test_neu_adapters_reflect_compile_status(self):
        r = self._runner()
        ran = {a["adapterId"]: a["status"] for a in r.neu_adapters(_obs())}
        self.assertEqual(ran["solidity-compile"], "RAN")
        self.assertEqual(ran["postgres-compile"], "RAN")
        skipped = {a["adapterId"]: a["status"] for a in
                   r.neu_adapters(_obs(eq_backends={"solidity": "skip", "postgres": "skip"}))}
        self.assertEqual(skipped["solidity-compile"], "SKIPPED")
        self.assertEqual(skipped["postgres-compile"], "SKIPPED")

    # ---- execution identity ----
    def test_binding_cells_on_same_spec_collapse(self):
        r = self._runner()
        spec = "test/ir/security/Inputs/core_multi_pair_role/generated/capability-spec/capability-spec.json"
        obs = {"spec_hash": _H}
        ad = r.binding_adapters()
        k1 = r.envelope_identity({"kind": "binding", "spec": spec, "locator": {"value": "fixed"}},
                                 "binding", obs, "p", ad)[0]
        k2 = r.envelope_identity({"kind": "binding", "spec": spec, "locator": {"value": "success"}},
                                 "binding", obs, "p", ad)[0]
        self.assertEqual(k1, k2)

    def test_binding_identity_uses_spec_procedure_not_domains_path(self):
        r = self._runner()
        cell = {"id": "bind:terminal_kind:success", "kind": "binding",
                "spec": "test/generalism/fixtures/terminal_kind.capability-spec.json",
                "locator": {"value": "success"}}
        obs = {"spec_hash": _H}
        _key, cap_id, source_hash, spec_hash, scenario_hash = r.envelope_identity(
            cell, "binding", obs, "p", r.binding_adapters())
        self.assertEqual(cap_id, "coordinate.core_multi_pair_role")
        self.assertEqual(source_hash, _H)
        self.assertEqual(spec_hash, _H)
        self.assertEqual(scenario_hash, "0" * 64)

    def test_neu_specHash_is_the_canonical_spec_not_solidity(self):
        # P1.5: specHash comes from the canonical capability-spec (waist_hash), never the .sol artifact.
        r = self._runner()
        neu = "procedure p {\n    trigger settlement\n}\n"
        cell = {"kind": "seed", "input": {"neu": neu},
                "scenario": {"scenario": "p", "procedure": "p", "inputs": {"amount": 100}}}
        obs = _obs(waist_hash="c" * 64, sol_hash="d" * 64)
        _key, _cap, _src, spec_hash, _scn = r.envelope_identity(cell, "seed", obs, "p", r.neu_adapters(obs))
        self.assertEqual(spec_hash, "c" * 64)
        self.assertNotEqual(spec_hash, obs["sol_hash"])

    # ---- P1.1: refused cells still have non-empty artifactHashes ----
    def test_refused_cell_artifact_hashes_non_empty(self):
        r = self._runner()
        ah = r.neu_artifact_hashes(_obs(spec_hash=None, waist_hash="e" * 64, sol_hash=None, pg_hash=None))
        self.assertTrue(ah, "a waist-refused cell must still carry a non-empty artifactHashes")
        self.assertIn("waist-refusal-diagnostics", ah)

    # ---- envelope: non-vacuous PASS + structural shape (evidence checked separately below) ----
    def test_built_faithful_envelope_non_evidence_shape(self):
        r, val = self._runner(), self._validator()
        obs = _obs()
        cases = [r.cell_case({"id": "cellA"}, "FAITHFUL", "success", {"cellId": "cellA"})]
        env = r.build_envelope("coordinate.demo", "1.0.0", _H, _H, _H,
                               r.neu_artifact_hashes(obs), cases, _PROV, r.neu_adapters(obs), _SP)
        diags = [d for d in val.validate_shape(env) + val.validate_invariants(env)
                 if not str(d.get("path", "")).startswith("$.evidence")]
        self.assertEqual(diags, [], f"non-evidence structure must be valid: {diags}")
        self.assertEqual(env["summary"]["profileStatus"], "PASS")

    def test_real_per_run_evidence_fully_validates(self):
        # Blocker 1: genuine per-run evidence, signed + verified through the pinned build-tools verifier,
        # makes an envelope pass the UNMODIFIED validator — no evidence exception. Guarded on the
        # verifier being provisioned (.ci/neutrino-build-tools; provided in CI, `make setup-...` locally).
        import shutil
        r, val = self._runner(), self._validator()
        m4 = r._m4_dir()
        if not m4:
            self.skipTest("build-tools verifier not provisioned (.ci/neutrino-build-tools)")
        os.environ["NEUTRINO_BUILD_TOOLS_GENERALISM_REPORT_CLI"] = os.path.join(
            m4, "generalism_verification_report.py")
        os.environ["NEUTRINO_BUILD_TOOLS_GENERALISM_REPORT_REVISION"] = r.BUILD_TOOLS_REVISION
        obs = _obs()
        cases = [r.cell_case({"id": "cellA"}, "FAITHFUL", "success",
                             {"cellId": "cellA", "solidityDecision": "accepted",
                              "postgresDecision": "accepted", "decisionEquivalent": True})]
        env = r.build_envelope("coordinate.demo", "1.0.0", _H, _H, _H,
                               r.neu_artifact_hashes(obs), cases, _PROV, r.neu_adapters(obs), _SP)
        outdir = os.path.join(REPO, "test", "generalism", "results", "_fasttest")
        os.makedirs(outdir, exist_ok=True)
        try:
            env["evidence"] = r.build_run_evidence(os.path.join(outdir, "result-fasttest"),
                                                   "coordinate.demo", "1.0.0", env["cases"],
                                                   env["summary"]["profileStatus"],
                                                   r.result_identity_digest(env))
            self.assertIsNotNone(env["evidence"])
            diags = val.validate_shape(env) + val.validate_invariants(env)
            self.assertEqual(diags, [], f"real-evidence envelope must fully validate: {diags}")

            # P1.1 negative: graft a SECOND envelope's intact, internally-valid evidence onto
            # this one — the result-identity binding must fail closed.
            cases2 = [r.cell_case({"id": "cellB"}, "REFUSED", "governed_refusal",
                                  {"cellId": "cellB", "solidityDecision": "refused",
                                   "postgresDecision": "refused", "decisionEquivalent": True})]
            env2 = r.build_envelope("coordinate.other", "2.0.0", _H, _H, _H,
                                    r.neu_artifact_hashes(obs), cases2, _PROV, r.neu_adapters(obs), _SP)
            env2["evidence"] = r.build_run_evidence(os.path.join(outdir, "result-other"),
                                                    "coordinate.other", "2.0.0", env2["cases"],
                                                    env2["summary"]["profileStatus"],
                                                    r.result_identity_digest(env2))
            grafted = dict(env)
            grafted["evidence"] = env2["evidence"]
            diags2 = val.validate_shape(grafted) + val.validate_invariants(grafted)
            self.assertTrue(any(d.get("code") == "generalism.evidence_binding" for d in diags2),
                            f"grafted evidence must fail the binding check: {diags2}")
        finally:
            shutil.rmtree(outdir, ignore_errors=True)

    def test_skipped_compile_makes_broken_case_and_fail_profile(self):
        # compile adapters are schema-OPTIONAL (skippable), but a skipped compile yields a BROKEN case,
        # so the profile still cannot PASS (non-vacuity is enforced at the verdict level).
        r, val = self._runner(), self._validator()
        obs = _obs(eq_backends={"solidity": "skip", "postgres": "skip"})
        cases = [r.cell_case({"id": "c"}, "BROKEN", "missing_required_tool", {"cellId": "c"})]
        env = r.build_envelope("coordinate.demo", "1.0.0", _H, _H, _H,
                               r.neu_artifact_hashes(obs), cases, _PROV, r.neu_adapters(obs), _SP)
        self.assertEqual(env["summary"]["profileStatus"], "FAIL")
        # the envelope is still schema-VALID (an optional adapter may be skipped).
        diags = [d for d in val.validate_shape(env) + val.validate_invariants(env)
                 if not str(d.get("path", "")).startswith("$.evidence")]
        self.assertEqual(diags, [], f"a skipped OPTIONAL compile adapter must stay valid: {diags}")

    def test_all_refused_envelope_is_non_vacuous_pass(self):
        # an envelope of governed REFUSED cases (adapters ran) is an honest PASS.
        r = self._runner()
        obs = _obs()
        cases = [r.cell_case({"id": "c"}, "REFUSED", "governed_refusal", {"cellId": "c"})]
        env = r.build_envelope("coordinate.demo", "1.0.0", _H, _H, _H,
                               r.neu_artifact_hashes(obs), cases, _PROV, r.neu_adapters(obs), _SP)
        self.assertEqual(env["summary"]["profileStatus"], "PASS")

    def test_aggregate_verdict_precedence(self):
        r = self._runner()
        self.assertEqual(r.aggregate_verdict({"BROKEN": 1, "FAITHFUL": 5}), "BROKEN")
        self.assertEqual(r.aggregate_verdict({"SILENT": 1, "FAITHFUL": 5}), "SILENT")
        self.assertEqual(r.aggregate_verdict({"FAITHFUL": 1, "REFUSED": 5}), "FAITHFUL")
        self.assertEqual(r.aggregate_verdict({"REFUSED": 3}), "REFUSED")

    def test_real_versions_not_hardcoded(self):
        # Blocker 4: capability.version + semanticProfile come from the binary/spec, not a hardcode.
        r = self._runner()
        self.assertEqual(r._neu_version('procedure p {\n  version "2.3.4"\n}\n'), "2.3.4")
        cases = [r.cell_case({"id": "c"}, "FAITHFUL", "success", {"cellId": "c"})]
        env = r.build_envelope("coordinate.demo", "7.7.7", _H, _H, _H,
                               r.neu_artifact_hashes(_obs()), cases, _PROV, r.neu_adapters(_obs()), _SP)
        self.assertEqual(env["capability"]["version"], "7.7.7")
        self.assertEqual(env["semanticProfile"], _SP)
        self.assertNotEqual(env["semanticProfile"]["version"], "1.0.0")

    def test_target_profiles_retained_in_observation(self):
        r = self._runner()
        _v, _c, sem = r.verdict_neu({"id": "x", "witness": "ledger"}, _obs(), None)
        self.assertEqual(sem["targetProfiles"], [("solidity", "target.evm.v1", 3)])
        self.assertEqual(sem["specVersion"], "1.0.0")

    _FULL_VERSION_JSON = ('{"toolVersion":"0.2.0","gitSha":"abc123def456","capabilitySpecVersion":"v1",'
                          '"semanticProfileVersion":3,"semanticLanguageVersion":"0.1.0"}')
    _TARGET_PROFILES_V3 = ('[{"target":"solidity","id":"target.evm.v1","version":3},'
                           '{"target":"postgres","id":"target.postgres.v1","version":3}]')

    def _fake_bindir(self, tag, version_json=None, target_profiles=None):
        """A bindir whose neutrino-translate/-gen fakes emit the given --version-json / --target-profiles
        (defaults are complete + valid), for exercising build_provenance without the real binaries."""
        import stat
        import shutil
        d = os.path.join(REPO, "test", "generalism", "results", "_prov_" + tag)
        os.makedirs(d, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))
        outputs = {"neutrino-translate": version_json if version_json is not None else self._FULL_VERSION_JSON,
                   "neutrino-gen": target_profiles if target_profiles is not None else self._TARGET_PROFILES_V3}
        for name, payload in outputs.items():
            p = os.path.join(d, name)
            with open(p, "w") as fh:
                fh.write("#!/bin/sh\ncat <<'JSONEOF'\n" + payload + "\nJSONEOF\n")
            os.chmod(p, os.stat(p).st_mode | stat.S_IEXEC)
        return d

    def test_target_profiles_pin_identity_including_refused_cells(self):
        # P1.3: the AUTHORITATIVE target profiles (neutrino-gen --target-profiles) are folded into
        # provenance, so a target-profile VERSION change splits the identity of a REFUSED cell too.
        r = self._runner()
        v4 = self._TARGET_PROFILES_V3.replace('"version":3', '"version":4')
        _p3, h3, _v3, _s3 = r.build_provenance(self._fake_bindir("tp3"))
        _p4, h4, _v4, _s4 = r.build_provenance(self._fake_bindir("tp4", target_profiles=v4))
        self.assertNotEqual(h3, h4, "a target-profile version change must change the provenance hash")
        refused = {"kind": "seed", "input": {"neu": "procedure p {\n}\n"},
                   "scenario": {"scenario": "p", "procedure": "p", "inputs": {}}}
        obs = _obs(waist_hash="e" * 64)  # a waist-refused cell: no per-cell equiv target profiles
        k3 = r.envelope_identity(refused, "seed", obs, h3, r.neu_adapters(obs))[0]
        k4 = r.envelope_identity(refused, "seed", obs, h4, r.neu_adapters(obs))[0]
        self.assertNotEqual(k3, k4, "the refused-cell identity must split on a target-profile change")

    def test_validate_skips_without_build_tools(self):
        # CTest SKIP contract: --validate without a provisioned build-tools verifier exits the skip
        # code (77), not a failure — so a plain `make test` / unprovisioned workflow skips, and the
        # build-test tier that provisions the verifier does the real validation.
        import sys as _sys
        r = self._runner()
        orig, old_argv = r._m4_dir, _sys.argv
        r._m4_dir = lambda: None
        _sys.argv = ["run_generalism_matrix.py", "--validate", "--bindir", "/nonexistent"]
        try:
            self.assertEqual(r.main(), 77)
        finally:
            r._m4_dir, _sys.argv = orig, old_argv

    def test_version_json_failure_is_fail_closed(self):
        # P1.3: an incomplete --version-json aborts, never a defaulted v0/0.0.0 identity.
        r = self._runner()
        with self.assertRaises(SystemExit):
            r.build_provenance(self._fake_bindir("badver", version_json="{}"))

    def test_target_profiles_require_exactly_one_per_required_target(self):
        # P1.3: --target-profiles must carry EXACTLY ONE well-typed object per required rigid target;
        # anything else fails closed rather than claiming authoritative identity with a target unpinned.
        r = self._runner()
        sol = '{"target":"solidity","id":"target.evm.v1","version":3}'
        pg = '{"target":"postgres","id":"target.postgres.v1","version":3}'
        bad = {
            "empty": "[]",
            "solidity_only": f"[{sol}]",                      # missing postgres
            "duplicate": f"[{sol},{sol},{pg}]",               # duplicate solidity
            "unknown_target": f'[{sol},{pg},{{"target":"slot","id":"x","version":1}}]',
            "non_object_entry": f"[{sol},{pg},42]",           # must not crash on .get()
            "string_version": f'[{{"target":"solidity","id":"target.evm.v1","version":"3"}},{pg}]',
            "missing_id": f'[{{"target":"solidity","id":"","version":3}},{pg}]',
            "not_a_list": '{"target":"solidity"}',
        }
        for tag, payload in bad.items():
            with self.assertRaises(SystemExit, msg=f"{tag} must fail closed"):
                r.build_provenance(self._fake_bindir("tp_" + tag, target_profiles=payload))
        # the well-formed both-target response succeeds.
        _p, _h, versions, _s = r.build_provenance(self._fake_bindir("tp_ok", target_profiles=f"[{sol},{pg}]"))
        self.assertEqual(versions["targetProfiles"],
                         [("postgres", "target.postgres.v1", 3), ("solidity", "target.evm.v1", 3)])

    def test_result_identity_digest_tracks_envelope_content(self):
        r = self._runner()
        base = {"capability": {"id": "c"}, "cases": [{"caseId": "a", "verdict": "FAITHFUL"}],
                "evidence": {"x": 1}}
        d1 = r.result_identity_digest(base)
        changed = {**base, "cases": [{"caseId": "a", "verdict": "REFUSED"}]}
        self.assertTrue(d1.startswith("sha256:"))
        self.assertNotEqual(d1, r.result_identity_digest(changed))
        # the evidence block itself is excluded (so it can reference this digest without a cycle).
        self.assertEqual(d1, r.result_identity_digest({**base, "evidence": {"y": 2}}))

    def test_profile_shape(self):
        # only the differential is a REQUIRED adapter (a required adapter may never skip); the live
        # compile adapters are OPTIONAL at the schema level but verdict-enforced for FAITHFUL.
        r = self._runner()
        self.assertEqual(r.PROFILE, "PR_FAST")
        self.assertEqual(r.REQUIRED_ADAPTERS, ["translator-differential"])
        self.assertIn("solidity-compile", r.OPTIONAL_ADAPTERS)
        self.assertIn("postgres-compile", r.OPTIONAL_ADAPTERS)


if __name__ == "__main__":
    unittest.main()

"""[fast] Backend-generalism cell manifest ( S1): the committed manifest is fresh vs the
capability-spec schema + Solidity classification + the 16 seed cells, and coverage is ratcheted — a
new derived feature with no covering cell and not banked in the baseline fails closed. Pure stdlib
(no build): the generator + gate read JSON only."""

import copy
import json
import os
import re
import unittest

from _fastcase import FastCase, REPO


def _proc_name(neu):
    m = re.search(r"procedure\s+(\S+)", neu)
    return m.group(1) if m else None


class GeneralismCells(FastCase):
    def test_coverage_gate_selftest(self):
        # FRESH + RATCHET + non-vacuous floors, against the committed manifest + baseline.
        self.val_ok("generalism cell coverage completeness ratchet",
                    "scripts/gates/check_generalism_cell_coverage.py", "--selftest")

    def test_crediting_cells_are_controlled_experiments(self):
        m = json.load(open(os.path.join(REPO, "test", "generalism", "generalism-cells.manifest.json"),
                           encoding="utf-8"))
        self.assertGreaterEqual(m["seedCount"], 16,
                                "the 16  hand-run regression cells must be seeded")
        # Every cell has a .neu, a materialized scenario, a witness in {ledger,refusal,render}, and no
        # expected-value field. A CREDITING cell must be a controlled experiment: exactly one covered
        # feature + a `control` (so --prove-witness can prove the feature CAUSES the difference); a
        # crediting refusal cell also needs a refusalCode. A SEED must NOT credit (regression fixture only)
        # — this is the  P1 fix (cell09/cell11 no longer credit boundary from unrelated refusals).
        counted = 0
        for c in m["cells"]:
            kind = c.get("kind")
            self.assertIn(c.get("witness"), ("ledger", "refusal", "render", "spec_refusal",
                                             "binding_consume"),
                          f"cell {c['id']} has no valid witness")
            for banned in ("expected", "expectedValue", "expect", "expectedLedger"):
                self.assertNotIn(banned, c, f"cell {c['id']} carries a forbidden expected-value field")
            if kind != "binding":   # .neu cells carry an inline source + materialized scenario
                self.assertTrue(c.get("input", {}).get("neu"), f"cell {c['id']} has no .neu input")
                self.assertEqual(c.get("scenario", {}).get("procedure"), _proc_name(c["input"]["neu"]),
                                 f"cell {c['id']} scenario procedure must match its .neu procedure")
            if c.get("credits"):
                counted += 1
                self.assertEqual(len(c.get("covers", [])), 1,
                                 f"crediting cell {c['id']} must credit exactly one feature")
                if kind == "binding":
                    # S1c crediting binding cell: bound to the closed valid_carry_and_consume proof table.
                    self.assertEqual(self._gen().binding_consume_proof_violations(c), [],
                                     f"binding cell {c['id']} is not bound to its closed consume proof")
                    self.assertEqual(c.get("consumeProof", {}).get("kind"), "valid_carry_and_consume",
                                     f"crediting binding cell {c['id']} lacks a consumeProof")
                else:
                    self.assertEqual(kind, "generated", f"crediting cell {c['id']} must be generated/binding")
                    self.assertTrue(c.get("mutation"), f"crediting cell {c['id']} has no typed mutation")
                    self.assertTrue(c.get("control"), f"crediting cell {c['id']} has no control")
                    # The control must reconstruct EXACTLY as apply(mutation, cell) — single-locus ( P1).
                    self.assertEqual(self._gen().control_reconstruction_violations(c), [],
                                     f"crediting cell {c['id']} control does not reconstruct from its mutation")
                    if c["witness"] == "refusal":
                        self.assertTrue(c.get("refusalCode"), f"crediting refusal {c['id']} has no refusalCode")
            elif kind == "seed":
                self.assertFalse(c.get("credits"), f"seed {c['id']} must not credit coverage")
            elif kind == "binding":
                # Non-crediting S1c binding cells are validator-contract fixtures (): a field-specific
                # validator refusal proves schema-RECOGNITION, not downstream CONSUMPTION.
                if c.get("refusalCode"):
                    self.assertEqual(self._gen().binding_locus_violations(c), [],
                                     f"binding cell {c['id']} is not bound to its canonical BINDING_LOCUS")
        self.assertEqual(counted, m["witnessedCellCount"], "witnessedCellCount must equal crediting cells")

    def test_binding_cells_proven_and_tamper_rejected(self):
        #  S1c: the binding/lifecycle cells witness against the real capability-spec validator, and a
        # RELABELED (wrong covers) or CONFOUNDED (wrong located value) binding cell fails closed.
        import copy
        g = self._gen()
        m = json.load(open(os.path.join(REPO, "test", "generalism", "generalism-cells.manifest.json"),
                           encoding="utf-8"))
        binding = [c for c in m["cells"] if c.get("kind") == "binding"]
        self.assertGreaterEqual(len(binding), 7, "S1c must witness the binding/lifecycle families")
        # Real proof: every committed binding cell holds against the validator.
        self.assertEqual(g.prove_binding(m, os.path.join(
            REPO, "scripts", "validators", "validate_capability_spec.py")), [],
            "committed binding cells must all be witnessed by the capability-spec validator")
        c = copy.deepcopy(binding[0])
        # RELABEL: credit a different feature than the locus enforces.
        other = next(k for k in g.BINDING_LOCUS if list(k) != c["covers"][0])
        relabel = copy.deepcopy(c); relabel["covers"] = [list(other)]
        self.assertTrue(g.binding_locus_violations(relabel),
                        "a binding cell crediting a feature it does not enforce must be flagged (relabeled)")
        # CONFOUND: point the locator at a value the spec does not carry -> the carry proof fails.
        confound = copy.deepcopy(c); confound["locator"] = dict(c["locator"], value="__nope__")
        # (also relabel BINDING_LOCUS-side by mutating the cell's declared locator so it self-inconsistent)
        self.assertTrue(g.binding_locus_violations(confound) or g.prove_binding(
            {"cells": [confound]}, os.path.join(REPO, "scripts", "validators",
                                                "validate_capability_spec.py")),
            "a binding cell whose located value is absent must fail (confounded/drifted)")

    def test_binding_lifecycle_disposition_ledger_is_complete_and_credits_only_proven_rows(self):
        #  tightened acceptance: the S1c inventory is per derived row, not per field family. The ledger
        # must account for every row without shrinking coverage from invalid-schema validator checks.
        import copy
        g = self._gen()
        m = json.load(open(os.path.join(REPO, "test", "generalism", "generalism-cells.manifest.json"),
                           encoding="utf-8"))
        dispositions = m.get("bindingLifecycleDispositions", [])
        self.assertEqual(len(dispositions), 28, "the  ledger must cover all 28 derived S1c rows")
        self.assertEqual(g.binding_lifecycle_disposition_violations(m), [],
                         "committed  disposition ledger must validate")
        crediting = [d for d in dispositions if d.get("creditsCoverage") is True]
        self.assertEqual(
            sorted((d["family"], d["value"]) for d in crediting),
            [("assurance", "A1"), ("assurance", "A2"), ("assurance", "A3"), ("assurance", "A4"),
             ("bind_min_assurance", ""), ("bind_min_assurance", "A1"),
             ("bind_min_assurance", "A2"), ("bind_min_assurance", "A3"),
             ("bind_min_assurance", "A4"), ("evidence_style", "batched_root"),
             ("evidence_style", "single_hash"), ("idempotency", "noop_on_identical"),
             ("idempotency", "reject"), ("independence", "correlated"),
             ("independence", "independent"),
             ("participant_binding", "fixed"),
	             ("participant_binding", "to_be_bound"),
	             ("terminal_kind", "aborted"), ("terminal_kind", "contested"),
	             ("terminal_kind", "success"),
	             ("transition_effect", "compensate"), ("transition_effect", "consume"),
	             ("transition_effect", "post"), ("transition_effect", "release"),
	             ("transition_effect", "reserve"), ("transition_guard", "deadline"),
	             ("transition_guard", "participant"), ("transition_guard", "sequence")],
	            " dispositions may credit only rows with valid carry-and-consume proof")
        self.assertTrue(all(d.get("status") == "valid_carry_and_consume" for d in crediting),
                        "crediting  dispositions must name the valid_carry_and_consume status")
        self.assertEqual(
            sum(1 for d in dispositions if d.get("status") == "validator_contract"),
            len([key for key in g.BINDING_LOCUS if key not in g.BINDING_CONSUME_PROOFS]),
            "validator-contract dispositions must be exactly the remaining non-crediting BINDING_LOCUS cells")

        missing = copy.deepcopy(m)
        missing["bindingLifecycleDispositions"] = missing["bindingLifecycleDispositions"][:-1]
        self.assertTrue(g.binding_lifecycle_disposition_violations(missing),
                        "dropping a derived S1c row from the disposition ledger must fail closed")

        extra = copy.deepcopy(m)
        extra["bindingLifecycleDispositions"].append({
            "family": "not_a_binding_family", "value": "x", "status": "blocked",
            "creditsCoverage": False, "blockingIssue": "neutrino-",
            "requiredProof": "valid_carry_and_consume", "reason": "negative test",
        })
        self.assertTrue(g.binding_lifecycle_disposition_violations(extra),
                        "a disposition for a non-derived row must fail closed")

        credit = copy.deepcopy(m)
        self.assertFalse(
            [d for d in credit["bindingLifecycleDispositions"]
             if d.get("status") == "validator_contract"],
            "all validator-contract  rows should be retired once transition_effect is credited")

    def test_participant_binding_consume_proof_is_non_vacuous(self):
        #  S1 participant_binding: credit requires an authoritative producer/consumer delta. The real
        # producer proof is CTest-native; this fast unit proves the Python harness itself rejects a producer
        # artifact that bypasses the carried binding value.
        g = self._gen()
        m = json.load(open(os.path.join(REPO, "test", "generalism", "generalism-cells.manifest.json"),
                           encoding="utf-8"))
        orig_render = g._render_slot_topology
        orig_spec = g._validate_spec
        orig_manifest = g._validate_binding_manifest

        def bypasses_binding(_renderer, _spec, _workdir, _label):
            proof = g.BINDING_CONSUME_PROOFS[("participant_binding", "fixed")]
            return {
                "kind": "neutrino.slot-binding-topology",
                "schemaVersion": 1,
                "capability": "coordinate.core_document_escrow",
                "capabilityVersion": "0.1.0",
                "procedure": "core_document_escrow",
                "organizations": [{
                    "organizationId": proof["manifest"]["binder"],
                    "participants": [{
                        "participantId": proof["participant"],
                        "role": "escrow",
                        "slots": [{
                            "slotId": f"coordinate.core_document_escrow#{proof['participant']}",
                            "lateBindingMode": "to_be_bound",
                            "allowedRuntimes": [proof["manifest"]["runtime"]],
                            "minAssurance": proof["manifest"]["assurance"],
                            "authorizedBinder": proof["manifest"]["binder"],
                            "evidenceProfile": None,
                        }],
                    }],
                }],
                "crossOrganization": True,
            }

        g._render_slot_topology = bypasses_binding
        g._validate_spec = lambda _validator, _spec, _workdir: (0, [])
        g._validate_binding_manifest = lambda _validator, _manifest, _topology, _workdir: (
            0, {"ok": True, "diagnostics": []})
        try:
            bad = g.prove_binding_consume(
                {"cells": [next(c for c in m["cells"] if c["id"] == "bind:participant_binding:fixed")]},
                os.path.join(REPO, "scripts", "generators", "gen_generalism_cells.py"),
                os.path.join(REPO, "scripts", "validators", "validate_binding_manifest.py"),
                os.path.join(REPO, "scripts", "validators", "validate_capability_spec.py"))
            self.assertTrue(bad and "did not carry participant_binding" in bad[0],
                            "bypassing the fixed binding value in producer output must fail")
        finally:
            g._render_slot_topology = orig_render
            g._validate_spec = orig_spec
            g._validate_binding_manifest = orig_manifest

    def test_bind_min_assurance_consume_proof_is_non_vacuous(self):
        #  S1 bind_min_assurance: the fast harness rejects a producer that does not carry the derived
        # minAssurance value. Empty bindMinAssurance explicitly maps to A1; higher rows must carry their
        # exact required assurance.
        g = self._gen()
        m = json.load(open(os.path.join(REPO, "test", "generalism", "generalism-cells.manifest.json"),
                           encoding="utf-8"))
        orig_render = g._render_slot_topology
        orig_spec = g._validate_spec
        orig_manifest = g._validate_binding_manifest

        def bypasses_min_assurance(_renderer, _spec, _workdir, _label):
            proof = g.BINDING_CONSUME_PROOFS[("bind_min_assurance", "A3")]
            return {
                "kind": "neutrino.slot-binding-topology",
                "schemaVersion": 1,
                "capability": "coordinate.core_document_escrow",
                "capabilityVersion": "0.1.0",
                "procedure": "core_document_escrow",
                "organizations": [{
                    "organizationId": proof["manifest"]["binder"],
                    "participants": [{
                        "participantId": proof["participant"],
                        "role": "escrow",
                        "slots": [{
                            "slotId": f"coordinate.core_document_escrow#{proof['participant']}",
                            "lateBindingMode": "to_be_bound",
                            "allowedRuntimes": [proof["manifest"]["runtime"]],
                            "minAssurance": "A1",
                            "authorizedBinder": proof["manifest"]["binder"],
                            "evidenceProfile": None,
                        }],
                    }],
                }],
                "crossOrganization": True,
            }

        g._render_slot_topology = bypasses_min_assurance
        g._validate_spec = lambda _validator, _spec, _workdir: (0, [])
        g._validate_binding_manifest = lambda _validator, _manifest, _topology, _workdir: (
            0, {"ok": True, "diagnostics": []})
        try:
            bad = g.prove_binding_consume(
                {"cells": [next(c for c in m["cells"] if c["id"] == "bind:bind_min_assurance:A3")]},
                os.path.join(REPO, "scripts", "generators", "gen_generalism_cells.py"),
                os.path.join(REPO, "scripts", "validators", "validate_binding_manifest.py"),
                os.path.join(REPO, "scripts", "validators", "validate_capability_spec.py"))
            self.assertTrue(bad and "did not carry bind_min_assurance" in bad[0],
                            "bypassing the minAssurance value in producer output must fail")
        finally:
            g._render_slot_topology = orig_render
            g._validate_spec = orig_spec
            g._validate_binding_manifest = orig_manifest

    def test_bind_min_assurance_adjacent_tier_collapse_is_rejected(self):
        #  per-row proof: A3/A4 must prove adjacent tier semantics, not merely "greater than A1".
        # Simulate a broken consumer that collapses A3 to A2. The A3 row must fail because its cell at
        # minAssurance=A3 with manifest=A2 would incorrectly pass.
        g = self._gen()
        m = json.load(open(os.path.join(REPO, "test", "generalism", "generalism-cells.manifest.json"),
                           encoding="utf-8"))
        orig_render = g._render_slot_topology
        orig_spec = g._validate_spec
        orig_manifest = g._validate_binding_manifest

        def topology_from_spec(_renderer, spec, _workdir, _label):
            proof = g.BINDING_CONSUME_PROOFS[("bind_min_assurance", "A3")]
            participant = next(p for p in spec["participants"] if p["name"] == proof["participant"])
            min_assurance = participant["bindMinAssurance"] or "A1"
            return {
                "kind": "neutrino.slot-binding-topology",
                "schemaVersion": 1,
                "capability": "coordinate.core_document_escrow",
                "capabilityVersion": "0.1.0",
                "procedure": "core_document_escrow",
                "organizations": [{
                    "organizationId": proof["manifest"]["binder"],
                    "participants": [{
                        "participantId": proof["participant"],
                        "role": "escrow",
                        "slots": [{
                            "slotId": f"coordinate.core_document_escrow#{proof['participant']}",
                            "lateBindingMode": "to_be_bound",
                            "allowedRuntimes": [proof["manifest"]["runtime"]],
                            "minAssurance": min_assurance,
                            "authorizedBinder": proof["manifest"]["binder"],
                            "evidenceProfile": None,
                        }],
                    }],
                }],
                "crossOrganization": True,
            }

        def collapsed_assurance_validator(_validator, manifest, topology, _workdir):
            ranks = {"A1": 1, "A2": 2, "A3": 2, "A4": 2}
            slot = topology["organizations"][0]["participants"][0]["slots"][0]
            got = manifest["bindings"][0]["assurance"]
            need = slot["minAssurance"]
            if ranks[got] < ranks[need]:
                return 5, {"ok": False, "diagnostics": [{"code": "NEU-2001"}]}
            return 0, {"ok": True, "diagnostics": []}

        g._render_slot_topology = topology_from_spec
        g._validate_spec = lambda _validator, _spec, _workdir: (0, [])
        g._validate_binding_manifest = collapsed_assurance_validator
        try:
            bad = g.prove_binding_consume(
                {"cells": [next(c for c in m["cells"] if c["id"] == "bind:bind_min_assurance:A3")]},
                os.path.join(REPO, "scripts", "generators", "gen_generalism_cells.py"),
                os.path.join(REPO, "scripts", "validators", "validate_binding_manifest.py"),
                os.path.join(REPO, "scripts", "validators", "validate_capability_spec.py"))
            self.assertTrue(bad and "cell consumer observation does not match expected" in bad[0],
                            "collapsing A3 to A2 must fail the adjacent-tier consume proof")
        finally:
            g._render_slot_topology = orig_render
            g._validate_spec = orig_spec
            g._validate_binding_manifest = orig_manifest

    def test_observer_set_consume_proof_rejects_spec_bypass(self):
        #  observerSet.assurance: credit requires the rebuilt capability-spec to carry the exact
        # observer-set value. A producer/helper that ignores the requested A4 and leaves A3 must fail.
        g = self._gen()
        m = json.load(open(os.path.join(REPO, "test", "generalism", "generalism-cells.manifest.json"),
                           encoding="utf-8"))
        orig_spec_with_field = g._spec_with_observer_set_field
        orig_validate_spec = g._validate_spec
        orig_validate_binding = g._validate_observation_binding

        def bypasses_observer_field(spec, ref, field, value):
            if value == "A4":
                return orig_spec_with_field(spec, ref, field, "A3")
            return orig_spec_with_field(spec, ref, field, value)

        g._spec_with_observer_set_field = bypasses_observer_field
        g._validate_spec = lambda _validator, _spec, _workdir: (0, [])
        g._validate_observation_binding = lambda _validator, _binding, _spec, _workdir: (
            0, {"ok": True, "diagnostics": []})
        try:
            bad = g.prove_binding_consume(
                {"cells": [next(c for c in m["cells"] if c["id"] == "bind:assurance:A4")]},
                os.path.join(REPO, "scripts", "generators", "gen_generalism_cells.py"),
                os.path.join(REPO, "scripts", "validators", "validate_binding_manifest.py"),
                os.path.join(REPO, "scripts", "validators", "validate_capability_spec.py"))
            self.assertTrue(bad and "cell spec did not carry assurance" in bad[0],
                            "bypassing observer-set assurance in the rebuilt spec must fail")
        finally:
            g._spec_with_observer_set_field = orig_spec_with_field
            g._validate_spec = orig_validate_spec
            g._validate_observation_binding = orig_validate_binding

    def test_observer_set_consume_proof_rejects_consumer_alias(self):
        #  observerSet.independence: if the observation-binding consumer accepts a mismatched valid
        # spec/binding pair, the proof is vacuous and must fail.
        g = self._gen()
        m = json.load(open(os.path.join(REPO, "test", "generalism", "generalism-cells.manifest.json"),
                           encoding="utf-8"))
        orig_validate_spec = g._validate_spec
        orig_validate_binding = g._validate_observation_binding
        g._validate_spec = lambda _validator, _spec, _workdir: (0, [])
        g._validate_observation_binding = lambda _validator, _binding, _spec, _workdir: (
            0, {"ok": True, "diagnostics": []})
        try:
            bad = g.prove_binding_consume(
                {"cells": [next(c for c in m["cells"] if c["id"] == "bind:independence:independent")]},
                os.path.join(REPO, "scripts", "generators", "gen_generalism_cells.py"),
                os.path.join(REPO, "scripts", "validators", "validate_binding_manifest.py"),
                os.path.join(REPO, "scripts", "validators", "validate_capability_spec.py"))
            self.assertTrue(bad and "control observation-binding consumer did not reject" in bad[0],
                            "accepting mismatched observer-set independence must fail")
        finally:
            g._validate_spec = orig_validate_spec
            g._validate_observation_binding = orig_validate_binding

    def test_terminal_kind_consume_proof_rejects_validator_bypass(self):
        #  terminalKind: credit requires a valid terminalStates->state mapping to be consumed by the
        # capability-spec validator. A consumer that accepts the valid control mismatch must fail.
        g = self._gen()
        m = json.load(open(os.path.join(REPO, "test", "generalism", "generalism-cells.manifest.json"),
                           encoding="utf-8"))
        orig_validate_spec = g._validate_spec
        g._validate_spec = lambda _validator, _spec, _workdir: (0, [])
        try:
            bad = g.prove_binding_consume(
                {"cells": [next(c for c in m["cells"] if c["id"] == "bind:terminal_kind:success")]},
                None,
                os.path.join(REPO, "scripts", "validators", "validate_binding_manifest.py"),
                os.path.join(REPO, "scripts", "validators", "validate_capability_spec.py"))
            self.assertTrue(bad and "control capability-spec consumer did not reject" in bad[0],
                            "accepting a terminalStates/terminalKind mismatch must fail")
        finally:
            g._validate_spec = orig_validate_spec

    def test_terminal_kind_consume_proof_rejects_wrong_mismatch_code(self):
        # The terminalKind consumer contract is the exact stable machine code. A generic schema refusal is
        # not enough to credit the row.
        g = self._gen()
        m = json.load(open(os.path.join(REPO, "test", "generalism", "generalism-cells.manifest.json"),
                           encoding="utf-8"))
        calls = {"n": 0}
        orig_validate_spec = g._validate_spec

        def wrong_code(_validator, _spec, _workdir):
            calls["n"] += 1
            if calls["n"] == 1:
                return 0, []
            return 1, [{"code": "spec.schema", "message": "generic refusal"}]

        g._validate_spec = wrong_code
        try:
            bad = g.prove_binding_consume(
                {"cells": [next(c for c in m["cells"] if c["id"] == "bind:terminal_kind:contested")]},
                None,
                os.path.join(REPO, "scripts", "validators", "validate_binding_manifest.py"),
                os.path.join(REPO, "scripts", "validators", "validate_capability_spec.py"))
            self.assertTrue(bad and "spec.bad_terminal_state" in bad[0],
                            "wrong diagnostic code must fail the terminalKind consume proof")
        finally:
            g._validate_spec = orig_validate_spec

    def test_terminal_kind_consume_proof_rejects_stale_identity(self):
        #  terminalKind: changing a schema-valid value without rebuilding capability/spec identity must
        # not receive credit just because spec.bad_terminal_state is also present.
        import copy
        g = self._gen()
        m = json.load(open(os.path.join(REPO, "test", "generalism", "generalism-cells.manifest.json"),
                           encoding="utf-8"))
        orig_state_field = g._spec_with_lifecycle_state_field

        def stale_identity(spec, state_name, field, value):
            out = copy.deepcopy(spec)
            s = g._lifecycle_state(out, state_name)
            if s is None:
                raise ValueError(f"lifecycle state {state_name!r} is missing")
            s[field] = value
            return out

        g._spec_with_lifecycle_state_field = stale_identity
        try:
            bad = g.prove_binding_consume(
                {"cells": [next(c for c in m["cells"] if c["id"] == "bind:terminal_kind:success")]},
                None,
                os.path.join(REPO, "scripts", "validators", "validate_binding_manifest.py"),
                os.path.join(REPO, "scripts", "validators", "validate_capability_spec.py"))
            self.assertTrue(bad and "identity was not rebuilt" in bad[0],
                            "stale capability/spec identity must fail the terminalKind consume proof")
        finally:
            g._spec_with_lifecycle_state_field = orig_state_field

    def test_idempotency_consume_proof_uses_coordination_coordination_plan_delta(self):
        #  idempotency: a schema-valid transition value must be carried into the normalized
        # coordination-plan from-spec consumer; valid cell/control values must produce different plan bytes.
        g = self._gen()
        m = json.load(open(os.path.join(REPO, "test", "generalism", "generalism-cells.manifest.json"),
                           encoding="utf-8"))
        cell = next(c for c in m["cells"] if c["id"] == "bind:idempotency:noop_on_identical")
        orig_validate_spec = g._validate_spec
        orig_render = g._render_coordination_plan

        def render(_neutrino_gen, spec, _workdir, _label):
            return {"lifecycleTransitions": [
                {"name": "COMMIT", "from": "PROPOSED", "to": "COMMITTED",
                 "idempotency": g._lifecycle_transition(spec, "COMMIT")["idempotency"]}
            ]}

        g._validate_spec = lambda _validator, _spec, _workdir: (0, [])
        g._render_coordination_plan = render
        try:
            bad = g.prove_binding_consume(
                {"cells": [cell]},
                None,
                os.path.join(REPO, "scripts", "validators", "validate_binding_manifest.py"),
                os.path.join(REPO, "scripts", "validators", "validate_capability_spec.py"),
                coordination_plan_renderer="/tmp/neutrino-gen")
            self.assertEqual(bad, [], "idempotency consume proof must accept a real coordination-plan delta")
        finally:
            g._validate_spec = orig_validate_spec
            g._render_coordination_plan = orig_render

    def test_idempotency_consume_proof_rejects_coordination_plan_consumer_alias(self):
        # If the coordination-plan consumer ignores transition idempotency, the proof must fail as vacuous.
        g = self._gen()
        m = json.load(open(os.path.join(REPO, "test", "generalism", "generalism-cells.manifest.json"),
                           encoding="utf-8"))
        cell = next(c for c in m["cells"] if c["id"] == "bind:idempotency:reject")
        orig_validate_spec = g._validate_spec
        orig_render = g._render_coordination_plan

        def ignored(_neutrino_gen, _spec, _workdir, _label):
            return {"lifecycleTransitions": [
                {"name": "COMMIT", "from": "PROPOSED", "to": "COMMITTED", "idempotency": "reject"}
            ]}

        g._validate_spec = lambda _validator, _spec, _workdir: (0, [])
        g._render_coordination_plan = ignored
        try:
            bad = g.prove_binding_consume(
                {"cells": [cell]},
                None,
                os.path.join(REPO, "scripts", "validators", "validate_binding_manifest.py"),
                os.path.join(REPO, "scripts", "validators", "validate_capability_spec.py"),
                coordination_plan_renderer="/tmp/neutrino-gen")
            self.assertTrue(bad and "coordination-plan control did not carry" in bad[0],
                            "ignoring transition idempotency must fail the consume proof")
        finally:
            g._validate_spec = orig_validate_spec
            g._render_coordination_plan = orig_render

    def test_transition_effect_consume_proof_uses_coordination_plan_delta(self):
        #  transition_effect: a schema-valid transition effects array must be carried into the
        # normalized coordination-plan from-spec consumer; valid cell/control values must produce
        # different coordination artifact bytes.
        g = self._gen()
        m = json.load(open(os.path.join(REPO, "test", "generalism", "generalism-cells.manifest.json"),
                           encoding="utf-8"))
        cell = next(c for c in m["cells"] if c["id"] == "bind:transition_effect:reserve")
        orig_validate_spec = g._validate_spec
        orig_render = g._render_coordination_plan

        def render(_neutrino_gen, spec, _workdir, _label):
            return {"lifecycleTransitions": [
                {"name": "COMMIT", "from": "PROPOSED", "to": "COMMITTED",
                 "effects": g._lifecycle_transition(spec, "COMMIT")["effects"],
                 "idempotency": "reject"}
            ]}

        g._validate_spec = lambda _validator, _spec, _workdir: (0, [])
        g._render_coordination_plan = render
        try:
            bad = g.prove_binding_consume(
                {"cells": [cell]},
                None,
                os.path.join(REPO, "scripts", "validators", "validate_binding_manifest.py"),
                os.path.join(REPO, "scripts", "validators", "validate_capability_spec.py"),
                coordination_plan_renderer="/tmp/neutrino-gen")
            self.assertEqual(bad, [], "transition_effect consume proof must accept a real coordination artifact delta")
        finally:
            g._validate_spec = orig_validate_spec
            g._render_coordination_plan = orig_render

    def test_transition_effect_consume_proof_has_no_pseudo_tamper_contract(self):
        #  transition_effect is proven by a valid cell/control coordination-plan byte delta.
        # There is no second tampered coordination-plan artifact in the runtime proof path, so the
        # manifest must not advertise one.
        m = json.load(open(os.path.join(REPO, "test", "generalism", "generalism-cells.manifest.json"),
                           encoding="utf-8"))
        cells = [c for c in m["cells"] if c["id"].startswith("bind:transition_effect:")]
        self.assertEqual(len(cells), 5, "expected all five transition_effect carry-and-consume rows")
        for cell in cells:
            proof = cell.get("consumeProof") or {}
            self.assertNotIn("tamper", proof, f"{cell['id']} must not advertise a nonexistent tamper")

    def test_transition_effect_consume_proof_rejects_coordination_plan_consumer_alias(self):
        # If the coordination-plan consumer ignores transition effects, the proof must fail as vacuous.
        g = self._gen()
        m = json.load(open(os.path.join(REPO, "test", "generalism", "generalism-cells.manifest.json"),
                           encoding="utf-8"))
        cell = next(c for c in m["cells"] if c["id"] == "bind:transition_effect:consume")
        orig_validate_spec = g._validate_spec
        orig_render = g._render_coordination_plan

        def ignored(_neutrino_gen, _spec, _workdir, _label):
            return {"lifecycleTransitions": [
                {"name": "COMMIT", "from": "PROPOSED", "to": "COMMITTED",
                 "effects": ["post"], "idempotency": "reject"}
            ]}

        g._validate_spec = lambda _validator, _spec, _workdir: (0, [])
        g._render_coordination_plan = ignored
        try:
            bad = g.prove_binding_consume(
                {"cells": [cell]},
                None,
                os.path.join(REPO, "scripts", "validators", "validate_binding_manifest.py"),
                os.path.join(REPO, "scripts", "validators", "validate_capability_spec.py"),
                coordination_plan_renderer="/tmp/neutrino-gen")
            self.assertTrue(bad and "coordination-plan did not carry" in bad[0],
                            "ignoring transition effects must fail the consume proof")
        finally:
            g._validate_spec = orig_validate_spec
            g._render_coordination_plan = orig_render

    def test_transition_guard_consume_proof_is_schema_derived_and_non_vacuous(self):
        g = self._gen()
        m = json.load(open(os.path.join(REPO, "test", "generalism", "generalism-cells.manifest.json"),
                           encoding="utf-8"))
        live = g._live_schema_values("transition_guard")
        cells = [c for c in m["cells"] if c["id"].startswith("bind:transition_guard:")]
        self.assertEqual(sorted(c["covers"][0][1] for c in cells), sorted(live))
        self.assertEqual(len(cells), 3)
        for cell in cells:
            proof = cell["consumeProof"]
            self.assertIn(proof["controlValue"], live)
            self.assertNotEqual(proof["cellValue"], proof["controlValue"])
            self.assertEqual(proof["producerTamper"],
                             "drop-transition-guard-kind-from-capability-spec")
            self.assertEqual(proof["consumerTamper"],
                             "drop-transition-guard-kind-from-coordination-plan")

        cell = next(c for c in cells if c["covers"][0][1] == "participant")
        orig_validate_spec = g._validate_spec
        orig_render = g._render_coordination_plan

        def validate(_validator, spec, _workdir):
            transition = g._lifecycle_transition(spec, "COMMIT") or {}
            if any(isinstance(guard, dict) and "kind" not in guard
                   for guard in transition.get("guards") or []):
                return 1, [{"code": "spec.schema", "message": "kind is required"}]
            return 0, []

        def render(_neutrino_gen, spec, _workdir, _label):
            transition = g._lifecycle_transition(spec, "COMMIT") or {}
            return {"lifecycleTransitions": [{
                "name": "COMMIT", "from": "PROPOSED", "to": "COMMITTED",
                "effects": ["post"], "guards": copy.deepcopy(transition.get("guards") or []),
                "idempotency": "reject",
            }]}

        g._validate_spec = validate
        g._render_coordination_plan = render
        try:
            bad = g.prove_binding_consume(
                {"cells": [cell]}, None,
                os.path.join(REPO, "scripts", "validators", "validate_binding_manifest.py"),
                os.path.join(REPO, "scripts", "validators", "validate_capability_spec.py"),
                coordination_plan_renderer="/tmp/neutrino-gen")
            self.assertEqual(bad, [])
        finally:
            g._validate_spec = orig_validate_spec
            g._render_coordination_plan = orig_render

    def test_transition_guard_proofs_follow_in_memory_generator_schema(self):
        g = self._gen()
        with open(g.SCHEMA, encoding="utf-8") as f:
            schema = json.load(f)
        with open(g.CLASSIFICATION, encoding="utf-8") as f:
            classification = json.load(f)
        guard_enum = schema["$defs"]["transition"]["properties"]["guards"]["items"][
            "properties"]["kind"]["enum"]

        added_schema = copy.deepcopy(schema)
        added_enum = added_schema["$defs"]["transition"]["properties"]["guards"]["items"][
            "properties"]["kind"]["enum"]
        added_enum.append("quorum")
        added = g.build_manifest(added_schema, classification, g.SEEDS)
        added_cell = next(c for c in added["cells"]
                          if c.get("id") == "bind:transition_guard:quorum")
        self.assertTrue(added_cell["credits"])
        self.assertIn(added_cell["consumeProof"]["controlValue"], added_enum)
        self.assertNotEqual(added_cell["consumeProof"]["controlValue"], "quorum")
        self.assertEqual(g.binding_lifecycle_disposition_violations(
            added, added_schema, classification), [])

        removed_schema = copy.deepcopy(schema)
        removed_enum = removed_schema["$defs"]["transition"]["properties"]["guards"]["items"][
            "properties"]["kind"]["enum"]
        removed_enum.remove("sequence")
        removed = g.build_manifest(removed_schema, classification, g.SEEDS)
        self.assertNotIn("sequence", [c["covers"][0][1] for c in removed["cells"]
                                      if c.get("id", "").startswith("bind:transition_guard:")])
        self.assertNotIn(("transition_guard", "sequence"), {
            (d["family"], d["value"]) for d in removed["bindingLifecycleDispositions"]})
        self.assertEqual(g.binding_lifecycle_disposition_violations(
            removed, removed_schema, classification), [])
        self.assertEqual(guard_enum, ["participant", "deadline", "sequence"],
                         "alternate-schema tests must not mutate the live schema object")

    def test_transition_guard_consume_proof_rejects_ignored_producer_and_consumer_kind(self):
        g = self._gen()
        m = json.load(open(os.path.join(REPO, "test", "generalism", "generalism-cells.manifest.json"),
                           encoding="utf-8"))
        cell = next(c for c in m["cells"] if c["id"] == "bind:transition_guard:participant")
        orig_validate_spec = g._validate_spec
        orig_render = g._render_coordination_plan

        def dropped(_neutrino_gen, spec, _workdir, _label):
            transition = g._lifecycle_transition(spec, "COMMIT") or {}
            guards = copy.deepcopy(transition.get("guards") or [])
            for guard in guards:
                guard.pop("kind", None)
            return {"lifecycleTransitions": [{"name": "COMMIT", "guards": guards}]}

        g._validate_spec = lambda _validator, _spec, _workdir: (0, [])
        g._render_coordination_plan = dropped
        try:
            producer_bad = g.prove_binding_consume(
                {"cells": [cell]}, None,
                os.path.join(REPO, "scripts", "validators", "validate_binding_manifest.py"),
                os.path.join(REPO, "scripts", "validators", "validate_capability_spec.py"),
                coordination_plan_renderer="/tmp/neutrino-gen")
            self.assertTrue(producer_bad and "dropping the producer guard kind" in producer_bad[0])

            def validate(_validator, spec, _workdir):
                transition = g._lifecycle_transition(spec, "COMMIT") or {}
                if any(isinstance(guard, dict) and "kind" not in guard
                       for guard in transition.get("guards") or []):
                    return 1, [{"code": "spec.schema", "message": "kind is required"}]
                return 0, []

            g._validate_spec = validate
            consumer_bad = g.prove_binding_consume(
                {"cells": [cell]}, None,
                os.path.join(REPO, "scripts", "validators", "validate_binding_manifest.py"),
                os.path.join(REPO, "scripts", "validators", "validate_capability_spec.py"),
                coordination_plan_renderer="/tmp/neutrino-gen")
            self.assertTrue(consumer_bad and "did not carry transition guard kind" in consumer_bad[0])
        finally:
            g._validate_spec = orig_validate_spec
            g._render_coordination_plan = orig_render

    def test_transition_evidence_consume_proof_is_schema_derived_and_non_vacuous(self):
        g = self._gen()
        m = json.load(open(os.path.join(REPO, "test", "generalism", "generalism-cells.manifest.json"),
                           encoding="utf-8"))
        live = g._live_schema_values("evidence_style")
        cells = [c for c in m["cells"] if c["id"].startswith("bind:evidence_style:")]
        self.assertEqual(sorted(c["covers"][0][1] for c in cells), sorted(live))
        self.assertEqual(len(cells), 2)
        for cell in cells:
            proof = cell["consumeProof"]
            self.assertIn(proof["controlValue"], live)
            self.assertNotEqual(proof["cellValue"], proof["controlValue"])
            self.assertIs(proof["evidenceChained"], True)
            self.assertEqual(proof["producerTamper"],
                             "drop-transition-evidence-style-from-capability-spec")
            self.assertEqual(proof["consumerTamper"],
                             "drop-transition-evidence-style-from-coordination-plan")

        cell = next(c for c in cells if c["covers"][0][1] == "single_hash")
        orig_validate_spec = g._validate_spec
        orig_render = g._render_coordination_plan

        def validate(_validator, spec, _workdir):
            evidence = g._transition_evidence(spec, "COMMIT") or {}
            if "style" not in evidence:
                return 1, [{"code": "spec.schema", "message": "style is required"}]
            return 0, []

        def render(_neutrino_gen, spec, _workdir, _label):
            evidence = copy.deepcopy(g._transition_evidence(spec, "COMMIT"))
            return {"lifecycleTransitions": [{"name": "COMMIT", "evidence": evidence}]}

        g._validate_spec = validate
        g._render_coordination_plan = render
        try:
            bad = g.prove_binding_consume(
                {"cells": [cell]}, None,
                os.path.join(REPO, "scripts", "validators", "validate_binding_manifest.py"),
                os.path.join(REPO, "scripts", "validators", "validate_capability_spec.py"),
                coordination_plan_renderer="/tmp/neutrino-gen")
            self.assertEqual(bad, [])
        finally:
            g._validate_spec = orig_validate_spec
            g._render_coordination_plan = orig_render

    def test_transition_evidence_proofs_follow_in_memory_generator_schema(self):
        g = self._gen()
        with open(g.SCHEMA, encoding="utf-8") as f:
            schema = json.load(f)
        with open(g.CLASSIFICATION, encoding="utf-8") as f:
            classification = json.load(f)
        path = schema["$defs"]["transition"]["properties"]["evidence"]["oneOf"][1][
            "properties"]["style"]["enum"]

        added_schema = copy.deepcopy(schema)
        added_enum = added_schema["$defs"]["transition"]["properties"]["evidence"]["oneOf"][1][
            "properties"]["style"]["enum"]
        added_enum.append("aggregate_log")
        added = g.build_manifest(added_schema, classification, g.SEEDS)
        added_cell = next(c for c in added["cells"]
                          if c.get("id") == "bind:evidence_style:aggregate_log")
        self.assertTrue(added_cell["credits"])
        self.assertIn(added_cell["consumeProof"]["controlValue"], added_enum)
        self.assertNotEqual(added_cell["consumeProof"]["controlValue"], "aggregate_log")
        self.assertEqual(g.binding_lifecycle_disposition_violations(
            added, added_schema, classification), [])

        removed_schema = copy.deepcopy(schema)
        removed_enum = removed_schema["$defs"]["transition"]["properties"]["evidence"]["oneOf"][1][
            "properties"]["style"]["enum"]
        removed_enum.append("aggregate_log")
        removed_enum.remove("single_hash")
        removed = g.build_manifest(removed_schema, classification, g.SEEDS)
        self.assertNotIn("single_hash", [c["covers"][0][1] for c in removed["cells"]
                                         if c.get("id", "").startswith("bind:evidence_style:")])
        self.assertNotIn(("evidence_style", "single_hash"), {
            (d["family"], d["value"]) for d in removed["bindingLifecycleDispositions"]})
        self.assertEqual(g.binding_lifecycle_disposition_violations(
            removed, removed_schema, classification), [])
        self.assertEqual(path, ["single_hash", "batched_root"],
                         "alternate-schema tests must not mutate the live schema object")

    def test_transition_evidence_consume_proof_rejects_dropped_or_ignored_style(self):
        g = self._gen()
        m = json.load(open(os.path.join(REPO, "test", "generalism", "generalism-cells.manifest.json"),
                           encoding="utf-8"))
        cell = next(c for c in m["cells"] if c["id"] == "bind:evidence_style:single_hash")
        orig_validate_spec = g._validate_spec
        orig_render = g._render_coordination_plan

        def dropped(_neutrino_gen, spec, _workdir, _label):
            evidence = copy.deepcopy(g._transition_evidence(spec, "COMMIT") or {})
            evidence.pop("style", None)
            return {"lifecycleTransitions": [{"name": "COMMIT", "evidence": evidence}]}

        g._validate_spec = lambda _validator, _spec, _workdir: (0, [])
        g._render_coordination_plan = dropped
        try:
            producer_bad = g.prove_binding_consume(
                {"cells": [cell]}, None,
                os.path.join(REPO, "scripts", "validators", "validate_binding_manifest.py"),
                os.path.join(REPO, "scripts", "validators", "validate_capability_spec.py"),
                coordination_plan_renderer="/tmp/neutrino-gen")
            self.assertTrue(producer_bad and "dropping the producer evidence style" in producer_bad[0])

            def validate(_validator, spec, _workdir):
                evidence = g._transition_evidence(spec, "COMMIT") or {}
                if "style" not in evidence:
                    return 1, [{"code": "spec.schema", "message": "style is required"}]
                return 0, []

            def ignored(_neutrino_gen, spec, _workdir, _label):
                evidence = copy.deepcopy(g._transition_evidence(spec, "COMMIT") or {})
                evidence["style"] = "batched_root"
                return {"lifecycleTransitions": [{"name": "COMMIT", "evidence": evidence}]}

            g._validate_spec = validate
            g._render_coordination_plan = ignored
            consumer_bad = g.prove_binding_consume(
                {"cells": [cell]}, None,
                os.path.join(REPO, "scripts", "validators", "validate_binding_manifest.py"),
                os.path.join(REPO, "scripts", "validators", "validate_capability_spec.py"),
                coordination_plan_renderer="/tmp/neutrino-gen")
            self.assertTrue(consumer_bad and "did not carry transition evidence style" in consumer_bad[0])
        finally:
            g._validate_spec = orig_validate_spec
            g._render_coordination_plan = orig_render

    def test_binding_refusal_is_the_machine_code_not_the_prose(self):
        #  P1: the coverage contract is the MACHINE CODE, not the message. If the validator emitted the
        # right prose MESSAGE under a DIFFERENT code, the proof must still FAIL — prove the match is on code.
        g = self._gen()
        m = json.load(open(os.path.join(REPO, "test", "generalism", "generalism-cells.manifest.json"),
                           encoding="utf-8"))
        locus = g.BINDING_LOCUS[("transition_effect", "post")]
        cell = {
            "id": "bind:transition_effect:post",
            "kind": "binding",
            "credits": False,
            "covers": [["transition_effect", "post"]],
            "witness": "spec_refusal",
            "spec": locus["spec"],
            "locator": {"array": locus["array"], "sub": locus["sub"], "value": locus["value"],
                        "contains": bool(locus.get("contains"))},
            "invalid": locus["invalid"],
            "refusalCode": locus["code"],
            "refusalMessage": locus["msg"],
        }
        calls = {"n": 0}
        orig = g._validate_spec

        def stub(validator, spec_obj, workdir):
            # 1st call = the clean cell (valid); 2nd = the control, refusing with the RIGHT message but the
            # WRONG code (generic `spec.schema` instead of the declared field-specific code).
            calls["n"] += 1
            if calls["n"] == 1:
                return 0, []
            return 1, [{"code": "spec.schema", "message": cell["refusalMessage"]}]
        g._validate_spec = stub
        try:
            bad = g.prove_binding({"cells": [cell]}, "unused")
            self.assertTrue(bad and "machine code" in bad[0],
                            "a refusal with the right message but wrong code must FAIL (code is the contract)")
        finally:
            g._validate_spec = orig

    def test_coverage_credited_only_by_controlled_experiments(self):
        # The covered-feature list may reference ONLY crediting controlled-experiment cells — never a seed
        # fixture (so an unrelated seed refusal can't inflate coverage;  P1).
        m = json.load(open(os.path.join(REPO, "test", "generalism", "generalism-cells.manifest.json"),
                           encoding="utf-8"))
        crediting = {c["id"] for c in m["cells"] if c.get("credits")}
        for f in m["features"]:
            for cid in f["cells"]:
                self.assertIn(cid, crediting,
                              f"feature {f['family']}/{f['value']} is 'covered' by non-crediting cell {cid}")

    def _load(self, relpath, name):
        import importlib.util
        p = os.path.join(REPO, relpath)
        spec = importlib.util.spec_from_file_location(name, p)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def _gate(self):
        return self._load("scripts/gates/check_generalism_cell_coverage.py", "gengate")

    def _gen(self):
        return self._load("scripts/generators/gen_generalism_cells.py", "gengen")

    def test_confounded_control_is_rejected(self):
        # TAMPER ( P1): a control that combines the INTENDED mutation with an UNRELATED change (a
        # version / allow / compute edit) must NOT reconstruct from the typed mutation -> flagged. A control
        # that is exactly apply(mutation, cell) must pass. This closes the partial-allowlist gap: the check
        # is a full reconstruction, not a fixed list of watched coordinates.
        g = self._gen()
        cell_neu = ('procedure p {\n    trigger settlement\n    version "1.0.0"\n'
                    '    input amount : money\n    input currency : currency\n'
                    '    input currency2 : currency\n    debit d {\n'
                    '        currency        = %currency2\n    }\n}\n')
        mut = {"op": "retoken", "old": "currency        = %currency2",
               "new": "currency        = %currency", "count": 1}
        clean = g.apply_mutation(cell_neu, mut)
        cell = {"input": {"neu": cell_neu}, "mutation": mut, "control": {"neu": clean}}
        self.assertEqual(g.control_reconstruction_violations(cell), [],
                         "a faithfully-derived single-locus control must reconstruct")
        # The reviewer's exact tamper: same mutation PLUS a version bump 1.0.0 -> 9.9.9.
        confounded_version = clean.replace('version "1.0.0"', 'version "9.9.9"')
        cell_v = {"input": {"neu": cell_neu}, "mutation": mut, "control": {"neu": confounded_version}}
        self.assertTrue(g.control_reconstruction_violations(cell_v),
                        "a control that also bumps the version must NOT reconstruct (confounded)")
        # And an unrelated `allow`/compute-style extra line combined with the mutation is caught too.
        confounded_allow = clean.replace("    debit d {", '    compute z = amount\n    debit d {')
        cell_a = {"input": {"neu": cell_neu}, "mutation": mut, "control": {"neu": confounded_allow}}
        self.assertTrue(g.control_reconstruction_violations(cell_a),
                        "a control that also adds a compute must NOT reconstruct (confounded)")
        # An exact-match-count violation (the retoken target is absent) is a mutation error, not silent.
        self.assertTrue(g.control_reconstruction_violations(
            {"input": {"neu": "procedure q {\n}\n"}, "mutation": mut, "control": {"neu": "x"}}),
            "a retoken whose target is absent must be flagged (exact match-count)")

    def test_relabeled_mutation_is_rejected(self):
        # TAMPER ( P1): a cell may not credit a feature whose canonical locus is NOT the mutation it
        # actually ran. Swap effect_kind/debit's mutation for the invariant/balanced locus (assert removal):
        # reconstruction still passes, but the covers<->mutation binding must turn it RED.
        g = self._gen()
        locus = g.FEATURE_LOCUS
        self.assertIn(("effect_kind", "debit"), locus)
        # A correctly-bound cell passes.
        neu = g._base("p")
        good = {"covers": [["effect_kind", "debit"]], "mutation": locus[("effect_kind", "debit")]}
        self.assertEqual(g.feature_locus_violations(good), [], "the canonical locus must bind cleanly")
        # Relabel: credit effect_kind/debit but run the invariant/balanced mutation.
        relabeled = {"covers": [["effect_kind", "debit"]], "mutation": locus[("invariant", "balanced")]}
        self.assertTrue(g.feature_locus_violations(relabeled),
                        "crediting a feature whose locus is not the run mutation must be flagged (relabeled)")
        # A feature with no canonical locus cannot be credited.
        self.assertTrue(g.feature_locus_violations(
            {"covers": [["compute", "present"]], "mutation": {"op": "scenario", "override": {}}}),
            "a feature with no canonical locus may not be credited at S1a")

    def test_monotonicity_growing_base_turns_gate_red(self):
        #  P2: a NON-VACUOUS growing-base test — invoke the real gate's check() with a resolvable base
        # whose uncovered set is a STRICT SUBSET of today's (so today's grew), and assert a monotonicity
        # RED. We exercise check() (not bare set math) by stubbing the base resolution to a smaller set.
        g = self._gate()
        m = json.load(open(os.path.join(REPO, "test", "generalism", "generalism-cells.manifest.json"),
                           encoding="utf-8"))
        smaller = [u for u in m["uncoveredFeatures"][:-1]]  # base lacks the last uncovered -> today grew
        orig_exists, orig_resolve = g._ref_exists, g._resolve_baseline_at
        old_env = os.environ.get("GENERALISM_BASE_REF")
        os.environ["GENERALISM_BASE_REF"] = "pretend-base"
        g._ref_exists = lambda ref: True
        g._resolve_baseline_at = lambda ref: {tuple(x) for x in smaller}
        try:
            reasons, notes = [], []
            g.check(reasons, notes)
            self.assertTrue(any("GREW vs base revision" in r for r in reasons),
                            f"a grown uncovered set must turn the gate RED; reasons={reasons}")
        finally:
            g._ref_exists, g._resolve_baseline_at = orig_exists, orig_resolve
            if old_env is None:
                os.environ.pop("GENERALISM_BASE_REF", None)
            else:
                os.environ["GENERALISM_BASE_REF"] = old_env

    def test_monotonicity_unavailable_required_base_is_red(self):
        #  P1.2: when a base ref is REQUIRED (CI sets GENERALISM_BASE_REF) but unresolvable (a shallow
        # checkout lacking the ref), the ratchet must FAIL CLOSED, never fail-open skip.
        g = self._gate()
        old = os.environ.get("GENERALISM_BASE_REF")
        os.environ["GENERALISM_BASE_REF"] = "no-such-ref-deadbeef"
        try:
            reasons = []
            ref, base = g._base_uncovered(reasons)
            self.assertIsNone(base, "an unresolvable required base must not resolve")
            self.assertTrue(any("fail-open" in r or "could not be resolved" in r for r in reasons),
                            "an unresolvable required base must record a hard failure")
        finally:
            if old is None:
                del os.environ["GENERALISM_BASE_REF"]
            else:
                os.environ["GENERALISM_BASE_REF"] = old


    def _regen(self, schema_path):
        import subprocess
        import tempfile
        out = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        out.close()
        subprocess.run([self.PY if hasattr(self, "PY") else "python3",
                        os.path.join(REPO, "scripts", "generators", "gen_generalism_cells.py"),
                        "--schema", schema_path, "--out", out.name], check=True,
                       capture_output=True)
        with open(out.name, encoding="utf-8") as fh:
            m = json.load(fh)
        os.remove(out.name)
        return m

    def test_mutation_new_value_at_known_enum_is_derived(self):
        # A NEW value at a KNOWN behavior enum coordinate must be enumerated as a feature (auto-picked up),
        # so it is covered or falls to the uncovered ledger — never silently dropped.
        import tempfile
        schema = json.load(open(os.path.join(REPO, "docs", "schemas", "capability-spec.schema.json"),
                                encoding="utf-8"))
        base = self._regen(os.path.join(REPO, "docs", "schemas", "capability-spec.schema.json"))
        # add a value to the exprNode.op enum (a known behavior coordinate)
        def add_op(node):
            if isinstance(node, dict):
                if node.get("enum") and "+" in node["enum"] and "%%" not in node["enum"]:
                    node["enum"] = node["enum"] + ["%%"]
                for v in node.values():
                    add_op(v)
            elif isinstance(node, list):
                for v in node:
                    add_op(v)
        add_op(schema)
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(schema, f)
            mpath = f.name
        mutated = self._regen(mpath)
        os.remove(mpath)
        self.assertGreater(mutated["featureCount"], base["featureCount"],
                           "a new value at a known enum was NOT derived as a new feature")

    def test_mutation_new_coordinate_is_unclassified(self):
        # A NEW enum at a PREVIOUSLY UNKNOWN coordinate must surface as unclassified (the completeness gate
        # then fails closed) — it cannot land invisibly.
        import tempfile
        schema = json.load(open(os.path.join(REPO, "docs", "schemas", "capability-spec.schema.json"),
                                encoding="utf-8"))
        schema.setdefault("properties", {})["__mutation_probe"] = {"type": "string", "enum": ["z"]}
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(schema, f)
            mpath = f.name
        mutated = self._regen(mpath)
        os.remove(mpath)
        self.assertIn("/__mutation_probe", mutated.get("unclassifiedCoordinates", []),
                      "a new enum at an unknown coordinate was NOT flagged unclassified")

    def test_derivation_is_not_a_hardcoded_list(self):
        # The generator must ENUMERATE from the schema + classification, not carry a hardcoded row list:
        # assert it reads both sources + traverses ALL coordinates.
        src = open(os.path.join(REPO, "scripts", "generators", "gen_generalism_cells.py"),
                   encoding="utf-8").read()
        self.assertIn("capability-spec.schema.json", src)
        self.assertIn("classification.json", src)
        self.assertIn("_all_enum_coordinates", src)


if __name__ == "__main__":
    unittest.main()

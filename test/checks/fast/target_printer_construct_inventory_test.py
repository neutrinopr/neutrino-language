#!/usr/bin/env python3
"""[fast]  substrate: the target-printer inventory governs the Solidity
CONSTRUCT-emission sites, and the one-time 4->9 baseline recovery is narrowly
pinned + non-reusable.

`printSolidity` is a reviewed emitter span, so its per-construct grammar (enum /
event / contract framing) and the storageDecl / signature decl helpers were
invisible to the statement inventory. This slice makes the scanner construct-aware
so each construct migration strictly decreases the count, and permits the one-time
detection-only growth ONLY under exact, source-unchanged conditions.
"""

import json
import os
import sys
import unittest
import unittest.mock

from _fastcase import REPO

sys.path.insert(0, os.path.join(REPO, "scripts", "gates"))
import check_target_node_registry as gate  # noqa: E402

# EnumDecl/StorageDecl/EventDecl, FunctionSig (+ its ParamRender authority), and
# now the contract CONTAINER (ContractShell) have all migrated to typed .td nodes.
# The per-construct printer-template inventory has reached ZERO for Solidity — no
# surviving handwritten construct site. (The shared quorum-guard INTERFACE shell +
# signatures are governed by the SEPARATE  raw-seam authority, not this
# construct-template detector.) The detectors below remain as regression
# tripwires: reintroducing any handwritten construct grammar is re-detected.
CONSTRUCT_NODES = set()

# The / one-time 4->9 recovery has landed on main, so origin/main is now
# itself at the recovered baseline. The historical permission is replayed against a
# PINNED synthetic old base: the pre-recovery inventory snapshot (byte-for-byte the
# committed base the recovery was authorized against, sha256 a0637a…).
_PRERECOVERY_INV = open(
    os.path.join(os.path.dirname(__file__), "fixtures",
                 "target_printer_inventory.prerecovery.json"),
    encoding="utf-8").read()
# The construct sites retired since  (EnumDecl via , StorageDecl via ,
# EventDecl via , FunctionSig via , and the contract CONTAINER here). The
# historical 4->9 recovery was authorized when ALL FIVE were still detected
# construct sites, so re-add them to reconstruct the pre-migration 9-site scan.
_RETIRED_CONSTRUCT_SITES = [
    {"target": "solidity", "node": "EnumDecl", "path": gate._CPP_REL,
     "matcher": "printSolidity emits `enum <name> { <variants> }`"},
    {"target": "solidity", "node": "StorageDecl", "path": gate._CPP_REL,
     "matcher": "storageDecl renders `<type> <modifiers> <name>;`"},
    {"target": "solidity", "node": "EventDecl", "path": gate._CPP_REL,
     "matcher": "printSolidity emits `event <name>(<params>);`"},
    {"target": "solidity", "node": "FunctionSig", "path": gate._HDR_REL,
     "matcher": "SolFunction::signature renders "
                "`<keyword> <name>(<params>) <modifiers>`"},
    {"target": "solidity", "node": "ContractShell", "path": gate._CPP_REL,
     "matcher": "printSolidity emits `contract <name> { ... }`"},
]


class ConstructSiteDetection(unittest.TestCase):
    def setUp(self):
        self.cpp = gate._read(gate.CPP)
        self.hdr = gate._read(gate.HDR)

    def test_detects_exactly_the_surviving_construct_sites(self):
        # ZERO endpoint: every per-construct printer template has migrated, so the
        # live construct-site scan is empty.
        sites = gate.solidity_construct_sites(self.cpp, self.hdr)
        self.assertEqual({s["node"] for s in sites}, CONSTRUCT_NODES)
        self.assertEqual(len(sites), 0)

    def test_contractshell_detector_still_bites_if_reintroduced(self):
        # ContractShell is RETIRED (its `"contract "` grammar is gone from the real
        # source), but the detector remains a REGRESSION TRIPWIRE: reintroducing the
        # original handwritten `printSolidity` contract-container grammar is
        # re-detected. Inject the synthetic marker inside the printSolidity body and
        # confirm the site reappears — proving the detector is not vacuous.
        injected = self.cpp.replace(
            "return doc.print(",
            'doc.add(block("contract " + m.name + " {", "}", {}));\n  return '
            "doc.print(", 1)
        self.assertNotEqual(injected, self.cpp, "fixture: injection anchor moved")
        nodes = {s["node"]
                 for s in gate.solidity_construct_sites(injected, self.hdr)}
        self.assertIn("ContractShell", nodes)

    def test_retired_detectors_still_bite_if_reintroduced(self):
        # FunctionSig and ParamRender are RETIRED (their markers are gone from the
        # real source), but their detectors remain as REGRESSION TRIPWIRES: if the
        # handwritten authority were reintroduced, the site is re-detected. Inject a
        # synthetic marker and confirm re-detection, then removal drops it.
        with_sig = self.hdr + "\n  std::string signature() const;\n"
        self.assertIn(
            "FunctionSig",
            {s["node"] for s in gate.solidity_construct_sites(self.cpp, with_sig)})
        # Reintroduce render INTO the real struct SolParam (the detector reads the
        # first SolParam body — appending a second struct would not exercise it).
        with_param = self.hdr.replace(
            "struct SolParam {",
            "struct SolParam {\n  std::string render() const { return {}; }", 1)
        self.assertIn(
            "ParamRender",
            {s["node"] for s in gate.solidity_construct_sites(self.cpp, with_param)})

    def test_param_render_detector_is_scoped_to_SolParam(self):
        #  P1.1: the detector must bind to the balanced `struct SolParam` body,
        # not any `std::string render() const` in the header. A SolParam::render
        # IS detected; an UNRELATED type's `render() const` (no SolParam) is NOT —
        # the exact reviewer bypass (rename SolParam::render away + decoy type).
        real_param = self.hdr.replace(
            "struct SolParam {",
            "struct SolParam {\n  std::string render() const { return {}; }", 1)
        self.assertIn(
            "ParamRender",
            {s["node"] for s in gate.solidity_construct_sites(self.cpp, real_param)})
        decoy_only = self.hdr + (
            "\nstruct UnrelatedThing {\n"
            "  std::string render() const { return {}; }\n};\n")
        self.assertNotIn(
            "ParamRender",
            {s["node"] for s in gate.solidity_construct_sites(self.cpp, decoy_only)},
            "an unrelated render() const false-greened ParamRender")

    def test_migrated_markers_are_retired(self):
        # The migrated constructs are gone from the source, so none is detected as
        # a handwritten site (EnumDecl/StorageDecl/EventDecl/FunctionSig + its
        # SolParam::render authority + now the contract container ContractShell).
        nodes = {s["node"] for s in gate.solidity_construct_sites(self.cpp, self.hdr)}
        for retired in ("EnumDecl", "StorageDecl", "EventDecl", "FunctionSig",
                        "ParamRender", "ContractShell"):
            self.assertNotIn(retired, nodes)

    def test_marker_in_a_comment_does_not_count(self):
        # The detector strips comments (keeping strings), so a construct marker
        # mentioned in prose must not register a governed site — the endpoint stays
        # at zero even with a comment-only mention of `contract `/`event `.
        cpp = self.cpp + (
            '\n// a stray mention of "contract " and "event " and storageDecl in '
            "prose\n")
        sites = gate.solidity_construct_sites(cpp, self.hdr)
        self.assertEqual(len(sites), 0)

    def test_inventory_lists_the_construct_sites(self):
        # The committed inventory carries NO solidity handwritten construct site —
        # the zero endpoint.
        inv = gate.load_inventory(gate.INVENTORY)
        sol_nodes = {s["node"] for s in inv["handwrittenSites"]
                     if s.get("target") == "solidity"}
        self.assertEqual(sol_nodes, CONSTRUCT_NODES)


class OneTimeBaselineRecovery(unittest.TestCase):
    def setUp(self):
        self.base = "origin/main"
        # Reconstruct the exact 9-site scan the historical 4->9 recovery was
        # authorized against: the 4 PG emitter sites of the pinned pre-recovery
        # base + the 5 construct-baseline sites (EnumDecl/StorageDecl/EventDecl/
        # FunctionSig/ContractShell), all since retired. The PG backdrop is taken
        # from the pinned BASE, NOT the live scan: a later PG-emitter migration —
        # e.g. 's `If` -> sealed `Guard` rename — legitimately evolves the live
        # PG sites, but this historical replay must use the sites that actually
        # existed at recovery time (when the base and current PG sites were
        # identical, the recovery having ADDED only the five constructs). The live
        # PG inventory is validated by the registry gate itself, not here.
        self.scanned = [s for s in json.loads(_PRERECOVERY_INV)["handwrittenSites"]
                        if s.get("target") == "postgres"]
        self.historic_scan = self.scanned + _RETIRED_CONSTRUCT_SITES

    def _old_base(self, ref, path):
        # Pre-recovery base: the pinned 4-site inventory; model source byte-identical
        # to HEAD (detection-only), so the recovery's source-unchanged check passes.
        if path == gate._rel(gate.INVENTORY):
            return _PRERECOVERY_INV
        if path in (gate._CPP_REL, gate._HDR_REL):
            return gate._read(os.path.join(REPO, path))
        return None

    def test_permits_the_genuine_detection_only_growth(self):
        # Replay the historical 4->9 recovery against the pinned pre-recovery base:
        # exactly the five construct sites added, source unchanged -> permitted.
        # (This PR migrated the last construct, ContractShell, so the live scan is 4
        # PG-only; historic_scan re-adds all five retired construct sites to
        # reconstruct the 9-site scan the recovery saw.)
        with unittest.mock.patch.object(gate, "_git_show", self._old_base):
            self.assertTrue(gate._construct_baseline_recovery_permitted(
                "synthetic-old-base", 4, 9, self.historic_scan))

    def test_rejects_forged_or_removed_site_against_old_base(self):
        with unittest.mock.patch.object(gate, "_git_show", self._old_base):
            # A removed base site (not only additions) must not launder through it.
            fewer = [s for s in self.historic_scan if s["node"] != "Blank"]
            self.assertFalse(gate._construct_baseline_recovery_permitted(
                "synthetic-old-base", 4, len(fewer), fewer))
            # A non-construct added site -> not the pinned five-site set.
            forged = [s for s in self.historic_scan if s["node"] != "EnumDecl"]
            forged.append({"target": "solidity", "node": "RogueDecl",
                           "path": gate._CPP_REL, "matcher": "forged"})
            self.assertFalse(gate._construct_baseline_recovery_permitted(
                "synthetic-old-base", 4, 9, forged))

    def test_recovery_is_non_reusable_once_main_is_recovered(self):
        # origin/main is now itself at 9, so the base already carries the construct
        # sites (nothing is added) and the one-time recovery no longer fires.
        self.assertFalse(gate._construct_baseline_recovery_permitted(
            self.base, 4, 9, self.scanned))

    def test_rejects_wrong_values_or_no_base(self):
        self.assertFalse(gate._construct_baseline_recovery_permitted(self.base, 5, 9, self.scanned))
        self.assertFalse(gate._construct_baseline_recovery_permitted(self.base, 4, 10, self.scanned))
        self.assertFalse(gate._construct_baseline_recovery_permitted(None, 4, 9, self.scanned))
        self.assertFalse(gate._construct_baseline_recovery_permitted("origin/main", 4, 9, self.scanned))


class DispatchRetirementCredit(unittest.TestCase):
    """The generated-handler credit is IDENTITY-based (): the node ADDED to the
    generated set must be the SAME node RETIRED from the handwritten set — not a
    mere `current < base` count decrease — so surfacing an unrelated pre-existing
    handwritten site (ParamRender) neither masks a real migration nor falsely
    credits an unrelated one."""

    def test_genuine_migration_credited_even_when_unrelated_site_surfaced(self):
        # EventDecl moved handwritten -> generated; ParamRender surfaced in the SAME
        # slice (a pre-existing site now made visible). The handwritten COUNT nets
        # to zero ({EventDecl} out, {ParamRender} in), but the migration is real.
        base_hw = frozenset({"ContractShell", "EventDecl", "FunctionSig"})
        cur_hw = frozenset({"ContractShell", "FunctionSig", "ParamRender"})
        base_gen = frozenset({"Require", "StorageDecl"})
        cur_gen = frozenset({"Require", "StorageDecl", "EventDecl"})
        self.assertTrue(gate._dispatch_retirement_credited(
            base_hw, cur_hw, base_gen, cur_gen))

    def test_decoration_not_credited(self):
        # A generated node added with NO corresponding handwritten retirement is
        # decoration — not credited.
        base_hw = frozenset({"ContractShell", "FunctionSig"})
        cur_hw = frozenset({"ContractShell", "FunctionSig"})
        base_gen = frozenset({"Require"})
        cur_gen = frozenset({"Require", "Decoration"})
        self.assertFalse(gate._dispatch_retirement_credited(
            base_hw, cur_hw, base_gen, cur_gen))

    def test_substitution_not_credited(self):
        # Retiring handwritten A while adding an UNRELATED generated B must NOT
        # credit (A is not the added node) — a substitution cannot launder a node.
        base_hw = frozenset({"ContractShell", "EventDecl", "FunctionSig"})
        cur_hw = frozenset({"ContractShell", "FunctionSig"})  # EventDecl retired
        base_gen = frozenset({"Require"})
        cur_gen = frozenset({"Require", "Unrelated"})  # but Unrelated added
        self.assertFalse(gate._dispatch_retirement_credited(
            base_hw, cur_hw, base_gen, cur_gen))

    def test_surfacing_alone_not_credited(self):
        # Surfacing ParamRender with NO generated addition credits nothing.
        base_hw = frozenset({"ContractShell", "FunctionSig"})
        cur_hw = frozenset({"ContractShell", "FunctionSig", "ParamRender"})
        base_gen = frozenset({"Require"})
        cur_gen = frozenset({"Require"})
        self.assertFalse(gate._dispatch_retirement_credited(
            base_hw, cur_hw, base_gen, cur_gen))

    def test_fails_closed_on_unreadable_base(self):
        self.assertFalse(gate._dispatch_retirement_credited(
            None, frozenset(), frozenset(), frozenset()))
        self.assertFalse(gate._dispatch_retirement_credited(
            frozenset(), frozenset(), None, frozenset()))


class GeneratedIdentityReconciliation(unittest.TestCase):
    """ P1.2: the gate reconciles the inventory's generated node IDENTITIES
    against the generated printer's actual handler rows — not just the count — so a
    count-preserving identity substitution (relabel an unrelated row as the retired
    node to forge a credit) fails closed."""

    def test_count_preserving_identity_substitution_fails(self):
        sol = next(b for b in gate.discover_backends() if b["target"] == "solidity")
        printer_text = gate._read(sol["printer"])
        real_inv = gate.load_inventory(gate.INVENTORY)
        tampered = json.loads(json.dumps(real_inv))
        # Relabel one generated node identity; the COUNT is unchanged.
        relabeled = False
        for h in tampered["generatedHandlers"]:
            if h.get("target") == "solidity" and h.get("node") == "EnumDecl":
                h["node"] = "ImaginaryDecl"
                relabeled = True
                break
        self.assertTrue(relabeled, "fixture: EnumDecl not found to relabel")
        reasons = []
        with unittest.mock.patch.object(gate, "load_inventory", lambda p: tampered), \
             unittest.mock.patch.object(gate, "_resolve_base_ref",
                                        lambda: "origin/main"):
            gate.check_inventory(sol, printer_text, None, reasons)
        self.assertTrue(
            any("do not match the generated printer" in r for r in reasons),
            f"count-preserving identity substitution not caught: {reasons}")


if __name__ == "__main__":
    unittest.main()

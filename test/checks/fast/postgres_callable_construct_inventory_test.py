#!/usr/bin/env python3
"""[fast] PostgreSQL callable-header construct inventory.

The CallableSig identity is retired only when the complete handwritten header is
gone. Synthetic sources keep the detector mutation-sensitive; committed-state
checks consume the current live-source inventory and never rely on a deleted
emitter path.
"""

import os
import re
import sys
import unittest

from _fastcase import REPO

sys.path.insert(0, os.path.join(REPO, "scripts", "gates"))
import check_target_node_registry as gate  # noqa: E402

# A synthetic handwritten addFunction carrying all four header clauses, so the
# scan LOGIC can be probed clause-by-clause independently of the committed source.
_SYNTH_EMITTER = '''
namespace neutrino::sql {
void addFunction(const Function &fn, ct::Document &doc) {
  doc.add(ct::line("CREATE OR REPLACE FUNCTION " + fn.name + "()"));
  doc.add(ct::line("RETURNS void"));
  doc.add(ct::line("LANGUAGE plpgsql"));
  doc.add(ct::line("AS $$"));
}
}
'''
_SYNTH_HDR = '''
struct PgParam {
  std::string name;
  std::string type;
  std::string render() const { return name + " " + type; }
};
'''
_HEADER_MARKERS = {
    '"CREATE OR REPLACE FUNCTION ': '"__migrated__ ',
    '"RETURNS void"': '"__migrated__"',
    '"LANGUAGE plpgsql"': '"__migrated__"',
    '"AS $$"': '"__migrated__"',
}
def _committed_callable_sites():
    with open(os.path.join(REPO, gate._PG_MODEL_HDR_REL), encoding="utf-8") as fh:
        model_header = fh.read()
    with open(os.path.join(REPO, gate._PG_MODEL_REL), encoding="utf-8") as fh:
        model_source = fh.read()
    return gate.postgres_callable_construct_sites(
        "",
        model_header,
        model_source,
        emitter_path="",
        model_path=gate._PG_MODEL_REL,
    )


class CallableScanLogic(unittest.TestCase):
    def nodes(self, emitter=_SYNTH_EMITTER, hdr=_SYNTH_HDR):
        return {s["node"] for s in gate.postgres_callable_construct_sites(emitter, hdr)}

    def test_synthetic_source_detects_both_sites(self):
        self.assertEqual(self.nodes(), {"CallableSig", "PgParamRender"})

    def test_removing_any_single_header_clause_does_not_retire_callable_sig(self):
        for marker, replacement in _HEADER_MARKERS.items():
            with self.subTest(marker=marker):
                mutated = _SYNTH_EMITTER.replace(marker, replacement, 1)
                self.assertNotIn(marker, mutated, "probe must remove the marker")
                self.assertIn("CallableSig", self.nodes(emitter=mutated),
                              f"removing only {marker!r} must NOT retire CallableSig")

    def test_removing_the_complete_header_retires_callable_sig(self):
        mutated = _SYNTH_EMITTER
        for marker, replacement in _HEADER_MARKERS.items():
            mutated = mutated.replace(marker, replacement, 1)
        self.assertNotIn("CallableSig", self.nodes(emitter=mutated))

    def test_header_clause_in_a_comment_does_not_keep_the_site_alive(self):
        mutated = _SYNTH_EMITTER
        for marker, replacement in _HEADER_MARKERS.items():
            mutated = mutated.replace(marker, replacement, 1)
        mutated += "\n// CREATE OR REPLACE FUNCTION RETURNS void LANGUAGE plpgsql AS $$\n"
        self.assertNotIn("CallableSig", self.nodes(emitter=mutated))

    def test_pg_param_render_retires_only_when_render_removed(self):
        self.assertIn("PgParamRender", self.nodes())
        mutated = re.sub(r"std::string\s+render\s*\(\s*\)\s*const\s*\{[^}]*\}",
                         "", _SYNTH_HDR, count=1)
        self.assertNotIn("PgParamRender", self.nodes(hdr=mutated))


class CallableCommittedState(unittest.TestCase):
    """ ENDPOINT: EVERY callable-framing construct is migrated to a .td node —
    the header (CallableSig), DECLARE (DeclareSection), body block (CallableBody),
    and the `$$;` close (CallableClose). The committed sources carry NO handwritten
    callable grammar (a ZERO callable inventory)."""

    def test_committed_sources_have_zero_callable_handwritten_sites(self):
        self.assertEqual(_committed_callable_sites(), [])

    def test_committed_inventory_has_no_callable_handwritten_site(self):
        inv = gate.load_inventory(gate.INVENTORY)
        callable_hw = [s for s in inv["handwrittenSites"]
                       if s["node"] in ("CallableSig", "PgParamRender",
                                        "DeclareSection", "CallableBody",
                                        "CallableClose")]
        self.assertEqual(callable_hw, [])

    def test_callable_sig_is_a_generated_handler(self):
        inv = gate.load_inventory(gate.INVENTORY)
        self.assertTrue(any(h.get("node") == "CallableSig"
                            for h in inv["generatedHandlers"]))


class DeclareSectionRetirement(unittest.TestCase):
    _EMITTER = '''
void addFunction(const Function &fn, ct::Document &doc) {
  doc.add(ct::block("DECLARE", "", {}));
}
'''
    _MODEL = '''
void printPostgres() {
  out.push_back("v_" + v + " bigint;");
  gate.extraDecls = {"v_claim text;"};
}
'''

    def nodes(self, emitter=None, model=None):
        return {s["node"] for s in gate.postgres_callable_construct_sites(
            self._EMITTER if emitter is None else emitter, "",
            self._MODEL if model is None else model)}

    def test_complete_handwritten_shape_is_detected(self):
        self.assertIn("DeclareSection", self.nodes())

    def test_partial_container_or_line_migration_cannot_retire(self):
        self.assertIn("DeclareSection",
                      self.nodes(emitter=self._EMITTER.replace('"DECLARE"', '"MOVED"')))
        self.assertIn("DeclareSection", self.nodes(model=""))

    def test_complete_replacement_retires_identity(self):
        self.assertNotIn("DeclareSection", self.nodes(emitter="", model=""))

    def test_committed_tree_has_generated_node_and_no_handwritten_site(self):
        sites = _committed_callable_sites()
        self.assertNotIn("DeclareSection", {s["node"] for s in sites})
        inv = gate.load_inventory(gate.INVENTORY)
        self.assertTrue(any(h.get("node") == "DeclareSection"
                            for h in inv["generatedHandlers"]))


class CallableBodyRetirement(unittest.TestCase):
    """ ENDPOINT: the outer body frame is two callable identities, BOTH now
    migrated to generated nodes:
      * CallableBody — the `BEGIN … END;` block frame. Detected while addFunction
        hand-authors a block literal OR constructs ANY `ct::block(...)`; retired
        once addFunction places the pre-rendered body block and constructs no
        block.
      * CallableClose — the trailing `$$;`. Detected while addFunction authors the
        raw `$$;` literal; retired once it consumes the typed close carrier.
    At the endpoint addFunction places OPAQUE section carriers and authors no
    literal, so neither fires (a ZERO callable inventory). The detectors survive to
    credit the base→current retirement (they still fire against the base sources)."""

    # The pre-migration handwritten frame: a ct::block plus the $$; close.
    _EMITTER = '''
void addFunction(const Function &fn, ct::Document &doc) {
  doc.add(ct::block("BEGIN", "END;", std::move(body)));
  doc.add(ct::line("$$;"));
}
'''
    # The ENDPOINT migrated form: addFunction places OPAQUE section carrier nodes
    # directly — no ct::block, no BEGIN/END; literal, no `$$;` literal.
    _MIGRATED = '''
void addFunction(const Function &fn, ct::Document &doc) {
  doc.add(fn.signature.node);
  doc.add(fn.bodyBlock.node);
  doc.add(fn.close.node);
}
'''

    def nodes(self, emitter):
        return {s["node"] for s in gate.postgres_callable_construct_sites(emitter, "", "")}

    def test_complete_handwritten_frame_is_detected(self):
        self.assertIn("CallableBody", self.nodes(self._EMITTER))

    def test_migrated_form_retires_callable_body(self):
        self.assertNotIn("CallableBody", self.nodes(self._MIGRATED))

    def test_migrated_form_retires_both_body_and_close(self):
        # The endpoint carrier form authors no frame literal at all, so BOTH the
        # block frame and the `$$;` close are gone from the committed emitter.
        self.assertEqual(self.nodes(self._MIGRATED), set())

    def test_removing_a_block_frame_literal_cannot_retire_body(self):
        # CallableBody survives while ANY block-frame literal (or the ct::block
        # construction) remains; removing one is not a complete migration.
        for marker in ('"BEGIN"', '"END;"'):
            with self.subTest(marker=marker):
                mutated = self._EMITTER.replace(marker, '"__migrated__"')
                self.assertIn("CallableBody", self.nodes(mutated),
                              f"removing only {marker} must NOT retire CallableBody")

    def test_concatenated_frame_literal_is_still_detected(self):
        # P1-2: a split literal (`"BE" "GIN"`) must not hide the frame — the
        # detector normalizes adjacent string-literal concatenation.
        concat = '''
void addFunction(const Function &fn, ct::Document &doc) {
  doc.add(ct::line("BE" "GIN"));
  addRenderedLines(fn.bodyBlock);
}
'''
        self.assertIn("CallableBody", self.nodes(concat))

    def test_ct_block_construction_alone_is_detected(self):
        # P1-2: re-introducing ANY ct::block in addFunction — even with non-frame
        # literals — is raw callable framing (the migrated addFunction constructs
        # no block); it must keep the site alive.
        wrapped = '''
void addFunction(const Function &fn, ct::Document &doc) {
  doc.add(ct::block("HDR", "FTR", std::move(body)));
}
'''
        self.assertIn("CallableBody", self.nodes(wrapped))

    def test_frame_literal_in_a_comment_does_not_keep_the_site_alive(self):
        commented = '''
void addFunction(const Function &fn, ct::Document &doc) {
  addRenderedLines(fn.bodyBlock);
  // BEGIN END; $$; are the frame literals
}
'''
        self.assertNotIn("CallableBody", self.nodes(commented))

    def test_committed_tree_migrated_callable_body_to_generated(self):
        sites = _committed_callable_sites()
        nodes = {s["node"] for s in sites}
        self.assertNotIn("CallableBody", nodes)
        inv = gate.load_inventory(gate.INVENTORY)
        self.assertTrue(any(h.get("node") == "CallableBody"
                            for h in inv["generatedHandlers"]))
        # CallableBody must NOT linger as a handwritten inventory entry.
        self.assertFalse(any(h.get("node") == "CallableBody"
                             for h in inv["handwrittenSites"]))

    def test_callable_close_migrated_to_generated_zero_inventory(self):
        # The  endpoint: the `$$;` close is a generated handler, absent from
        # the handwritten inventory, and the committed sources carry NO callable
        # handwritten sites at all.
        self.assertEqual(_committed_callable_sites(), [])
        inv = gate.load_inventory(gate.INVENTORY)
        self.assertTrue(any(h.get("node") == "CallableClose"
                            and h.get("target") == "postgres"
                            for h in inv["generatedHandlers"]))
        self.assertFalse(any(h.get("node") == "CallableClose"
                             for h in inv["handwrittenSites"]))

if __name__ == "__main__":
    unittest.main()

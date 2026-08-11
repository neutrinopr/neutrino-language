#!/usr/bin/env python3
"""[fast] : the generalized target-node registry gate discovers the PostgreSQL
backend automatically and gates it NON-VACUOUSLY, mirroring the Solidity lit tamper
matrix. Also pins the three architect P1 fixes:

  P1.2 — the backend model source/header + generated-output names are derived from
         the record's `Target` field (postgres -> PostgresModel.{cpp,h} /
         PostgresTargetNodes.inc / PostgresPrinterHandlers.inc), not the .td stem.
  P1.1 — the ratchet/retirement accounting is per-target (PG reconciles against its
         own generated .inc, its own inventory entries, and its own syntax-authority
         inventory).
  P1.3 — a backend whose Target-derived identity/files are missing is rejected
         explicitly (fail closed), with no Solidity fallback.
"""

import os
import re
import sys
import tempfile
import unittest

from _fastcase import REPO

sys.path.insert(0, os.path.join(REPO, "scripts", "gates"))
import check_target_node_registry as gate  # noqa: E402
sys.path.insert(0, os.path.join(REPO, "scripts", "generators"))
import gen_target_node_registry as generator  # noqa: E402
import check_idiom_table_capability as idiom  # noqa: E402


def _pg_backend():
    return next(b for b in gate.discover_backends() if b["target"] == "postgres")


class BackendDiscovery(unittest.TestCase):
    def test_discovers_both_backends(self):
        targets = {b["target"] for b in gate.discover_backends()}
        self.assertIn("postgres", targets)
        self.assertIn("solidity", targets)

    def test_p1_2_names_derived_from_target_not_stem(self):
        # The PostgreSQL descriptor is derived from the record Target field, not
        # the .td stem. Other backends may use a reviewed thin adapter as their
        # carrier; every descriptor must still resolve all committed files.
        for b in gate.discover_backends():
            # And every derived file must exist (no fallback identity).
            self.assertEqual(gate._backend_identity_reasons(b), [])
        pg = _pg_backend()
        self.assertEqual(os.path.basename(pg["cpp"]), "PostgresModel.cpp")
        self.assertEqual(os.path.basename(pg["hdr"]), "PostgresModel.h")
        self.assertEqual(os.path.basename(pg["inc"]), "PostgresTargetNodes.inc")
        self.assertEqual(os.path.basename(pg["printer"]),
                         "PostgresPrinterHandlers.inc")
        self.assertEqual(pg["macro"], "NEU_PG_PGSTMT_NODE")
        self.assertEqual(pg["model"], "PgStmt")
        self.assertEqual(pg["printer_model"], "PgStmt")
        self.assertEqual(pg["models"], ["PgSchemaDecl", "PgStmt"])
        self.assertEqual(pg["macros"], {
            "PgSchemaDecl": "NEU_PG_PGSCHEMADECL_NODE",
            "PgStmt": "NEU_PG_PGSTMT_NODE",
        })

    def test_p1_3_fail_closed_on_target_derived_file_mismatch(self):
        # A backend whose Target points at a non-existent model source is rejected
        # explicitly (the reviewer's P1.3), not silently defaulted to Solidity.
        pg = dict(_pg_backend())
        pg["cpp"] = os.path.join(REPO, "lib", "backends", "postgres", "NopeModel.cpp")
        reasons = gate._backend_identity_reasons(pg)
        self.assertTrue(any("does not exist" in r for r in reasons), reasons)

    def test_p1_3_fail_closed_on_missing_identity(self):
        broken = {"name": "ghost", "target": None, "model": None, "macro": None,
                  "inc": None, "printer": None, "cpp": None, "hdr": None,
                  "inc_basename": None, "printer_model": None}
        reasons = gate._backend_identity_reasons(broken)
        self.assertTrue(any("could not derive" in r for r in reasons), reasons)


class MultiModelGeneration(unittest.TestCase):
    @staticmethod
    def record(model, sym, ordinal):
        return {
            "sym": sym, "ordinal": ordinal, "handler": sym.lower(),
            "leaf": "true", "feature": "test", "target": "postgres",
            "model": model, "abbrev": "PG", "layout": "line",
            "syntax": f"-- {sym}", "closeSyntax": "", "listField": "",
            "listInner": "", "listOuter": "", "generated": True,
            "fields": [], "enumFields": [], "itemSyntax": "",
            "itemFields": [],
        }

    def test_overlapping_ordinals_generate_disjoint_model_lookups(self):
        recs = [self.record("PgStmt", "StmtProbe", 0),
                self.record("PgSchemaDecl", "SchemaProbe", 0)]
        declarations = [
            {"target": "postgres", "model": "PgStmt", "abbrev": "PG",
             "primary": True},
            {"target": "postgres", "model": "PgSchemaDecl", "abbrev": "PG",
             "primary": False},
        ]
        backend = generator.backend_identity(recs, declarations)
        registry = generator.render("PostgresTargetNodes.td", recs, backend)
        printer = generator.render_printer("PostgresTargetNodes.td", recs, backend)
        self.assertIn("NEU_PG_PGSTMT_NODE(StmtProbe, 0", registry)
        self.assertIn("NEU_PG_PGSCHEMADECL_NODE(SchemaProbe, 0", registry)
        self.assertIn("kPgStmtHandlers", printer)
        self.assertIn("kPgSchemaDeclHandlers", printer)
        self.assertIn("handlerFor(PgStmt::Kind", printer)
        self.assertIn("handlerFor(PgSchemaDecl::Kind", printer)
        self.assertIn("resolvePgStmtField", printer)
        self.assertIn("resolvePgSchemaDeclField", printer)

    def test_primary_role_is_stable_under_record_and_wrapper_order(self):
        declarations = [
            {"target": "postgres", "model": "PgSchemaDecl", "abbrev": "PG",
             "primary": False},
            {"target": "postgres", "model": "PgStmt", "abbrev": "PG",
             "primary": True},
        ]
        recs = [self.record("PgSchemaDecl", "SchemaProbe", 0),
                self.record("PgStmt", "StmtProbe", 0)]
        self.assertEqual(generator.backend_identity(recs, declarations)["model"],
                         "PgStmt")
        self.assertEqual(generator.backend_identity(list(reversed(recs)),
                                                    list(reversed(declarations)))["model"],
                         "PgStmt")

        td = gate._read(_pg_backend()["td"])
        wrappers = idiom.discover_wrappers(idiom.strip_line_comments(td))
        self.assertEqual([model for _wrapper, _target, model in wrappers],
                         ["PgSchemaDecl", "PgStmt"])
        self.assertEqual(_pg_backend()["model"], "PgStmt")

    def test_second_wrapper_record_is_discovered_and_governed(self):
        td = gate._read(_pg_backend()["td"])
        injected = td + '''
def HiddenSchema : PgSchemaNode<0, "hidden-schema", 1, "schema",
                                "line", "CREATE TYPE hidden AS ENUM ('x');",
                                [], 1>;
'''
        reasons = []
        records = idiom.validate_td(injected, reasons)
        self.assertEqual(reasons, [])
        self.assertIn("PgSchemaDecl::HiddenSchema", records)

        printer = gate._read(_pg_backend()["printer"])
        idiom.validate_generated_printer(printer, records, "postgres", reasons)
        self.assertTrue(any("PgSchemaDecl::HiddenSchema" in reason
                            for reason in reasons), reasons)

    def test_forbidden_second_wrapper_record_tamper_bites(self):
        td = gate._read(_pg_backend()["td"])
        injected = td + '''
def HiddenSchema : PgSchemaNode<0, "hidden-schema", 1, "schema",
                                "line", !if(1, "CREATE TYPE hidden;", ""),
                                [], 1>;
'''
        reasons = []
        idiom.validate_td(injected, reasons)
        self.assertTrue(any("bang operators" in reason for reason in reasons), reasons)

    def test_anti_decoration_identity_is_model_qualified(self):
        self.assertNotEqual(gate._qualified("PgStmt", "Same"),
                            gate._qualified("PgSchemaDecl", "Same"))


class PostgresReconciliation(unittest.TestCase):
    def setUp(self):
        self.pg = _pg_backend()
        # The PR-relative ratchet needs a resolvable base; the committed change is
        # per-target-clean against origin/main.
        gate._BASE_REF_OVERRIDE = "origin/main"
        gate._SIMULATE_NO_BASE = False

    def tearDown(self):
        gate._BASE_REF_OVERRIDE = None

    def _check(self, inc=None, printer=None, cpp=None, hdr=None):
        reasons = []
        gate.check(self.pg, inc or self.pg["inc"], printer or self.pg["printer"],
                   cpp or self.pg["cpp"], hdr or self.pg["hdr"], reasons)
        return reasons

    def _tmp(self, text, suffix):
        fd, path = tempfile.mkstemp(suffix=suffix)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        self.addCleanup(os.unlink, path)
        return path

    def test_happy_path_reconciles(self):
        self.assertEqual(self._check(), [])

    def test_generated_set_includes_c3_balanced_invariant_comment(self):
        gen = gate.generated_handlers(gate._read(self.pg["printer"]))
        self.assertEqual({sym for model, _, _, sym in gen if model == "PgStmt"},
                         {"Blank", "Raise", "Assign", "StatusWrite",
                          "LedgerUpsert", "PostingInsert",
                          "ProgressFlag", "PostingIdempotency", "KeyClaimInsert",
                          "CommittedGroupInsert", "QuorumAcceptInsert",
                          "TemporalAcceptInsert", "IdempotentReturn",
                          "EvidenceClaimComment", "PolicyCaseSelect",
                          "EffectLedgerComment", "IdempotencyGuardComment",
                          "BalancedInvariantComment",
                          #  callable-framing migration (endpoint: all four):
                          "CallableSig", "DeclareSection", "CallableBody",
                          "CallableClose",
                          "StatusWriteUpdate", "RaiseArg",
                          "PostingInsertWithMemo",
                          #  family-1: the IF/END IF guard containers
                          # (If = nested block; FlatIf = flat  guard):
                          "If", "FlatIf"})

    def test_inventory_exactly_matches_live_41_handler_surface(self):
        inventory = gate.load_inventory(gate.INVENTORY)
        rows = [row for row in inventory["generatedHandlers"]
                if row.get("target") == "postgres"]
        actual = {
            gate._qualified(model, node)
            for model, _ordinal, target, node
            in gate.generated_handlers(gate._read(self.pg["printer"]))
            if target == "postgres"
        }
        committed = {
            gate._qualified(gate._item_model(row), row["node"])
            for row in rows
        }
        self.assertEqual(len(rows), 41)
        self.assertEqual(committed, actual)
        self.assertEqual(
            {row["path"] for row in rows},
            {"lib/backends/postgres/generated/PostgresPrinterHandlers.inc"})
        self.assertEqual(inventory["handwrittenSites"], [])
        self.assertEqual(inventory["sealedBodyCarriers"], [])

    def test_payload_bearing_blank_cannot_inherit_generic_framing(self):
        # Blank is reviewed framing only while it is fieldless. A placeholder-only
        # template still looks "bare" after placeholder stripping, so mutate BOTH
        # the operand count and syntax to prove the operand closure itself bites.
        printer = gate._read(self.pg["printer"])
        original = ('"Blank", "blank", target_printer::LayoutKind::Blank, true, '
                    '"", "", nullptr, 0')
        payload = ('"Blank", "blank", target_printer::LayoutKind::Blank, true, '
                   '"${payload}", "", kPgStmtBlankFields, 1')
        tampered = printer.replace(original, payload, 1)
        self.assertNotEqual(tampered, printer, "fixture: Blank row anchor moved")
        reasons = self._check(printer=self._tmp(tampered, ".inc"))
        self.assertTrue(
            any("generic-framing Blank must be fieldless" in reason
                for reason in reasons),
            reasons)

    def test_zero_field_records_emit_nullptr_not_empty_array(self):
        # A fieldless generated record must NOT emit an empty C-style
        # FieldBinding array: `k...Fields[] = {}` is a GNU extension, ill-formed
        # under -std=c++17 -pedantic-errors ("zero size arrays are an
        # extension"). The generator omits the array for a 0-field record and the
        # handler passes `nullptr, 0`. Pin BOTH committed backend printer includes
        # (regression for the  Bucket-A IdempotentReturn + the pre-existing
        # Solidity Blank).
        empty_rx = re.compile(r"FieldBinding\s+k\w+Fields\[\]\s*=\s*\{\s*\}\s*;")
        for b in gate.discover_backends():
            text = gate._read(b["printer"])
            self.assertEqual(
                empty_rx.findall(text), [],
                f"{b['printer']}: zero-length FieldBinding array emitted (GNU "
                "extension, ill-formed under -pedantic-errors); a fieldless "
                "record must use nullptr, 0")
        pg = gate._read(_pg_backend()["printer"])
        self.assertRegex(
            pg, r'"IdempotentReturn",[^\n]*, nullptr, 0, nullptr',
            "the fieldless IdempotentReturn handler must pass nullptr, 0")
        self.assertRegex(
            pg, r'"EvidenceClaimComment",[^\n]*, nullptr, 0, nullptr',
            "the fieldless EvidenceClaimComment handler must pass nullptr, 0")
        self.assertRegex(
            pg, r'"IdempotencyGuardComment",[^\n]*, nullptr, 0, nullptr',
            "the fieldless IdempotencyGuardComment handler must pass nullptr, 0")
        self.assertRegex(
            pg, r'"BalancedInvariantComment",[^\n]*, nullptr, 0, nullptr',
            "the fieldless BalancedInvariantComment handler must pass nullptr, 0")

    def test_dropped_registry_record_is_unreachable(self):
        # Remove ProgressFlag from the registry .inc: the generated handler still
        # exists, so it becomes unreachable from the registry.
        inc = gate._read(self.pg["inc"])
        tampered = "\n".join(l for l in inc.splitlines()
                             if "NEU_PG_PGSTMT_NODE(ProgressFlag," not in l) + "\n"
        reasons = self._check(inc=self._tmp(tampered, ".inc"))
        self.assertTrue(any("unreachable from the registry" in r for r in reasons), reasons)

    def test_removed_generated_handler_has_no_dispatch(self):
        # Remove the ProgressFlag generated handler row: the registry kind then has
        # neither a generated nor a handwritten (case) handler.
        printer = gate._read(self.pg["printer"])
        tampered = "\n".join(l for l in printer.splitlines()
                             if '"ProgressFlag"' not in l) + "\n"
        reasons = self._check(printer=self._tmp(tampered, ".inc"))
        self.assertTrue(any("NO generated or handwritten printer handler" in r for r in reasons), reasons)

    def test_retained_handwritten_fallback_rejected(self):
        # Re-grow a handwritten dispatch case for the migrated ProgressFlag kind
        # beside its generated handler: multiply-bound → rejected.
        cpp = gate._read(self.pg["cpp"])
        tampered = cpp + """
codetext::Node toNode(const PgStmt &s) {
  switch (s.kind) {
  case PgStmt::Kind::ProgressFlag:
    return codetext::blank();
  }
  return codetext::blank();
}
"""
        self.assertNotEqual(tampered, cpp)
        reasons = self._check(cpp=self._tmp(tampered, ".cpp"))
        self.assertTrue(any("retained handwritten" in r for r in reasons), reasons)

    def test_header_must_expand_registry(self):
        hdr = gate._read(self.pg["hdr"])
        tampered = hdr.replace('#include "PostgresTargetNodes.inc"',
                               "enum_body_hand_written")
        self.assertNotEqual(tampered, hdr)
        reasons = self._check(hdr=self._tmp(tampered, ".h"))
        self.assertTrue(any("does not expand the generated registry" in r for r in reasons), reasons)


class PerTargetRetirement(unittest.TestCase):
    def test_pg_syntax_authority_inventory_is_the_retirement_source(self):
        # P1.1: PG's retirement credit reads the PostgreSQL syntax-authority
        # inventory, not Solidity's.
        self.assertEqual(gate._SYNTAX_AUTHORITY_REL["postgres"],
                         "scripts/gates/postgres_syntax_authority_inventory.json")
        pg = _pg_backend()
        feats = gate._node_features(pg)
        self.assertEqual(feats.get("ProgressFlag"), "temporal-progress")
        self.assertEqual(feats.get("PostingIdempotency"), "effectful")
        self.assertEqual(feats.get("KeyClaimInsert"), "temporal-claim")
        self.assertEqual(feats.get("CommittedGroupInsert"), "temporal-claim")
        self.assertEqual(feats.get("QuorumAcceptInsert"), "quorum-accept")
        self.assertEqual(feats.get("TemporalAcceptInsert"), "quorum-accept")
        self.assertEqual(feats.get("IdempotentReturn"), "control-flow")
        self.assertEqual(feats.get("EvidenceClaimComment"), "evidence")
        self.assertEqual(feats.get("PolicyCaseSelect"), "temporal-accept-gate")
        self.assertEqual(feats.get("EffectLedgerComment"), "effectful")
        self.assertEqual(feats.get("IdempotencyGuardComment"), "comment")
        self.assertEqual(feats.get("BalancedInvariantComment"), "comment")


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""[fast] : the committed PostgreSQL recipe-builder includes are fresh and
deterministic.

The concrete PgStmt construction for every recipe-extracted node is generated
from PostgresTargetNodes.td (not handwritten). This gate proves the committed
PostgresRecipeBuilders.decl.inc / .inc are byte-identical to a fresh generation
(so the checked-in construction dispatch cannot drift from the schema) and that
generation is deterministic. Regenerate with `make regen-postgres-recipe-builders`.
"""

import os
import contextlib
import io
import shutil
import subprocess
import sys
import unittest

from _fastcase import REPO

sys.path.insert(0, os.path.join(REPO, "scripts", "generators"))
import backend_recipe_gen as gen  # noqa: E402

TD = os.path.join(REPO, "lib/backends/postgres/model/PostgresTargetNodes.td")
INCLUDES = [os.path.join(REPO, "lib/backends")]
DECL = os.path.join(REPO, "lib/backends/postgres/generated/PostgresRecipeBuilders.decl.inc")
DEFN = os.path.join(REPO, "lib/backends/postgres/generated/PostgresRecipeBuilders.inc")
MODEL = os.path.join(REPO, "lib/backends/postgres/model/PostgresModel.h")


def _tblgen():
    for name in ("llvm-tblgen", "llvm-tblgen-15"):
        found = shutil.which(name)
        if found:
            return found
    prefixes = [os.environ.get("LLVM_PREFIX")]
    for probe in (["brew", "--prefix", "llvm"], ["brew", "--prefix", "llvm@15"],
                  ["llvm-config", "--prefix"]):
        try:
            out = subprocess.run(probe, capture_output=True, text=True)
            if out.returncode == 0 and out.stdout.strip():
                prefixes.append(out.stdout.strip())
        except OSError:
            pass
    prefixes += ["/opt/homebrew/opt/llvm", "/usr/local/opt/llvm"]
    for prefix in prefixes:
        if prefix and os.path.exists(os.path.join(prefix, "bin", "llvm-tblgen")):
            return os.path.join(prefix, "bin", "llvm-tblgen")
    return None


class RecipeBuilderFreshness(unittest.TestCase):
    def setUp(self):
        self.tblgen = _tblgen()
        if not self.tblgen:
            self.skipTest("llvm-tblgen not found")

    def test_committed_includes_are_fresh(self):
        decl, defn = gen.pgrb_generate(TD, INCLUDES, self.tblgen)
        with open(DECL, encoding="utf-8") as f:
            self.assertEqual(f.read(), decl,
                             "PostgresRecipeBuilders.decl.inc is stale; run "
                             "`make regen-postgres-recipe-builders`")
        with open(DEFN, encoding="utf-8") as f:
            self.assertEqual(f.read(), defn,
                             "PostgresRecipeBuilders.inc is stale; run "
                             "`make regen-postgres-recipe-builders`")

    def test_generation_is_deterministic(self):
        a = gen.pgrb_generate(TD, INCLUDES, self.tblgen)
        b = gen.pgrb_generate(TD, INCLUDES, self.tblgen)
        self.assertEqual(a, b)

    def test_callable_close_is_extracted(self):
        # The first extracted vertical: CallableClose (ordinal 24) constructs
        # through the generated dispatch.
        _, defn = gen.pgrb_generate(TD, INCLUDES, self.tblgen)
        self.assertIn("case 24u:", defn)
        self.assertIn("PgStmt::Kind::CallableClose", defn)
        self.assertIn("emitCallableClose", defn)

    def test_common_callable_sections_are_schema_derived(self):
        _, defn = gen.pgrb_generate(TD, INCLUDES, self.tblgen)
        for ordinal, kind, entry in (
                (21, "CallableSig", "emitCallableSig"),
                (22, "DeclareSection", "emitDeclareSection"),
                (23, "CallableBody", "emitCallableBody")):
            self.assertIn(f"case {ordinal}u:", defn)
            self.assertIn(f"PgStmt::Kind::{kind}", defn)
            self.assertIn(entry, defn)
        self.assertIn("std::string name", defn)
        self.assertIn(
            "std::vector<std::vector<std::string>> params", defn)
        self.assertIn(
            "std::vector<std::vector<std::string>> items", defn)
        self.assertIn("std::vector<PgStmt> body", defn)
        #  (/): the handwritten section-role -> node-kind dispatch
        # (`generatedSectionNodeKind`) and the guard-carrier membership helper
        # (`generatedIsGuardCarrier`) were retired by the generated typed-root
        # renderer / recipe-owned dispatch. Their freshness assertions are
        # removed here (not restored); recipes now own section selection and the
        # generic renderer dispatches on the typed node, byte-pinned by
        # postgres-model-test and the PostgreSQL golden lit tests.

    def test_common_b1_factories_are_generated_and_handwritten_bodies_retired(
            self):
        decl, defn = gen.pgrb_generate(TD, INCLUDES, self.tblgen)
        for kind, factory in (
                ("Blank", "blank"),
                ("Raise", "raise"),
                ("Assign", "assign"),
                ("If", "ifThen"),
                ("FlatIf", "flatIf"),
                ("StatusWrite", "statusWrite"),
                ("LedgerUpsert", "ledgerUpsert"),
                ("PostingInsert", "postingInsert"),
                ("ProgressFlag", "progressFlag"),
                ("PostingIdempotency", "postingIdempotency"),
                ("KeyClaimInsert", "keyClaimInsert"),
                ("CommittedGroupInsert", "committedGroupInsert"),
                ("QuorumAcceptInsert", "quorumAcceptInsert"),
                ("TemporalAcceptInsert", "temporalAcceptInsert"),
                ("IdempotentReturn", "idempotentReturn"),
                ("PolicyCaseSelect", "policyCaseSelect"),
                ("EffectLedgerComment", "effectLedgerComment"),
                ("IdempotencyGuardComment", "idempotencyGuardComment"),
                ("BalancedInvariantComment", "balancedInvariantComment")):
            self.assertIn(f"PgStmt PgStmt::{factory}(", defn)
            self.assertIn(f"Kind::{kind}", defn)
        self.assertIn("static PgStmt raise(std::string msg);", decl)
        self.assertIn(
            "static PgStmt raiseArg(std::string msg, std::string arg);",
            decl)
        with open(MODEL, encoding="utf-8") as f:
            model = f.read()
        self.assertNotIn("static PgStmt blank() {", model)
        self.assertNotIn("static PgStmt raise(std::string msg", model)
        self.assertNotIn("static PgStmt assign(std::string var", model)
        self.assertNotIn("static PgStmt statusWrite(std::string proc", model)
        self.assertNotIn(
            "static PgStmt ledgerUpsert(std::string ledger", model)
        self.assertNotIn(
            "static PgStmt postingInsert(std::string proc", model)
        for factory in (
                "ifThen", "flatIf", "progressFlag", "postingIdempotency",
                "keyClaimInsert", "committedGroupInsert",
                "quorumAcceptInsert", "temporalAcceptInsert", "policyCaseSelect",
                "effectLedgerComment", "idempotencyGuardComment",
                "balancedInvariantComment", "idempotentReturn"):
            self.assertNotIn(f"static PgStmt {factory}(", model)

    def test_fixed_operand_participates_in_dense_order(self):
        data = gen.load_records(TD, INCLUDES, self.tblgen)
        data["B1LedgerBalanceColumn"]["OperandOrdinal"] = 3
        original = gen.load_records
        try:
            gen.load_records = lambda *_args, **_kwargs: data
            diagnostic = io.StringIO()
            with contextlib.redirect_stderr(diagnostic):
                with self.assertRaises(SystemExit):
                    gen.pgrb_generate(TD, INCLUDES, self.tblgen)
            self.assertIn(
                "LedgerUpsert: duplicate recipe-factory operand ordinal 3",
                diagnostic.getvalue())
        finally:
            gen.load_records = original

    def test_fixed_literal_rejects_non_operand_storage(self):
        data = gen.load_records(TD, INCLUDES, self.tblgen)
        data["B1LedgerBalanceColumn"]["Storage"] = "text"
        data["B1LedgerBalanceColumn"]["OperandOrdinal"] = -1
        original = gen.load_records
        try:
            gen.load_records = lambda *_args, **_kwargs: data
            diagnostic = io.StringIO()
            with contextlib.redirect_stderr(diagnostic):
                with self.assertRaises(SystemExit):
                    gen.pgrb_generate(TD, INCLUDES, self.tblgen)
            self.assertIn(
                "LedgerUpsert.balanceColumn: text requires string",
                diagnostic.getvalue())
        finally:
            gen.load_records = original

    def test_operands_carrier_rejects_duplicate_order(self):
        data = gen.load_records(TD, INCLUDES, self.tblgen)
        data["B1EffectSuffix"]["OperandOrdinal"] = 2
        original = gen.load_records
        try:
            gen.load_records = lambda *_args, **_kwargs: data
            diagnostic = io.StringIO()
            with contextlib.redirect_stderr(diagnostic):
                with self.assertRaises(SystemExit):
                    gen.pgrb_generate(TD, INCLUDES, self.tblgen)
            self.assertIn(
                "EffectLedgerComment: duplicate recipe-factory operand "
                "ordinal 2", diagnostic.getvalue())
        finally:
            gen.load_records = original

    def test_typed_body_rejects_scalar_substitution(self):
        data = gen.load_records(TD, INCLUDES, self.tblgen)
        data["B1GuardBody"]["CppType"] = "string"
        original = gen.load_records
        try:
            gen.load_records = lambda *_args, **_kwargs: data
            diagnostic = io.StringIO()
            with contextlib.redirect_stderr(diagnostic):
                with self.assertRaises(SystemExit):
                    gen.pgrb_generate(TD, INCLUDES, self.tblgen)
            self.assertIn("If.body: body requires stmt-list",
                          diagnostic.getvalue())
        finally:
            gen.load_records = original

    def test_bool_operand_requires_closed_literal_mapping(self):
        data = gen.load_records(TD, INCLUDES, self.tblgen)
        data["B1ProgressValue"]["FalseLiteral"] = ""
        original = gen.load_records
        try:
            gen.load_records = lambda *_args, **_kwargs: data
            diagnostic = io.StringIO()
            with contextlib.redirect_stderr(diagnostic):
                with self.assertRaises(SystemExit):
                    gen.pgrb_generate(TD, INCLUDES, self.tblgen)
            self.assertIn(
                "ProgressFlag.value: bool operand requires closed true/false "
                "literals", diagnostic.getvalue())
        finally:
            gen.load_records = original

    def test_ledger_upsert_consumes_fixed_shape_and_finalized_operand(self):
        """: the column atom is builder-owned; signedAmount stays input."""
        decl, defn = gen.pgrb_generate(TD, INCLUDES, self.tblgen)
        self.assertIn(
            "static PgStmt ledgerUpsert(\n"
            "    std::string ledger,\n"
            "    std::string party,\n"
            "    std::string currency,\n"
            "    std::string signedAmount);",
            decl)
        self.assertIn(
            "std::move(signedAmount),\n"
            '                 "balance"}',
            defn)
        self.assertNotIn("std::string balanceColumn", decl)
        with open(TD, encoding="utf-8") as f:
            target_table = f.read()
        self.assertNotIn(
            "DO UPDATE SET balance = ledger_balance.balance +",
            target_table)
        self.assertIn(
            "DO UPDATE SET ${balanceColumn} = "
            "ledger_balance.${balanceColumn} + (${signedAmount});",
            target_table)

        data = gen.load_records(TD, INCLUDES, self.tblgen)
        data["B1LedgerBalanceColumn"]["FixedLiteral"] = ""
        original = gen.load_records
        try:
            gen.load_records = lambda *_args, **_kwargs: data
            diagnostic = io.StringIO()
            with contextlib.redirect_stderr(diagnostic):
                with self.assertRaises(SystemExit):
                    gen.pgrb_generate(TD, INCLUDES, self.tblgen)
            self.assertIn(
                "LedgerUpsert.balanceColumn: fixed-string requires a "
                "non-empty FixedLiteral", diagnostic.getvalue())
        finally:
            gen.load_records = original


if __name__ == "__main__":
    unittest.main()

"""[fast]  C3: PostgreSQL raw PgStmt syntax authority is zero."""

import json
import os
import tempfile

from _fastcase import PY, REPO, FastCase

PG_DIR = os.path.join(REPO, "lib", "backends", "postgres")
#  R4a () moved the model TUs under model/.
CPP = os.path.join(PG_DIR, "model", "PostgresModel.cpp")
HEADER = os.path.join(PG_DIR, "model", "PostgresModel.h")
INVENTORY = os.path.join(REPO, "scripts", "gates",
                         "postgres_syntax_authority_inventory.json")


class PostgresSyntaxAuthority(FastCase):
    def test_gate_and_non_vacuity_probes(self):
        self.val_ok("zero syntax-authority endpoint",
                    "scripts/gates/check_postgres_syntax_authority.py", "--selftest")

    def _cpp_rejects(self, suffix, expected):
        with open(CPP, encoding="utf-8") as fh:
            src = fh.read()
        fixture = os.path.join(self.tmp, "rogue.cpp")
        with open(fixture, "w", encoding="utf-8") as fh:
            fh.write(src + "\n" + suffix)
        r = self.assert_reject("raw-authority reintroduction must fail", PY,
                               "scripts/gates/check_postgres_syntax_authority.py",
                               "--cpp", fixture)
        self.assertIn(expected, self._tail(r))

    def test_raw_seam_reintroduction_is_rejected(self):
        self._cpp_rejects('void p(){ pgLine(cap, "DROP TABLE postings;"); }\n',
                          "PROHIBITED")

    def test_public_factory_reintroduction_is_rejected(self):
        self._cpp_rejects('void p(){ auto s = PgStmt::line("evil"); }\n',
                          "public PgStmt::line factory reintroduced")

    def test_raw_kind_and_ordinal_cast_are_rejected(self):
        self._cpp_rejects('void p(){ auto k = PgStmt::Kind::Line; }\n',
                          "PROHIBITED Kind::Line")
        self._cpp_rejects(
            'void p(){ auto k = static_cast<PgStmt::Kind>(0); }\n',
            "ordinal raw-kind bypass")

    def test_differently_named_member_factory_is_rejected(self):
        with open(HEADER, encoding="utf-8") as fh:
            header = fh.read()
        #  B1 retired the handwritten `static PgStmt X()` factories (now
        # generated); anchor the injected rogue member on the stable in-struct
        # construction-guard declaration instead.
        anchor = "static void ensureAuthorable(Kind k);"
        self.assertIn(anchor, header)
        fixture = os.path.join(self.tmp, "PostgresModel.h")
        with open(fixture, "w", encoding="utf-8") as fh:
            fh.write(header.replace(
                anchor,
                'static PgStmt verbatim(std::string t) { return PgStmt(Kind::Line, std::move(t), {}, {}, false, {}, {}); }\n  ' + anchor,
                1))
        r = self.assert_reject("renamed raw member factory must fail", PY,
                               "scripts/gates/check_postgres_syntax_authority.py",
                               "--dir", self.tmp)
        self.assertIn("PROHIBITED Kind::Line", self._tail(r))

    def test_constructor_guard_detachment_is_rejected(self):
        with open(HEADER, encoding="utf-8") as fh:
            header = fh.read()
        with open(CPP, encoding="utf-8") as fh:
            model = fh.read()
        with tempfile.TemporaryDirectory(dir=self.tmp) as d:
            with open(os.path.join(d, "PostgresModel.h"), "w", encoding="utf-8") as fh:
                fh.write(header.replace("kind((ensureAuthorable(k), k))", "kind(k)"))
            with open(os.path.join(d, "PostgresModel.cpp"), "w", encoding="utf-8") as fh:
                fh.write(model)
            r = self.assert_reject("detached canonical ctor guard must fail", PY,
                                   "scripts/gates/check_postgres_syntax_authority.py",
                                   "--dir", d)
            self.assertIn("DETACHED", self._tail(r))

    def test_old_constructor_probe_completion_is_rejected(self):
        self._cpp_rejects(
            "namespace neutrino::postgres_model { struct PgStmtCtorProbe { "
            "static PgStmt go(); }; }\n",
            "PROHIBITED")

    def test_inventory_is_explicit_zero_endpoint(self):
        with open(INVENTORY, encoding="utf-8") as fh:
            inv = json.load(fh)
        self.assertEqual(inv["kind"], "neutrino.postgres-syntax-authority.v2")
        self.assertEqual(inv["baseline"], 0)
        self.assertEqual(inv["executable"], [])
        self.assertEqual(inv["comments"], [])
        self.assertNotIn("implMembers", inv)
        self.assertIn("prohibited", inv["scope"].lower())


if __name__ == "__main__":
    import unittest
    unittest.main()

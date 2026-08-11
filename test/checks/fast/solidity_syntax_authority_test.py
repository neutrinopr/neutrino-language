"""[fast]  endpoint: the Solidity statement-syntax-authority PROHIBITION gate.

 reached its endpoint — every construct is a typed SolidityTargetNodes.td node
and the raw RawCap/rawLine/rawBlock seam was DELETED. The gate is no longer a
ratchet; it PROHIBITS any raw statement authoring (the only legal count is zero).
Here we smoke the gate on committed source, run its non-vacuity reintroduction
probes, and assert the fail-closed direction directly (a re-added raw site — code,
comment, or off-TU wrapper — must reject) plus the zero-endpoint invariant.
"""

import glob
import json
import os
import shutil
import unittest

from _fastcase import PY, REPO, FastCase

SOL_DIR = os.path.join(REPO, "lib", "backends", "solidity")
CPP = os.path.join(SOL_DIR, "provider", "SolidityTargetAdapter.cpp")
HDR = os.path.join(SOL_DIR, "provider", "SolidityTargetAdapter.h")
INVENTORY = os.path.join(REPO, "scripts", "gates",
                         "solidity_syntax_authority_inventory.json")
# The raw seam is deleted. Inject at the exact typed-node -> CodeText adapter
# ownership point so the probe remains live after the monolith split.
ANCHOR = "codetext::Node toNode(const SolStmt &s) {"


class SoliditySyntaxAuthority(FastCase):
    def test_gate_and_probes_pass_on_committed_source(self):
        # --selftest runs the gate on the committed source AND its reintroduction
        # probes (re-added seam line/block, seam-as-value, public factory, aggregate,
        # field mutation, direct aggregate, computed arg, comment, off-TU wrapper).
        self.val_ok("syntax-authority gate + non-vacuity probes", "scripts/gates/check_solidity_syntax_authority.py", "--selftest")

    def test_new_executable_raw_site_is_rejected(self):
        # The fail-closed direction, asserted directly: a re-added raw executable
        # statement is PROHIBITED and must reject at committed count zero.
        with open(CPP, encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn(ANCHOR, src, "test anchor drifted; update ANCHOR")
        rogue = os.path.join(self.tmp, "rogue.cpp")
        with open(rogue, "w", encoding="utf-8") as fh:
            fh.write(src.replace(
                ANCHOR,
                ANCHOR + '\n  body.push_back(rawLine(cap, "selfdestruct(payable(msg.sender));"));'))
        r = self.assert_reject("a re-added raw executable authoring site must fail",
                               PY, "scripts/gates/check_solidity_syntax_authority.py", "--cpp", rogue)
        self.assertIn("PROHIBITED", self._tail(r))

    def test_differently_named_member_factory_is_rejected(self):
        # The review P1: a DIFFERENTLY NAMED SolStmt member that reaches the private
        # ctor to author a raw Kind::Line with a COMPUTED operand — the exact bypass a
        # name-based scanner missed. The Kind-level prohibition must catch it. Copy the
        # backend into a temp dir, splice the member beside the generated Emit
        # declarations, and scan the dir.
        d = os.path.join(self.tmp, "sol")
        os.makedirs(d)
        #  R1: the backend is now split into structural subdirs; flatten the
        # source/generated files back into one dir (as the pre-move layout was) so
        # the gate scans a single backend directory. test/ stays excluded.
        for f in glob.glob(os.path.join(SOL_DIR, "*")):
            if os.path.isfile(f):
                shutil.copy(f, d)
        for sub in ("provider", "harness", "generated", "model", "recipes"):
            for f in glob.glob(os.path.join(SOL_DIR, sub, "*")):
                if os.path.isfile(f):
                    shutil.copy(f, d)
        h = os.path.join(d, "SolidityTargetAdapter.h")
        with open(h, encoding="utf-8") as fh:
            src = fh.read()
        anchor = '#include "SolidityEmitBuilderDecls.inc"'
        self.assertIn(anchor, src, "header anchor drifted; update the test")
        member = anchor + "\n  static SolStmt verbatim(std::string t) { return SolStmt(Kind::Line, {std::move(t)}); }"
        with open(h, "w", encoding="utf-8") as fh:
            fh.write(src.replace(anchor, member, 1))
        r = self.run_cmd(PY, "scripts/gates/check_solidity_syntax_authority.py", "--dir", d)
        self.assertNotEqual(r.returncode, 0, "a differently named raw-authoring member must reject")
        out = r.stdout.decode("utf-8", "replace") if r.stdout else ""
        self.assertIn("PROHIBITED", out)
        self.assertIn("Kind::Line", out)

    def test_old_constructor_probe_completion_is_rejected(self):
        # 's exact former exploit: restore the production friend grant,
        # complete its namespace-scope name in another TU, and bypass
        # localDecl's separator validation through the private constructor.
        d = os.path.join(self.tmp, "sol")
        os.makedirs(d)
        #  R1: the backend is now split into structural subdirs; flatten the
        # source/generated files back into one dir (as the pre-move layout was) so
        # the gate scans a single backend directory. test/ stays excluded.
        for f in glob.glob(os.path.join(SOL_DIR, "*")):
            if os.path.isfile(f):
                shutil.copy(f, d)
        for sub in ("provider", "harness", "generated", "model", "recipes"):
            for f in glob.glob(os.path.join(SOL_DIR, sub, "*")):
                if os.path.isfile(f):
                    shutil.copy(f, d)
        h = os.path.join(d, "SolidityTargetAdapter.h")
        with open(h, encoding="utf-8") as fh:
            src = fh.read()
        anchor = "\n};\n\n// The GENERATED node-metadata table"
        self.assertIn(anchor, src, "friend-completion anchor drifted")
        restored = ("\n  friend struct SolStmtCtorProbe;\n};\n\n"
                    "struct SolStmtCtorProbe;\n\n"
                    "// The GENERATED node-metadata table")
        with open(h, "w", encoding="utf-8") as fh:
            fh.write(src.replace(anchor, restored, 1))
        with open(os.path.join(d, "CtorEscape.cpp"), "w", encoding="utf-8") as fh:
            fh.write(
                "namespace neutrino::solidity_model { struct SolStmtCtorProbe { "
                "static SolStmt go() { return SolStmt(SolStmt::Kind::LocalDecl, "
                "{std::string(\"uint256 x; selfdestruct(); //\"), "
                "std::string(\"ignored\"), std::string(\"0\")}, {}); } }; }\n")
        r = self.run_cmd(PY, "scripts/gates/check_solidity_syntax_authority.py",
                         "--dir", d)
        self.assertNotEqual(r.returncode, 0,
                            "the retired constructor friend must reject")
        out = r.stdout.decode("utf-8", "replace") if r.stdout else ""
        self.assertIn("constructor capability reintroduced", out)

    def test_new_comment_site_is_prohibited(self):
        # No reviewed-comment seam survives the endpoint: a re-added single-line `//`
        # comment authored through a raw call is ALSO prohibited (not reconciled).
        with open(CPP, encoding="utf-8") as fh:
            src = fh.read()
        fixture = os.path.join(self.tmp, "comment.cpp")
        with open(fixture, "w", encoding="utf-8") as fh:
            fh.write(src.replace(ANCHOR, ANCHOR + '\n  body.push_back(rawLine(cap, "// fresh doc line"));'))
        r = self.assert_reject("a re-added comment authoring site must be prohibited",
                               PY, "scripts/gates/check_solidity_syntax_authority.py", "--cpp", fixture)
        self.assertIn("PROHIBITED", self._tail(r))

    def test_header_wrapper_is_discovered_and_rejected(self):
        # PROVE real recursive/header surface discovery (not an in-memory map insert):
        # copy the whole backend into a temp dir, drop a rogue header wrapper, and run
        # the gate over that dir — a raw seam wrapper in ANY other TU/header must be
        # found and rejected (it is also a compile error IRL, since the seam is
        # deleted; this proves the gate's recursive discovery).
        d = os.path.join(self.tmp, "sol")
        os.makedirs(d)
        for f in glob.glob(os.path.join(SOL_DIR, "*")):
            if os.path.isfile(f):
                shutil.copy(f, d)
        with open(os.path.join(d, "RawWrapper.h"), "w", encoding="utf-8") as fh:
            fh.write('inline SolStmt mk() { return rawLine("selfdestruct();"); }\n')
        r = self.run_cmd(PY, "scripts/gates/check_solidity_syntax_authority.py", "--dir", d)
        self.assertNotEqual(r.returncode, 0, "a rogue header wrapper must reject")
        out = r.stdout.decode("utf-8", "replace") if r.stdout else ""
        self.assertIn("RawWrapper.h", out)
        self.assertIn("PROHIBITED", out)

    def test_inventory_surface_is_at_the_zero_endpoint(self):
        #  reached its endpoint: every raw construct migrated to a typed .td node
        # and the seam was deleted. Non-vacuity is the fail-closed reintroduction
        # tests above (which prove the prohibition still bites at count zero); the
        # inventory is the vestigial zero-site artifact the  meta-gate counts.
        with open(INVENTORY, encoding="utf-8") as fh:
            inv = json.load(fh)
        self.assertEqual(inv["baseline"], 0,
                         "raw authoring is prohibited; a nonzero baseline is a regression")
        self.assertEqual(inv["baseline"], len(inv["executable"]),
                         "inventory baseline must equal its listed executable sites")
        self.assertEqual(len(inv["comments"]), 0,
                         "no reviewed-comment authoring survives the endpoint")


if __name__ == "__main__":
    unittest.main()

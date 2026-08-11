"""[fast] : decision-path MLIR/target-dialect dependency lock.

The gate is build-free: it derives registry-backed backend decision targets from
TargetRegistry.def + lib/**/CMakeLists.txt and pins their legalizers/projection
core to zero MLIR dialect / PDL / rewrite surface.
"""

import os
import shutil
import unittest

from _fastcase import FastCase, REPO


class DecisionPathLock(FastCase):
    def test_decision_path_lock_holds(self):
        self.val_ok("decision path has no MLIR target-dialect lowering surface",
                    "scripts/gates/check_decision_path_lock.py")

    def test_selftest_is_non_vacuous(self):
        self.val_ok("decision-path lock bites on independent red-line probes",
                    "scripts/gates/check_decision_path_lock.py", "--selftest")

    def test_dialect_include_fails_closed(self):
        dst = os.path.join(self.tmp, "SolidityTargetValidation.cpp")
        shutil.copy(
            os.path.join(REPO, "lib/backends/solidity/provider/SolidityTargetValidation.cpp"),
            dst,
        )
        with open(dst, "a", encoding="utf-8") as f:
            f.write('\n#include "Neutrino/NeutrinoDialect.h"\n')
        self.val_reject("MLIR dialect include in legalizer",
                        "scripts/gates/check_decision_path_lock.py", "--file", dst)

    def test_generic_mlir_func_dialect_fails_closed(self):
        dst = os.path.join(self.tmp, "FuncDialect.cpp")
        with open(dst, "w", encoding="utf-8") as f:
            f.write('#include "mlir/Dialect/Func/IR/FuncOps.h"\n'
                    "void useDialect(mlir::func::FuncOp op) { (void)op; }\n")
        self.val_reject("generic MLIR Func dialect include in decision path",
                        "scripts/gates/check_decision_path_lock.py", "--file", dst)

    def test_rewrite_pattern_fails_closed(self):
        dst = os.path.join(self.tmp, "PostgresModel.cpp")
        shutil.copy(os.path.join(REPO, "lib/backends/postgres/PostgresModel.cpp"), dst)
        with open(dst, "a", encoding="utf-8") as f:
            f.write('\n#include "mlir/IR/PatternMatch.h"\n'
                    "struct BadPattern : mlir::RewritePattern {};\n")
        self.val_reject("PDL/rewrite API in decision path",
                        "scripts/gates/check_decision_path_lock.py", "--file", dst)

    def test_comment_stripping_is_string_aware(self):
        dst = os.path.join(self.tmp, "StringComment.cpp")
        with open(dst, "w", encoding="utf-8") as f:
            f.write('const char *url = "http://example"; '
                    "struct BadPattern : mlir::RewritePattern {};\n")
        self.val_reject("RewritePattern after // inside string",
                        "scripts/gates/check_decision_path_lock.py", "--file", dst)

    def test_comment_stripping_is_raw_string_aware(self):
        dst = os.path.join(self.tmp, "RawStringComment.cpp")
        with open(dst, "w", encoding="utf-8") as f:
            f.write('const char *raw = R"(// not a comment)"; '
                    "struct BadPattern : mlir::RewritePattern {};\n")
        self.val_reject("RewritePattern after // inside raw string",
                        "scripts/gates/check_decision_path_lock.py", "--file", dst)

    def test_target_op_construction_fails_closed(self):
        dst = os.path.join(self.tmp, "TargetPrinter.cpp")
        shutil.copy(os.path.join(REPO, "lib/codetext/TargetPrinter.cpp"), dst)
        with open(dst, "a", encoding="utf-8") as f:
            f.write("\nvoid bad(mlir::OpBuilder &b, mlir::Location loc) {\n"
                    "  b.create<neutrino::DebitOp>(loc);\n"
                    "}\n")
        self.val_reject("target-op construction in shared printer core",
                        "scripts/gates/check_decision_path_lock.py", "--file", dst)

    def test_ods_record_fails_closed_without_forbidding_def_token(self):
        dst = os.path.join(self.tmp, "SolidityTargetNodes.td")
        shutil.copy(os.path.join(REPO, "lib/backends/solidity/model/SolidityTargetNodes.td"), dst)
        # Existing printer `def ... : SolNode<...>` records must remain allowed;
        # adding an actual ODS op/dialect record must fail.
        with open(dst, "a", encoding="utf-8") as f:
            f.write('\ninclude "mlir/IR/OpBase.td"\n'
                    'def BadDialect : Dialect { let name = "bad"; }\n')
        self.val_reject("ODS dialect record in printer TableGen surface",
                        "scripts/gates/check_decision_path_lock.py", "--file", dst)

    def test_indirect_neutrino_ods_record_fails_closed(self):
        dst = os.path.join(self.tmp, "IndirectNeutrinoOp.td")
        with open(dst, "w", encoding="utf-8") as f:
            f.write('include "Neutrino/NeutrinoOps.td"\n'
                    'def BadDecisionOp : Neutrino_Op<"bad_decision", []>;\n')
        self.val_reject("indirect Neutrino ODS op ancestry",
                        "scripts/gates/check_decision_path_lock.py", "--file", dst)


if __name__ == "__main__":
    unittest.main()

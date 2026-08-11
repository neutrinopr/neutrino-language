"""[fast] M5 R4 (): renderer include-boundary lock — a positive allowlist keeps
renderer TUs on the capability-spec contract (no ProcedureView/kernel/parser reach-back).

NOTE: distinct from the full-tier `renderer-include-lock` CTest (a build-time structural sweep
extracted from run_cpp_tests.sh [89]). This fast-tier check drives check_renderer_includes.py's
positive allowlist + negative injections with NO build.
"""

import os
import shutil
import unittest

from _fastcase import FastCase, REPO


class RendererIncludeBoundary(FastCase):
    def test_allowlist_holds(self):
        self.val_ok("renderer include allowlist (all migrated renderers)",
                    "scripts/gates/check_renderer_includes.py")

    def test_forbidden_view_include_fails_closed(self):
        # Copy a spec renderer under its own name so the own-header resolves, inject Neutrino/View.h,
        # and prove it is rejected.
        dst = os.path.join(self.tmp, "GenViewsSpec.cpp")
        shutil.copy(os.path.join(REPO, "lib/views/GenViewsSpec.cpp"), dst)
        with open(dst, "a") as f:
            f.write('#include "Neutrino/View.h"\n')
        self.val_reject("forbidden ProcedureView include in a renderer TU",
                        "scripts/gates/check_renderer_includes.py", "--file", dst)

    def test_analysis_reachback_fails_closed(self):
        # A spec-JSON renderer must NOT reach ProcedureView via the shared analyses — Analysis.h is
        # forbidden for EVERY renderer now (the former GenSlot exception is retired, ).
        dst = os.path.join(self.tmp, "GenPostgresSpec.cpp")
        shutil.copy(os.path.join(REPO, "lib/backends/postgres/GenPostgresSpec.cpp"), dst)
        with open(dst, "a") as f:
            f.write('#include "Neutrino/Analysis.h"\n')
        self.val_reject("spec renderer reaching ProcedureView via Analysis.h",
                        "scripts/gates/check_renderer_includes.py", "--file", dst)


if __name__ == "__main__":
    unittest.main()

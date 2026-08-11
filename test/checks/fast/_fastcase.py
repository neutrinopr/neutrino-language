"""Shared base for the fast validator tier ( /  S5c).

The fast tier is the no-build PR smoke gate (docs/testing/TESTING.md): the stdlib-Python contract
validators run against their committed positive + negative fixtures, catching gross breakage
of a validator or its fixtures before paying for the MLIR build. The precise per-code behavior
is pinned by the full tier.

This replaces the bash harness (`test/checks/fast/_harness.sh` + `scripts/run_fast_checks.sh`):
Python owns the validators, so the tier is Python too (stdlib `unittest`) — no shell glue. Each
family is a `*_test.py` module registered as its own labelled CTest test (`ctest -L fast`) AND
discovered by `make test-fast` (`python3 -m unittest`). Standard library only; no build, no
MLIR, no third-party deps — so the `fast (no build)` CI job stays toolchain-free.

`FastCase` provides the harness the shells used:
  - `val_ok` / `val_reject` — exit-code smoke assertions on `python3 scripts/<validator> ...`
    (the fail-closed direction is `val_reject`: the command MUST exit non-zero);
  - `run_cmd` — a raw command runner (cwd = repo root) for the few non-validator invocations;
  - `self.tmp` — an auto-cleaned scratch dir (per test);
  - `require_floor` — the NON-VACUOUS guard: a family fails closed if it discovered/asserted
    fewer fixtures than its known floor, so a wrong dir / renamed / eroded fixture set can never
    pass on zero work (the anti-vacuous-pass contract, //).
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# Repo root: this file is test/checks/fast/_fastcase.py -> three levels up. Independent of cwd, so a
# test works whether invoked by `ctest` (from the build dir) or `python3 -m unittest` (from anywhere).
REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))

# The interpreter running the suite — used verbatim for the `python3 scripts/...` validator calls so
# the tier runs under one Python (matches the old `python3` on PATH, but pinned to this process).
PY = sys.executable


class FastCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="neutrino_fast.")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def run_cmd(self, *cmd, input=None):
        """Run a command (cwd = repo root); return the CompletedProcess with combined output."""
        return subprocess.run(
            [str(c) for c in cmd], cwd=REPO, input=input,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    def _tail(self, r):
        return r.stdout.decode("utf-8", "replace")[-1500:] if r.stdout else ""

    def assert_ok(self, desc, *cmd, **kw):
        r = self.run_cmd(*cmd, **kw)
        self.assertEqual(r.returncode, 0, f"{desc} (expected ok)\n{self._tail(r)}")
        return r

    def assert_reject(self, desc, *cmd, **kw):
        r = self.run_cmd(*cmd, **kw)
        self.assertNotEqual(r.returncode, 0, f"{desc} (expected fail-closed / non-zero exit)")
        return r

    # Validator convenience wrappers: `python3 scripts/<script> <args...>`.
    def val_ok(self, desc, script, *args, **kw):
        return self.assert_ok(desc, PY, script, *args, **kw)

    def val_reject(self, desc, script, *args, **kw):
        return self.assert_reject(desc, PY, script, *args, **kw)

    # JSON read/mutate/write helpers (context-managed, so no ResourceWarning), used by the tamper
    # negatives that mutate a committed artifact into a scratch fixture.
    def load_json(self, path):
        with open(path) as f:
            return json.load(f)

    def dump_json(self, obj, path):
        with open(path, "w") as f:
            json.dump(obj, f)
        return path

    def require_floor(self, what, count, minimum):
        """Non-vacuous floor: fail closed if fewer than `minimum` fixtures were exercised."""
        self.assertGreaterEqual(
            count, minimum,
            f"non-vacuous: {what} discovered {count}, expected >= {minimum} "
            "(empty or eroded fixture set?)")

    # Deterministic glob relative to the repo root (sorted, files only). `**` is recursive, so a
    # `dir/**/*.json` pattern matches every depth like the shells' `find` (and plain patterns are
    # unaffected).
    def globr(self, pattern):
        import glob
        return sorted(
            p for p in glob.glob(os.path.join(REPO, pattern), recursive=True)
            if os.path.isfile(p))

    def curated_members(self):
        """Receipt-verify and return the pack-only curated release corpus."""
        gates = os.path.join(REPO, "scripts", "gates")
        if gates not in sys.path:
            sys.path.insert(0, gates)
        import m6_pack_resolver

        manifest = self.load_json(
            os.path.join(REPO, "docs", "m6-curated-example-corpus.json")
        )
        return m6_pack_resolver.resolve_members(manifest, repo=Path(REPO))

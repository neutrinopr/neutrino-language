#!/usr/bin/env python3
"""Phase 11 — backend validation hardening.

Runs target-native validators over generated backend artifacts and emits a
deterministic validation report (`validation.json` + `diagnostics.json`, the same
conventions the agent layer consumes).

Checks:
  - solc --standard-json compile of the generated Solidity  [MANDATORY]
  - Slither static analysis of the generated Solidity        [optional]
  - libpg_query (pglast) parse of the generated SQL          [optional]

`ok` is true iff every MANDATORY check passed. Optional checks are reported but
do not gate. Real execution checks (Foundry / docker+psql) stay in
`make solidity-test` / `make db-test`.

  validate_backends.py --solidity DIR --postgres DIR --out DIR [--solc PATH]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys


def solc_standard_json(soldir, solc):
    """MANDATORY: compile every src/*.sol via the solc standard-json interface."""
    srcs = sorted(glob.glob(os.path.join(soldir, "src", "*.sol")))
    if not srcs:
        return {"backend": "solidity", "tool": "solc --standard-json", "mandatory": True,
                "status": "fail", "message": "no src/*.sol found"}
    sources = {os.path.basename(p): {"content": open(p).read()} for p in srcs}
    std_in = {"language": "Solidity", "sources": sources,
              "settings": {"outputSelection": {"*": {"*": ["abi"]}}}}
    try:
        proc = subprocess.run([solc, "--standard-json"], input=json.dumps(std_in),
                              capture_output=True, text=True)
    except OSError as e:
        # Missing/non-executable solc: a MANDATORY tool is unavailable -> a
        # deterministic failed report, not a Python traceback.
        return {"backend": "solidity", "tool": "solc --standard-json", "mandatory": True,
                "status": "fail", "message": f"solc not runnable ({solc}): {e}"}
    try:
        out = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"backend": "solidity", "tool": "solc --standard-json", "mandatory": True,
                "status": "fail", "message": (proc.stderr or proc.stdout)[:400]}
    errors = [e for e in out.get("errors", []) if e.get("severity") == "error"]
    warnings = [e for e in out.get("errors", []) if e.get("severity") == "warning"]
    return {"backend": "solidity", "tool": "solc --standard-json", "mandatory": True,
            "status": "pass" if not errors else "fail",
            "errors": len(errors), "warnings": len(warnings),
            "messages": [e.get("formattedMessage", e.get("message", "")).strip() for e in errors[:5]]}


def slither(soldir, solc):
    """Optional: Slither static analysis on the single generated contract.

    Runs on an isolated copy (no foundry.toml) and forces the solc framework so
    crytic-compile compiles the lone file with solc directly — never invoking
    forge. Reports `pass` only when Slither actually analyzed (success:true);
    a present-but-broken Slither is `error`, not a false `pass`.
    """
    import tempfile
    if shutil.which("slither") is None:
        return {"backend": "solidity", "tool": "slither", "mandatory": False, "status": "skipped",
                "message": "slither not installed"}
    srcs = sorted(glob.glob(os.path.join(soldir, "src", "*.sol")))
    if not srcs:
        return {"backend": "solidity", "tool": "slither", "mandatory": False, "status": "skipped"}
    work = tempfile.mkdtemp(prefix="slither_")
    f = os.path.join(work, os.path.basename(srcs[0]))
    shutil.copy(srcs[0], f)
    outjson = os.path.join(work, "slither.json")
    proc = subprocess.run(["slither", f, "--solc", solc,
                           "--compile-force-framework", "solc", "--json", outjson],
                          capture_output=True, text=True, cwd=work)
    success, findings = False, None
    if os.path.exists(outjson):
        try:
            rep = json.load(open(outjson))
            success = bool(rep.get("success"))
            findings = len(rep.get("results", {}).get("detectors", []))
        except Exception:
            pass
    shutil.rmtree(work, ignore_errors=True)
    if success:
        return {"backend": "solidity", "tool": "slither", "mandatory": False,
                "status": "pass", "findings": findings}
    return {"backend": "solidity", "tool": "slither", "mandatory": False, "status": "error",
            "message": (proc.stderr or proc.stdout).strip().splitlines()[-1][:200] if (proc.stderr or proc.stdout) else "slither did not produce a report"}


def pglast_parse(pgdir):
    """Optional: libpg_query (pglast) parse of the generated SQL."""
    try:
        import pglast
    except Exception:
        return {"backend": "postgres", "tool": "libpg_query (pglast)", "mandatory": False,
                "status": "skipped", "message": "pglast not installed"}
    files = [f for f in ("schema.sql", "procedure.sql", "reconciliation.sql")
             if os.path.exists(os.path.join(pgdir, f))]
    if not files:
        # Nothing to validate is not a pass — an empty/missing postgres dir would
        # otherwise report status:"pass", filesParsed:0, which falsely implies the
        # SQL was checked. Skip honestly (this is an optional check).
        return {"backend": "postgres", "tool": "libpg_query (pglast)", "mandatory": False,
                "status": "skipped", "message": "no SQL files found "
                "(schema.sql/procedure.sql/reconciliation.sql)", "filesParsed": 0}
    bad = []
    for f in files:
        try:
            pglast.parse_sql(open(os.path.join(pgdir, f)).read())
        except Exception as e:
            bad.append({"file": f, "error": str(e)[:200]})
    return {"backend": "postgres", "tool": "libpg_query (pglast)", "mandatory": False,
            "status": "pass" if not bad else "fail", "filesParsed": len(files), "errors": bad}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--solidity", required=True)
    ap.add_argument("--postgres", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--solc", default=shutil.which("solc") or "solc")
    args = ap.parse_args()

    checks = [solc_standard_json(args.solidity, args.solc),
              slither(args.solidity, args.solc),
              pglast_parse(args.postgres)]
    ok = all(c["status"] == "pass" for c in checks if c["mandatory"])

    os.makedirs(args.out, exist_ok=True)
    report = {"kind": "neutrino.validation-report", "version": "0.1.0", "ok": ok, "checks": checks}
    with open(os.path.join(args.out, "validation.json"), "w") as f:
        json.dump(report, f, indent=2)
    diags = []
    for c in checks:
        # Record both hard failures and optional-tool errors. A "fail" gates only
        # when mandatory (error); an optional "fail"/"error" (e.g. a present-but-
        # broken Slither) is surfaced as a warning so it isn't silently dropped.
        if c["status"] not in ("fail", "error"):
            continue
        sev = "error" if (c["mandatory"] and c["status"] == "fail") else "warning"
        code = f"{c['backend']}.validation_failed" if c["status"] == "fail" \
            else f"{c['backend']}.validation_error"
        diags.append({"severity": sev, "code": code,
                      "message": f"{c['tool']}: {c.get('message') or c.get('messages') or c.get('errors')}"})
    with open(os.path.join(args.out, "diagnostics.json"), "w") as f:
        json.dump({"ok": ok, "diagnostics": diags}, f, indent=2)

    for c in checks:
        m = "mandatory" if c["mandatory"] else "optional"
        extra = c.get("warnings", c.get("findings", c.get("filesParsed", "")))
        print(f"  {c['status']:7} [{m}] {c['backend']}: {c['tool']}"
              + (f"  ({extra})" if extra != "" else ""))
    print(f"\nvalidation {'OK' if ok else 'FAILED'} -> {os.path.join(args.out, 'validation.json')}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

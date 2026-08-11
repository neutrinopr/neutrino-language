#!/usr/bin/env python3
"""M3 native build gate for generated sample code artifacts ().

M3 must prove the strategy  samples are not just accepted by Neutrino's syntax/JSON
validators: any artifact a sample *claims as generated code* (Solidity/EVM, PostgreSQL/SQL,
JVM/Kotlin/Java, Rust/WASM, …) must compile/validate with its **native** target toolchain,
or be explicitly marked metadata-only / future-profile and excluded from native compilation —
so M4 never receives deterministic-but-unbuildable artifacts.

This gate reads the sample portfolio matrix (examples/m3-sample-portfolio.json, ) — which
classifies every committed artifact as native-validated / json-schema-validated / metadata-only
/ future-profile-deferred () — and enforces, fail-closed:

  - **No mislabelled buildable code.** A committed artifact whose extension is a native target
    language (.sol/.sql/.kt/.java/.rs/.wasm) MUST be classified `native-validated` — it can
    never be hidden as json-schema-validated / metadata-only / future-profile-deferred.
  - **Native build for claimed code (`--run`).** For each committed native-target artifact, the
    gate runs its native toolchain (e.g. `solc` for `.sol`); a missing toolchain or a compile
    failure fails the gate. There must be a wired native gate for the target, or it cannot be
    claimed as committed native code (mark it future-profile-deferred instead).
  - **Honest non-code classification.** `.neu` sources are native-validated (translator/
    generator), JSON sidecars are json-schema-validated.

It also emits a machine-readable release-note build summary (kind
`neutrino.m3-native-build-summary`) so release notes can state precisely which sample artifacts
are native-compiled, translator/JSON-validated, metadata-only, or deferred to M4. The M3/M4
boundary holds: this gate BUILDS/validates generated code; it never RUNS executable instances.

  native_build_gate.py [--portfolio FILE] [--run] [--summary-out FILE]
Exit 0 ok / 1 violations / 2 usage.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
NATIVE_VALIDATED = "native-validated"
# committed file extension -> (target name, native toolchain command builder | None)
TARGET_LANGUAGES = {
    ".sol": "solidity",
    ".sql": "postgres",
    ".kt": "jvm",
    ".java": "jvm",
    ".rs": "rust",
    ".wasm": "wasm",
}
# targets with a wired native build/validate step in this gate
WIRED_NATIVE_GATES = {"solidity"}
SOURCE_EXPECTED = {".neu": "native-validated", ".json": "json-schema-validated"}


def _validation_entries(sample):
    v = sample.get("validation")
    return v if isinstance(v, list) else []


def _run_solidity(abspath, errors, where):
    solc = shutil.which("solc")
    if not solc:
        errors.append(f"{where}: solc not found — cannot natively build claimed Solidity {abspath!r} "
                      "(install solc in this environment or mark the artifact future-profile-deferred)")
        return
    try:
        r = subprocess.run([solc, "--bin", abspath], capture_output=True, text=True, cwd=REPO)
    except OSError as e:
        errors.append(f"{where}: solc invocation failed for {abspath!r}: {e}")
        return
    if r.returncode != 0:
        errors.append(f"{where}: Solidity {abspath!r} did not compile with solc: "
                      f"{r.stderr.strip().splitlines()[-1] if r.stderr.strip() else 'non-zero exit'}")


def gate(portfolio, errors, summary, *, run):
    samples = portfolio.get("samples")
    if not isinstance(samples, list):
        errors.append("portfolio.samples must be an array")
        return
    for s in samples:
        if not isinstance(s, dict) or s.get("status") != "current-valid":
            continue
        sid = s.get("id", "<unknown>")
        for v in _validation_entries(s):
            if not isinstance(v, dict):
                continue
            path = v.get("path")
            cls = v.get("classification")
            if not (isinstance(path, str) and path):
                continue
            ext = os.path.splitext(path)[1]
            entry = {"sample": sid, "path": path, "classification": cls}
            where = f"sample {sid!r} artifact {path!r}"
            if ext in TARGET_LANGUAGES:
                target = TARGET_LANGUAGES[ext]
                entry["target"] = target
                # committed native-target code may NOT be hidden as non-native
                if cls != NATIVE_VALIDATED:
                    errors.append(f"{where}: committed {target} code is classified {cls!r}; "
                                  f"committed native-target code must be {NATIVE_VALIDATED!r} and "
                                  "pass its native toolchain (or not be committed)")
                    entry["nativeGate"] = "MISLABELLED"
                elif target not in WIRED_NATIVE_GATES:
                    errors.append(f"{where}: no native build gate wired for {target!r}; cannot claim "
                                  "it as committed native code — wire the gate or mark future-profile-deferred")
                    entry["nativeGate"] = "UNWIRED"
                elif run:
                    abspath = os.path.join(REPO, path)
                    if not os.path.exists(abspath):
                        errors.append(f"{where}: native-target artifact does not exist")
                        entry["nativeGate"] = "MISSING"
                    else:
                        before = len(errors)
                        if target == "solidity":
                            _run_solidity(abspath, errors, where)
                        entry["nativeGate"] = "built" if len(errors) == before else "FAILED"
                else:
                    entry["nativeGate"] = "deferred (--run not set)"
            else:
                entry["nativeGate"] = "n/a (not native-target code)"
                expected = SOURCE_EXPECTED.get(ext)
                if expected and cls != expected:
                    errors.append(f"{where}: {ext} artifact classified {cls!r}; expected {expected!r}")
            summary.append(entry)


def main() -> int:
    global REPO
    ap = argparse.ArgumentParser(description="M3 native build gate for generated sample code artifacts ()")
    ap.add_argument("--portfolio", default="examples/m3-sample-portfolio.json")
    ap.add_argument("--repo-root", default=REPO)
    ap.add_argument("--run", action="store_true", help="run native toolchains on committed native-target code")
    ap.add_argument("--summary-out", help="write the machine-readable build summary here")
    args = ap.parse_args()
    REPO = os.path.abspath(args.repo_root)
    path = args.portfolio if os.path.isabs(args.portfolio) else os.path.join(REPO, args.portfolio)
    try:
        portfolio = json.load(open(path))
    except (OSError, ValueError) as e:
        print(f"native build gate: cannot read {args.portfolio!r}: {e}", file=sys.stderr)
        return 2
    errors, summary = [], []
    gate(portfolio, errors, summary, run=args.run)
    out = {"schemaVersion": 1, "kind": "neutrino.m3-native-build-summary",
           "ran": bool(args.run), "ok": not errors, "artifacts": summary}
    if args.summary_out:
        parent = os.path.dirname(args.summary_out)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(args.summary_out, "w") as f:
            json.dump(out, f, indent=2)
    if errors:
        print("native build gate: FAILED", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    code = sum(1 for a in summary if a.get("target"))
    print(f"native build gate: OK ({len(summary)} classified artifact(s), {code} native-target)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

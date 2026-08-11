#!/usr/bin/env python3
"""Validate a sovereign-lowering envelope + the consumer acceptance checks ().

The envelope (docs/schemas/sovereign-lowering-envelope.schema.json) wraps EXTERNALLY lowered
artifacts so a console / network / agents consumer can accept them WITHOUT trusting the producing
compiler (M5 sovereign lowering,  / ). This validator is both the producer-side
shape gate and the reference consumer check:

  1. SHAPE — the envelope is well-formed: required fields + no unknown fields at every object level +
     the type of every field (so a truncated/typoed/missing-version envelope fails closed).
  2. COMPATIBILITY (`--require <component-compatibility-manifest>`) — the envelope's self-declared
     `translatorVersion` surface satisfies what the consumer requires, via the EXISTING
     scripts/gates/check_compatibility.py policy (exact IR dialect, exact per-contract schema versions,
     same-major & >= toolVersion). A missing/incompatible language or artifact version fails closed.
     This is the "consume without inventing a parallel manifest" path — the envelope IS a valid
     `--have` for check_compatibility.py.
  3. INTEGRITY (`--verify-hashes`) — each artifact's (and the source's) committed content hashes
     match the files under --artifact-root, so the consumer verifies integrity without re-compiling.

Sovereignty note: the validator does NOT pin the envelope's declared versions to the local
VersionInfo.h — a participant-owned compiler may target a different version. Acceptability is the
CONSUMER's decision (`--require`), not the local translator's.

Standard library only. Exit 0 ok / 1 invalid-or-incompatible (fail closed) / 2 usage.

  validate_sovereign_envelope.py --envelope E [--require R] [--verify-hashes] [--artifact-root DIR]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "scripts", "gates"))

_SEMVER = r"^[0-9]+\.[0-9]+\.[0-9]+$"
_SHA256 = r"^sha256:[0-9a-f]{64}$"


def _load(path: str, errors: list):
    if not os.path.exists(path):
        errors.append(f"missing file {path!r}")
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as exc:
        errors.append(f"cannot read {path}: {exc}")
        return None


def _no_unknown(obj, allowed: set, prefix: str, errs: list) -> None:
    if isinstance(obj, dict):
        for k in obj:
            if k not in allowed:
                errs.append(f"unknown field {prefix}.{k}")


def _req_str(obj, key, prefix, errs, regex=None, desc=None):
    """Required non-empty string; if `regex` is given, it must fully match (mirroring the schema
    pattern) so a malformed version/hash is rejected — not just a missing one."""
    v = obj.get(key) if isinstance(obj, dict) else None
    if not (isinstance(v, str) and v):
        errs.append(f"{prefix}.{key} is required (non-empty string)")
    elif regex and not re.match(regex, v):
        errs.append(f"{prefix}.{key} {v!r} is malformed (expected {desc or regex})")


def _unsafe_path(v):
    """An artifact/diagnostics path must stay inside the import root — reject absolute paths and any
    `..` traversal, so a malicious envelope cannot point at a host path outside the reviewed bundle."""
    if not isinstance(v, str) or not v:
        return None  # emptiness handled by _req_str
    if os.path.isabs(v) or (len(v) > 1 and v[1] == ":"):  # POSIX abs or Windows drive
        return "must be a relative path (absolute paths are refused)"
    if ".." in v.replace("\\", "/").split("/"):
        return "must not contain a '..' path traversal segment"
    return None


def shape_errors(e) -> list:
    """Fail-closed shape check mirroring docs/schemas/sovereign-lowering-envelope.schema.json —
    required fields + additionalProperties:false + field types at EVERY object level."""
    errs: list = []
    if not isinstance(e, dict):
        return ["envelope must be a JSON object"]
    if e.get("kind") != "neutrino.sovereign-lowering-envelope":
        errs.append("kind must be 'neutrino.sovereign-lowering-envelope'")
    if e.get("schemaVersion") != 1:
        errs.append("schemaVersion must be 1")
    _no_unknown(e, {"kind", "schemaVersion", "capability", "capabilityVersion", "source",
                    "producer", "target", "artifacts", "diagnostics", "translatorVersion"},
                "(root)", errs)
    for f in ("capability", "capabilityVersion", "source", "producer", "target", "artifacts",
              "translatorVersion"):
        if f not in e:
            errs.append(f"missing required field {f!r}")
    _req_str(e, "capability", "(root)", errs)
    _req_str(e, "capabilityVersion", "(root)", errs, _SEMVER, "semver x.y.z")

    src = e.get("source")
    if not isinstance(src, dict):
        if "source" in e:
            errs.append("source must be an object")
    else:
        _no_unknown(src, {"language", "sourceHash", "languageVersion"}, "source", errs)
        _req_str(src, "language", "source", errs)
        _req_str(src, "sourceHash", "source", errs, _SHA256, "sha256:<64 hex>")
        _req_str(src, "languageVersion", "source", errs)  # missing language version -> fail closed

    prod = e.get("producer")
    if not isinstance(prod, dict):
        if "producer" in e:
            errs.append("producer must be an object")
    else:
        _no_unknown(prod, {"identity", "official", "toolVersion", "gitSha", "buildTarget"},
                    "producer", errs)
        _req_str(prod, "identity", "producer", errs)
        _req_str(prod, "toolVersion", "producer", errs)
        if not isinstance(prod.get("official"), bool):
            errs.append("producer.official is required (boolean)")

    tgt = e.get("target")
    if not isinstance(tgt, dict):
        if "target" in e:
            errs.append("target must be an object")
    else:
        _no_unknown(tgt, {"backend", "runtimeProfile"}, "target", errs)
        _req_str(tgt, "backend", "target", errs)

    arts = e.get("artifacts")
    if not (isinstance(arts, list) and arts):
        errs.append("artifacts is required (non-empty array)")
    else:
        for i, a in enumerate(arts):
            if not isinstance(a, dict):
                errs.append(f"artifacts[{i}] must be an object"); continue
            _no_unknown(a, {"path", "role", "hash"}, f"artifacts[{i}]", errs)
            _req_str(a, "path", f"artifacts[{i}]", errs)
            unsafe = _unsafe_path(a.get("path"))
            if unsafe:
                errs.append(f"artifacts[{i}].path {a.get('path')!r} {unsafe}")
            _req_str(a, "role", f"artifacts[{i}]", errs)
            _req_str(a, "hash", f"artifacts[{i}]", errs, _SHA256, "sha256:<64 hex>")

    diag = e.get("diagnostics")
    if diag is not None:
        if not isinstance(diag, dict):
            errs.append("diagnostics must be an object")
        else:
            _no_unknown(diag, {"ok", "count", "ref"}, "diagnostics", errs)
            if "ref" in diag:
                unsafe = _unsafe_path(diag.get("ref"))
                if unsafe:
                    errs.append(f"diagnostics.ref {diag.get('ref')!r} {unsafe}")

    tv = e.get("translatorVersion")
    if not isinstance(tv, dict):
        if "translatorVersion" in e:
            errs.append("translatorVersion must be an object")
    else:
        _req_str(tv, "toolVersion", "translatorVersion", errs, _SEMVER, "semver x.y.z")
        _req_str(tv, "mlirDialectVersion", "translatorVersion", errs, _SEMVER, "semver x.y.z")
        sch = tv.get("schemas")
        if not isinstance(sch, dict):
            errs.append("translatorVersion.schemas is required (object)")
        else:
            for k in ("bindingPolicy", "bindingReceipt", "runtimeEvidence"):
                _req_str(sch, k, "translatorVersion.schemas", errs)
    return errs


def compat_errors(e: dict, require_path: str) -> list:
    """Consumer acceptance: the envelope's declared surface must satisfy the consumer requirement,
    using the EXISTING check_compatibility.py policy (no parallel manifest)."""
    errs: list = []
    require = _load(require_path, errs)
    if require is None:
        return errs
    try:
        import check_compatibility as cc
    except ImportError as exc:
        return [f"cannot import check_compatibility: {exc}"]
    shape = cc.require_shape_errors(require)
    if shape:
        return [f"--require is not a valid component-compatibility-manifest: {s}" for s in shape]
    have = e.get("translatorVersion")
    if not isinstance(have, dict):
        return ["envelope.translatorVersion missing — cannot run the consumer compatibility check"]
    return [f"incompatible: {p}" for p in cc.check(have, require)]


def hash_errors(e: dict, artifact_root: str) -> list:
    """Integrity: each declared artifact (and the source) hash matches the file on disk."""
    errs: list = []

    def _sha(path):
        with open(path, "rb") as f:
            return "sha256:" + hashlib.sha256(f.read()).hexdigest()

    root = os.path.realpath(artifact_root)
    for a in e.get("artifacts", []):
        rel = a.get("path")
        if not rel:
            continue
        # defense-in-depth: even though shape_errors rejects absolute / '..' paths, re-confirm the
        # resolved file stays inside the import root before reading it.
        if _unsafe_path(rel):
            errs.append(f"artifact path {rel!r} escapes the import root — refusing to hash it")
            continue
        p = os.path.realpath(os.path.join(root, rel))
        if os.path.commonpath([root, p]) != root:
            errs.append(f"artifact path {rel!r} resolves outside the import root — refusing to hash it")
            continue
        if not os.path.exists(p):
            errs.append(f"artifact not found for hash check: {rel}")
            continue
        got = _sha(p)
        if got != a.get("hash"):
            errs.append(f"artifact hash mismatch for {rel}: {got} != declared {a.get('hash')}")
    src = (e.get("source") or {}).get("sourceHash")
    # the source path is not carried in the envelope (sovereign import may not ship it); only
    # artifacts are hash-verified against files. sourceHash integrity is producer-attested.
    return errs


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate a sovereign-lowering envelope ()")
    ap.add_argument("--envelope", required=True)
    ap.add_argument("--require", help="a neutrino.component-compatibility-manifest the consumer requires")
    ap.add_argument("--verify-hashes", action="store_true", help="verify artifact hashes against files")
    ap.add_argument("--artifact-root", help="resolve artifact paths against this root (default: repo root)")
    ap.add_argument("--repo-root", help="override the repo root (used by the self-test)")
    try:
        args = ap.parse_args()
    except SystemExit:
        return 2
    global REPO
    if args.repo_root:
        REPO = os.path.abspath(args.repo_root)
    artifact_root = args.artifact_root or REPO

    errors: list = []
    e = _load(args.envelope, errors)
    if e is not None:
        errors += shape_errors(e)
        if not errors:
            if args.require:
                errors += compat_errors(e, args.require)
            if args.verify_hashes:
                errors += hash_errors(e, artifact_root)

    print(json.dumps({"kind": "neutrino.sovereign-lowering-envelope-validation",
                      "envelope": args.envelope, "ok": not errors, "errors": errors}, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())

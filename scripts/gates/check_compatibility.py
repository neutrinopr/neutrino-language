#!/usr/bin/env python3
"""Compatibility checker (): does a translator's version/compatibility surface
satisfy what a component-compatibility-manifest REQUIRES?

A downstream consumer (console / agents / network / wrapper) runs this to **fail
closed** before trusting artifacts produced by — or destined for — a given
translator. It compares:

  --have    the translator's surface: a `neutrino.translator-version` envelope
            (`neutrino-* --version-json`) OR a `manifest.json` carrying
            `translatorVersion` (written by every `neutrino-gen` run).
  --require a `neutrino.component-compatibility-manifest`
            (docs/schemas/component-compatibility-manifest.schema.json).

Policy (drift behavior — rejected unless compatible):
  - mlirDialectVersion: must match EXACTLY (the IR contract) — mismatch rejected.
  - schemas.{bindingPolicy,bindingReceipt,runtimeEvidence}: each required version
    must equal the translator's — mismatch rejected.
  - translator.toolVersion: SemVer — same MAJOR and have >= require (a newer
    patch/minor is compatible; an older or different-major tool is rejected).
  - conformanceVectorVersion: if required, must match exactly.

Standard library only (matches the repo's other validators). Exit 0 compatible /
1 incompatible (fail closed) / 2 usage.

  check_compatibility.py --have version.json --require component-compatibility.json
"""
from __future__ import annotations

import argparse
import json
import sys


def _surface(doc: dict) -> dict:
    """Normalize --have into the translator-version surface dict."""
    if doc.get("kind") == "neutrino.translator-version":
        return doc
    # A manifest.json OR a sovereign-lowering envelope () both carry the producer's
    # declared surface under translatorVersion, so a console/network consumer fails closed on an
    # imported artifact bundle with this same checker — no parallel manifest.
    if "translatorVersion" in doc:
        return doc["translatorVersion"]
    raise ValueError(
        "--have must be a neutrino.translator-version envelope (--version-json), a manifest.json "
        "with translatorVersion, or a neutrino.sovereign-lowering-envelope")


def require_shape_errors(require: dict) -> list[str]:
    """Fail-closed shape check of a --require component-compatibility-manifest,
    mirroring docs/schemas/component-compatibility-manifest.schema.json (required
    fields + additionalProperties:false, so a truncated manifest or a typoed field
    like `mlirDialectVerzion` is REJECTED, not silently treated as compatible)."""
    errs: list[str] = []
    if not isinstance(require, dict):
        return ["--require must be a JSON object"]

    top_required = ["kind", "dslVersion", "translator", "schemas"]
    top_allowed = {"kind", "dslVersion", "mlirDialectVersion", "translator",
                   "agents", "network", "schemas", "conformanceVectorVersion"}
    for r in top_required:
        if r not in require:
            errs.append(f"missing required field '{r}'")
    for k in require:
        if k not in top_allowed:
            errs.append(f"unknown field '{k}' (typo? schema is additionalProperties:false)")
    if require.get("kind") != "neutrino.component-compatibility-manifest":
        errs.append("kind must be 'neutrino.component-compatibility-manifest'")

    tr = require.get("translator")
    if isinstance(tr, dict):
        for k in tr:
            if k not in {"toolVersion", "imageDigest", "wrapperVersion"}:
                errs.append(f"translator.{k}: unknown field")
        if "toolVersion" not in tr and "imageDigest" not in tr:
            errs.append("translator: needs at least one of toolVersion / imageDigest")
    elif tr is not None:
        errs.append("translator must be an object")

    sch = require.get("schemas")
    if isinstance(sch, dict):
        for r in ("bindingPolicy", "bindingReceipt", "runtimeEvidence"):
            if r not in sch:
                errs.append(f"schemas: missing required '{r}'")
        for k in sch:
            if k not in {"bindingPolicy", "bindingReceipt", "runtimeEvidence"}:
                errs.append(f"schemas.{k}: unknown field")
    elif sch is not None:
        errs.append("schemas must be an object")

    # Optional downstream blocks are also additionalProperties:false in the schema —
    # reject typoed keys so a malformed downstream requirement can't pass as compatible.
    for block, allowed in (("agents", {"sdkVersion"}),
                           ("network", {"jvmSdkVersion", "tsSdkVersion", "wasmCoreDigest"})):
        b = require.get(block)
        if isinstance(b, dict):
            for k in b:
                if k not in allowed:
                    errs.append(f"{block}.{k}: unknown field")
        elif b is not None:
            errs.append(f"{block} must be an object")

    return errs


def _semver(v: str):
    parts = v.split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        return None
    return tuple(int(p) for p in parts)


def check(have: dict, require: dict) -> list[str]:
    problems: list[str] = []

    rd = require.get("mlirDialectVersion")
    if rd is not None and rd != have.get("mlirDialectVersion"):
        problems.append(
            f"mlirDialectVersion: require {rd!r} != translator {have.get('mlirDialectVersion')!r} "
            "(IR contract must match exactly)")

    req_schemas = require.get("schemas", {})
    have_schemas = have.get("schemas", {})
    for name, rv in req_schemas.items():
        hv = have_schemas.get(name)
        if hv != rv:
            problems.append(f"schemas.{name}: require {rv!r} != translator {hv!r}")

    rt = require.get("translator", {}).get("toolVersion")
    ht = have.get("toolVersion")
    if rt is not None:
        rs, hs = _semver(rt), _semver(ht or "")
        if rs is None or hs is None:
            problems.append(f"toolVersion: unparseable SemVer (require {rt!r}, translator {ht!r})")
        elif hs[0] != rs[0]:
            problems.append(
                f"toolVersion: major mismatch — require {rt} but translator is {ht} "
                "(incompatible major)")
        elif hs < rs:
            problems.append(
                f"toolVersion: translator {ht} is older than required {rt}")

    rc = require.get("conformanceVectorVersion")
    if rc is not None and rc != have.get("conformanceVectorVersion"):
        problems.append(
            f"conformanceVectorVersion: require {rc!r} != translator {have.get('conformanceVectorVersion')!r}")

    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description="translator compatibility checker ()")
    ap.add_argument("--have", required=True,
                    help="translator --version-json envelope or a manifest.json")
    ap.add_argument("--require", required=True,
                    help="a neutrino.component-compatibility-manifest")
    args = ap.parse_args()

    try:
        have = _surface(json.load(open(args.have)))
        require = json.load(open(args.require))
    except (OSError, ValueError, json.JSONDecodeError) as e:
        print(f"usage error: {e}", file=sys.stderr)
        return 2

    # Validate the requirement's SHAPE before comparing — a truncated or typoed
    # manifest must FAIL CLOSED, never be read as "compatible" ( review).
    shape = require_shape_errors(require)
    if shape:
        print("INVALID --require manifest (fail closed):")
        for p in shape:
            print(f"  - {p}")
        return 1

    problems = check(have, require)
    if problems:
        print("INCOMPATIBLE (fail closed):")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(f"compatible: translator toolVersion={have.get('toolVersion')} "
          f"mlirDialectVersion={have.get('mlirDialectVersion')} "
          f"schemas={have.get('schemas')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

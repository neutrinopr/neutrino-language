#!/usr/bin/env python3
"""Validate the published translator compatibility manifest ().

`COMPATIBILITY.json` is the translator-owned M5 compatibility surface downstream
components inspect to fail closed on an unsupported language level or schema
version (/). This validator is the CI drift gate: it checks the
manifest's SHAPE and then pins every version value to its single source of truth,
so a bump that is not reflected in the manifest — or a manifest that declares an
UNSUPPORTED/incompatible schema version — is REJECTED:

  - translator.{toolVersion,mlirDialectVersion,schemaBundleVersion},
    compatibilityManifestVersion, conformanceVectorVersion, and
    artifactSchemas.{bindingPolicy,bindingReceipt,runtimeEvidence} are pinned to
    include/Neutrino/VersionInfo.h (the  single source of truth);
  - artifactSchemas.{l2DomainSemantics,slotBindingTopology,dialectExpansionManifest,
    l3BindingManifest,backendProfileCatalog} are pinned to the committed
    docs/schemas/*.schema.json (and backend-profiles/catalog.json) version consts —
    so a manifest cannot declare a schema version the translator does not actually
    ship;
  - consumers.{network,agents}.minToolVersion is pinned to the current toolVersion.

Standard library only. Exit 0 compatible / 1 incompatible-or-invalid (fail closed)
/ 2 usage.

  validate_compatibility_manifest.py [--manifest COMPATIBILITY.json] [--repo-root DIR]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

# repo root = parent of this scripts/ dir, unless --repo-root overrides (used by the negative self-test).
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VERSIONINFO = "include/Neutrino/VersionInfo.h"

# manifest field -> VersionInfo.h constant (the  single source of truth).
_VI_FIELDS = {
    ("translator", "toolVersion"): "kToolVersion",
    ("translator", "mlirDialectVersion"): "kMlirDialectVersion",
    ("translator", "schemaBundleVersion"): "kSchemaBundleVersion",
    ("compatibilityManifestVersion",): "kCompatibilityManifestVersion",
    ("conformanceVectorVersion",): "kConformanceVectorVersion",
    ("semanticLanguageVersion",): "kSemanticLanguageVersion",
    ("artifactSchemas", "bindingPolicy"): "kSchemaBindingPolicy",
    ("artifactSchemas", "bindingReceipt"): "kSchemaBindingReceipt",
    ("artifactSchemas", "runtimeEvidence"): "kSchemaRuntimeEvidence",
}

# manifest field -> VersionInfo.h INTEGER constant (). Parsed/compared as int.
_VI_INT_FIELDS = {
    ("semanticProfileVersion",): "kSemanticProfileVersion",
}

# manifest artifactSchemas.<key> -> the schema file whose schemaVersion const/enum it must equal.
_SCHEMA_FILES = {
    "l2DomainSemantics": "docs/schemas/l2-domain-semantics.schema.json",
    "slotBindingTopology": "docs/schemas/slot-binding-topology.schema.json",
    "dialectExpansionManifest": "docs/schemas/dialect-expansion-manifest.schema.json",
    "l3BindingManifest": "docs/schemas/binding-manifest.schema.json",
}
_CATALOG = "examples/backend-profiles/catalog.json"


def _load(rel: str, errors: list):
    path = os.path.join(REPO, rel)
    if not os.path.exists(path):
        errors.append(f"missing committed path {rel!r}")
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as exc:
        errors.append(f"cannot read {rel}: {exc}")
        return None


def _get(doc: dict, path: tuple):
    cur = doc
    for k in path:
        if not isinstance(cur, dict) or k not in cur:
            return None
        cur = cur[k]
    return cur


def _no_unknown(obj, allowed: set, prefix: str, errs: list) -> None:
    """Mirror the schema's additionalProperties:false for a nested object — an unknown field is
    rejected, so a machine-readable contract cannot smuggle an undeclared key past the CI gate."""
    if isinstance(obj, dict):
        for k in obj:
            if k not in allowed:
                errs.append(f"unknown field {prefix}.{k}")


def _shape_errors(m) -> list:
    """Fail-closed shape check mirroring docs/schemas/translator-compatibility-manifest.schema.json
    (required fields + no unknown fields at EVERY object level), so a truncated or typoed manifest —
    including an undeclared nested key — is rejected."""
    errs: list = []
    if not isinstance(m, dict):
        return ["manifest must be a JSON object"]
    if m.get("kind") != "neutrino.translator-compatibility-manifest":
        errs.append("kind must be 'neutrino.translator-compatibility-manifest'")
    if m.get("schemaVersion") != 1:
        errs.append("schemaVersion must be 1")
    top_allowed = {"kind", "schemaVersion", "compatibilityManifestVersion", "_note", "translator",
                   "language", "artifactSchemas", "featureFlags", "conformanceVectorVersion",
                   "semanticProfileVersion", "semanticLanguageVersion", "consumers"}
    _no_unknown(m, top_allowed, "(root)", errs)
    for f in ("compatibilityManifestVersion", "translator", "language", "artifactSchemas",
              "conformanceVectorVersion", "semanticProfileVersion", "semanticLanguageVersion"):
        if f not in m:
            errs.append(f"missing required field {f!r}")
    # The semantic-profile contract version () is a positive integer pinned below.
    if "semanticProfileVersion" in m and not (
            isinstance(m["semanticProfileVersion"], int)
            and not isinstance(m["semanticProfileVersion"], bool)
            and m["semanticProfileVersion"] >= 1):
        errs.append("semanticProfileVersion must be a positive integer")
    # nested additionalProperties:false (the JSON schema locks these down; mirror it here since the
    # repo validators are stdlib-only and cannot assume a jsonschema dependency in CI).
    _no_unknown(m.get("translator"), {"toolVersion", "mlirDialectVersion", "schemaBundleVersion"},
                "translator", errs)
    _no_unknown(m.get("artifactSchemas"),
                {"l2DomainSemantics", "l3BindingManifest", "slotBindingTopology",
                 "dialectExpansionManifest", "backendProfileCatalog", "bindingPolicy",
                 "bindingReceipt", "runtimeEvidence"}, "artifactSchemas", errs)
    _no_unknown(m.get("language"), {"l1ArtifactFormat", "levels"}, "language", errs)
    _no_unknown(_get(m, ("language", "levels")), {"supported", "future", "max"},
                "language.levels", errs)
    _no_unknown(m.get("consumers"), {"_note", "network", "agents"}, "consumers", errs)
    for who in ("network", "agents"):
        _no_unknown(_get(m, ("consumers", who)), {"minToolVersion", "maxToolVersion"},
                    f"consumers.{who}", errs)
    tr = m.get("translator")
    if isinstance(tr, dict):
        for f in ("toolVersion", "mlirDialectVersion", "schemaBundleVersion"):
            if not (isinstance(tr.get(f), str) and tr[f]):
                errs.append(f"translator.{f} is required (non-empty string)")
    a = m.get("artifactSchemas")
    if isinstance(a, dict):
        for f in ("l2DomainSemantics", "slotBindingTopology", "dialectExpansionManifest",
                  "backendProfileCatalog"):
            if not isinstance(a.get(f), int):
                errs.append(f"artifactSchemas.{f} is required (integer)")
        if not (isinstance(a.get("l3BindingManifest"), list) and a["l3BindingManifest"]
                and all(isinstance(x, int) for x in a["l3BindingManifest"])):
            errs.append("artifactSchemas.l3BindingManifest is required (non-empty integer array)")
        for f in ("bindingPolicy", "bindingReceipt", "runtimeEvidence"):
            if not (isinstance(a.get(f), str) and a[f]):
                errs.append(f"artifactSchemas.{f} is required (non-empty string)")
    # a required nested field present but of the WRONG type must fail closed (otherwise the
    # isinstance(dict) checks above silently skip it).
    for f in ("translator", "artifactSchemas", "language"):
        if f in m and not isinstance(m.get(f), dict):
            errs.append(f"{f} must be an object")
    for f in ("compatibilityManifestVersion", "conformanceVectorVersion"):
        if f in m and not (isinstance(m.get(f), str) and m[f]):
            errs.append(f"{f} must be a non-empty string")
    lang = m.get("language")
    if isinstance(lang, dict):
        if not (isinstance(lang.get("l1ArtifactFormat"), str) and lang["l1ArtifactFormat"]):
            errs.append("language.l1ArtifactFormat is required (non-empty string)")
        if "levels" in lang and not isinstance(lang["levels"], dict):
            errs.append("language.levels must be an object")
    lv = _get(m, ("language", "levels"))
    if isinstance(lv, dict):
        if not (isinstance(lv.get("supported"), list) and lv["supported"]):
            errs.append("language.levels.supported is required (non-empty array)")
        if not (isinstance(lv.get("max"), str) and lv["max"]):
            errs.append("language.levels.max is required (non-empty string)")
        for f in ("supported", "future"):
            if f in lv and not (isinstance(lv[f], list) and all(isinstance(x, str) for x in lv[f])):
                errs.append(f"language.levels.{f} must be an array of strings")
    # optional sections: featureFlags is an object of booleans; consumers is an object with
    # network/agents objects whose tool-version bounds are string-or-null. A wrong TYPE for these
    # optional sections (e.g. a string) must fail closed too — the schema locks their type down.
    if "featureFlags" in m:
        ff = m["featureFlags"]
        if not isinstance(ff, dict):
            errs.append("featureFlags must be an object")
        else:
            for k, v in ff.items():
                if not isinstance(v, bool):
                    errs.append(f"featureFlags.{k} must be a boolean")
    if "consumers" in m:
        cons = m["consumers"]
        if not isinstance(cons, dict):
            errs.append("consumers must be an object")
        else:
            for who in ("network", "agents"):
                if who in cons:
                    if not isinstance(cons[who], dict):
                        errs.append(f"consumers.{who} must be an object")
                    else:
                        for vf in ("minToolVersion", "maxToolVersion"):
                            if vf in cons[who] and cons[who][vf] is not None \
                                    and not isinstance(cons[who][vf], str):
                                errs.append(f"consumers.{who}.{vf} must be a string or null")
    return errs


def _versioninfo_constants(errors: list) -> dict:
    """Parse the kXxx string constants from VersionInfo.h (the version single source of truth)."""
    text = None
    path = os.path.join(REPO, VERSIONINFO)
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError as exc:
        errors.append(f"cannot read {VERSIONINFO}: {exc}")
        return {}
    out = {}
    for const in set(_VI_FIELDS.values()):
        mm = re.search(const + r'\s*=\s*"([^"]*)"', text)
        if mm:
            out[const] = mm.group(1)
        else:
            errors.append(f"{const} not found in {VERSIONINFO}")
    # Integer constants (): parse the `= <int>;` form.
    for const in set(_VI_INT_FIELDS.values()):
        mm = re.search(const + r'\s*=\s*([0-9]+)\s*;', text)
        if mm:
            out[const] = int(mm.group(1))
        else:
            errors.append(f"{const} not found in {VERSIONINFO}")
    return out


def _versioninfo_language_levels(errors: list) -> dict:
    """Parse the languageLevels {supported, future, max} that versionInfo() emits in VersionInfo.h,
    so the published manifest cannot advertise a level (e.g. L2) the translator marks future-only."""
    path = os.path.join(REPO, VERSIONINFO)
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError as exc:
        errors.append(f"cannot read {VERSIONINFO}: {exc}")
        return {}

    def _array(name):
        mm = re.search(r'\{"' + name + r'",\s*llvm::json::Array\{([^}]*)\}', text, re.DOTALL)
        if not mm:
            errors.append(f"languageLevels.{name} not found in {VERSIONINFO}")
            return None
        return re.findall(r'"([^"]+)"', mm.group(1))

    mx = re.search(r'\{"max",\s*"([^"]+)"\}', text)
    if not mx:
        errors.append(f"languageLevels.max not found in {VERSIONINFO}")
    return {"supported": _array("supported"), "future": _array("future"),
            "max": mx.group(1) if mx else None}


def _schema_version(rel: str, errors: list):
    """Return the schemaVersion const (int) or enum (list) declared by a committed schema file."""
    doc = _load(rel, errors)
    if doc is None:
        return None
    sv = doc.get("properties", {}).get("schemaVersion", {})
    if "const" in sv:
        return sv["const"]
    if "enum" in sv:
        return sv["enum"]
    # backend-profiles/catalog.json is an instance, not a schema — its own schemaVersion field.
    if "schemaVersion" in doc:
        return doc["schemaVersion"]
    errors.append(f"{rel}: no schemaVersion const/enum found")
    return None


def _pin_errors(m: dict) -> list:
    """Pin every manifest version value to its single source of truth; drift/unsupported fails closed."""
    errs: list = []
    consts = _versioninfo_constants(errs)
    for path, const in {**_VI_FIELDS, **_VI_INT_FIELDS}.items():
        want = consts.get(const)
        have = _get(m, path)
        if want is not None and have != want:
            errs.append(f"{'.'.join(path)} {have!r} != {VERSIONINFO} {const} {want!r} (version drift)")
    # artifact schema versions pinned to the committed schema files / catalog
    for key, rel in _SCHEMA_FILES.items():
        want = _schema_version(rel, errs)
        have = _get(m, ("artifactSchemas", key))
        if want is not None and have != want:
            errs.append(f"artifactSchemas.{key} {have!r} != {rel} schemaVersion {want!r} "
                        f"(unsupported/incompatible schema version)")
    want_cat = _schema_version(_CATALOG, errs)
    have_cat = _get(m, ("artifactSchemas", "backendProfileCatalog"))
    if want_cat is not None and have_cat != want_cat:
        errs.append(f"artifactSchemas.backendProfileCatalog {have_cat!r} != {_CATALOG} "
                    f"schemaVersion {want_cat!r}")
    # language levels pinned to versionInfo()'s languageLevels — the manifest cannot advertise a
    # level the translator marks future-only (e.g. L2), which would let a consumer trust it.
    vlevels = _versioninfo_language_levels(errs)
    have_lv = _get(m, ("language", "levels")) or {}
    if vlevels.get("supported") is not None and \
            set(have_lv.get("supported") or []) != set(vlevels["supported"]):
        errs.append(f"language.levels.supported {have_lv.get('supported')!r} != {VERSIONINFO} "
                    f"languageLevels.supported {vlevels['supported']!r}")
    if vlevels.get("future") is not None and \
            set(have_lv.get("future") or []) != set(vlevels["future"]):
        errs.append(f"language.levels.future {have_lv.get('future')!r} != {VERSIONINFO} "
                    f"languageLevels.future {vlevels['future']!r}")
    if vlevels.get("max") is not None and have_lv.get("max") != vlevels["max"]:
        errs.append(f"language.levels.max {have_lv.get('max')!r} != {VERSIONINFO} "
                    f"languageLevels.max {vlevels['max']!r}")
    # consumers.*.minToolVersion pinned to the current toolVersion
    tool = consts.get("kToolVersion")
    for who in ("network", "agents"):
        mn = _get(m, ("consumers", who, "minToolVersion"))
        if mn is not None and tool is not None and mn != tool:
            errs.append(f"consumers.{who}.minToolVersion {mn!r} != current toolVersion {tool!r}")
    return errs


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate COMPATIBILITY.json ()")
    ap.add_argument("--manifest", default="COMPATIBILITY.json",
                    help="path (relative to --repo-root) to the compatibility manifest")
    ap.add_argument("--repo-root", help="resolve the manifest + sources against this root "
                                        "(default: the repo this script lives in)")
    try:
        args = ap.parse_args()
    except SystemExit:
        return 2
    global REPO
    if args.repo_root:
        REPO = os.path.abspath(args.repo_root)

    errors: list = []
    m = _load(args.manifest, errors)
    if m is not None:
        errors += _shape_errors(m)
        if not errors:  # only pin values once the shape is sound
            errors += _pin_errors(m)

    envelope = {
        "kind": "neutrino.translator-compatibility-manifest-validation",
        "manifest": args.manifest,
        "ok": not errors,
        "errors": errors,
    }
    print(json.dumps(envelope, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())

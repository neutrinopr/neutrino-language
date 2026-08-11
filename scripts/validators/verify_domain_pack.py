#!/usr/bin/env python3
"""Verify a domain pack against a published CORE CONTRACT BUNDLE ().

The PUBLIC conformance boundary: an external domain pack validates its manifest +
artifacts against a released bundle using ONLY the standard library and the
bundle directory — no translator headers, modules, or source checkout.

A domain-pack manifest (`neutrino.domain-pack`, validated against a bundled
domain-pack contract) declares:
  * targetsBundle: {bundleId, bundleVersion, bundleDigest}  — pins the EXACT bundle;
  * translatorPins: {axis: version, ...}                    — the version axes it pins;
  * requiredContracts / optionalContracts: [name]           — feature negotiation;
  * v1 artifacts: [{contract, path}]                         — JSON instances to validate;
  * v2 payloads: [{role, path, mediaType, sha256, contract?}]
                                                            — the complete byte inventory.

Verification is FAIL-CLOSED, with stable `pack.*` diagnostic codes:
  * pack.shape             — the manifest violates the domain-pack contract
  * pack.digest            — the bundle self-digest / target-pin / a bundled schema
                             digest does not match
  * pack.bundle_mismatch   — targets a different bundleId/version
  * pack.unknown_version   — pins an axis the bundle does not publish
  * pack.pin_mismatch      — pins an axis incompatibly (see the bundle policy)
  * pack.unknown_contract  — references a contract not in the bundle
  * pack.missing_required  — a required contract is absent from the bundle
  * pack.path              — an artifact/contract path escapes its root
  * pack.completeness      — the v2 payload inventory is duplicate/incomplete/extra
  * pack.integrity         — v2 pack identity or payload bytes fail their SHA-256 pin
  * pack.schema            — an artifact violates its contract's schema
  * pack.unknown_semantic_feature — a target-profile declares a closed semantic
                             feature outside the bundle's published vocabulary
  * pack.io                — the manifest/bundle/artifact is unreadable

  verify_domain_pack.py --bundle BUNDLE.json --bundle-root DIR
                        --pack PACK.json [--pack-root DIR]
Exit 0 conformant / 1 non-conformant / 2 usage.
"""
from __future__ import annotations

import argparse
import calendar
from collections import Counter
import hashlib
import json
import os
import re
import sys

_DATETIME_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(\.\d+)?"
    r"([Zz]|[+-](\d{2}):(\d{2}))$")
_SEMVER_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


def _json_equal(a, b):
    """JSON value equality (Draft 2020-12): type-sensitive — a boolean is never
    equal to a number, so True != 1 (Python's == conflates them). Recurses into
    arrays/objects; 1 and 1.0 are the one JSON number value."""
    ka = "bool" if isinstance(a, bool) else "num" if isinstance(a, (int, float)) else type(a).__name__
    kb = "bool" if isinstance(b, bool) else "num" if isinstance(b, (int, float)) else type(b).__name__
    if ka != kb:
        return False
    if ka == "list":
        return len(a) == len(b) and all(_json_equal(x, y) for x, y in zip(a, b))
    if ka == "dict":
        return a.keys() == b.keys() and all(_json_equal(a[k], b[k]) for k in a)
    return a == b


def _valid_datetime(s):
    """RFC 3339 date-time with real calendar/range validation (not just shape)."""
    m = _DATETIME_RE.match(s)
    if not m:
        return False
    y, mo, d, hh, mm, ss = (int(m.group(i)) for i in range(1, 7))
    if not 1 <= mo <= 12 or not 1 <= d <= calendar.monthrange(y, mo)[1]:
        return False
    if hh > 23 or mm > 59 or ss > 60:  # 60 permits a leap second
        return False
    if m.group(9) is not None and (int(m.group(9)) > 23 or int(m.group(10)) > 59):
        return False
    return True


def _fail(diags, code, msg):
    diags.append(f"[{code}] {msg}")


def file_sha256(path):
    with open(path, "rb") as f:
        return "sha256:" + hashlib.sha256(f.read()).hexdigest()


def _sha256(path):
    return file_sha256(path)


def canonical_pack_digest(pack):
    """Identity of a v2 manifest, including its ordered payload inventory."""
    body = {k: v for k, v in pack.items() if k != "packDigest"}
    canonical = json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def normalized_payload_path(path):
    """Return the canonical slash-separated relative spelling, or None."""
    if not isinstance(path, str) or not path or "\0" in path or "\\" in path:
        return None
    if os.path.isabs(path) or path.startswith("/") or path.endswith("/"):
        return None
    parts = path.split("/")
    if any(part in ("", ".", "..") for part in parts):
        return None
    normalized = os.path.normpath(path).replace(os.sep, "/")
    return path if normalized == path else None


def _load(path, diags):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except OSError as e:
        _fail(diags, "pack.io", f"cannot read {path!r}: {e}")
    except ValueError as e:
        _fail(diags, "pack.shape", f"{path!r} is not valid JSON: {e}")
    return None


def _load_semantic_payload(path, label, diags):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except OSError as e:
        _fail(diags, "pack.io", f"cannot read {label} {path!r}: {e}")
    except (UnicodeError, ValueError) as e:
        _fail(diags, "pack.schema", f"{label} {path!r} is not valid JSON: {e}")
    return None


# --- a Draft 2020-12 validator covering every keyword the bundled schemas use ---
# The supported keyword set is asserted COMPLETE against the bundled schemas by
# scripts/gates/check_core_contract_bundle.py's keyword-coverage check.
SUPPORTED_KEYWORDS = frozenset({
    "$id", "$schema", "$ref", "$defs", "$comment", "title", "description",
    "type", "required", "properties", "additionalProperties", "propertyNames",
    "enum", "const", "pattern", "minLength", "format",
    "minimum", "maximum", "items", "minItems", "minProperties", "uniqueItems",
    "oneOf", "anyOf", "allOf", "not", "if", "then", "else",
})

# The `format` values the validator actually ENFORCES (only `date-time`, in
# _validate). A bundled schema using any other format value would be silently
# ignored by an external consumer, so the completeness gate rejects it — this is
# the single source of truth for that check.
SUPPORTED_FORMATS = frozenset({"date-time"})


def _type_ok(inst, t):
    # Fail closed on an unknown type name (a schema bug must never pass silently).
    return {
        "object": isinstance(inst, dict),
        "array": isinstance(inst, list),
        "string": isinstance(inst, str),
        "integer": isinstance(inst, int) and not isinstance(inst, bool),
        "number": isinstance(inst, (int, float)) and not isinstance(inst, bool),
        "boolean": isinstance(inst, bool),
        "null": inst is None,
    }.get(t, False)


def _resolve_ref(ref, root):
    if not ref.startswith("#/"):
        return None
    node = root
    for part in ref[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _is_valid(inst, schema, root):
    d: list = []
    _validate(inst, schema, "", d, root)
    return not d


def _validate(inst, schema, path, diags, root):
    if schema is True or schema == {}:
        return
    if schema is False:
        _fail(diags, "pack.schema", f"{path or 'value'} is not allowed")
        return
    if not isinstance(schema, dict):
        return
    if "$ref" in schema:
        target = _resolve_ref(schema["$ref"], root)
        if target is None:
            _fail(diags, "pack.schema", f"{path}: unresolvable $ref {schema['$ref']!r}")
        else:
            _validate(inst, target, path, diags, root)
    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_type_ok(inst, t) for t in types):
            _fail(diags, "pack.schema", f"{path or 'value'} must be of type {schema['type']}")
            return
    if "const" in schema and not _json_equal(inst, schema["const"]):
        _fail(diags, "pack.schema", f"{path or 'value'} must equal {schema['const']!r}")
    if "enum" in schema and not any(_json_equal(inst, e) for e in schema["enum"]):
        _fail(diags, "pack.schema", f"{path or 'value'} {inst!r} is not one of {schema['enum']}")
    if isinstance(inst, str):
        if "pattern" in schema and not re.search(schema["pattern"], inst):
            _fail(diags, "pack.schema", f"{path} does not match pattern {schema['pattern']!r}")
        if "minLength" in schema and len(inst) < schema["minLength"]:
            _fail(diags, "pack.schema", f"{path} is shorter than {schema['minLength']}")
        if schema.get("format") == "date-time" and not _valid_datetime(inst):
            _fail(diags, "pack.schema", f"{path} is not an RFC 3339 date-time")
    if isinstance(inst, (int, float)) and not isinstance(inst, bool):
        if "minimum" in schema and inst < schema["minimum"]:
            _fail(diags, "pack.schema", f"{path} is less than the minimum {schema['minimum']}")
        if "maximum" in schema and inst > schema["maximum"]:
            _fail(diags, "pack.schema", f"{path} is greater than the maximum {schema['maximum']}")
    if isinstance(inst, dict):
        props = schema.get("properties", {})
        for req in schema.get("required", []):
            if req not in inst:
                _fail(diags, "pack.schema", f"{path or 'value'} is missing required {req!r}")
        if "minProperties" in schema and len(inst) < schema["minProperties"]:
            _fail(diags, "pack.schema", f"{path or 'value'} has fewer than {schema['minProperties']} properties")
        ap = schema.get("additionalProperties")
        pn = schema.get("propertyNames")
        for k, v in inst.items():
            kp = f"{path}.{k}"
            if pn is not None:
                _validate(k, pn, f"{path}.<key {k!r}>", diags, root)
            if k in props:
                _validate(v, props[k], kp, diags, root)
            elif ap is False:
                _fail(diags, "pack.schema", f"{path or 'value'} has unknown property {k!r}")
            elif isinstance(ap, dict):
                _validate(v, ap, kp, diags, root)
    if isinstance(inst, list):
        if "minItems" in schema and len(inst) < schema["minItems"]:
            _fail(diags, "pack.schema", f"{path} has fewer than {schema['minItems']} items")
        if schema.get("uniqueItems"):
            if any(_json_equal(inst[i], inst[j])
                   for i in range(len(inst)) for j in range(i + 1, len(inst))):
                _fail(diags, "pack.schema", f"{path} has duplicate items")
        if isinstance(schema.get("items"), dict):
            for i, item in enumerate(inst):
                _validate(item, schema["items"], f"{path}[{i}]", diags, root)
    for s in schema.get("allOf", []):
        _validate(inst, s, path, diags, root)
    if "oneOf" in schema:
        if sum(1 for s in schema["oneOf"] if _is_valid(inst, s, root)) != 1:
            _fail(diags, "pack.schema", f"{path or 'value'} must match exactly one of oneOf")
    if "anyOf" in schema:
        if not any(_is_valid(inst, s, root) for s in schema["anyOf"]):
            _fail(diags, "pack.schema", f"{path or 'value'} must match at least one of anyOf")
    if "not" in schema and _is_valid(inst, schema["not"], root):
        _fail(diags, "pack.schema", f"{path or 'value'} must not match the 'not' schema")
    if "if" in schema:
        if _is_valid(inst, schema["if"], root):
            if "then" in schema:
                _validate(inst, schema["then"], path, diags, root)
        elif "else" in schema:
            _validate(inst, schema["else"], path, diags, root)


# --- path containment: a pack/bundle path must resolve UNDER its root ---
def _contained(root, rel, diags, what):
    if not isinstance(rel, str) or os.path.isabs(rel) or ".." in rel.replace("\\", "/").split("/"):
        _fail(diags, "pack.path", f"{what} {rel!r} must be a relative in-tree path (no absolute / '..')")
        return None
    root_abs = os.path.realpath(root)
    target = os.path.realpath(os.path.join(root_abs, rel))
    if os.path.commonpath([root_abs, target]) != root_abs:
        _fail(diags, "pack.path", f"{what} {rel!r} escapes its root")
        return None
    return target


def _discover_payload_paths(pack_root, pack_path):
    """Return every file/symlink entry below pack_root except the manifest."""
    root_abs = os.path.abspath(pack_root)
    manifest_abs = os.path.abspath(pack_path)
    found = []
    for current, dirs, files in os.walk(root_abs, followlinks=False):
        symlink_dirs = [name for name in dirs if os.path.islink(os.path.join(current, name))]
        dirs[:] = [name for name in dirs if name not in symlink_dirs]
        for name in files + symlink_dirs:
            absolute = os.path.abspath(os.path.join(current, name))
            if absolute == manifest_abs:
                continue
            found.append(os.path.relpath(absolute, root_abs).replace(os.sep, "/"))
    return sorted(found)


def _contract_schema(contract, bundle_root, diags):
    schema_abs = _contained(bundle_root, contract["path"], diags, "bundled schema")
    if schema_abs is None:
        return None
    if not os.path.exists(schema_abs):
        _fail(
            diags,
            "pack.digest",
            f"bundled schema {contract['path']!r} is missing from the bundle root",
        )
        return None
    if _sha256(schema_abs) != contract["sha256"]:
        _fail(
            diags,
            "pack.digest",
            f"bundled schema {contract['path']!r} fails its bundle digest pin",
        )
        return None
    return _load(schema_abs, diags)


def _validate_semantic_payload(
    instance_path, contract_name, contract, bundle_root, path_label, diags
):
    schema = _contract_schema(contract, bundle_root, diags)
    if schema is None:
        return None
    instance = _load_semantic_payload(instance_path, path_label, diags)
    if instance is None:
        return None
    _validate(instance, schema, contract_name, diags, schema)
    return instance


def _verify_v2_payloads(pack, pack_path, pack_root, bundle_root, contracts, diags):
    payloads = pack["payloads"]
    paths = [row["path"] for row in payloads]
    for path in paths:
        if normalized_payload_path(path) != path:
            _fail(diags, "pack.path", f"payload path {path!r} is not a normalized relative path")
    if any(d.startswith("[pack.path]") for d in diags):
        return

    if paths != sorted(paths):
        _fail(
            diags,
            "pack.completeness",
            "payload inventory must be ordered lexicographically by path",
        )
    duplicate_paths = sorted(
        path for path, count in Counter(paths).items() if count > 1
    )
    if duplicate_paths:
        _fail(
            diags,
            "pack.completeness",
            f"payload inventory has duplicate paths: {duplicate_paths!r}",
        )

    root_real = os.path.realpath(pack_root)
    if os.path.islink(pack_root):
        _fail(diags, "pack.path", "pack root must not be a symlink")
        return
    for path in sorted(set(paths)):
        lexical = os.path.abspath(os.path.join(pack_root, *path.split("/")))
        resolved = os.path.realpath(lexical)
        try:
            inside = os.path.commonpath([root_real, resolved]) == root_real
        except ValueError:
            inside = False
        if not inside:
            _fail(
                diags,
                "pack.path",
                f"payload {path!r} escapes the pack root through a symlink",
            )
        elif os.path.islink(lexical):
            _fail(diags, "pack.path", f"payload {path!r} must be a regular file, not a symlink")
    if any(d.startswith("[pack.path]") for d in diags):
        return

    discovered = _discover_payload_paths(pack_root, pack_path)
    declared = set(paths)
    missing = sorted(declared - set(discovered))
    extra = sorted(set(discovered) - declared)
    if missing:
        _fail(diags, "pack.completeness", f"payload inventory is missing files: {missing!r}")
    if extra:
        _fail(diags, "pack.completeness", f"pack has unlisted extra files: {extra!r}")
    if duplicate_paths or missing or extra or paths != sorted(paths):
        return

    for row in payloads:
        absolute = os.path.join(pack_root, *row["path"].split("/"))
        try:
            actual = file_sha256(absolute)
        except OSError as exc:
            _fail(diags, "pack.io", f"cannot read payload {row['path']!r}: {exc}")
            continue
        if actual != row["sha256"]:
            _fail(
                diags,
                "pack.integrity",
                f"payload {row['path']!r} digest {actual} != manifest {row['sha256']}",
            )
    if any(d.startswith(("[pack.integrity]", "[pack.io]")) for d in diags):
        return

    named_contracts = {row.get("contract") for row in payloads if row.get("contract")}
    for name in pack.get("requiredContracts") or []:
        if name in contracts and name not in named_contracts:
            _fail(
                diags,
                "pack.missing_required",
                f"required contract {name!r} has no payload in the complete inventory",
            )
    for i, row in enumerate(payloads):
        contract_name = row.get("contract")
        if not contract_name:
            continue
        if contract_name not in contracts:
            _fail(
                diags,
                "pack.unknown_contract",
                f"payloads[{i}] references contract {contract_name!r} not in the bundle",
            )
            continue
        absolute = os.path.join(pack_root, *row["path"].split("/"))
        instance = _validate_semantic_payload(
            absolute,
            contract_name,
            contracts[contract_name],
            bundle_root,
            f"payloads[{i}]",
            diags,
        )
        if contract_name == "target-profile" and isinstance(instance, dict):
            yield i, instance


def verify(bundle_path, bundle_root, pack_path, pack_root, diags):
    bundle = _load(bundle_path, diags)
    pack = _load(pack_path, diags)
    if bundle is None or pack is None:
        return
    if not isinstance(bundle, dict) or not isinstance(pack, dict):
        _fail(diags, "pack.shape", "bundle and pack must be JSON objects")
        return

    # (1) Bundle integrity: recompute its self-digest fail-closed.
    stored = bundle.get("bundleDigest")
    body = {k: v for k, v in bundle.items() if k != "bundleDigest"}
    recomputed = "sha256:" + hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        .encode("utf-8")).hexdigest()
    if stored != recomputed:
        _fail(diags, "pack.digest", f"bundle self-digest {stored} != recomputed {recomputed}")
        return
    contracts = {c["name"]: c for c in bundle.get("contracts", [])
                 if isinstance(c, dict) and isinstance(c.get("name"), str)
                 and isinstance(c.get("path"), str) and isinstance(c.get("sha256"), str)}
    versions = bundle.get("versions", {})
    if not isinstance(versions, dict):
        _fail(diags, "pack.shape", "bundle 'versions' must be an object")
        return

    # Load the published closed semantic-feature vocabulary (digest-verified,
    # schema-validated, version-consistent), so a pack's semantic-profile features
    # are matched against the SAME closed set the translator enforces — an unknown
    # feature fails closed (pack.unknown_semantic_feature).
    vocab_features, vocab_version = _load_vocabulary(bundle, bundle_root, versions, contracts, diags)

    # The published capability registry is digest/schema/version-verified and
    # single-source-consistent with the vocabulary, so a package-only verifier can
    # independently validate the authoritative capability contract ().
    _check_capability_registry(bundle, bundle_root, versions, contracts, vocab_features, diags)

    # (2) The manifest contract is explicit. Legacy v1 manifests have no
    # schemaVersion; complete manifests name schemaVersion 2.
    manifest_version = pack.get("schemaVersion", 1)
    if manifest_version not in (1, 2):
        _fail(
            diags,
            "pack.shape",
            f"unsupported domain-pack schemaVersion {manifest_version!r}",
        )
        return
    pack_contract_name = "domain-pack-v2" if manifest_version == 2 else "domain-pack"
    pack_contract = contracts.get(pack_contract_name)
    if pack_contract is None:
        _fail(
            diags,
            "pack.unknown_contract",
            f"the bundle publishes no {pack_contract_name!r} contract to validate the manifest",
        )
        return
    pack_schema_abs = _contained(bundle_root, pack_contract["path"], diags, "bundled schema")
    if pack_schema_abs is None:
        return
    if not os.path.exists(pack_schema_abs):
        _fail(diags, "pack.digest", f"bundled domain-pack schema {pack_contract['path']!r} is missing from the bundle root")
        return
    if _sha256(pack_schema_abs) != pack_contract["sha256"]:
        _fail(diags, "pack.digest", f"bundled schema {pack_contract['path']!r} fails its bundle digest pin")
        return
    pack_schema = _load(pack_schema_abs, diags)
    if pack_schema is None:
        return
    shape: list = []
    _validate(pack, pack_schema, "pack", shape, pack_schema)
    if shape:
        diags.extend(shape)
        return  # the manifest is malformed; do not dereference it further

    # v2 identity covers the canonical manifest body, including the complete,
    # ordered payload inventory. A stale identity makes the manifest untrusted.
    if manifest_version == 2:
        actual_pack_digest = canonical_pack_digest(pack)
        if pack["packDigest"] != actual_pack_digest:
            _fail(
                diags,
                "pack.integrity",
                f"packDigest {pack['packDigest']} != recomputed {actual_pack_digest}",
            )
            return

    # (3) Exact bundle targeting: id + version + the EXACT bundleDigest pin.
    tgt = pack["targetsBundle"]
    if tgt["bundleId"] != bundle.get("bundleId"):
        _fail(diags, "pack.bundle_mismatch", f"pack targets bundleId {tgt['bundleId']!r} != {bundle.get('bundleId')!r}")
    if tgt["bundleVersion"] != bundle.get("bundleVersion"):
        _fail(diags, "pack.bundle_mismatch", f"pack targets bundleVersion {tgt['bundleVersion']!r} != {bundle.get('bundleVersion')!r}")
    if tgt["bundleDigest"] != stored:
        _fail(diags, "pack.digest", f"pack pins bundleDigest {tgt['bundleDigest']} != this bundle's {stored} "
              "(the pinned bundle was re-published with different contents)")

    # (4) Version-axis pins negotiated per the bundle's policy.
    for axis, want in (pack.get("translatorPins") or {}).items():
        if axis not in versions:
            _fail(diags, "pack.unknown_version", f"pins unknown axis {axis!r} not published by the bundle")
            continue
        _compatible_pin(axis, want, versions[axis], diags)

    # (5) Feature negotiation: BOTH required and optional names must be real
    # bundle contracts (a typo is not graceful degradation); required must also
    # be present.
    for name in (pack.get("requiredContracts") or []):
        if name not in contracts:
            _fail(diags, "pack.missing_required", f"required contract {name!r} is not in the bundle")
    for name in (pack.get("optionalContracts") or []):
        if name not in contracts:
            _fail(diags, "pack.unknown_contract", f"optional contract {name!r} is not a bundle contract (typo?)")

    # (6) v2 verifies the complete byte inventory before selectively applying
    # semantic JSON contracts. v1 retains its historical artifact behavior.
    if manifest_version == 2:
        for i, instance in _verify_v2_payloads(
            pack, pack_path, pack_root, bundle_root, contracts, diags
        ):
            _check_profile_vocabulary(
                instance, vocab_features, vocab_version, i, diags
            )
        return

    for i, art in enumerate(pack["artifacts"]):
        cname, apath = art["contract"], art["path"]
        if cname not in contracts:
            _fail(
                diags,
                "pack.unknown_contract",
                f"artifacts[{i}] references contract {cname!r} not in the bundle",
            )
            continue
        art_abs = _contained(pack_root, apath, diags, "artifact")
        if art_abs is None:
            continue
        instance = _validate_semantic_payload(
            art_abs, cname, contracts[cname], bundle_root, f"artifacts[{i}]", diags
        )
        if cname == "target-profile" and isinstance(instance, dict):
            _check_profile_vocabulary(
                instance, vocab_features, vocab_version, i, diags
            )


# Distinguishes "the bundle publishes no vocabulary" (None) from "a vocabulary is
# published but was rejected here" (_VOCAB_INVALID) so downstream profile matching
# does not add a factually-false "no vocabulary published" diagnostic on top of the
# real rejection.
_VOCAB_INVALID = object()


def _digest_verified_schema(contract, bundle_root, diags):
    """Load a bundled schema after digest-verifying it, or None (with a pack.digest
    diagnostic) if it is missing/tampered."""
    if contract is None:
        return None
    abs_ = _contained(bundle_root, contract.get("path"), diags, "bundled schema")
    if abs_ is None:
        return None
    if not os.path.exists(abs_):
        _fail(diags, "pack.digest", f"bundled schema {contract.get('path')!r} is missing from the bundle root")
        return None
    if _sha256(abs_) != contract.get("sha256"):
        _fail(diags, "pack.digest", f"bundled schema {contract.get('path')!r} fails its bundle digest pin")
        return None
    return _load(abs_, diags)


def _load_vocabulary(bundle, bundle_root, versions, contracts, diags):
    """The published closed semantic-feature vocabulary -> (features, semanticProfileVersion).
    Digest-verified against the bundle-referenced file, VALIDATED against its
    published schema (kind/schemaVersion/features shape), and VERSION-CONSISTENT:
    the artifact's own semanticProfileVersion must equal the bundle's
    semanticVocabulary metadata AND versions.semanticProfileVersion — so a
    self-consistently re-signed but internally-drifted vocabulary fails closed, not
    only stale bytes.

    Three distinct outcomes so downstream matching does not add a misleading error:
      - a frozenset  -> present + valid;
      - None         -> the bundle publishes NO vocabulary (a pre-1.1 bundle);
      - _VOCAB_INVALID -> present but REJECTED here (a diagnostic was already emitted;
        the caller must NOT then claim it is absent)."""
    voc = bundle.get("semanticVocabulary")
    if not isinstance(voc, dict):
        return None, None
    abs_ = _contained(bundle_root, voc.get("path"), diags, "semantic vocabulary")
    if abs_ is None:
        return _VOCAB_INVALID, None
    if not os.path.exists(abs_):
        _fail(diags, "pack.digest", f"bundled semantic vocabulary {voc.get('path')!r} is missing from the bundle root")
        return _VOCAB_INVALID, None
    if _sha256(abs_) != voc.get("sha256"):
        _fail(diags, "pack.digest", f"semantic vocabulary {voc.get('path')!r} fails its bundle digest pin")
        return _VOCAB_INVALID, None
    art = _load(abs_, diags)
    if not isinstance(art, dict):
        _fail(diags, "pack.shape", "the semantic vocabulary artifact is malformed")
        return _VOCAB_INVALID, None
    # Validate the artifact against its OWN published (digest-verified) schema:
    # kind/schemaVersion, plus a non-empty, unique, well-formed feature set.
    vocab_schema = _digest_verified_schema(contracts.get("semantic-feature-vocabulary"), bundle_root, diags)
    if vocab_schema is None:
        return _VOCAB_INVALID, None
    shape: list = []
    _validate(art, vocab_schema, "semanticVocabulary", shape, vocab_schema)
    if shape:
        diags.extend(shape)
        return _VOCAB_INVALID, None
    # Tri-consistency of the version pin: artifact == metadata == versions.
    art_v, meta_v, bundle_v = (art.get("semanticProfileVersion"),
                               voc.get("semanticProfileVersion"),
                               versions.get("semanticProfileVersion"))
    if not (art_v == meta_v == bundle_v):
        _fail(diags, "pack.pin_mismatch",
              f"semantic vocabulary version drift: artifact {art_v!r} / bundle metadata {meta_v!r} / "
              f"versions.semanticProfileVersion {bundle_v!r} must all agree")
        return _VOCAB_INVALID, None
    return frozenset(f for f in art["features"] if isinstance(f, str)), meta_v


def _check_capability_registry(bundle, bundle_root, versions, contracts, vocab_features, diags):
    """The published capability registry (): digest-verified against its
    bundle-referenced file, VALIDATED against its published schema, VERSION-
    CONSISTENT (artifact == bundle metadata == versions.semanticProfileVersion),
    and — when a vocabulary is present — SINGLE-SOURCE CONSISTENT (its capability
    id set equals the published closed vocabulary). So a package-only verifier can
    obtain and independently validate the SAME closed capability contract the
    translator emits, and a tampered/drifted/re-signed registry fails closed. A
    pre-1.7 bundle publishes none (nothing to check)."""
    reg = bundle.get("semanticCapabilityRegistry")
    if not isinstance(reg, dict):
        return
    abs_ = _contained(bundle_root, reg.get("path"), diags, "semantic capability registry")
    if abs_ is None:
        return
    if not os.path.exists(abs_):
        _fail(diags, "pack.digest", f"bundled semantic capability registry {reg.get('path')!r} is missing from the bundle root")
        return
    if _sha256(abs_) != reg.get("sha256"):
        _fail(diags, "pack.digest", f"semantic capability registry {reg.get('path')!r} fails its bundle digest pin")
        return
    art = _load(abs_, diags)
    if not isinstance(art, dict):
        _fail(diags, "pack.shape", "the semantic capability registry artifact is malformed")
        return
    reg_schema = _digest_verified_schema(contracts.get("semantic-capability-registry"), bundle_root, diags)
    if reg_schema is None:
        return
    shape: list = []
    _validate(art, reg_schema, "semanticCapabilityRegistry", shape, reg_schema)
    if shape:
        diags.extend(shape)
        return
    art_v, meta_v, bundle_v = (art.get("semanticProfileVersion"),
                               reg.get("semanticProfileVersion"),
                               versions.get("semanticProfileVersion"))
    if not (art_v == meta_v == bundle_v):
        _fail(diags, "pack.pin_mismatch",
              f"semantic capability registry version drift: artifact {art_v!r} / bundle metadata {meta_v!r} / "
              f"versions.semanticProfileVersion {bundle_v!r} must all agree")
        return
    # Single-source: the registry's capability id set must EQUAL the published
    # closed vocabulary (when present) — a package-only verifier confirms the
    # registry neither adds nor drops a capability relative to the vocabulary the
    # intake seam anchors executable reductions against.
    if isinstance(vocab_features, frozenset):
        reg_ids = frozenset(c.get("id") for c in art.get("capabilities", [])
                            if isinstance(c, dict))
        if reg_ids != vocab_features:
            _fail(diags, "pack.pin_mismatch",
                  "the published capability registry's id set does not equal the "
                  "published closed vocabulary (single-source drift)")


def _check_profile_vocabulary(profile, vocab_features, vocab_version, i, diags):
    """A target-profile's CLOSED semanticProfile.features must all be in the
    published vocabulary, and its version must match — else fail closed."""
    sp = profile.get("semanticProfile")
    if not isinstance(sp, dict):
        return
    feats = sp.get("features")
    if not isinstance(feats, list):
        return
    if vocab_features is _VOCAB_INVALID:
        return  # the vocabulary was published but already rejected upstream; a
        #         second "absent" diagnostic would be factually false.
    if vocab_features is None:
        _fail(diags, "pack.unknown_semantic_feature",
              f"artifacts[{i}] declares semantic-profile features but the bundle publishes no vocabulary to match them")
        return
    for f in feats:
        if f not in vocab_features:
            _fail(diags, "pack.unknown_semantic_feature",
                  f"artifacts[{i}] semantic-profile feature {f!r} is not in the bundle's closed semantic-feature vocabulary")
    if vocab_version is not None and sp.get("version") != vocab_version:
        _fail(diags, "pack.pin_mismatch",
              f"artifacts[{i}] semanticProfile.version {sp.get('version')!r} != bundle vocabulary semanticProfileVersion {vocab_version!r}")


def _compatible_pin(axis, want, have, diags):
    """Apply the bundle's per-axis policy: toolVersion is same-MAJOR and have >=
    want; every other axis is exact. Fail-closed on anything unknown."""
    if axis == "toolVersion":
        # Require the exact MAJOR.MINOR.PATCH SemVer shape as a string — reject an
        # integer pin or a short form like "0.2" (which int-list compare would
        # accept against "0.2.0").
        if not isinstance(want, str) or not _SEMVER_RE.match(want):
            _fail(diags, "pack.pin_mismatch",
                  f"toolVersion pin {want!r} must be an exact MAJOR.MINOR.PATCH SemVer string")
            return
        if not isinstance(have, str) or not _SEMVER_RE.match(have):
            _fail(diags, "pack.pin_mismatch", f"bundle toolVersion {have!r} is not SemVer")
            return
        wj = [int(x) for x in want.split(".")]
        hj = [int(x) for x in have.split(".")]
        if wj[0] != hj[0] or hj < wj:
            _fail(diags, "pack.pin_mismatch",
                  f"toolVersion pin {want!r} not satisfied by bundle {have!r} (needs same major and bundle >= pin)")
        return
    if not _json_equal(want, have):
        _fail(diags, "pack.pin_mismatch", f"{axis} pin {want!r} != bundle {have!r} (exact)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", required=True)
    ap.add_argument("--bundle-root", required=True,
                    help="root the bundle's repo-root-relative contract paths resolve against")
    ap.add_argument("--pack", required=True)
    ap.add_argument("--pack-root", default=".",
                    help="root the pack's artifact paths resolve against (default: .)")
    args = ap.parse_args()
    diags: list = []
    try:
        verify(args.bundle, args.bundle_root, args.pack, args.pack_root, diags)
    except (KeyError, TypeError, AttributeError, IndexError) as e:  # defence in depth
        _fail(diags, "pack.shape", f"malformed bundle/pack structure: {e}")
    if diags:
        for d in diags:
            print(f"  - {d}")
        print(f"domain-pack conformance: {len(diags)} problem(s)")
        return 1
    print("domain-pack conformance: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())

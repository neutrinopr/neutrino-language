#!/usr/bin/env python3
""" — validate the cross-rail fixture catalog (examples/cross-rail-fixtures.json).

The catalog is the translator-owned contract telling downstream rails (network, agents,
console, release notes) which example fixtures are cross-rail and which artifact files are
normative. This validator keeps it honest, fail-closed:

  - every referenced path is committed and present;
  - each fixture's capabilityId/Version matches its generated binding-topology;
  - the catalog's declared lateBoundSlots EXACTLY match the topology's `to_be_bound`
    slots (slotId, org, participant, allowedRuntimes, minAssurance, authorizedBinder),
    so the runtime/assurance policy a downstream consumer reads from the catalog is the
    real policy — not a stale copy;
  - the Binding Manifest binds exactly those late-bound slots (multi-slot completeness),
    for the same capability, with each binding within its slot's policy;
  - every declared target output's artifacts exist.

Standard library only. Exit 0 ok / 1 violations / 2 usage.

  scripts/validators/validate_cross_rail_catalog.py [--catalog examples/cross-rail-fixtures.json]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

ASSURANCE = {"A1": 1, "A2": 2, "A3": 3, "A4": 4}
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# The single source of truth for the translator compatibility surface (). The catalog's
# top-level `compatibility` block must be pinned to these constants, so a version bump that
# is not reflected in the catalog fails closed.
VERSIONINFO = "include/Neutrino/VersionInfo.h"
_COMPAT_FIELDS = {
    "toolVersion": "kToolVersion",
    "mlirDialectVersion": "kMlirDialectVersion",
    "schemaBundleVersion": "kSchemaBundleVersion",
    "conformanceVectorVersion": "kConformanceVectorVersion",
    "compatibilityManifestVersion": "kCompatibilityManifestVersion",
}
# Per-contract schema versions: catalog compatibility.schemas.<key> -> VersionInfo.h constant.
_COMPAT_SCHEMAS = {
    "bindingPolicy": "kSchemaBindingPolicy",
    "bindingReceipt": "kSchemaBindingReceipt",
    "runtimeEvidence": "kSchemaRuntimeEvidence",
}


def _load(rel: str, errors: list, where: str):
    path = os.path.join(REPO, rel)
    if not os.path.exists(path):
        errors.append(f"{where}: missing committed path {rel!r}")
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as exc:
        errors.append(f"{where}: cannot read {rel!r}: {exc}")
        return None


def _exists(rel: str, errors: list, where: str) -> None:
    if not os.path.exists(os.path.join(REPO, rel)):
        errors.append(f"{where}: missing committed path {rel!r}")


def _topology_slots(topo: dict) -> dict:
    """slotId -> normalized to_be_bound slot policy."""
    out = {}
    for org in topo.get("organizations", []):
        for p in org.get("participants", []):
            for s in p.get("slots", []):
                if s.get("lateBindingMode") == "to_be_bound":
                    out[s.get("slotId")] = {
                        "slotId": s.get("slotId"),
                        "organizationId": org.get("organizationId"),
                        "participantId": p.get("participantId"),
                        "allowedRuntimes": s.get("allowedRuntimes") or [],
                        "minAssurance": s.get("minAssurance"),
                        "authorizedBinder": s.get("authorizedBinder"),
                    }
    return out


def _check_fixture(fx: dict, errors: list) -> None:
    fid = fx.get("fixtureId", "<unknown>")
    where = f"fixture {fid!r}"

    for key in ("fixtureId", "capabilityId", "capabilityVersion", "source", "scenario",
                "targets", "generated", "bindingTopology", "bindingManifest",
                "selfTest", "lateBoundSlots"):
        if key not in fx:
            errors.append(f"{where}: missing required field {key!r}")
    if errors and any(e.startswith(f"{where}: missing required field") for e in errors):
        return

    # Plain path existence.
    _exists(fx["source"], errors, where)
    _exists(fx["scenario"], errors, where)

    # Declared target outputs: every listed target has a generated[] block, all present.
    for target in fx["targets"]:
        files = fx["generated"].get(target)
        if not files:
            errors.append(f"{where}: target {target!r} has no generated artifacts listed")
            continue
        for rel in files:
            _exists(rel, errors, f"{where} target {target}")

    # Capability identity in the GENERATED capability artifact (): the catalog is the
    # domain registry, and its declared capabilityId/Version must match the version the
    # compiler stamped into capability.json (capabilityVersion flows source `version` ->
    # IR -> capability identity; see docs/domains/DOMAIN_REGISTRY.md). So a registry entry cannot
    # advertise a domain version the generated artifacts don't actually carry.
    cap_files = [rel for files in fx["generated"].values() if isinstance(files, list) for rel in files]
    cap_rel = next((r for r in cap_files if os.path.basename(r) == "capability.json"), None)
    if cap_rel is not None:
        cap = _load(cap_rel, errors, where)
        if cap is not None:
            if cap.get("capability") != fx["capabilityId"]:
                errors.append(
                    f"{where}: capability.json capability {cap.get('capability')!r} != catalog capabilityId {fx['capabilityId']!r}")
            if cap.get("capabilityVersion") != fx["capabilityVersion"]:
                errors.append(
                    f"{where}: capability.json capabilityVersion {cap.get('capabilityVersion')!r} != catalog {fx['capabilityVersion']!r}")

    # Topology: capability identity + the exact late-bound slot policy set.
    topo = _load(fx["bindingTopology"], errors, where)
    cat_slots = {s["slotId"]: s for s in fx["lateBoundSlots"]}
    if topo is not None:
        if topo.get("capability") != fx["capabilityId"]:
            errors.append(
                f"{where}: topology capability {topo.get('capability')!r} != catalog {fx['capabilityId']!r}")
        if topo.get("capabilityVersion") != fx["capabilityVersion"]:
            errors.append(
                f"{where}: topology capabilityVersion {topo.get('capabilityVersion')!r} != catalog {fx['capabilityVersion']!r}")
        topo_slots = _topology_slots(topo)
        if set(topo_slots) != set(cat_slots):
            errors.append(
                f"{where}: late-bound slots drift — catalog {sorted(cat_slots)} != topology {sorted(topo_slots)}")
        for sid in sorted(set(topo_slots) & set(cat_slots)):
            t, c = topo_slots[sid], cat_slots[sid]
            for field in ("organizationId", "participantId", "allowedRuntimes",
                          "minAssurance", "authorizedBinder"):
                if t.get(field) != c.get(field):
                    errors.append(
                        f"{where} slot {sid}: {field} catalog {c.get(field)!r} != topology {t.get(field)!r}")

    # Binding Manifest: same capability, binds exactly the declared late-bound slots once,
    # each binding within its slot's policy (runtime in allowedRuntimes, assurance >= min,
    # binder == authorizedBinder). Completeness mirrors validate_binding_manifest.py.
    man = _load(fx["bindingManifest"], errors, where)
    if man is not None:
        if man.get("capability") != fx["capabilityId"]:
            errors.append(
                f"{where}: manifest capability {man.get('capability')!r} != catalog {fx['capabilityId']!r}")
        bindings = man.get("bindings") or []
        bound = [b.get("slotId") for b in bindings]
        if sorted(bound) != sorted(cat_slots):
            errors.append(
                f"{where}: manifest binds {sorted(bound)} != catalog late-bound slots {sorted(cat_slots)}")
        for b in bindings:
            sid = b.get("slotId")
            c = cat_slots.get(sid)
            if c is None:
                continue
            # Binding Manifest identity: a binding must name the same (org, participant)
            # as the slot it binds, so a manifest cannot bind a known slotId under the
            # wrong org/participant and still be certified for downstream consumption.
            if b.get("organizationId") != c["organizationId"]:
                errors.append(
                    f"{where} binding {sid}: organizationId {b.get('organizationId')!r} != slot {c['organizationId']!r}")
            if b.get("participantId") != c["participantId"]:
                errors.append(
                    f"{where} binding {sid}: participantId {b.get('participantId')!r} != slot {c['participantId']!r}")
            if b.get("runtime") not in c["allowedRuntimes"]:
                errors.append(
                    f"{where} binding {sid}: runtime {b.get('runtime')!r} not in allowedRuntimes {c['allowedRuntimes']}")
            a = b.get("assurance")
            if a not in ASSURANCE:
                errors.append(f"{where} binding {sid}: assurance {a!r} is not A1..A4")
            elif ASSURANCE[a] < ASSURANCE.get(c["minAssurance"], 1):
                errors.append(
                    f"{where} binding {sid}: assurance {a} below slot minAssurance {c['minAssurance']}")
            if b.get("binder") != c["authorizedBinder"]:
                errors.append(
                    f"{where} binding {sid}: binder {b.get('binder')!r} != authorizedBinder {c['authorizedBinder']!r}")

    # Optional L2 domain-semantics sidecar (): if a fixture cites an `l2` artifact,
    # the path must exist and the artifact must implement THIS fixture's capability —
    # so the cross-link cannot silently point at the wrong or a stale L2 sidecar. The
    # L2 artifact's own well-formedness is pinned separately by validate_l2_domain_semantics.py.
    l2 = fx.get("l2")
    if l2 is not None:
        l2obj = _load(l2, errors, where)
        if l2obj is not None:
            if l2obj.get("implements") != fx["capabilityId"]:
                errors.append(
                    f"{where}: l2 sidecar implements {l2obj.get('implements')!r} != catalog capabilityId {fx['capabilityId']!r}")
            _check_l2_traces_generated(fx, l2obj, errors, where)

    _check_import_projection(fx, errors, where)


_DOMAIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "domain")
V2_VALIDATOR = os.path.join(_DOMAIN_DIR, "validate_l2_domain_semantics_v2.py")
V3_VALIDATOR = os.path.join(_DOMAIN_DIR, "validate_l2_domain_semantics_v3.py")


def _sidecar_validator(obj: dict) -> str:
    """Pick the validator by the sidecar's own schemaVersion: v3 () is the
    producer output; v2 is the retained legacy baseline. Both share the same
    cross-record + hash contract."""
    return V3_VALIDATOR if obj.get("schemaVersion") == 3 else V2_VALIDATOR


def _check_import_projection(fx: dict, errors: list, where: str) -> None:
    """The catalog's `imports` are a canonical PROJECTION of the domain's own
    l2.import records (). The check is BIDIRECTIONAL and enforced against the
    VALIDATED, hash-recomputed v2 sidecar the fixture references, so the
    projection cannot become a second, drifting ontology source of truth:

      * a fixture with `l2v2` MUST declare `imports`, and they must equal the
        governed sidecar's imports EXACTLY (including the empty projection) —
        otherwise the resolver would see a leaf where the artifact has edges;
      * a fixture that declares `imports` MUST reference a governed sidecar;
      * the referenced v2 artifact is VALIDATED (shape + semantics + RECOMPUTED
        domainSemanticsHash) via the stdlib v2 validator, and the `l2v2Hash` pin
        must equal that recomputed/verified hash — so a coordinated edit to the
        sidecar's stored hash field + the catalog pin cannot pass."""
    imports = fx.get("imports")
    l2v2, l2v2_hash = fx.get("l2v2"), fx.get("l2v2Hash")
    if imports is None and l2v2 is None:
        return  # a domain with no imports and no governed sidecar: nothing to check
    if imports is not None and not isinstance(imports, list):
        errors.append(f"{where}: imports must be an array")
        return
    if imports is not None:
        for i, im in enumerate(imports):
            if not (isinstance(im, dict) and isinstance(im.get("capabilityId"), str)
                    and isinstance(im.get("capabilityVersion"), str)):
                errors.append(f"{where}: imports[{i}] must be {{capabilityId, capabilityVersion}}")
                return
    if imports is not None and (not l2v2 or not l2v2_hash):
        errors.append(f"{where}: a fixture declaring imports must reference a governed "
                      "v2 sidecar (l2v2 + l2v2Hash) so the projection is checkable")
        return
    if l2v2 is not None and imports is None:
        errors.append(f"{where}: a fixture with a governed v2 sidecar (l2v2) must declare "
                      "its `imports` projection (use [] if it imports nothing) so a "
                      "resolver cannot silently see a leaf where the artifact has edges")
        return
    if not l2v2_hash:
        errors.append(f"{where}: l2v2 requires an l2v2Hash pin")
        return
    # A governed reference is repository-root-relative (the catalog path
    # contract, shared with the C++ resolver). Reject an absolute path or a '..'
    # escape so both trust paths resolve the same in-tree bytes.
    if os.path.isabs(l2v2) or ".." in l2v2.replace("\\", "/").split("/"):
        errors.append(f"{where}: l2v2 {l2v2!r} must be a repository-root-relative "
                      "path with no '..' escape")
        return
    obj = _load(l2v2, errors, where)
    if obj is None:
        return
    # Validate the referenced v2 artifact (shape + semantics + RECOMPUTED hash).
    l2v2_path = os.path.join(REPO, l2v2)
    r = subprocess.run([sys.executable, _sidecar_validator(obj), "--artifact", l2v2_path],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if r.returncode != 0:
        errors.append(f"{where}: governed v2 sidecar {l2v2!r} is invalid: "
                      f"{r.stdout.decode('utf-8', 'replace').strip()}")
        return
    if obj.get("implements") != fx["capabilityId"]:
        errors.append(f"{where}: l2v2 implements {obj.get('implements')!r} != capabilityId {fx['capabilityId']!r}")
    if obj.get("version") != fx["capabilityVersion"]:
        errors.append(f"{where}: l2v2 version {obj.get('version')!r} != capabilityVersion {fx['capabilityVersion']!r}")
    if obj.get("domainSemanticsHash") != l2v2_hash:
        errors.append(f"{where}: l2v2Hash pin {l2v2_hash!r} != validated sidecar domainSemanticsHash "
                      f"{obj.get('domainSemanticsHash')!r}")
    projection = sorted((im["capabilityId"], im["capabilityVersion"]) for im in (imports or []))
    governed = sorted((im.get("capability"), im.get("version"))
                      for im in obj.get("imports", []) if isinstance(im, dict))
    if projection != governed:
        errors.append(f"{where}: imports projection {projection} != governed v2 sidecar "
                      f"imports {governed} (the catalog projection drifted from the "
                      "hash-pinned artifact)")


def _check_l2_traces_generated(fx: dict, l2obj: dict, errors: list, where: str) -> None:
    """The sidecar's l1 anchors must come from THIS fixture's GENERATED L1 artifacts, not be
    self-declared/invented/stale ( "tied to L1 examples / aligned with generated artifacts").
    Builds the L1 surface from capability.json (capability, entries[].name, operations, ledgers)
    and the balance obligation from compensation.json (invariantAfterCompensation), then requires
    every l2.l1.capability/primitives/obligations entry to resolve into it."""
    l1 = l2obj.get("l1") if isinstance(l2obj.get("l1"), dict) else {}
    gen_files = [rel for files in fx["generated"].values() if isinstance(files, list) for rel in files]
    cap = next((_load(r, errors, where) for r in gen_files if os.path.basename(r) == "capability.json"), None)
    comp = next((_load(r, errors, where) for r in gen_files if os.path.basename(r) == "compensation.json"), None)
    if cap is None:
        return  # no generated capability surface to align against (validated elsewhere)
    if l1.get("capability") != cap.get("capability"):
        errors.append(
            f"{where}: l2.l1.capability {l1.get('capability')!r} != generated capability {cap.get('capability')!r}")
    gen_primitives = ({e.get("name") for e in cap.get("entries", []) if isinstance(e, dict)}
                      | set(cap.get("operations", [])) | set(cap.get("ledgers", [])))
    for p in l1.get("primitives", []):
        if p not in gen_primitives:
            errors.append(
                f"{where}: l2.l1 primitive {p!r} is not in the generated L1 surface "
                "(capability.json entries[].name / operations / ledgers) — invented or stale")
    gen_obligations = set()
    if comp is not None and comp.get("invariantAfterCompensation"):
        gen_obligations.add(comp["invariantAfterCompensation"])
    if gen_obligations:
        for o in l1.get("obligations", []):
            if o not in gen_obligations:
                errors.append(
                    f"{where}: l2.l1 obligation {o!r} is not a generated obligation "
                    "(compensation.json invariantAfterCompensation) — invented or stale")


def _versioninfo_constants(errors: list) -> dict:
    """Parse the kXxx string constants from VersionInfo.h (the version single source of truth)."""
    path = os.path.join(REPO, VERSIONINFO)
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError as exc:
        errors.append(f"compatibility: cannot read {VERSIONINFO}: {exc}")
        return {}
    out = {}
    for const in set(_COMPAT_FIELDS.values()) | set(_COMPAT_SCHEMAS.values()):
        m = re.search(const + r'\s*=\s*"([^"]*)"', text)
        if m:
            out[const] = m.group(1)
        else:
            errors.append(f"compatibility: {const} not found in {VERSIONINFO}")
    return out


def _check_compatibility(cat: dict, errors: list) -> None:
    """The catalog's top-level compatibility surface must be pinned to VersionInfo.h ():
    a version bump that is not reflected in the catalog fails closed here."""
    c = cat.get("compatibility")
    if not isinstance(c, dict):
        errors.append("catalog: a top-level 'compatibility' object is required ( version surface)")
        return
    consts = _versioninfo_constants(errors)
    if not consts:
        return
    for field, const in _COMPAT_FIELDS.items():
        want = consts.get(const)
        if want is not None and c.get(field) != want:
            errors.append(f"compatibility.{field} {c.get(field)!r} != {VERSIONINFO} {const} {want!r}")
    schemas = c.get("schemas")
    if not isinstance(schemas, dict):
        errors.append("compatibility.schemas is required (bindingPolicy/bindingReceipt/runtimeEvidence)")
    else:
        # Pin each per-contract schema to its VersionInfo.h constant (the value versionInfo()
        # emits), not merely to the bundle — so a per-contract bump is caught.
        for key, const in _COMPAT_SCHEMAS.items():
            want = consts.get(const)
            if want is not None and schemas.get(key) != want:
                errors.append(
                    f"compatibility.schemas.{key} {schemas.get(key)!r} != {VERSIONINFO} {const} {want!r}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", default="examples/cross-rail-fixtures.json")
    ap.add_argument("--repo-root",
                    help="resolve catalog + referenced paths against this root "
                         "(default: the repo this script lives in); used by the [51] negative test")
    try:
        args = ap.parse_args()
    except SystemExit:
        return 2
    if args.repo_root:
        global REPO
        REPO = os.path.abspath(args.repo_root)

    errors: list = []
    cat = _load(args.catalog, errors, "catalog")
    if cat is None:
        for e in errors:
            print(f"  - {e}")
        return 1
    if cat.get("kind") != "neutrino.cross-rail-fixture-catalog":
        errors.append("catalog: kind must be 'neutrino.cross-rail-fixture-catalog'")
    _check_compatibility(cat, errors)
    fixtures = cat.get("fixtures")
    if not isinstance(fixtures, list) or not fixtures:
        errors.append("catalog: fixtures must be a non-empty array")
        fixtures = []
    for fx in fixtures:
        _check_fixture(fx, errors)

    if errors:
        for e in errors:
            print(f"  - {e}")
        print(f"cross-rail catalog check: {len(errors)} problem(s)")
        return 1
    print(f"cross-rail catalog check: OK ({len(fixtures)} fixture(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())

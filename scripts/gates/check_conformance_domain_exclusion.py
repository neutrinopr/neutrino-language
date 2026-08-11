#!/usr/bin/env python3
"""Structural domain-content exclusion for the core-contract-bundle conformance
boundary ( slice 4).

The CORE conformance surface must never import external DOMAIN ownership — nothing
from the committed production-domain tree — so an external pack validates from the
bundle alone and a production domain is never pulled back into core.

Ownership is CONTENT-INDEPENDENT so a new producer/checker cannot slip in unscanned:
the surface is the producer/validator/gate trees scanned WHOLESALE (every file is
covered by default — there is no marker to opt out of, and removing text cannot drop
coverage), plus the release packager, plus the bundle-test tree + conformance docs,
plus the PUBLISHED bundle manifest itself and every artifact it pins. Only a small,
reviewed EXCLUDED set is skipped — and each exclusion is reconciled: it must exist
and must ACTUALLY reference domain content, so a conformance producer (which does
not) cannot be excluded to sidestep the scan.

Fails closed on:
  - a path reference into the production-domain tree, or an embedded production-domain
    identifier (a committed domain's name, as a whole token), in any surface file —
    including the bundle manifest and every pinned artifact;
  - a bundle-pinned artifact that is missing/unreadable, or whose path is not
    contained within the core `docs/` tree (absolute / `..` rejected);
  - a stale or unjustified entry in the reviewed EXCLUDED set.

  check_conformance_domain_exclusion.py            # gate the surface
  check_conformance_domain_exclusion.py --selftest # mutation probes
Exit 0 ok / 1 violations / 2 usage.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DOMAIN_ROOT = "examples/domains"
BUNDLE = "docs/core-contract-bundle.json"
EXTERNALIZED_REGISTRY = "docs/externalized-domain-registry.json"
HISTORICAL_INVENTORY = "docs/process/m6_transfer_with_memo_pack_probe/inventory.json"
HISTORICAL_CANDIDATE_PACK = "docs/process/m6_transfer_with_memo_pack_probe/candidate-pack.json"
HISTORICAL_RECEIPT = "docs/process/m6_transfer_with_memo_pack_probe/receipt.json"

# WHOLESALE-scanned trees: every file is covered by default (content-independent).
PRODUCER_TREES = ("scripts/gates", "scripts/generators", "scripts/validators")
CONFORMANCE_TREES = ("test/ir/bundle", "docs/conformance")
PRODUCER_FILES = ("scripts/make_release.sh",)  # the release packager (a root script)

# Reviewed exclusions: files inside the scanned trees that legitimately reference the
# production-domain tree and are NOT part of the core-contract-bundle boundary. Each
# is reconciled (must exist AND actually reference domain content), so a conformance
# producer cannot be hidden here.
EXCLUDED = {
    "scripts/gates/check_conformance_domain_exclusion.py": "names the policy tokens",
    "scripts/gates/check_architecture_boundaries.py": "governs separate domain isolation",
    "scripts/gates/gate_integrity_manifest.json": "governs non-core and domain gates",
}

# The whole-repository reach-back scan is deliberately broader than the legacy
# core-conformance scan above. It inspects every committed file (build, tests,
# fixtures, CI, release, compiler, packaging, and docs) and exempts only the
# persistent registry, its biting test, and the immutable policy/probe record.
# Every exemption is reconciled below: it must exist, belong to one of these
# closed categories, and actually contain a registered identity/repository.
REACHBACK_EXCLUDED = {
    "docs/core-feature-example-matrix.json": "derived curated-corpus coverage authority",
    "docs/externalized-domain-registry.json": "persistent externalized-domain identity authority",
    "docs/m6-curated-example-corpus.json": "architect-frozen curated pack-coordinate authority",
    "test/checks/fast/core_contract_bundle_test.py": "biting registry-removal witness",
    "docs/process/M6_DOMAIN_EXTERNALIZATION_ADR.md": "ratified externalization policy record",
    "docs/process/m6_transfer_with_memo_pack_probe/EXTRACTION.md": "immutable extraction record",
    "docs/process/m6_transfer_with_memo_pack_probe/REPORT.md": "immutable pre-extraction report",
    "docs/process/m6_transfer_with_memo_pack_probe/candidate-pack.json": "immutable probe candidate",
    "docs/process/m6_transfer_with_memo_pack_probe/inventory.json": "immutable payload inventory",
    "docs/process/m6_transfer_with_memo_pack_probe/receipt.json": "immutable verification receipt",
    "scripts/gates/gate_integrity_manifest.json": "governed  retirement transition evidence",
}

# Two payloads are deliberately domain-neutral boilerplate and are byte-identical
# across many live fixtures; their hashes cannot identify copied production
# ownership. The remaining twelve payload hashes are domain-specific and denied.
SHARED_PAYLOAD_DIGESTS = {
    "sha256:9376545e4d3cef235015c7aca18869e8cef7bace79a7ccc682f82c2e69cace52":
        "empty PostgreSQL reconciliation boilerplate shared by live domains",
    "sha256:d3755c5f9b2cc7b596bb1dc786a0e5ca9408872e58b3a02a00d831853aa45d6c":
        "Foundry project configuration shared by live Solidity fixtures",
}


def _production_domains(root: str) -> list:
    d = os.path.join(root, DOMAIN_ROOT)
    return sorted(n for n in os.listdir(d) if os.path.isdir(os.path.join(d, n))) if os.path.isdir(d) else []


def _load_externalized_registry(root: str) -> tuple[list, list, list]:
    path = os.path.join(root, EXTERNALIZED_REGISTRY)
    text = _read(path)
    if text is None:
        return [], [], [f"[domain.registry_missing] {EXTERNALIZED_REGISTRY} is missing or unreadable"]
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as error:
        return [], [], [f"[domain.registry_schema] invalid JSON: {error}"]
    errors = []
    root_keys = {"kind", "schemaVersion", "registeredCount", "domains"}
    if not isinstance(doc, dict) or set(doc) != root_keys:
        errors.append("[domain.registry_schema] registry root fields are not the closed v1 shape")
        return [], [], errors
    if doc["kind"] != "neutrino.externalized-domain-registry" or doc["schemaVersion"] != 1:
        errors.append("[domain.registry_schema] registry kind/schemaVersion mismatch")
    rows = doc["domains"]
    if not isinstance(rows, list):
        return [], [], errors + ["[domain.registry_schema] domains must be an array"]
    if doc["registeredCount"] != len(rows):
        errors.append(
            f"[domain.registry_count] registeredCount {doc['registeredCount']!r} != {len(rows)} rows"
        )
    expected_row_keys = {
        "id", "repository", "mergeCommit", "contentCommit", "immutableTag", "immutableTagCommit",
        "packPath", "packId", "packDigest", "treeIdentity", "receiptPath", "bundle",
    }
    expected_bundle_keys = {"bundleId", "bundleVersion", "bundleDigest"}
    ids, repositories = [], []
    commit = re.compile(r"^[0-9a-f]{40}$")
    digest = re.compile(r"^sha256:[0-9a-f]{64}$")
    for index, row in enumerate(rows):
        prefix = f"[domain.registry_schema] domains[{index}]"
        if not isinstance(row, dict) or set(row) != expected_row_keys:
            errors.append(f"{prefix} fields are not the closed v1 shape")
            continue
        bundle = row["bundle"]
        if not isinstance(bundle, dict) or set(bundle) != expected_bundle_keys:
            errors.append(f"{prefix}.bundle fields are not the closed v1 shape")
        elif not isinstance(bundle["bundleDigest"], str) or not digest.fullmatch(bundle["bundleDigest"]):
            errors.append(f"{prefix}.bundle.bundleDigest is not a canonical digest")
        for key in ("mergeCommit", "contentCommit", "immutableTagCommit"):
            if not isinstance(row[key], str) or not commit.fullmatch(row[key]):
                errors.append(f"{prefix}.{key} is not a canonical commit")
        for key in ("packDigest", "treeIdentity"):
            if not isinstance(row[key], str) or not digest.fullmatch(row[key]):
                errors.append(f"{prefix}.{key} is not a canonical digest")
        if not isinstance(row["id"], str) or not re.fullmatch(r"[a-z][a-z0-9_]*", row["id"]):
            errors.append(f"{prefix}.id is not a canonical snake_case identity")
        else:
            ids.append(row["id"])
        if not isinstance(row["repository"], str) or row["repository"].count("/") != 1:
            errors.append(f"{prefix}.repository is not an owner/repository identity")
        else:
            repositories.append(row["repository"])
        for key in ("packPath", "receiptPath"):
            value = row[key]
            if (not isinstance(value, str) or not value or os.path.isabs(value)
                    or ".." in value.replace("\\", "/").split("/")):
                errors.append(f"{prefix}.{key} is not a safe repository-relative path")
    if ids != sorted(ids) or len(ids) != len(set(ids)):
        errors.append("[domain.registry_order] domain identities must be unique and sorted")
    canonical = json.dumps(doc, indent=2, sort_keys=True) + "\n"
    if text != canonical:
        errors.append("[domain.registry_canonical] registry bytes are not canonical")
    return ids, repositories, errors


def _governed_domains(root: str) -> list:
    externalized, _, _ = _load_externalized_registry(root)
    return sorted(set(_production_domains(root)) | set(externalized))


def _load_payload_digests(root: str) -> tuple[dict, list]:
    """Load the immutable pre-extraction payload hashes without reading the
    external repository. Exact copies are forbidden anywhere outside historical
    evidence, even when a payload happens not to spell the domain identity."""
    path = os.path.join(root, HISTORICAL_INVENTORY)
    text = _read(path)
    if text is None:
        return {}, [f"[domain.inventory_missing] {HISTORICAL_INVENTORY} is missing or unreadable"]
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as error:
        return {}, [f"[domain.inventory_schema] invalid JSON: {error}"]
    payloads = doc.get("payloads") if isinstance(doc, dict) else None
    if (not isinstance(payloads, list) or doc.get("payloadCount") != len(payloads)
            or len(payloads) != 14):
        return {}, ["[domain.inventory_schema] immutable payload inventory must contain exactly 14 rows"]
    digest_re = re.compile(r"^sha256:[0-9a-f]{64}$")
    digests, errors, identities = {}, [], []
    for index, row in enumerate(payloads):
        digest = row.get("sha256") if isinstance(row, dict) else None
        payload_path = row.get("path") if isinstance(row, dict) else None
        if (not isinstance(digest, str) or not digest_re.fullmatch(digest)
                or not isinstance(payload_path, str) or not payload_path):
            errors.append(f"[domain.inventory_schema] payloads[{index}] lacks a canonical path/digest")
            continue
        if digest in digests:
            errors.append(f"[domain.inventory_schema] duplicate payload digest {digest}")
        digests[digest] = payload_path
        identities.append({"path": payload_path, "sha256": digest})
    if [row["path"] for row in identities] != sorted(row["path"] for row in identities):
        errors.append("[domain.inventory_schema] payload paths must be sorted")
    if len({row["path"] for row in identities}) != len(identities):
        errors.append("[domain.inventory_schema] payload paths must be unique")

    # Authenticate the mutable-looking path/digest rows against every independent
    # immutable witness committed by the extraction: the candidate pack's
    # self-digest, its payload identity list, the receipt, and the persistent
    # externalized-domain registry. A digest can therefore neither be removed
    # from the denylist nor changed in concert with inventory.treeIdentity.
    tree_identity = "sha256:" + hashlib.sha256(
        json.dumps(
            identities, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()
    if doc.get("treeIdentity") != tree_identity:
        errors.append(
            "[domain.inventory_binding] payload path/digest rows do not match "
            "inventory.treeIdentity"
        )
    candidate_text = _read(os.path.join(root, HISTORICAL_CANDIDATE_PACK))
    receipt_text = _read(os.path.join(root, HISTORICAL_RECEIPT))
    registry_text = _read(os.path.join(root, EXTERNALIZED_REGISTRY))
    try:
        candidate = json.loads(candidate_text) if candidate_text is not None else None
        receipt = json.loads(receipt_text) if receipt_text is not None else None
        registry = json.loads(registry_text) if registry_text is not None else None
    except json.JSONDecodeError as error:
        errors.append(f"[domain.inventory_binding] immutable witness is invalid JSON: {error}")
        candidate = receipt = registry = None
    if not isinstance(candidate, dict):
        errors.append("[domain.inventory_binding] candidate-pack witness is missing")
    else:
        candidate_payloads = candidate.get("payloads")
        candidate_identities = (
            [{"path": row.get("path"), "sha256": row.get("sha256")}
             for row in candidate_payloads]
            if isinstance(candidate_payloads, list)
            and all(isinstance(row, dict) for row in candidate_payloads)
            else None
        )
        unsigned_candidate = dict(candidate)
        recorded_pack_digest = unsigned_candidate.pop("packDigest", None)
        computed_pack_digest = "sha256:" + hashlib.sha256(
            json.dumps(
                unsigned_candidate, sort_keys=True, separators=(",", ":"),
                ensure_ascii=False
            ).encode("utf-8")
        ).hexdigest()
        if recorded_pack_digest != computed_pack_digest:
            errors.append(
                "[domain.inventory_binding] candidate-pack self-digest is invalid"
            )
        if candidate_identities != identities:
            errors.append(
                "[domain.inventory_binding] inventory identities differ from candidate-pack"
            )
    receipt_tree = (
        receipt.get("inventory", {}).get("treeIdentity")
        if isinstance(receipt, dict) and isinstance(receipt.get("inventory"), dict)
        else None
    )
    if receipt_tree != tree_identity:
        errors.append(
            "[domain.inventory_binding] inventory tree identity differs from receipt"
        )
    registry_trees = (
        [row.get("treeIdentity") for row in registry.get("domains", [])
         if isinstance(row, dict)]
        if isinstance(registry, dict) and isinstance(registry.get("domains"), list)
        else []
    )
    if tree_identity not in registry_trees:
        errors.append(
            "[domain.inventory_binding] inventory tree identity is not authenticated "
            "by the externalized-domain registry"
        )
    missing_shared = sorted(set(SHARED_PAYLOAD_DIGESTS) - set(digests))
    if missing_shared:
        errors.append(
            f"[domain.inventory_schema] shared-boilerplate digest exemptions are stale: "
            f"{missing_shared}"
        )
    for digest in SHARED_PAYLOAD_DIGESTS:
        digests.pop(digest, None)
    return digests, errors


def _committed_files(root: str) -> list:
    """Return the complete committed surface. Temporary probe repositories are
    not git worktrees, so they fall back to a whole-tree walk."""
    try:
        top = subprocess.check_output(
            ["git", "-C", root, "rev-parse", "--show-toplevel"],
            text=True, stderr=subprocess.DEVNULL).strip()
        if os.path.realpath(top) == os.path.realpath(root):
            listed = subprocess.check_output(
                ["git", "-C", root, "ls-files"], text=True,
                stderr=subprocess.DEVNULL).splitlines()
            return sorted(rel for rel in listed if os.path.isfile(os.path.join(root, rel)))
    except (OSError, subprocess.CalledProcessError):
        pass
    files = []
    for base, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in (".git", ".ci", "out", "build", "__pycache__"))
        for name in sorted(names):
            rel = os.path.relpath(os.path.join(base, name), root)
            if _is_source(rel):
                files.append(rel)
    return sorted(files)


def _read(path: str):
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            return f.read()
    except OSError:
        return None


def _read_bytes(path: str):
    try:
        with open(path, "rb") as stream:
            return stream.read()
    except OSError:
        return None


def _within_docs(root: str, rel) -> bool:
    """True iff `rel` resolves CONTAINED within root/docs (rejecting absolute paths
    and `..` traversal — a `docs/` prefix alone is not containment)."""
    if not isinstance(rel, str) or not rel or os.path.isabs(rel) or ".." in rel.replace("\\", "/").split("/"):
        return False
    root_abs = os.path.realpath(root)
    docs_abs = os.path.realpath(os.path.join(root_abs, "docs"))
    target = os.path.realpath(os.path.join(root_abs, rel))
    return os.path.commonpath([docs_abs, target]) == docs_abs


def _is_source(rel: str) -> bool:
    # Committed source only — never build artifacts (bytecode is gitignored and merely
    # mirrors the SOURCE, whose committed form is scanned or reviewed-excluded).
    parts = rel.replace("\\", "/").split("/")
    return "__pycache__" not in parts and not rel.endswith((".pyc", ".pyo", ".so"))


def _surface(root: str) -> list:
    files = set()
    for t in CONFORMANCE_TREES + PRODUCER_TREES:
        for p in glob.glob(os.path.join(root, t, "**", "*"), recursive=True):
            if os.path.isfile(p):
                rel = os.path.relpath(p, root)
                if _is_source(rel):
                    files.add(rel)
    for f in PRODUCER_FILES + (BUNDLE,):  # the published bundle manifest is scanned too
        if os.path.isfile(os.path.join(root, f)):
            files.add(f)
    return sorted(files - set(EXCLUDED))


def _domain_forms(slug: str):
    """The stable identifier forms a domain's identity takes in committed artifacts:
    the snake_case directory slug AND the PascalCase/camelCase forms that generated
    backends encode (e.g. core_document_escrow -> CoreDocumentEscrow / coreDocumentEscrow,
    as in CoreDocumentEscrow.sol / CoreDocumentEscrowReconciled)."""
    parts = slug.split("_")
    pascal = "".join(p[:1].upper() + p[1:] for p in parts if p)
    camel = (parts[0] + "".join(p[:1].upper() + p[1:] for p in parts[1:])) if parts else slug
    return slug, pascal, camel


def _match_whole(text: str, tok: str) -> bool:
    # snake_case: bounded by non-alnum/underscore on both sides (a substring in a
    # longer identifier is not a hit).
    n, i = len(tok), text.find(tok)
    while i != -1:
        lo = text[i - 1] if i > 0 else ""
        hi = text[i + n] if i + n < len(text) else ""
        if not (lo.isalnum() or lo == "_") and not (hi.isalnum() or hi == "_"):
            return True
        i = text.find(tok, i + 1)
    return False


def _match_component(text: str, tok: str) -> bool:
    # PascalCase/camelCase: a COMPONENT-aligned match — clean left boundary (or a
    # camelCase case-transition into an uppercase start), and a right boundary that
    # is not a lowercase continuation (so `CoreDocumentEscrowReconciled` matches but
    # `CoreDocumentEscrowed` does not).
    n, i = len(tok), text.find(tok)
    while i != -1:
        lo = text[i - 1] if i > 0 else ""
        hi = text[i + n] if i + n < len(text) else ""
        left = (lo == "" or not (lo.isalnum() or lo == "_")
                or (tok[:1].isupper() and (lo.islower() or lo.isdigit())))
        right = (hi == "" or not hi.islower())
        if left and right:
            return True
        i = text.find(tok, i + 1)
    return False


def _scan_text(rel: str, text: str, domains: list, repositories=()) -> list:
    out = []
    if DOMAIN_ROOT in text:
        out.append(f"[domain.path] {rel} references the production-domain tree (external domain ownership)")
    for d in domains:
        slug, pascal, camel = _domain_forms(d)
        if _match_whole(text, slug) or _match_component(text, pascal) or _match_component(text, camel):
            out.append(f"[domain.identifier] {rel} embeds production-domain identity {d!r} "
                       "(slug or its generated PascalCase/camelCase form — a domain artifact copied "
                       "into a core conformance fixture?)")
    for repository in repositories:
        repo_name = repository.rsplit("/", 1)[-1]
        if repository in text or _match_whole(text, repo_name):
            out.append(
                f"[domain.repository] {rel} reaches toward external repository {repository!r} "
                "(core build/test/release must not import, clone, copy, or resolve domain content)"
            )
    return out


def _scan_reachback(rel: str, data: bytes, externalized: list,
                    repositories: list, payload_digests: dict) -> list:
    """Scan the complete committed tree for externalized identity/repository
    reach-back and byte-exact copies of the retired production payloads."""
    text = data.decode("utf-8", "ignore")
    out = []
    for identity in externalized:
        slug, pascal, camel = _domain_forms(identity)
        if (_match_whole(text, slug) or _match_component(text, pascal)
                or _match_component(text, camel)):
            out.append(
                f"[domain.reachback_identity] {rel} embeds registered externalized identity "
                f"{identity!r}"
            )
    for repository in repositories:
        repo_name = repository.rsplit("/", 1)[-1]
        if repository in text or _match_whole(text, repo_name):
            out.append(
                f"[domain.reachback_repository] {rel} reaches toward external repository "
                f"{repository!r}"
            )
    digest = "sha256:" + hashlib.sha256(data).hexdigest()
    if digest in payload_digests:
        out.append(
            f"[domain.reachback_payload] {rel} is a byte-exact copy of retired production "
            f"payload {payload_digests[digest]!r}"
        )
    return out


def _reachback_surface(root: str, excluded=REACHBACK_EXCLUDED) -> list:
    return [
        rel for rel in _committed_files(root)
        if rel not in excluded and _is_source(rel)
    ]


def _reconcile_reachback_exclusions(root: str, externalized: list,
                                    repositories: list,
                                    excluded=REACHBACK_EXCLUDED) -> list:
    """The whole-tree carve-out is closed and load-bearing: only the registry,
    its biting test, and fixed historical evidence may be omitted, and every
    entry must genuinely name the registered externalized boundary."""
    out = []
    allowed_exact = {
        "docs/core-feature-example-matrix.json",
        EXTERNALIZED_REGISTRY,
        "docs/m6-curated-example-corpus.json",
        "scripts/gates/gate_integrity_manifest.json",
        "test/checks/fast/core_contract_bundle_test.py",
        "docs/process/M6_DOMAIN_EXTERNALIZATION_ADR.md",
    }
    historical_prefix = "docs/process/m6_transfer_with_memo_pack_probe/"
    items = excluded.items() if isinstance(excluded, dict) else (
        (rel, "") for rel in excluded
    )
    for rel, reason in sorted(items):
        if rel not in allowed_exact and not rel.startswith(historical_prefix):
            out.append(
                f"[domain.reachback_exclusion_scope] excluded file {rel!r} is not the registry, "
                "biting test, or immutable historical evidence"
            )
            continue
        data = _read_bytes(os.path.join(root, rel))
        if data is None:
            out.append(
                f"[domain.reachback_exclusion_stale] excluded file {rel!r} does not exist"
            )
            continue
        # Do not supply payload hashes here: an exclusion is justified by its
        # explicit identity/repository role, never merely by sharing payload bytes.
        if not _scan_reachback(rel, data, externalized, repositories, {}):
            out.append(
                f"[domain.reachback_exclusion_unjustified] excluded file {rel!r} contains no "
                "registered externalized identity or repository"
            )
    return out


def _reconcile_shared_payload_digests(root: str,
                                      excluded=REACHBACK_EXCLUDED) -> list:
    counts = {digest: [] for digest in SHARED_PAYLOAD_DIGESTS}
    for rel in _reachback_surface(root, excluded):
        data = _read_bytes(os.path.join(root, rel))
        if data is None:
            continue
        digest = "sha256:" + hashlib.sha256(data).hexdigest()
        if digest in counts:
            counts[digest].append(rel)
    out = []
    for digest, paths in sorted(counts.items()):
        if len(paths) < 2:
            out.append(
                f"[domain.shared_payload_unjustified] {digest} is exempted as domain-neutral "
                f"boilerplate but has only {len(paths)} committed occurrence(s)"
            )
    return out


def _reconcile(root: str, excluded=EXCLUDED) -> list:
    """Every reviewed exclusion must EXIST and ACTUALLY reference domain content, so
    a conformance producer (which references none) cannot be excluded to escape the scan."""
    out = []
    domains = _governed_domains(root)
    _, repositories, _ = _load_externalized_registry(root)
    items = excluded.items() if isinstance(excluded, dict) else (
        (rel, "") for rel in excluded
    )
    for rel, reason in sorted(items):
        text = _read(os.path.join(root, rel))
        if text is None:
            out.append(f"[domain.exclusion_stale] excluded file {rel!r} does not exist (drop it from EXCLUDED)")
        elif not _scan_text(rel, text, domains, repositories):
            out.append(f"[domain.exclusion_unjustified] excluded file {rel!r} references no domain content — "
                       "it must be scanned, not excluded")
    return out


def check(root: str, reachback_excluded=REACHBACK_EXCLUDED) -> list:
    fails = []
    externalized, repositories, registry_errors = _load_externalized_registry(root)
    fails.extend(registry_errors)
    payload_digests, inventory_errors = _load_payload_digests(root)
    fails.extend(inventory_errors)
    live = _production_domains(root)
    domains = sorted(set(live) | set(externalized))
    for identity in sorted(set(live) & set(externalized)):
        fails.append(
            f"[domain.reintroduced] registered externalized domain {identity!r} exists again under "
            f"{DOMAIN_ROOT}"
        )

    for rel in _surface(root):
        text = _read(os.path.join(root, rel))
        if text is not None:
            fails.extend(_scan_text(rel, text, domains, repositories))

    # Complete source-tree reach-back scan: unlike the legacy conformance
    # producer surface, this covers CMake, Make, workflows, all tests/fixtures,
    # compiler code, packaging, examples, and documentation.
    for rel in _reachback_surface(root, reachback_excluded):
        data = _read_bytes(os.path.join(root, rel))
        if data is not None:
            fails.extend(
                _scan_reachback(rel, data, externalized, repositories, payload_digests)
            )

    # every artifact the bundle PINS: contained within docs/, present, and content-scanned.
    bp = os.path.join(root, BUNDLE)
    if os.path.isfile(bp):
        bundle = json.load(open(bp, encoding="utf-8"))
        pinned = [c.get("path") for c in bundle.get("contracts", [])]
        for key in ("diagnosticTaxonomy", "semanticVocabulary"):
            blk = bundle.get(key)
            if isinstance(blk, dict) and blk.get("path"):
                pinned.append(blk["path"])
        for p in pinned:
            if not _within_docs(root, p):
                fails.append(f"[domain.published] bundle pins path {p!r} not contained within the core docs/ tree")
                continue
            text = _read(os.path.join(root, p))
            if text is None:
                fails.append(f"[domain.published] bundle-pinned artifact {p!r} is missing or unreadable")
            else:
                fails.extend(_scan_text(p, text, domains, repositories))

    fails.extend(_reconcile(root))
    fails.extend(
        _reconcile_reachback_exclusions(
            root, externalized, repositories, reachback_excluded
        )
    )
    fails.extend(_reconcile_shared_payload_digests(root, reachback_excluded))
    return sorted(set(fails))


def _selftest() -> int:
    import shutil
    import tempfile
    fails = []
    domains = _governed_domains(REPO)
    a_domain = domains[0] if domains else "core_document_escrow"

    if check(REPO):
        fails.append(f"committed conformance surface rejected: {check(REPO)}")

    # build artifacts (bytecode) are NOT scanned — they are gitignored and merely mirror the
    # SOURCE, whose committed form is scanned/excluded; scanning a .pyc of an excluded file
    # would re-flag its embedded domain strings.
    if _is_source("scripts/generators/__pycache__/x.cpython-310.pyc") or not _is_source("scripts/x.py"):
        fails.append("the build-artifact (.pyc/__pycache__) skip regressed")

    # unit: whole-token identifier + path + clean + substring-safe.
    if not _scan_text("x", f'"{a_domain}"', domains):
        fails.append("an embedded production-domain identifier was not caught")
    if not _scan_text("x", f"{DOMAIN_ROOT}/{a_domain}", domains):
        fails.append("a production-domain path was not caught")
    if _scan_text("x", '{"kind":"neutrino.domain-pack"}', domains):
        fails.append("a clean synthetic fixture was wrongly flagged")
    if _scan_text("x", f"my_{a_domain}_helper", domains):
        fails.append("a substring inside a longer token was wrongly flagged")

    def _seed_reachback_evidence(root):
        for rel in REACHBACK_EXCLUDED:
            dst = os.path.join(root, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(os.path.join(REPO, rel), dst)

    def _stage(mutate):
        d = tempfile.mkdtemp(prefix="domexcl.")
        for sub in ("docs/schemas", "scripts/generators", os.path.join(DOMAIN_ROOT, a_domain)):
            os.makedirs(os.path.join(d, sub))
        _seed_reachback_evidence(d)
        open(os.path.join(d, "docs", "schemas", "x.schema.json"), "w").write('{"$id":"x"}')
        registry = json.load(open(os.path.join(REPO, EXTERNALIZED_REGISTRY), encoding="utf-8"))
        with open(os.path.join(d, EXTERNALIZED_REGISTRY), "w", encoding="utf-8") as stream:
            stream.write(json.dumps(registry, indent=2, sort_keys=True) + "\n")
        bundle = {"contracts": [{"name": "x", "path": "docs/schemas/x.schema.json"}]}
        mutate(d, bundle)
        json.dump(bundle, open(os.path.join(d, BUNDLE), "w"))
        return d

    # P1: a poisoned bundle-PINNED artifact is caught (derived from the bundle).
    if not any("domain.identifier" in x for x in
               check(_stage(lambda d, b: open(os.path.join(d, "docs/schemas/x.schema.json"), "w")
                            .write(f'{{"n":"{a_domain}"}}')))):
        fails.append("a poisoned bundle-pinned artifact was not caught")

    # P1: a GENERATED-form artifact (PascalCase, no snake slug — e.g. a real
    # `contract CoreDocumentEscrow` copied in) is caught, not just the directory slug.
    pascal = _domain_forms(a_domain)[1]
    if _match_whole(f"contract {pascal} {{}}", a_domain):
        fails.append("test error: the PascalCase probe accidentally contains the snake slug")
    if not any("domain.identifier" in x for x in
               check(_stage(lambda d, b: open(os.path.join(d, "docs/schemas/x.schema.json"), "w")
                            .write(f"contract {pascal}Reconciled {{}}")))):
        fails.append("a copied generated (PascalCase) domain artifact was not caught")

    # P1: the PUBLISHED bundle manifest's own metadata is scanned.
    if not any("domain.identifier" in x for x in
               check(_stage(lambda d, b: b.__setitem__("_meta", a_domain)))):
        fails.append("a poisoned bundle manifest was not caught")

    # P1 (content-independent): a NO-MARKER wrapper producer is scanned wholesale.
    if not any("domain.identifier" in x for x in
               check(_stage(lambda d, b: open(os.path.join(d, "scripts/generators/wrapper.py"), "w")
                            .write(f"from x import main\nDOMAIN='{a_domain}'\n")))):
        fails.append("a no-marker wrapper producer was not scanned (coverage is content-dependent)")

    # P2: a `..`-traversal / missing pinned path fails closed.
    if not any("not contained" in x for x in
               check(_stage(lambda d, b: b["contracts"][0].__setitem__("path", "docs/../outside.json")))):
        fails.append("a `..`-traversal bundle path was accepted (containment not enforced)")
    if not any("missing or unreadable" in x for x in
               check(_stage(lambda d, b: b["contracts"][0].__setitem__("path", "docs/schemas/gone.json")))):
        fails.append("a missing pinned artifact was not caught")

    # RECONCILIATION: a stale exclusion, and an unjustified exclusion (a conformance file that
    # references no domain content), both fail — you cannot exclude a producer to hide it.
    if not any("exclusion_stale" in x for x in _reconcile(REPO, {"scripts/gates/nonexistent.py"})):
        fails.append("a stale exclusion entry was not caught")
    if not any("exclusion_unjustified" in x for x in _reconcile(REPO, {"scripts/validators/verify_domain_pack.py"})):
        fails.append("excluding a conformance producer (no domain content) was not caught")

    for probe_id in PROBES:
        expected, reasons = _probe_reasons(probe_id)
        if not any(expected in reason for reason in reasons):
            fails.append(f"{probe_id} did not bite with {expected}: {reasons}")

    if fails:
        for f in fails:
            print(f"[domain.selftest] {f}", file=sys.stderr)
        return 1
    print("ok (selftest)")
    return 0


PROBES = (
    "registry-row-removal",
    "registered-domain-reintroduced",
    "live-only-denylist",
    "external-repository-reachback",
    "cmake-repository-reachback",
    "workflow-repository-reachback",
    "active-fixture-copy",
    "inventory-digest-tamper",
    "historical-exclusion-unjustified",
)


def _probe_reasons(probe_id: str) -> tuple[str, list]:
    import shutil
    import tempfile

    with tempfile.TemporaryDirectory(prefix="domexcl-probe.") as root:
        for sub in ("docs/schemas", "scripts/generators", DOMAIN_ROOT):
            os.makedirs(os.path.join(root, sub), exist_ok=True)
        for rel in REACHBACK_EXCLUDED:
            dst = os.path.join(root, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(os.path.join(REPO, rel), dst)
        with open(os.path.join(root, "docs/schemas/x.schema.json"), "w", encoding="utf-8") as stream:
            stream.write('{"$id":"x"}')
        with open(os.path.join(root, BUNDLE), "w", encoding="utf-8") as stream:
            json.dump({"contracts": [{"name": "x", "path": "docs/schemas/x.schema.json"}]}, stream)
        registry = json.load(open(os.path.join(REPO, EXTERNALIZED_REGISTRY), encoding="utf-8"))
        identity = registry["domains"][0]["id"]
        repository = registry["domains"][0]["repository"]
        expected = ""
        if probe_id == "registry-row-removal":
            registry["domains"].pop(0)
            expected = "domain.registry_count"
        elif probe_id == "registered-domain-reintroduced":
            os.makedirs(os.path.join(root, DOMAIN_ROOT, identity))
            expected = "domain.reintroduced"
        elif probe_id == "live-only-denylist":
            with open(os.path.join(root, "scripts/generators/wrapper.py"), "w", encoding="utf-8") as stream:
                stream.write(f'DOMAIN = "{identity}"\n')
            expected = "domain.identifier"
        elif probe_id == "external-repository-reachback":
            with open(os.path.join(root, "scripts/make_release.sh"), "w", encoding="utf-8") as stream:
                stream.write(f"git clone git@github.com:{repository}.git\n")
            expected = "domain.repository"
        elif probe_id == "cmake-repository-reachback":
            with open(os.path.join(root, "CMakeLists.txt"), "w", encoding="utf-8") as stream:
                stream.write(
                    f'execute_process(COMMAND git clone https://github.com/{repository}.git)\n'
                )
            expected = "domain.reachback_repository"
        elif probe_id == "workflow-repository-reachback":
            workflow = os.path.join(root, ".github/workflows/reachback.yml")
            os.makedirs(os.path.dirname(workflow), exist_ok=True)
            with open(workflow, "w", encoding="utf-8") as stream:
                stream.write(
                    "steps:\n"
                    f"  - run: git clone git@github.com:{repository}.git\n"
                )
            expected = "domain.reachback_repository"
        elif probe_id == "active-fixture-copy":
            fixture = os.path.join(root, "test/fixtures/copied-production.sol")
            os.makedirs(os.path.dirname(fixture), exist_ok=True)
            copied = (
                "// synthetic stand-in for a retired production payload\n"
                f"contract {_domain_forms(identity)[1]} {{}}\n"
            ).encode()
            with open(fixture, "wb") as stream:
                stream.write(copied)
            inventory_path = os.path.join(root, HISTORICAL_INVENTORY)
            inventory = json.load(open(inventory_path, encoding="utf-8"))
            inventory["payloads"][0]["sha256"] = (
                "sha256:" + hashlib.sha256(copied).hexdigest()
            )
            identities = [
                {"path": row["path"], "sha256": row["sha256"]}
                for row in inventory["payloads"]
            ]
            inventory["treeIdentity"] = "sha256:" + hashlib.sha256(
                json.dumps(
                    identities, sort_keys=True, separators=(",", ":"),
                    ensure_ascii=False
                ).encode("utf-8")
            ).hexdigest()
            with open(inventory_path, "w", encoding="utf-8") as stream:
                stream.write(json.dumps(inventory, indent=2, sort_keys=True) + "\n")
            candidate_path = os.path.join(root, HISTORICAL_CANDIDATE_PACK)
            candidate = json.load(open(candidate_path, encoding="utf-8"))
            candidate["payloads"][0]["sha256"] = inventory["payloads"][0]["sha256"]
            unsigned_candidate = dict(candidate)
            unsigned_candidate.pop("packDigest")
            candidate["packDigest"] = "sha256:" + hashlib.sha256(
                json.dumps(
                    unsigned_candidate, sort_keys=True, separators=(",", ":"),
                    ensure_ascii=False
                ).encode("utf-8")
            ).hexdigest()
            with open(candidate_path, "w", encoding="utf-8") as stream:
                stream.write(json.dumps(candidate, indent=2, sort_keys=True) + "\n")
            receipt_path = os.path.join(root, HISTORICAL_RECEIPT)
            receipt = json.load(open(receipt_path, encoding="utf-8"))
            receipt["inventory"]["treeIdentity"] = inventory["treeIdentity"]
            with open(receipt_path, "w", encoding="utf-8") as stream:
                stream.write(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
            registry["domains"][0]["treeIdentity"] = inventory["treeIdentity"]
            expected = "domain.reachback_payload"
        elif probe_id == "inventory-digest-tamper":
            inventory_path = os.path.join(root, HISTORICAL_INVENTORY)
            inventory = json.load(open(inventory_path, encoding="utf-8"))
            inventory["payloads"][0]["sha256"] = "sha256:" + "0" * 64
            with open(inventory_path, "w", encoding="utf-8") as stream:
                stream.write(json.dumps(inventory, indent=2, sort_keys=True) + "\n")
            expected = "domain.inventory_binding"
        elif probe_id == "historical-exclusion-unjustified":
            with open(
                os.path.join(
                    root,
                    "docs/process/m6_transfer_with_memo_pack_probe/EXTRACTION.md",
                ),
                "w",
                encoding="utf-8",
            ) as stream:
                stream.write("# unrelated clean history\n")
            expected = "domain.reachback_exclusion_unjustified"
        with open(os.path.join(root, EXTERNALIZED_REGISTRY), "w", encoding="utf-8") as stream:
            stream.write(json.dumps(registry, indent=2, sort_keys=True) + "\n")
        return expected, check(root)


def _probe(probe_id: str) -> int:
    expected, reasons = _probe_reasons(probe_id)
    matches = [reason for reason in reasons if expected in reason]
    if matches:
        print(matches[0])
        print(f"probe-failed-as-expected:{probe_id}")
        return 1
    print(f"probe did not bite:{probe_id}: {reasons}", file=sys.stderr)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--selftest", action="store_true")
    mode.add_argument("--probe", choices=PROBES)
    args = ap.parse_args()
    if args.selftest:
        return _selftest()
    if args.probe:
        return _probe(args.probe)
    fails = check(REPO)
    if fails:
        for f in fails:
            print(f"  - {f}")
        print(f"conformance domain-exclusion gate: {len(fails)} violation(s)")
        return 1
    payload_digests, _ = _load_payload_digests(REPO)
    print(f"conformance domain-exclusion gate OK: the boundary imports no external domain ownership "
          f"({len(_surface(REPO))} core-conformance files + bundle-pinned artifacts and "
          f"{len(_reachback_surface(REPO))} committed build/test/CI/release files scanned, "
          f"{len(EXCLUDED)} conformance + {len(REACHBACK_EXCLUDED)} narrow reach-back exclusions "
          f"reconciled, {len(payload_digests)} retired payload hashes denied, "
          f"{len(_production_domains(REPO))} live + "
          f"{len(_load_externalized_registry(REPO)[0])} externalized identities excluded)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

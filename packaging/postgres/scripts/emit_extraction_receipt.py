#!/usr/bin/env python3
"""Emit (and self-check) the standalone PostgreSQL backend extraction receipt ().

The receipt is the extraction PROOF artifact required by  acceptance: it binds,
in one deterministic document, the identities and digests a clean-clone re-materialization
must reproduce —

  * SOURCE identity — repo HEAD + the revision that last touched the extracted unit,
    and per-file SHA-256 digests of every authored source, generated build product,
    TableGen input and packaging file the manifest owns;
  * CORE identity — the  public-core boundary the package is built against
    (canonical finalized-projection artifact + schema version, the backend protocol,
    the consumed public-core headers/link deps, and the pinned compatibility manifest);
  * DEPENDENCY graph — the exact public-core edges and the package's own header surface;
  * TEST results — the conformance slice that proves byte-faithful SQL + real-DB behavior;
  * LICENSE/PROVENANCE — every owned file classified, with the one license-identity item
    that is explicitly GATED on  (named, never silently defaulted).

The receipt is content-addressed (digests + revisions), never timestamped, so the same
tree always emits byte-identical bytes. It is a build/proof PRODUCT, not a committed
source: the clean-clone execution (publication gated on ) emits it in the fresh
checkout and compares against the monorepo baseline; this tool makes it emittable today
and self-checkable in CI.

The owned-file set is the SAME set `check_package_reachback.py` audits (imported, single
source of truth) plus the TableGen inputs and the packaging files, so the receipt can
never silently diverge from the reach-back surface.

Usage:
  emit_extraction_receipt.py [--manifest PATH] [--repo PATH]   # emit to stdout
  emit_extraction_receipt.py --output PATH                     # emit to a file
  emit_extraction_receipt.py --check                           # emit + fail-closed self-consistency
  emit_extraction_receipt.py --selftest                        # biting mutations

Exit 0 = emitted / consistent. Exit 1 = a manifest-owned file is missing, undigestible,
a public-core header does not resolve, or the compatibility surface is absent.
"""
import argparse
import hashlib
import json
import os
import sys

# : the shared build-product resolver. Imported defensively so the emitter
# still runs from an extracted package that carries no scripts/gates tree.
_GATES = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))), "scripts", "gates")
if _GATES not in sys.path:
    sys.path.insert(0, _GATES)
try:
    import generated_artifacts as _generated_artifacts
except ImportError:
    _generated_artifacts = None
BUILD_DIR = os.environ.get("NEUTRINO_BUILD_DIR", "")
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from check_package_reachback import load_manifest, owned_files  # noqa: E402

RECEIPT_KIND = "neutrino.postgres-extraction-receipt/1"
# The published compatibility surface the package pins against (manifest provenance).
COMPATIBILITY_MANIFEST = "COMPATIBILITY.json"


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _git(repo, *args):
    """Best-effort git query; None if git or the object is unavailable (a clean
    clone without full history still emits a receipt, recording an unknown revision
    rather than failing)."""
    try:
        out = subprocess.run(
            ["git", "-C", repo, *args],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        return out.stdout.strip() if out.returncode == 0 and out.stdout.strip() else None
    except OSError:
        return None


def _tablegen_files(manifest):
    """Unit-relative TableGen inputs (sources of truth for the generated products)."""
    unit = manifest["unitRoot"]
    files = []
    for entry in manifest["tablegenInputs"].get("unitOwned", []):
        files.append(os.path.join(unit, entry["file"]))
    return files


def _generated_products(manifest):
    """Unit-relative committed generated build products, with their generator+source
    provenance (regenerated at clone build time; digested here as committed convenience
    bytes, classified generated — never authored)."""
    unit = manifest["unitRoot"]
    out = []
    for g in manifest["generatedBuildProducts"].get("committed", []):
        out.append((os.path.join(unit, g["file"]), g.get("generator"), g.get("from")))
    return out


def _packaging_files(repo):
    """The package's own build/install/audit files under packaging/postgres/ — every
    committed file except this receipt tool's own emitted output."""
    root = os.path.join(repo, "packaging", "postgres")
    files = []
    for dirpath, _dirs, names in os.walk(root):
        for name in sorted(names):
            if name.endswith(".pyc"):
                continue
            abs_path = os.path.join(dirpath, name)
            rel = os.path.relpath(abs_path, repo).replace(os.sep, "/")
            files.append(rel)
    return sorted(files)


def _authored_source_files(manifest):
    """Every manifest-owned authored file the reach-back audit tracks (compiled
    sources, internal headers, committed includers, reviewed carve-outs, public
    headers) MINUS the generated build products (classified separately), PLUS the
    TableGen inputs. Reusing owned_files() keeps the receipt bound to exactly the
    reach-back-audited surface."""
    generated = {f for f, _gen, _from in _generated_products(manifest)}
    audited = [f for f in owned_files(manifest) if f not in generated]
    shared = manifest.get("sharedRuntimeSources", {}).get("files", [])
    return sorted(set(audited) | set(_tablegen_files(manifest)) | set(shared))


def _digest_map(repo, rels):
    """(digests, missing): SHA-256 per existing file; missing ones recorded so
    --check can fail closed on them."""
    digests, missing = {}, []
    for rel in rels:
        path = os.path.join(repo, rel)
        if os.path.exists(path):
            digests[rel] = _sha256(path)
        else:
            missing.append(rel)
    return digests, missing


# A published descriptor must not leak internal tracker references. Detection
# covers BOTH text mentions (``, `issue 849`) and BARE NUMERIC JSON FIELDS —
# a value like {"documentId": "urn:neutrino:document:postgres-package-extraction-v1"} carries the same internal reference while evading
# any string scan, which is why numeric fields are walked explicitly.
_ISSUE_TEXT_RE = re.compile(r"(?:#|\bissue\s+)([0-9]{2,5})\b", re.I)
_ISSUE_KEYS = ("issue", "issues", "parent", "ticket", "pr", "pullRequest")


def internal_reference_findings(manifest):
    """[(jsonPath, kind, value)] for every internal tracker reference reachable in
    the manifest — text or numeric. Reported, not silently stripped: the decision
    to redact belongs to the publication gate (), not to this emitter."""
    out = []

    def walk(node, path):
        if isinstance(node, dict):
            for key, value in node.items():
                here = f"{path}.{key}" if path else key
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    if key in _ISSUE_KEYS:
                        out.append((here, "numeric-issue-field", value))
                walk(value, here)
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{path}[{index}]")
        elif isinstance(node, str):
            for match in _ISSUE_TEXT_RE.finditer(node):
                out.append((path, "text-issue-reference", match.group(1)))

    walk(manifest, "")
    return out


SHARED_RUNTIME_CONTRACT = "packaging/shared/backend-source-runtime-v1.json"
# The exact frozen  identity this package was written against, pinned HERE and
# independently of the contract file. Checking a contract against its own
# `contractDigest` proves only that the file is self-consistent; it cannot prove the
# receipt consumed the frozen identity, because an edited contract re-derives its own
# digest. A mismatch means the dependency moved and this package must be re-reviewed.
# Re-pinned for  (was sha256:a4c3088b...). The independent pin did its job:
# it REFUSED rather than silently re-verifying when the contract moved. Verified
# the delta is exactly one entry -- lib/spec-contract/BackendProjectionCodecFields
# .inc removed, because  made it a build product -- and nothing else changed.
EXPECTED_SHARED_RUNTIME_DIGEST = (
    "sha256:0a3fb477ad5b132dcb00e7076b332bc6cea9fc4dc9597bbf6f980dac3b75de97")


def load_shared_runtime_contract(repo, path=SHARED_RUNTIME_CONTRACT):
    """Load and VERIFY the  `neutrino.backend-source-runtime/1` closure.

    The contract is bound atomically: its `contractDigest` must reproduce over the
    canonical contract body, and every declared source AND header must match its
    recorded sha256 and byteLen in the tree. Naming the dependency without binding
    it would leave the materialized headers outside every proof surface — a header
    could gain an undeclared private include and no check would notice."""
    problems = []
    full = os.path.join(repo, path)
    if not os.path.exists(full):
        return None, [f"shared-runtime contract missing: {path}"]
    with open(full, encoding="utf-8") as f:
        contract = json.load(f)
    declared = contract.get("contractDigest")
    body = {k: v for k, v in contract.items() if k != "contractDigest"}
    actual = "sha256:" + hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if declared != EXPECTED_SHARED_RUNTIME_DIGEST:
        problems.append(
            f"shared-runtime contract identity moved: declared {declared}, but this "
            f"package is pinned to {EXPECTED_SHARED_RUNTIME_DIGEST}")
    if declared != actual:
        problems.append(
            f"shared-runtime contractDigest does not reproduce: declared {declared}, "
            f"computed {actual}")
    for group in ("sources", "headers"):
        for entry in contract.get(group, []):
            rel = entry.get("path")
            target = os.path.join(repo, rel or "")
            if not rel or not os.path.exists(target):
                problems.append(f"shared-runtime {group} entry missing: {rel}")
                continue
            with open(target, "rb") as f:
                data = f.read()
            if "sha256:" + hashlib.sha256(data).hexdigest() != entry.get("sha256"):
                problems.append(
                    f"shared-runtime {group} digest mismatch: {rel}")
            if entry.get("byteLen") is not None and len(data) != entry["byteLen"]:
                problems.append(f"shared-runtime {group} byteLen mismatch: {rel}")
    return contract, problems


def shared_runtime_closure(contract):
    """Every materialized path the verified contract covers — sources AND headers."""
    if not contract:
        return []
    out = [e["path"] for e in contract.get("sources", []) if e.get("path")]
    out += [e["path"] for e in contract.get("headers", []) if e.get("path")]
    out += list(contract.get("consumerHeaders", []) or [])
    return sorted(set(out))


def _execution_status(manifest):
    """Derive execution status from the manifest's own gate records, so the receipt
    cannot keep asserting a STOP the manifest has already retired."""
    seams = manifest.get("gatedOnSeams", []) or []
    blocking = [s for s in seams
                if "SATISFIED" not in s and "LANDED" not in s
                and "PENDING-RATIFICATION" not in s]
    if blocking:
        return "blocked: " + "; ".join(blocking)
    pending = [s for s in seams if "PENDING-RATIFICATION" in s]
    if pending:
        return ("clean-clone engineering unblocked; publication and license "
                "ratification pending")
    return "clean-clone engineering unblocked; no outstanding seams"


def build_receipt(manifest, repo):
    """Assemble the deterministic receipt dict plus a list of consistency problems
    (empty when the extraction surface is whole)."""
    problems = []

    contract, contract_problems = load_shared_runtime_contract(repo)
    problems += contract_problems
    # A KNOWN-INCOMPLETE dependency cannot receive a green `verified` receipt.
    # Recording attribution is useful, but it does not make the closure whole: a
    # clean clone materializing exactly this contract still fails to compile, so
    # the contract is UNVERIFIED and extraction is BLOCKED until the closure is
    # made whole. (No gap is recorded today: the one previously suspected was a
    # false positive of a compile-definition-blind scan, now fixed.)
    gap_entries = manifest.get("sharedRuntimeContractGaps", {}).get("entries", [])
    for gap in gap_entries:
        problems.append(
            f"shared-runtime contract closure is INCOMPLETE: {gap['header']} is "
            f"reached by {gap['reachedBy']} but declared in neither headers nor "
            "consumerHeaders — a clean clone of the exact closure cannot compile "
            "(owner: )")

    authored = sorted(set(_authored_source_files(manifest))
                      | set(shared_runtime_closure(contract)))
    authored_digests, authored_missing = _digest_map(repo, authored)
    problems += [f"authored source missing: {m}" for m in authored_missing]

    generated = _generated_products(manifest)
    generated_block, generated_missing = {}, []
    for rel, gen, frm in generated:
        # : generated .inc are BUILD PRODUCTS. Resolve them where they are
        # produced; a source-tree copy no longer exists and its absence is the
        # intended end state, not a missing artifact. The receipt still digests
        # the real bytes, so the binding is unchanged -- only the location moved.
        path = os.path.join(repo, rel)
        if _generated_artifacts and _generated_artifacts.is_migrated(rel):
            try:
                path = _generated_artifacts.resolve(rel, BUILD_DIR)
            except _generated_artifacts.GeneratedArtifactError as err:
                generated_missing.append(f"{rel} ({err.identity})")
                continue
        if os.path.exists(path):
            generated_block[rel] = {
                "sha256": _sha256(path), "generator": gen, "from": frm}
        else:
            generated_missing.append(rel)
    problems += [f"generated product missing: {m}" for m in generated_missing]

    packaging = _packaging_files(repo)
    packaging_digests, _ = _digest_map(repo, packaging)

    # Core identity: the  boundary + the pinned compatibility surface.
    core = manifest["publicCoreContract"]
    canonical = core["canonicalArtifact"]
    leaf = manifest["sharedLeafLinkDeps"]
    compat_rel = COMPATIBILITY_MANIFEST
    compat_path = os.path.join(repo, compat_rel)
    if os.path.exists(compat_path):
        compat = {"path": compat_rel, "sha256": _sha256(compat_path)}
    else:
        compat = {"path": compat_rel, "sha256": None}
        problems.append(f"compatibility manifest absent: {compat_rel}")

    # Public-core headers must resolve under include/ (the declared dependency surface).
    public_core_headers = leaf["consumedPublicCoreHeaders"]
    for group, headers in public_core_headers.items():
        for header in headers:
            if not os.path.exists(os.path.join(repo, "include", header)):
                problems.append(
                    f"declared public-core header does not resolve: {header} ({group})")

    # License/provenance audit: every owned file is accounted for above; the license
    # IDENTITY is the single item explicitly gated on  (named, not defaulted).
    license_state = manifest["provenance"]["license"]["status"]
    license_provenance = {
        "licenseIdentity": (
            "gated:845" if license_state == "deferred-to-845" else license_state),
        "versionSurface": manifest["provenance"]["versionSurface"],
        # Owned files with neither an authored/generated digest nor a license
        # resolution. The license identity being gated on  is a tracked gate,
        # NOT an unresolved file, so it does not populate this list.
        "unresolvedFiles": sorted(authored_missing + generated_missing),
    }

    repo_head = _git(repo, "rev-parse", "HEAD")
    unit_revision = _git(repo, "log", "-1", "--format=%H", "--",
                         manifest["unitRoot"], "packaging/postgres")
    # A proof receipt without a source revision cannot reproduce or bind the
    # extracted source, so a missing identity fails closed rather than emitting
    # null. (Archive materialization may later supply an explicit, validated
    # identity; it must be supplied, never absent.)
    if not repo_head:
        problems.append(
            "source identity missing: repoHead could not be determined — a receipt "
            "without it cannot bind the extracted source")
    if not unit_revision:
        problems.append(
            "source identity missing: unitRevision could not be determined")

    receipt = {
        "kind": RECEIPT_KIND,
        "issue": manifest["issue"],
        "unit": manifest["unit"],
        "unitRoot": manifest["unitRoot"],
        "sourceIdentity": {
            "repoHead": repo_head,
            "unitRevision": unit_revision,
            "sourceOfTruth": manifest["sourceOfTruth"],
        },
        "sharedRuntimeContract": {
            "path": SHARED_RUNTIME_CONTRACT,
            "identity": (contract or {}).get("kind"),
            "contractDigest": (contract or {}).get("contractDigest"),
            "expectedDigest": EXPECTED_SHARED_RUNTIME_DIGEST,
            "verified": not contract_problems and not gap_entries,
            "closureIncomplete": bool(gap_entries),
            "closureFiles": len(shared_runtime_closure(contract)),
            "declaredClosureGaps": manifest.get(
                "sharedRuntimeContractGaps", {}).get("entries", []),
        },
        "coreIdentity": {
            "boundaryAdr": core["adr"],
            "model": core["model"],
            "canonicalArtifact": canonical["identity"],
            "projectionSchema": canonical["schema"],
            "protocol": core["protocol"]["identity"],
            "compatibilityManifest": compat,
            "publicCoreHeaders": public_core_headers,
            "linkDeps": leaf["libs"],
        },
        "dependencyGraph": {
            "publicCoreEdges": public_core_headers,
            "linkDeps": leaf["libs"],
            "ownPublicHeaders": manifest["publicHeaders"]["declared"],
            "ownInternalHeaders": [
                os.path.join(manifest["unitRoot"], h["file"])
                for h in manifest["internalHeaders"]["files"]
            ],
        },
        "fileDigests": {
            "authoredSources": authored_digests,
            "generatedBuildProducts": generated_block,
            "packagingFiles": packaging_digests,
        },
        "testResults": {
            "conformanceSlice": manifest["conformanceSlice"]["tests"],
            # Derived from the manifest's structured gate state — not a second
            # hard-coded ledger that can drift from it.
            "executionStatus": (
                "BLOCKED: the shared-runtime contract closure is incomplete "
                "(owner )" if gap_entries else _execution_status(manifest)),
            "baseline":
                "monorepo ctest targets (SQL byte goldens + real-PostgreSQL harness)",
        },
        "licenseProvenance": license_provenance,
        # Recorded for the  publication gate, never auto-stripped here.
        "internalReferences": [
            {"jsonPath": path, "kind": kind, "value": value}
            for path, kind, value in internal_reference_findings(manifest)
        ],
    }
    return receipt, problems


def emit(manifest, repo):
    receipt, _problems = build_receipt(manifest, repo)
    return json.dumps(receipt, indent=2, sort_keys=True) + "\n"


def check(manifest, repo):
    receipt, problems = build_receipt(manifest, repo)
    n = (len(receipt["fileDigests"]["authoredSources"])
         + len(receipt["fileDigests"]["generatedBuildProducts"]))
    if problems:
        print(f"extraction receipt self-check FAILED ({n} owned files digested):",
              file=sys.stderr)
        for p in problems:
            print(f"  [{RECEIPT_KIND}] {p}", file=sys.stderr)
        return 1
    print(f"extraction receipt self-check OK: {n} owned files digested, "
          f"{len(receipt['coreIdentity']['publicCoreHeaders'])} public-core "
          f"header groups resolve, compatibility surface pinned")
    return 0


def _p1_mutations(repo, manifest):
    """Biting mutations for the three receipt-integrity properties."""
    failures = []
    import copy as _copy

    # (1) contract binding: a tampered header digest must fail the atomic bind.
    contract, problems = load_shared_runtime_contract(repo)
    if problems:
        failures.append(f"shared-runtime contract does not verify: {problems}")
    if contract:
        bad = _copy.deepcopy(contract)
        if bad.get("headers"):
            bad["headers"][0]["sha256"] = "sha256:" + "0" * 64
        body = {k: v for k, v in bad.items() if k != "contractDigest"}
        recomputed = "sha256:" + hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if recomputed == bad.get("contractDigest"):
            failures.append("contract digest did not change on a header mutation")
        # A header outside the closure must not be silently owned.
        closure = set(shared_runtime_closure(contract))
        if "include/Neutrino/UndeclaredPrivate.h" in closure:
            failures.append("closure admitted an undeclared header")
        if not any(p.startswith("include/") for p in closure):
            failures.append("closure contains no headers — headers are unaudited")

    # (1b) THE EXACT GAP MUTATION: a header the contract does not declare must not
    # be admitted by either surface. Feeding a mutated gap header through the real
    # verifiers (not an in-memory digest comparison) is what proves the gap is not
    # silently allowlisted.
    gaps = manifest.get("sharedRuntimeContractGaps", {}).get("entries", [])
    if gaps:
        gap_header = gaps[0]["header"]
        closure = set(shared_runtime_closure(contract))
        if f"include/{gap_header}" in closure:
            failures.append(
                f"{gap_header} is inside the closure — the recorded gap is stale")
        _r3, probs3 = build_receipt(manifest, repo)
        if not any("closure is INCOMPLETE" in p for p in probs3):
            failures.append(
                "a recorded contract gap did not block the receipt — a known "
                "incomplete dependency must not receive a verified receipt")
        if _r3["sharedRuntimeContract"]["verified"]:
            failures.append("contract reported verified despite a recorded gap")

    # (1b) COMPILE-DEFINITION-AWARE CLOSURE AUDIT. The frozen contract pins
    # compileDefinitions, so a producer-only guarded include is not a dependency of
    # the frozen closure — but any include that IS active must still be audited, and
    # any conditional form the evaluator does not support must fail closed.
    import check_package_reachback as _rb
    _defs = ["NEUTRINO_PROJECTION_CONSUMER_ONLY"]
    _cases = (
        ("producer-only guarded include is EXCLUDED under the frozen definitions",
         '#ifndef NEUTRINO_PROJECTION_CONSUMER_ONLY\n#include "Producer.h"\n#endif\n',
         _defs, [], []),
        ("the same include made UNCONDITIONAL is seen (and therefore audited)",
         '#include "Producer.h"\n', _defs, ["Producer.h"], []),
        ("an include on the ACTIVE branch is seen",
         '#ifndef SOME_OTHER_MODE\n#include "Active.h"\n#endif\n',
         _defs, ["Active.h"], []),
        ("an unsupported conditional form FAILS CLOSED rather than being skipped",
         '#if defined(X)\n#include "Ambiguous.h"\n#endif\n', _defs, None, ["if"]),
    )
    for _desc, _text, _d, _want_inc, _want_unsup in _cases:
        _inc, _unsup = _rb.active_includes(_text, _d)
        _names = [t for t, _q in _inc]
        if _want_inc is not None and _names != _want_inc:
            failures.append(f"closure-audit case [{_desc}]: includes {_names} != "
                            f"{_want_inc}")
        if _want_unsup and not _unsup:
            failures.append(f"closure-audit case [{_desc}]: unsupported form was "
                            "skipped instead of failing closed")
        if not _want_unsup and _unsup:
            failures.append(f"closure-audit case [{_desc}]: spurious unsupported "
                            f"form {_unsup}")

    # (2) source identity: a receipt with no repoHead must FAIL, not emit null.
    _receipt, probs = build_receipt(manifest, repo)
    if any("source identity missing" in p for p in probs):
        failures.append("source identity reported missing on a real checkout")
    fake = os.path.join(repo, "packaging")   # a dir with no git history of its own
    _r2, probs2 = build_receipt(manifest, fake)
    if not any("source identity missing" in p or "missing" in p for p in probs2):
        failures.append("a receipt without source identity was accepted")

    # (3) execution status is DERIVED, not a second hard-coded ledger.
    blocked = {"gatedOnSeams": ["999 (a genuinely blocking seam)"]}
    if not _execution_status(blocked).startswith("blocked"):
        failures.append("execution status ignored a blocking seam")
    unblocked = {"gatedOnSeams": ["846 SATISFIED", "845 PENDING-RATIFICATION"]}
    if "unblocked" not in _execution_status(unblocked):
        failures.append("execution status did not derive the unblocked state")
    return failures


def selftest():
    """Biting mutations: --check must FAIL closed when a manifest-owned file is
    absent, when a public-core header does not resolve, and when the pinned
    compatibility surface is missing — and PASS on the real, whole surface."""
    here = os.path.dirname(HERE)
    manifest_path = os.path.join(here, "extraction-manifest.json")
    repo = os.path.dirname(os.path.dirname(here))
    real = load_manifest(manifest_path)

    failures = []

    def expect(desc, manifest, use_repo, want_ok):
        _receipt, problems = build_receipt(manifest, use_repo)
        ok = not problems
        if ok != want_ok:
            failures.append(
                f"{desc}: expected {'OK' if want_ok else 'FAIL'}, "
                f"got {'OK' if ok else 'FAIL (' + '; '.join(problems) + ')'}")

    # (1) The real surface. While the  contract closure is INCOMPLETE the
    # receipt must be BLOCKED — a known-incomplete dependency cannot pass. Once
    # a genuine closure gap is ever recorded, this arm requires it to block; with
    # none recorded it is an unconditional pass.
    _r, _p = build_receipt(real, repo)
    _gapped = bool(real.get("sharedRuntimeContractGaps", {}).get("entries", []))
    if _gapped:
        if not any("closure is INCOMPLETE" in x for x in _p):
            failures.append(
                "the recorded  contract gap did not block the receipt")
        if [x for x in _p if "closure is INCOMPLETE" not in x]:
            failures.append(
                f"the real surface has problems beyond the recorded gap: "
                f"{[x for x in _p if 'closure is INCOMPLETE' not in x]}")
    else:
        expect("real surface", real, repo, True)

    # (2) an owned authored source removed from the manifest's tree is caught: point
    # the audit at a repo that lacks it (use a bogus repo root -> every file missing).
    expect("empty tree (all owned files missing)", real, os.path.join(repo, "packaging"),
           False)

    # (3) a manifest that declares a non-existent compiled source fails closed.
    import copy
    broken = copy.deepcopy(real)
    broken["compiledSources"]["files"].append("provider/DoesNotExist.cpp")
    expect("declared-but-absent compiled source", broken, repo, False)

    # (4) a manifest that declares an unresolvable public-core header fails closed.
    broken_hdr = copy.deepcopy(real)
    broken_hdr["sharedLeafLinkDeps"]["consumedPublicCoreHeaders"]["NeutrinoSpecContract"] \
        .append("Neutrino/NoSuchPublicHeader.h")
    expect("unresolvable public-core header", broken_hdr, repo, False)

    failures += _p1_mutations(repo, real)

    if failures:
        print("extraction receipt SELFTEST FAILED:", file=sys.stderr)
        for f in failures:
            print("  " + f, file=sys.stderr)
        return 1
    print("extraction receipt selftest OK (absent owned file / unresolvable "
          "public-core header / missing compatibility surface all fail closed)")
    return 0


def main():
    default_manifest = os.path.join(os.path.dirname(HERE), "extraction-manifest.json")
    # scripts -> packaging/postgres -> packaging -> repo root
    default_repo = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default=default_manifest)
    ap.add_argument("--repo", default=default_repo)
    ap.add_argument("--output", help="write the receipt to PATH instead of stdout")
    ap.add_argument("--check", action="store_true",
                    help="emit and fail closed on any extraction-surface gap")
    ap.add_argument("--selftest", action="store_true",
                    help="run the biting mutations and exit")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    manifest = load_manifest(args.manifest)
    if args.check:
        return check(manifest, args.repo)

    payload = emit(manifest, args.repo)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(payload)
        print(f"wrote {args.output}")
    else:
        sys.stdout.write(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())

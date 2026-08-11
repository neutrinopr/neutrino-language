#!/usr/bin/env python3
"""Generate the deterministic CORE CONTRACT BUNDLE ().

The bundle is the published, versioned, machine-readable boundary an EXTERNAL
domain pack validates against WITHOUT importing translator source or a sibling
checkout. It is GENERATED from the authoritative core contracts — never hand
maintained — so it cannot drift from them:

  * the version/compatibility axes come from `neutrino-translate --version-json`
    (the single VersionInfo.h surface, );
  * each contract's identity ($id) and digest come from its committed
    docs/schemas/*.schema.json;
  * the diagnostic taxonomy reference + its categories come from the committed
    docs/diagnostic-taxonomy.json.

Deterministic: sorted keys, no timestamps, sha256 digests. `bundleDigest` is the
sha256 over the compact canonical bundle with the digest field removed (the same
discipline as capabilityHash / domainSemanticsHash). Regenerating byte-matches
the committed docs/core-contract-bundle.json (a gate pins it); the release
manifest surfaces the digest.

  make_core_contract_bundle.py --translate <neutrino-translate> [--repo-root DIR]
Exit 0 ok / 1 error.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# The BUNDLE's own version (the published boundary version). Bumped when the
# bundle's shape or its registered contract set changes; distinct from the
# per-contract and tool versions it carries.
BUNDLE_ID = "neutrino.core-contract-bundle"
BUNDLE_VERSION = "1.12.0"

# The authoritative core contracts the bundle publishes, grouped by family. A
# schema added to a core family MUST be registered here (the completeness gate
# fails otherwise); the digest + $id are read from the committed file, never
# copied. Ordered for a stable, readable manifest.
CONTRACTS = [
    ("capability-spec", "capability-spec", "docs/schemas/capability-spec.schema.json"),
    # : v2 is a NEW contract (its own /v2 id) — v1 + the top-level obligations
    # section + schemaVersion 4. Adding a new contract is a COMPATIBLE bundle
    # evolution (v1 stays byte-identical); it does not reversion v1. Same shape as
    # the l2-domain-semantics v2->v3 split ().
    ("capability-spec-v2", "capability-spec", "docs/schemas/capability-spec-v2.schema.json"),
    ("capability-spec-validation", "capability-spec", "docs/schemas/capability-spec-validation.schema.json"),
    ("l2-domain-semantics-v2", "l2-domain", "docs/schemas/l2-domain-semantics-v2.schema.json"),
    # : v3 is a NEW contract (its own /v3 id) — v2's reduction graph + a required
    # intakeVersioning object. Adding a new contract is a COMPATIBLE bundle evolution
    # (v2 stays byte-identical); it does not reversion v2.
    ("l2-domain-semantics-v3", "l2-domain", "docs/schemas/l2-domain-semantics-v3.schema.json"),
    ("domain-dialect", "l2-domain", "docs/schemas/domain-dialect.schema.json"),
    ("domain-observation-set", "l2-domain", "docs/schemas/domain-observation-set.schema.json"),
    ("target-profile", "profile", "docs/schemas/target-profile.schema.json"),
    ("backend-package-target-profile-v1", "profile",
     "docs/schemas/backend-package-target-profile-v1.schema.json"),
    ("semantic-feature-vocabulary", "semantic", "docs/schemas/semantic-feature-vocabulary.schema.json"),
    ("semantic-capability-registry", "semantic", "docs/schemas/semantic-capability-registry.schema.json"),
    ("semantic-requirements", "semantic", "docs/schemas/semantic-requirements.schema.json"),
    ("finalized-projection-v1", "semantic", "docs/schemas/finalized-projection-v1.schema.json"),
    ("binding-manifest", "binding", "docs/schemas/binding-manifest.schema.json"),
    ("binding-policy", "binding", "docs/schemas/binding-policy.schema.json"),
    ("binding-receipt", "binding", "docs/schemas/binding-receipt.schema.json"),
    ("slot-binding-topology", "binding", "docs/schemas/slot-binding-topology.schema.json"),
    ("runtime-evidence-envelope", "binding", "docs/schemas/runtime-evidence-envelope.schema.json"),
    ("test-realization", "scenario-result", "docs/schemas/test-realization.schema.json"),
    ("generalism-result", "scenario-result", "docs/schemas/generalism-result.schema.json"),
    ("participant-view", "scenario-result", "docs/schemas/participant-view.schema.json"),
    ("domain-pack", "conformance", "docs/schemas/domain-pack.schema.json"),
    ("domain-pack-v2", "conformance", "docs/schemas/domain-pack-v2.schema.json"),
]

TAXONOMY = "docs/diagnostic-taxonomy.json"
# The closed  semantic-feature vocabulary artifact (emitted by
# `neutrino-translate --semantic-feature-vocabulary`), published in the bundle
# with its version + digest so an external pack matches profile features against
# the SAME closed set the translator enforces.
VOCABULARY = "docs/semantic-feature-vocabulary.json"
# The authoritative capability registry artifact (emitted by
# `neutrino-translate --capability-registry`, ), published in the bundle with
# its version + digest so a package-only producer/verifier can obtain and
# independently validate the SAME closed capability contract the translator emits
# and the M7 intake seam anchors executable reductions against.
CAPABILITY_REGISTRY = "docs/semantic-capability-registry.json"

# The per-axis compatibility policy an external consumer applies against a
# translator surface (mirrors check_compatibility.py, ). Published so a pack
# knows exactly how each pin is negotiated — fail-closed on anything unknown.
COMPAT_POLICY = {
    "toolVersion": "semver: same MAJOR and translator >= bundle",
    "mlirDialectVersion": "exact",
    "capabilitySpecVersion": "exact",
    "semanticProfileVersion": "exact",
    "schemaBundleVersion": "exact",
    "conformanceVectorVersion": "exact",
    "compatibilityManifestVersion": "exact",
}

CANONICALIZATION = {
    "json": "UTF-8, object keys sorted, no insignificant whitespace",
    "digest": "lowercase sha256, 'sha256:' prefixed",
    "bundleDigest": "sha256 over the compact canonical bundle (sort_keys, "
                    "separators=(',',':')) with the bundleDigest field removed",
}


def _abs(rel: str) -> str:
    return os.path.join(REPO, rel)


def _sha256(rel: str) -> str:
    with open(_abs(rel), "rb") as f:
        return "sha256:" + hashlib.sha256(f.read()).hexdigest()


def _contract_id(rel: str) -> str:
    with open(_abs(rel), encoding="utf-8") as f:
        return json.load(f).get("$id", "")


def _version_surface(translate: str) -> dict:
    r = subprocess.run([translate, "--version-json"], stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE)
    if r.returncode != 0:
        raise SystemExit(f"error: {translate} --version-json failed: "
                         f"{r.stderr.decode('utf-8', 'replace').strip()}")
    return json.loads(r.stdout)


def _canonical(obj: dict) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def build(translate: str) -> dict:
    v = _version_surface(translate)
    contracts = []
    for name, family, rel in CONTRACTS:
        contracts.append({
            "name": name,
            "family": family,
            "contractId": _contract_id(rel),
            "path": rel,
            "sha256": _sha256(rel),
        })
    tax = json.load(open(_abs(TAXONOMY), encoding="utf-8"))
    bundle = {
        "kind": "neutrino.core-contract-bundle",
        "schemaVersion": 1,
        "bundleId": BUNDLE_ID,
        "bundleVersion": BUNDLE_VERSION,
        "translatorCompatibility": {
            "toolVersion": v["toolVersion"],
            "policy": COMPAT_POLICY,
        },
        "versions": {
            "toolVersion": v["toolVersion"],
            "mlirDialectVersion": v["mlirDialectVersion"],
            "schemaBundleVersion": v["schemaBundleVersion"],
            "capabilitySpecVersion": v["capabilitySpecVersion"],
            "semanticProfileVersion": v["semanticProfileVersion"],
            "conformanceVectorVersion": v["conformanceVectorVersion"],
            "compatibilityManifestVersion": v["compatibilityManifestVersion"],
            "semanticLanguageVersion": v["semanticLanguageVersion"],
            "schemas": v["schemas"],
        },
        "contracts": contracts,
        "diagnosticTaxonomy": {
            "path": TAXONOMY,
            "sha256": _sha256(TAXONOMY),
            "categories": tax["categories"],
        },
        "semanticVocabulary": {
            "semanticProfileVersion": v["semanticProfileVersion"],
            "path": VOCABULARY,
            "sha256": _sha256(VOCABULARY),
        },
        "semanticCapabilityRegistry": {
            "semanticProfileVersion": v["semanticProfileVersion"],
            "path": CAPABILITY_REGISTRY,
            "sha256": _sha256(CAPABILITY_REGISTRY),
        },
        "canonicalization": CANONICALIZATION,
    }
    bundle["bundleDigest"] = "sha256:" + hashlib.sha256(
        _canonical(bundle).encode("utf-8")).hexdigest()
    return bundle


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--translate", required=True,
                    help="path to neutrino-translate (for --version-json)")
    ap.add_argument("--repo-root", help="override the repository root")
    args = ap.parse_args()
    if args.repo_root:
        global REPO
        REPO = os.path.abspath(args.repo_root)
    bundle = build(args.translate)
    print(json.dumps(bundle, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())

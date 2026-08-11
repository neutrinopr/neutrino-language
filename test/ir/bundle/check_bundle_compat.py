"""/ current-vs-prior bundle compatibility. Proves the committed,
COMPLETE + self-consistent frozen v1.0 and v1.9 boundaries (bundle plus every
pinned artifact) are valid consumer targets validated by the current released
verifier against their frozen roots; that the current bundle is a
backward-compatible evolution across the WHOLE
normative compatibility surface (contracts, bundle identity + canonicalization,
exact version axes + compatibility policy, and the diagnostic taxonomy compared BY
CONTENT — every prior stable code survives with its identity/category/precedence/
status — with additive codes and the new semanticVocabulary surface allowed); that
the exact-pin keeps the two boundaries distinct; and that removed/re-versioned
contracts, a removed/renumbered prior diagnostic code, and an exact-version-axis
drift are all classified breaking by the SAME evaluator the acceptance relies on.

Usage: check_bundle_compat.py <repo-root> <v1.0-root> <v1.9-root>
                              <current-pack> <verifier>
"""
import copy
import hashlib
import json
import os
import subprocess
import sys

REPO, V10_ROOT, V19_ROOT, V11_PACK, VERIFIER = sys.argv[1:6]
fails = []


def semver(v):
    return [int(x) for x in str(v).split(".")]


def contract_map(b):
    return {c["name"]: (c["contractId"], c["sha256"]) for c in b["contracts"]}


def code_map(tax):
    # code -> its stable identity: (category, precedence, status).
    return {c["code"]: (c.get("category"), c.get("precedence"), c.get("status"))
            for c in (tax or {}).get("codes", [])}


def _flat(d, prefix=""):
    # flatten nested version axes (e.g. versions.schemas.bindingPolicy) to dotted keys.
    out = {}
    for k, v in (d or {}).items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(_flat(v, key + "."))
        else:
            out[key] = v
    return out


def compat_findings(prior, current, prior_tax, current_tax):
    """The ONE compatibility evaluation over the WHOLE normative surface. `current`
    must be a backward-compatible evolution of `prior`; every finding is a breaking
    change. Additions (new contracts, new diagnostic codes, the semanticVocabulary
    block) are compatible."""
    out = []
    # (a) contracts: no removed/re-versioned prior contract.
    a, b = contract_map(prior), contract_map(current)
    out += [("contract_removed", n) for n in sorted(set(a) - set(b))]
    out += [("contract_reversioned", n) for n in sorted(n for n in a if n in b and b[n] != a[n])]
    # (b) stable bundle identity + canonicalization/hash rules (exact).
    for k in ("bundleId", "kind", "schemaVersion", "canonicalization"):
        if prior.get(k) != current.get(k):
            out.append(("identity_changed", k))
    # (c) the COMPLETE compatibility policy map is public/versioned — no rule may change (relax or
    #     tighten) within the same major, including the non-exact toolVersion rule.
    ppol = (prior.get("translatorCompatibility") or {}).get("policy") or {}
    cpol = (current.get("translatorCompatibility") or {}).get("policy") or {}
    for axis in sorted(set(ppol) | set(cpol)):
        if ppol.get(axis) != cpol.get(axis):
            out.append(("policy_changed", axis))
    # (d) EVERY published version axis is governed by the released verifier's negotiation rule:
    #     toolVersion is same-major + monotonic (semver); every OTHER axis — including
    #     semanticLanguageVersion and the nested schemas.* map — is exact.
    pver, cver = _flat(prior.get("versions")), _flat(current.get("versions"))
    for axis in sorted(set(pver) | set(cver)):
        if axis == "toolVersion":
            try:
                pv, cv = semver(pver[axis]), semver(cver[axis])
                if pv[0] != cv[0] or cv < pv:
                    out.append(("tool_version_incompatible", axis))
            except (KeyError, ValueError):
                out.append(("tool_version_incompatible", axis))
        elif pver.get(axis) != cver.get(axis):
            out.append(("exact_axis_drift", axis))
    # (e) diagnostic taxonomy: ENVELOPE identity (kind/schemaVersion) + the bundle's PUBLISHED
    #     categories (append-only) + every prior stable CODE surviving with its identity by CONTENT.
    for k in ("kind", "schemaVersion"):
        if (prior_tax or {}).get(k) != (current_tax or {}).get(k):
            out.append(("taxonomy_envelope_changed", k))
    pcat = (prior.get("diagnosticTaxonomy") or {}).get("categories") or []
    ccat = (current.get("diagnosticTaxonomy") or {}).get("categories") or []
    if pcat != ccat[:len(pcat)]:  # published categories may only be appended to
        out.append(("taxonomy_categories_changed", "categories"))
    pc, cc = code_map(prior_tax), code_map(current_tax)
    for code, ident in pc.items():
        if code not in cc:
            out.append(("taxonomy_code_removed", code))
        elif cc[code] != ident:
            out.append(("taxonomy_code_changed", code))
    return out


def pinned_artifacts(b):
    pins = [(c["path"], c["sha256"]) for c in b["contracts"]]
    for key in (
        "diagnosticTaxonomy",
        "semanticVocabulary",
        "semanticCapabilityRegistry",
    ):
        blk = b.get(key)
        if isinstance(blk, dict) and blk.get("path"):
            pins.append((blk["path"], blk["sha256"]))
    return pins


def sha(path):
    return "sha256:" + hashlib.sha256(open(path, "rb").read()).hexdigest()


def load_taxonomy(bundle, root):
    p = os.path.join(root, bundle["diagnosticTaxonomy"]["path"])
    return json.load(open(p, encoding="utf-8"))


def verify(bundle, bundle_root, pack, pack_root):
    r = subprocess.run([sys.executable, VERIFIER, "--bundle", bundle, "--bundle-root", bundle_root,
                        "--pack", pack, "--pack-root", pack_root],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return r.returncode


v10 = json.load(open(os.path.join(V10_ROOT, "core-contract-bundle.json"), encoding="utf-8"))
v19 = json.load(open(os.path.join(V19_ROOT, "core-contract-bundle.json"), encoding="utf-8"))
v11 = json.load(open(os.path.join(REPO, "docs/core-contract-bundle.json"), encoding="utf-8"))
tax10 = load_taxonomy(v10, V10_ROOT)
tax19 = load_taxonomy(v19, V19_ROOT)
tax11 = load_taxonomy(v11, REPO)

# 1. version relationship: a same-MAJOR forward evolution.
for label, prior in (("v1.0", v10), ("v1.9", v19)):
    if not (
        semver(v11["bundleVersion"])[0] == semver(prior["bundleVersion"])[0]
        and semver(v11["bundleVersion"]) > semver(prior["bundleVersion"])
    ):
        fails.append(
            f"current {v11['bundleVersion']} is not a same-major forward "
            f"evolution of {label} {prior['bundleVersion']}"
        )

# 2. REAL pairs: current is compatible across the WHOLE normative surface.
for label, prior, prior_tax in (
    ("v1.0", v10, tax10),
    ("v1.9", v19, tax19),
):
    real = compat_findings(prior, v11, prior_tax, tax11)
    if real:
        fails.append(f"current bundle is not backward-compatible with {label}: {real}")
added_contracts = sorted(set(contract_map(v11)) - set(contract_map(v10)))
added_codes = sorted(set(code_map(tax11)) - set(code_map(tax10)))

# 3. Both frozen boundaries are COMPLETE + self-consistent.
def validate_pins(label, bundle, root):
    pins = pinned_artifacts(bundle)
    for path, want in pins:
        f = os.path.join(root, path)
        if not os.path.exists(f):
            fails.append(f"the frozen {label} boundary is missing pinned artifact {path}")
        elif sha(f) != want:
            fails.append(
                f"frozen {label} pinned artifact {path} does not match its pin "
                "(boundary not self-contained)"
            )
    return pins


pins10 = validate_pins("v1.0", v10, V10_ROOT)
pins19 = validate_pins("v1.9", v19, V19_ROOT)

# 4. Every consumer validates against its respective boundary using the current verifier.
if verify(os.path.join(V10_ROOT, "core-contract-bundle.json"), V10_ROOT,
          os.path.join(V10_ROOT, "pack.json"), V10_ROOT) != 0:
    fails.append("the v1.0 consumer does not validate against the frozen v1.0 boundary")
if verify(os.path.join(V19_ROOT, "core-contract-bundle.json"), V19_ROOT,
          os.path.join(V19_ROOT, "pack.json"), V19_ROOT) != 0:
    fails.append("the v1.9 consumer does not validate against the frozen v1.9 boundary")
if verify(os.path.join(REPO, "docs/core-contract-bundle.json"), REPO, V11_PACK, os.path.dirname(V11_PACK)) != 0:
    fails.append("the current consumer does not validate against the current bundle")

# 5. The exact-pin keeps the pre-change v1.9 and current boundaries DISTINCT.
if verify(os.path.join(REPO, "docs/core-contract-bundle.json"), REPO,
          os.path.join(V19_ROOT, "pack.json"), V19_ROOT) == 0:
    fails.append("a v1.9 pack validated against current — the exact-pin boundary is not enforced")
if verify(os.path.join(V19_ROOT, "core-contract-bundle.json"), V19_ROOT,
          V11_PACK, os.path.dirname(V11_PACK)) == 0:
    fails.append("the current pack validated against v1.9 — the exact-pin boundary is not enforced")

# 6. NON-VACUOUS: the SAME compat_findings() must classify each planted breakage — a removed and a
#    re-versioned contract, a removed AND a renumbered prior diagnostic code, and an exact-axis drift.
prior_code = tax10["codes"][0]["code"]  # a code that exists in v1.0 and current


def has(findings, kind, name=None):
    return any(k == kind and (name is None or n == name) for k, n in findings)


bc = copy.deepcopy(v11)
bc["contracts"] = [c for c in bc["contracts"] if c["name"] != "binding-policy"]
if not has(compat_findings(v10, bc, tax10, tax11), "contract_removed", "binding-policy"):
    fails.append("a removed prior contract was not classified breaking (vacuous)")

rc = copy.deepcopy(v11)
rc["contracts"][0]["contractId"] += "-x"
if not has(compat_findings(v10, rc, tax10, tax11), "contract_reversioned"):
    fails.append("a re-versioned prior contract was not classified breaking (vacuous)")

trm = copy.deepcopy(tax11)
trm["codes"] = [c for c in trm["codes"] if c["code"] != prior_code]
if not has(compat_findings(v10, v11, tax10, trm), "taxonomy_code_removed", prior_code):
    fails.append("a removed prior diagnostic code was not classified breaking (vacuous)")

trn = copy.deepcopy(tax11)
for c in trn["codes"]:
    if c["code"] == prior_code:
        c["precedence"] = (c.get("precedence") or 0) + 100000  # renumber the prior code
if not has(compat_findings(v10, v11, tax10, trn), "taxonomy_code_changed", prior_code):
    fails.append("a renumbered prior diagnostic code was not classified breaking (vacuous)")

ax = copy.deepcopy(v11)
ax["versions"]["capabilitySpecVersion"] = "v99"
if not has(compat_findings(v10, ax, tax10, tax11), "exact_axis_drift", "capabilitySpecVersion"):
    fails.append("an exact-version-axis drift was not classified breaking (vacuous)")

# a relaxed TOOL policy rule (the whole policy map is versioned, not just exact axes).
tp = copy.deepcopy(v11)
tp["translatorCompatibility"]["policy"]["toolVersion"] = "anything"
if not has(compat_findings(v10, tp, tax10, tax11), "policy_changed", "toolVersion"):
    fails.append("a relaxed toolVersion policy rule was not classified breaking (vacuous)")

# a previously-UNGOVERNED axis (nested schemas.*) drifting — must be exact.
ns = copy.deepcopy(v11)
ns["versions"]["schemas"]["bindingPolicy"] = "v99"
if not has(compat_findings(v10, ns, tax10, tax11), "exact_axis_drift", "schemas.bindingPolicy"):
    fails.append("a nested schemas.* axis drift was not classified breaking (vacuous)")

# a non-monotonic toolVersion (major bump) is incompatible; and a semanticLanguageVersion drift.
tv = copy.deepcopy(v11)
tv["versions"]["toolVersion"] = "9.0.0"
if not has(compat_findings(v10, tv, tax10, tax11), "tool_version_incompatible", "toolVersion"):
    fails.append("an incompatible (major-bumped) toolVersion was not classified breaking (vacuous)")

# taxonomy ENVELOPE identity + published categories.
te = copy.deepcopy(tax11)
te["kind"] = "other"
if not has(compat_findings(v10, v11, tax10, te), "taxonomy_envelope_changed", "kind"):
    fails.append("a taxonomy envelope kind change was not classified breaking (vacuous)")
cat = copy.deepcopy(v11)
cat["diagnosticTaxonomy"]["categories"] = []
if not has(compat_findings(v10, cat, tax10, tax11), "taxonomy_categories_changed", "categories"):
    fails.append("a cleared published taxonomy categories list was not classified breaking (vacuous)")

if fails:
    print("bundle compatibility check FAILED:", file=sys.stderr)
    for f in fails:
        print(f"    {f}", file=sys.stderr)
    sys.exit(1)
print(
    "bundle compat OK: frozen v1.0 "
    f"({len(pins10)} pinned artifacts) and v1.9 ({len(pins19)} pinned artifacts) "
    "boundaries are self-contained valid consumer targets; current is a compatible "
    "evolution across contracts/identity/version-policy/taxonomy "
    f"(added contracts {added_contracts}, added codes {len(added_codes)}); "
    "the v1.9/current exact-pins keep the boundaries distinct; compat_findings "
    "classifies contract, taxonomy, and exact-axis breakage (non-vacuous)"
)

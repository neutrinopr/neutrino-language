#!/usr/bin/env python3
""" — default-deny security-primitive carve-out gate (stdlib only, no build).

Verifies docs/security-primitive-carveout-registry.json against the working tree.

Enforced (each fail-closed; nothing is silently repaired):
  1. structure — closed shape with FORM-SPECIFIC required fields:
       exact-body        : identitySha256 + requiredSecurityTests + exact allowedConsumers
       reviewed-generator: closureFiles + closureSha256 + anchor + regionSha256 +
                           parameterSurface + outputVerifier (+ revoke coupling per role)
     wildcard/overbroad artifacts (any '*' or non-file path) fail specifically for scope widening;
  2. identity — exact-body byte sha256; reviewed-generator per-entry implementation-site REGION
     sha256 (from its unique anchor to the region end). The transitive-closure hash remains
     diagnostic provenance only: unrelated edits elsewhere in a closure cannot block a reviewed
     primitive whose exact region is unchanged;
  3. default-deny discovery — (a) every *.sol.inc / *.sql.inc under lib/backends/**, and
     (b) every generator SITE matched by the governed form-level patterns (acceptance-gate
     builders, REVOKE emitters) must be claimed by exactly one entry (or pendingClassification,
     draft status only). An unclaimed site, a claimed-but-missing site, or a cloned/new site fails;
  4. consumers — an exact-body's observed lib code consumers must equal allowedConsumers EXACTLY;
  5. resolver — the (governedTarget, finalizedKind) -> implementation mapping is machine-checked:
     exactly one row per pair, every row resolves, every non-REVOKE entry is reachable;
  6. guard->REVOKE coupling — signature-level: each acceptance entry's coupling marker must EQUAL
     its dependency's revokeSignatureMarker and appear verbatim in that dependency's site region;
     each REVOKE region must contain its own marker (missing / wrong-overload / wrong-function /
     wrong-variant routing each fail);
  7. trackedToZero — in tier2-final status every absenceProbe must be absent from lib/backends;
  8. core purity — no registry ID appears in lib/ outside lib/backends (the core never names a
     backend implementation ID).

--selftest runs the biting probe matrix; discovery accepts an in-memory overlay so clone/new-site
probes bite without mutating the tree.
"""
import copy
import hashlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import generated_artifacts  # noqa: E402

# : set from --build-dir (or $NEUTRINO_BUILD_DIR) before any closure
# derivation. The generated .inc live in the build tree, so a derivation that
# cannot see them silently shrinks rather than failing.
BUILD_DIR = ""

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REGISTRY = os.path.join(REPO, "docs", "security-primitive-carveout-registry.json")

ENTRY_REQUIRED = {"id", "form", "backend", "artifact", "purpose", "threatBoundary",
                  "whyNotDeclarative", "allowedConsumers", "approvingDecision"}
FORM_REQUIRED = {
    "exact-body": {"identitySha256", "requiredSecurityTests"},
    "reviewed-generator": {"closureFiles", "closureSha256", "anchor", "regionSha256",
                           "parameterSurface", "outputVerifier"},
}
# extensions an output verifier / security test may have — anything else is inert evidence
EXECUTABLE_VERIFIER_EXTS = (".sql", ".cmake", ".sh", ".py", ".sol")
# where OUTPUT verification may live: target-output test surfaces — never governance gates
VERIFIER_ROOTS = ("test/", "lib/backends/", "examples/oracle-reference/")
ENTRY_ALLOWED = (ENTRY_REQUIRED | FORM_REQUIRED["exact-body"] | FORM_REQUIRED["reviewed-generator"]
                 | {"finalizedKind", "revokeSignatureMarker", "revokeCoupling",
                    "entryPoint", "revokeFunctionPrefix", "dynamicNameOperand"})
TOP_REQUIRED = {"kind", "schemaVersion", "status", "issue", "defaultDeny", "scopeRule",
                "entries", "resolver", "pendingClassification", "trackedToZero", "prohibitions"}
# Governed form-level generator-site patterns: discovery is INDEPENDENT of registry content,
# so deleting an entry cannot hide its site.
SITE_PATTERNS = [re.compile(rb"PgFunction build\w*Accept\w*Gate\("),
                 re.compile(rb"pgddl::RawSql \w*[Aa]ccept\w*Revoke\(")]
REVOKE_LITERAL = b"REVOKE EXECUTE ON FUNCTION"


def joined_literals(region):
    """C++ adjacent string literals ("A" "B", possibly across lines) concatenate; join them so an
    emitted identity split across literals is still searchable as its contiguous text."""
    return re.sub(rb'"\s*"', b"", region)


class GateError(RuntimeError):
    pass


def _read_relative(rel, overlay):
    """Read a closure member by repo-relative path, build-tree aware."""
    if overlay and rel in overlay and overlay[rel] is not None:
        return overlay[rel]
    if generated_artifacts.is_migrated(rel):
        return generated_artifacts.read_text(rel, BUILD_DIR).encode()
    return _read(os.path.join(REPO, rel), overlay)


def _read(path, overlay):
    rel = os.path.relpath(path, REPO)
    if overlay and rel in overlay:
        if overlay[rel] is None:
            raise GateError(f"artifact absent: {rel}")
        return overlay[rel]
    with open(path, "rb") as f:
        return f.read()


def _walk(subdir, exts, overlay):
    out = []
    root = os.path.join(REPO, subdir)
    for r, _d, files in os.walk(root):
        for name in files:
            if name.endswith(exts):
                out.append(os.path.relpath(os.path.join(r, name), REPO))
    for rel in (overlay or {}):
        if rel.startswith(subdir) and rel.endswith(exts) and rel not in out \
                and overlay[rel] is not None:
            out.append(rel)
    return sorted(o for o in out if not (overlay and overlay.get(o, b"") is None))


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def derive_closure(roots, overlay):
    """The mechanical output-affecting closure: recursive local `#include "..."` resolution
    restricted to the backend directory, plus the same-stem source partner of every reached
    header (a header's .cpp affects the emitted output). Core `Neutrino/` headers are the
    upstream  waist, governed by their own gates — the carve-out trust boundary is the
    backend-local implementation."""
    #  R4: mirror the compiler's quote-include resolution over the package.
    # A backend split into role subdirs (model/ leaf/ generated/ provider/ …) has
    # the subdirs on its private -I, so bare `#include "X"` in one subdir resolves
    # a sibling-subdir file. Resolve each include relative to the INCLUDING file's
    # dir first (the `../leaf/`-style cross-dir includes), then across the package
    # role subdirs + the package root (the -I set). For a flat backend the search
    # collapses to the artifact dir, so Solidity closures/digests are unchanged.
    art_dir = os.path.dirname(roots[0])
    _ROLES = ("recipes", "model", "generated", "provider", "leaf", "harness")
    backend_root = (os.path.dirname(art_dir)
                    if os.path.basename(art_dir) in _ROLES else art_dir)
    # : a role dir may exist ONLY in the build tree now -- `generated/` was
    # deleted from the source tree, and filtering on source-tree existence alone
    # dropped it from the -I set, so every migrated artifact silently fell out
    # of the closure. The compiler still has it on -I, so the derivation must.
    search_dirs = [backend_root] + [
        os.path.join(backend_root, d) for d in _ROLES
        if os.path.isdir(os.path.join(REPO, backend_root, d))
        or (BUILD_DIR and os.path.isdir(os.path.join(BUILD_DIR, backend_root, d)))]

    def _exists(rel):
        # Overlay-aware existence (an overlay may inject or mask a file); a
        # cloned/duplicated site must be visible to the ambiguity check below.
        if overlay and rel in overlay:
            return overlay[rel] is not None
        # : a generated .inc lives in the BUILD tree, not the source tree.
        # The compiler's -I set now spans both, so the closure derivation must
        # too -- otherwise every migrated artifact silently drops out and the
        # closure shrinks without anything having changed semantically.
        if generated_artifacts.is_migrated(rel):
            try:
                generated_artifacts.resolve(rel, BUILD_DIR)
                return True
            except generated_artifacts.GeneratedArtifactError:
                return False
        return os.path.isfile(os.path.join(REPO, rel))

    def _resolve(including_rel, inc):
        # Definitive first: a quote-include relative to the including file's own
        # directory is exactly what the compiler binds (handles `../leaf/…` and
        # same-dir siblings). Only when that misses does it resolve via the
        # package -I set — and there a basename present in more than one role dir
        # is AMBIGUOUS: the gate could hash a different file than the compiler
        # consumes, so fail closed rather than pick a role order.
        own = os.path.normpath(os.path.join(os.path.dirname(including_rel), inc))
        if _exists(own):
            return own
        matches = []
        for d in search_dirs:
            cand = os.path.normpath(os.path.join(d, inc))
            if _exists(cand) and cand not in matches:
                matches.append(cand)
        if len(matches) > 1:
            raise GateError(
                f"ambiguous package include '{inc}' from {including_rel}: "
                f"matches multiple role dirs {matches} — the gate cannot bind the "
                "same file the compiler does; rename or fully-qualify the include")
        return matches[0] if matches else None

    seen, todo = set(), list(roots)
    while todo:
        rel = todo.pop()
        try:
            data = _read_relative(rel, overlay)
        except (GateError, FileNotFoundError,
                generated_artifacts.GeneratedArtifactError):
            continue
        if rel in seen:
            continue
        seen.add(rel)
        for m in re.finditer(rb'#include "([^"]+)"', data):
            cand = _resolve(rel, m.group(1).decode())
            if cand and cand not in seen:
                todo.append(cand)
                stem = os.path.splitext(cand)[0]
                for ext in (".cpp", ".h"):
                    partner = stem + ext
                    if _exists(partner):
                        todo.append(partner)
    return sorted(seen)


def closure_sha256(paths, overlay):
    h = hashlib.sha256()
    for p in sorted(paths):
        h.update(p.encode() + b"\0")
        h.update(_read_relative(p, overlay))
        h.update(b"\0")
    return h.hexdigest()


def site_region(entry, overlay):
    """The implementation region: from the entry's unique anchor to the region end (`\\n}\\n`)."""
    anchor = entry["anchor"].encode()
    hits = []
    for p in entry["closureFiles"]:
        data = _read_relative(p, overlay)
        start = 0
        while True:
            i = data.find(anchor, start)
            if i < 0:
                break
            hits.append((p, i, data))
            start = i + 1
    if len(hits) != 1:
        raise GateError(f"{entry['id']}: anchor must match exactly once in its closure "
                        f"(found {len(hits)}) — renamed/moved/cloned implementation site")
    p, i, data = hits[0]
    j = data.find(b"\n}\n", i)
    if j < 0:
        raise GateError(f"{entry['id']}: anchored region has no terminator in {p}")
    return p, data[i:j + 3]


def _no_wildcard(entry, field, value):
    values = value if isinstance(value, list) else [value]
    for v in values:
        if "*" in v or "?" in v:
            raise GateError(f"{entry['id']}: {field} {v!r} is a wildcard/overbroad scope — "
                            "scope widening is prohibited (exact identities only)")


def check_structure(reg):
    if set(reg) - (TOP_REQUIRED | {"statusNote"}) or TOP_REQUIRED - set(reg):
        raise GateError(f"registry top-level shape invalid: {sorted(set(reg) ^ TOP_REQUIRED)}")
    if reg["kind"] != "neutrino.security-primitive-carveout-registry" or reg["schemaVersion"] != 1:
        raise GateError("registry identity invalid")
    if reg["defaultDeny"] is not True:
        raise GateError("defaultDeny must be true")
    if reg["status"] not in ("draft-pre-tier2-final", "tier2-final"):
        raise GateError(f"unknown status {reg['status']!r}")
    ids = set()
    for e in reg["entries"]:
        missing = (ENTRY_REQUIRED | FORM_REQUIRED.get(e.get("form"), set())) - set(e)
        unknown = set(e) - ENTRY_ALLOWED
        if e.get("form") not in FORM_REQUIRED:
            raise GateError(f"entry {e.get('id')!r}: unknown form {e.get('form')!r}")
        if missing or unknown:
            raise GateError(f"entry {e.get('id')!r}: missing={sorted(missing)} unknown={sorted(unknown)}")
        if not re.match(r"^[A-Z0-9]+(-[A-Z0-9]+)*$", e["id"]) or e["id"] in ids:
            raise GateError(f"entry id invalid/duplicate: {e['id']!r}")
        ids.add(e["id"])
        _no_wildcard(e, "artifact", e["artifact"])
        _no_wildcard(e, "allowedConsumers", e["allowedConsumers"])
        if e["form"] == "exact-body" and not e.get("requiredSecurityTests"):
            raise GateError(f"{e['id']}: an exact-body entry must declare at least one "
                            "requiredSecurityTests verifier (an empty list is not evidence)")
        if e["form"] == "reviewed-generator" and not e.get("outputVerifier"):
            raise GateError(f"{e['id']}: a reviewed-generator entry must declare at least one "
                            "outputVerifier (an empty list is not evidence)")
        if e["form"] == "reviewed-generator":
            _no_wildcard(e, "closureFiles", e["closureFiles"])
            is_revoke = e["id"].endswith("-REVOKE")
            if is_revoke and ("revokeSignatureMarker" not in e or "revokeFunctionPrefix" not in e):
                raise GateError(f"{e['id']}: a -REVOKE entry requires revokeSignatureMarker "
                                "AND revokeFunctionPrefix (the complete function identity)")
            if not is_revoke and ("revokeCoupling" not in e or "entryPoint" not in e
                                   or "dynamicNameOperand" not in e):
                raise GateError(f"{e['id']}: an acceptance generator requires revokeCoupling, "
                                "its emitted entryPoint, and its dynamicNameOperand")
    return ids


def _relevance_tokens(reg, e):
    """Tokens a verifier's CONTENT must reference to count as verifying THIS primitive —
    derived from the entry (never attacker-pickable data): its finalizedKind root and/or its
    (coupled) emitted entry point, plus the exact-body artifact stem."""
    ids = {x["id"]: x for x in reg["entries"]}
    toks = set()
    kind = e.get("finalizedKind")
    if not kind and e["id"].endswith("-REVOKE"):
        for a in reg["entries"]:
            if a.get("revokeCoupling", {}).get("dependency") == e["id"]:
                kind = a.get("finalizedKind")
                toks.add(a.get("entryPoint", ""))
    if kind:
        toks.add(kind.split(".")[0].lower())          # e.g. "quorumacceptance" -> match "quorum…"
        toks.add(kind.split(".")[0].split("Acceptance")[0].lower())  # "quorum"
    if "entryPoint" in e:
        toks.add(e["entryPoint"])
    if e["form"] == "exact-body":
        toks.add(os.path.splitext(os.path.basename(e["artifact"]))[0].split(".")[0].lower())
    return {t for t in toks if t}


def check_verifiers(reg):
    """A declared verifier must (a) exist under an OUTPUT-verification root with an executable
    extension, (b) not belong to this gate's own governance surface (no self-evidence), (c) carry
    a PINNED registered invocation — surface contains marker; the marker or its pinned `via` hop
    demonstrably consumes the verifier — and (d) reference this primitive's derived relevance
    token in its content (an unrelated registered executable is not evidence)."""
    own_surface = {"docs/security-primitive-carveout-registry.json",
                   "docs/schemas/security-primitive-carveout-registry.schema.json",
                   "scripts/gates/check_security_primitive_carveout.py",
                   "test/checks/fast/security_primitive_carveout_test.py"}
    for e in reg["entries"]:
        for field in ("requiredSecurityTests", "outputVerifier"):
            for v in e.get(field, []):
                pth, inv = v["path"], v["invocation"]
                if pth in own_surface or pth.startswith("scripts/gates/"):
                    raise GateError(f"{e['id']}: {field} {pth} is not an output-verification "
                                    "surface (a governance gate cannot be its own evidence)")
                if not pth.startswith(VERIFIER_ROOTS):
                    raise GateError(f"{e['id']}: {field} {pth} is outside the output-verification "
                                    f"roots {VERIFIER_ROOTS}")
                if not os.path.isfile(os.path.join(REPO, pth)):
                    raise GateError(f"{e['id']}: {field} path does not exist: {pth}")
                if not pth.endswith(EXECUTABLE_VERIFIER_EXTS):
                    raise GateError(f"{e['id']}: {field} {pth} is inert evidence "
                                    f"(not an executable verifier: {EXECUTABLE_VERIFIER_EXTS})")
                surf = os.path.join(REPO, inv["surface"])
                if not os.path.isfile(surf) or inv["marker"].encode() not in open(surf, "rb").read():
                    raise GateError(f"{e['id']}: {field} {pth}: pinned invocation marker "
                                    f"{inv['marker']!r} not found in {inv['surface']}")
                consumed = os.path.basename(pth) in inv["marker"]
                if not consumed and "via" in inv:
                    via = os.path.join(REPO, inv["via"]["surface"])
                    hop = inv["via"]["mustContain"]
                    if os.path.isfile(via) and hop.encode() in open(via, "rb").read()                             and hop in pth:
                        consumed = True
                if not consumed:
                    raise GateError(f"{e['id']}: {field} {pth}: the pinned invocation does not "
                                    "demonstrably consume this verifier (marker lacks its name "
                                    "and no via-hop covers its path)")
                content = open(os.path.join(REPO, pth), "rb").read().lower()
                toks = _relevance_tokens(reg, e)
                if not any(t.lower().encode() in content for t in toks):
                    raise GateError(f"{e['id']}: {field} {pth} does not reference this "
                                    f"primitive's output identity (none of {sorted(toks)}) — "
                                    "an unrelated registered executable is not evidence")


def check_identities(reg, overlay):
    for e in reg["entries"]:
        if e["form"] == "exact-body":
            path = os.path.join(REPO, e["artifact"])
            if not os.path.isfile(path):
                raise GateError(f"{e['id']}: artifact missing (moved/renamed body?): {e['artifact']}")
            actual = sha256_bytes(_read(path, overlay))
            if actual != e["identitySha256"]:
                raise GateError(f"{e['id']}: identity drift — {actual[:16]}… vs pinned "
                                f"{e['identitySha256'][:16]}… (re-review + re-bank required)")
        else:
            derived = derive_closure([e["artifactRoots"][0], e["artifactRoots"][1]]
                                     if "artifactRoots" in e else
                                     ["lib/backends/postgres/model/PostgresModel.cpp",
                                      "lib/backends/postgres/model/PostgresModel.h"], overlay)
            if sorted(e["closureFiles"]) != derived:
                raise GateError(f"{e['id']}: closureFiles are not the mechanically derived "
                                f"closure — pinned {len(e['closureFiles'])} vs derived "
                                f"{len(derived)} files (re-derive + re-bank)")
            # The closure digest is retained as provenance, but the security
            # identity is the exact reviewed region below. A target file also
            # contains ordinary legalization code; edits outside the region
            # must not force a mechanical security re-bank.
            _p, region = site_region(e, overlay)
            ractual = sha256_bytes(region)
            if ractual != e["regionSha256"]:
                raise GateError(f"{e['id']}: implementation-region drift — {ractual[:16]}… vs "
                                f"pinned {e['regionSha256'][:16]}… (re-review + re-bank required)")
    for p in reg["pendingClassification"]:
        path = os.path.join(REPO, p["artifact"])
        if not os.path.isfile(path):
            raise GateError(f"pendingClassification artifact missing: {p['artifact']}")
        if sha256_bytes(_read(path, overlay)) != p["identitySha256"]:
            raise GateError(f"pendingClassification {p['artifact']}: identity drift")


def check_default_deny(reg, overlay):
    registered = {e["artifact"] for e in reg["entries"] if e["form"] == "exact-body"}
    pending = {p["artifact"] for p in reg["pendingClassification"]}
    if reg["status"] == "tier2-final" and pending:
        raise GateError("tier2-final registry carries a non-empty pendingClassification")
    for cand in _walk("lib/backends", (".sol.inc", ".sql.inc"), overlay):
        if cand in registered:
            continue
        if cand in pending:
            if reg["status"] != "draft-pre-tier2-final":
                raise GateError(f"{cand}: pending classification is only admissible in draft status")
            continue
        raise GateError(f"default-deny: unregistered handwritten target-source blob {cand}")
    # generator SITES: pattern discovery independent of the registry
    gens = [e for e in reg["entries"] if e["form"] == "reviewed-generator"]
    claimed = {}
    for e in gens:
        p, region = site_region(e, overlay)
        claimed[(p, region[:80])] = e["id"]
    for src in _walk("lib/backends", (".cpp", ".h"), overlay):
        data = _read_relative(src, overlay)
        for pat in SITE_PATTERNS:
            for m in pat.finditer(data):
                key = (src, data[m.start():m.start() + 80])
                if key not in claimed:
                    raise GateError(f"default-deny: unclaimed reviewed-generator site in {src} "
                                    f"(pattern {pat.pattern.decode()!r}) — register or remove it")


def check_consumers(reg, overlay):
    """Consumption of an exact-body blob is textual INCLUSION (`#include "...<basename>"`), the
    only way a verbatim body enters a TU — a comment mention is not consumption, a rogue include
    is. Observed includers must EQUAL allowedConsumers (no same-directory exemption)."""
    sources = _walk("lib", (".cpp", ".h"), overlay)
    for e in reg["entries"]:
        if e["form"] != "exact-body":
            continue
        base = re.escape(os.path.basename(e["artifact"]))
        inc = re.compile(rb"#\s*include\s*\"[^\"]*" + base.encode() + rb"\"")
        observed = sorted(s for s in sources
                          if s != e["artifact"] and inc.search(_read_relative(s, overlay)))
        if observed != sorted(e["allowedConsumers"]):
            raise GateError(f"{e['id']}: consumer set mismatch — observed {observed} != "
                            f"allowed {sorted(e['allowedConsumers'])} (exact equality required)")
    # reviewed-generator caller sets: every file referencing the implementation symbol must be
    # exactly the allowed set (a new TU calling the generator is an unauthorized caller).
    for e in reg["entries"]:
        if e["form"] != "reviewed-generator":
            continue
        symbol = re.search(r"([A-Za-z_][A-Za-z0-9_]*)\($", e["anchor"]).group(1).encode()
        observed = sorted(s2 for s2 in sources
                          if re.search(rb"\b" + symbol + rb"\(", _read(os.path.join(REPO, s2), overlay)))
        if observed != sorted(e["allowedConsumers"]):
            raise GateError(f"{e['id']}: generator caller set mismatch — observed {observed} != "
                            f"allowed {sorted(e['allowedConsumers'])}")


def check_resolver(reg):
    ids = {e["id"]: e for e in reg["entries"]}
    seen = {}
    for row in reg["resolver"]:
        if set(row) != {"target", "finalizedKind", "implementation"}:
            raise GateError(f"resolver row shape invalid: {row!r}")
        key = (row["target"], row["finalizedKind"])
        if key in seen:
            raise GateError(f"resolver duplicate-match for {key}: {seen[key]} and {row['implementation']}")
        if row["implementation"] not in ids:
            raise GateError(f"resolver zero-match: {key} names unknown entry {row['implementation']}")
        if row["implementation"].endswith("-REVOKE"):
            raise GateError(f"resolver may not target a hardening trailer: {row!r}")
        if ids[row["implementation"]]["backend"] != row["target"]:
            raise GateError(f"resolver target/backend mismatch: ({row['target']}, "
                            f"{row['finalizedKind']}) -> {row['implementation']} whose backend is "
                            f"{ids[row['implementation']]['backend']}")
        seen[key] = row["implementation"]
    unresolved = [i for i, e in ids.items()
                  if not i.endswith("-REVOKE") and i not in seen.values()]
    if unresolved:
        raise GateError(f"resolver zero-match: entries unreachable from any (target, kind): {unresolved}")
    for i, e in ids.items():
        if not i.endswith("-REVOKE") and "finalizedKind" not in e:
            raise GateError(f"{i}: acceptance entry lacks finalizedKind")
        if "finalizedKind" in e:
            rows = [k for k, impl in seen.items() if impl == i]
            for target, kind in rows:
                if kind != e["finalizedKind"]:
                    raise GateError(f"resolver wrong-variant: ({target},{kind}) -> {i} whose "
                                    f"finalizedKind is {e['finalizedKind']}")


def check_coupling(reg, overlay):
    ids = {e["id"]: e for e in reg["entries"]}
    for e in reg["entries"]:
        if e["form"] != "reviewed-generator" or e["id"].endswith("-REVOKE"):
            continue
        c = e["revokeCoupling"]
        dep = ids.get(c.get("dependency"))
        if dep is None:
            raise GateError(f"{e['id']}: revokeCoupling names unknown entry {c.get('dependency')!r}")
        if not dep["id"].endswith("-REVOKE"):
            raise GateError(f"{e['id']}: revokeCoupling dependency {dep['id']} is not a -REVOKE entry")
        if c.get("signatureMarker") != dep.get("revokeSignatureMarker"):
            raise GateError(f"{e['id']}: wrong-variant coupling — its signatureMarker does not equal "
                            f"{dep['id']}'s revokeSignatureMarker (wrong overload/function routing)")
        expected_prefix = "REVOKE EXECUTE ON FUNCTION " + e["entryPoint"]
        if dep["revokeFunctionPrefix"] != expected_prefix:
            raise GateError(f"{dep['id']}: revokeFunctionPrefix does not bind the coupled "
                            f"entry point {e['entryPoint']!r} (wrong-function coupling)")
        _p, region = site_region(dep, overlay)
        if REVOKE_LITERAL not in region:
            raise GateError(f"{dep['id']}: its implementation region emits no REVOKE (missing REVOKE)")
        if dep["revokeFunctionPrefix"].encode() not in joined_literals(region):
            raise GateError(f"{dep['id']}: region does not emit its revoked function identity "
                            f"{dep['revokeFunctionPrefix']!r} (wrong-function REVOKE)")
        if c["signatureMarker"].encode() not in joined_literals(region):
            raise GateError(f"{dep['id']}: region does not carry the coupled signature marker "
                            f"{c['signatureMarker']!r} (wrong-overload REVOKE)")
        _ap, aregion = site_region(e, overlay)
        ja = joined_literals(aregion)
        ep = re.escape(e["entryPoint"]).encode()
        op = re.escape(e["dynamicNameOperand"]).encode()
        if not re.search(rb'\.name\s*=\s*"' + ep + rb'"\s*\+\s*' + op + rb"\b", ja):
            raise GateError(f"{e['id']}: guard name construction is not "
                            f"'{e['entryPoint']}' + {e['dynamicNameOperand']} — the emitted "
                            "guard name diverges from the coupled contract")
        jd = joined_literals(region)
        if not re.search(rb"FUNCTION " + ep + rb'"\)\s*\+\s*R\(' + op + rb"\)", jd):
            raise GateError(f"{dep['id']}: REVOKE does not target the same dynamic name "
                            f"construction '{e['entryPoint']}' + R({e['dynamicNameOperand']}) — "
                            "guard and REVOKE identities diverge")


def check_tracked_to_zero(reg, overlay):
    if reg["status"] != "tier2-final":
        return
    for t in reg["trackedToZero"]:
        for probe in t.get("absenceProbes", []):
            for src in _walk("lib/backends", (".cpp", ".h"), overlay):
                if probe.encode() in _read_relative(src, overlay):
                    raise GateError(f"tier2-final: tracked-to-zero identity {probe!r} still present "
                                    f"in {src} ({t['issueRef']})")


def check_core_purity(reg, overlay):
    for src in _walk("lib", (".cpp", ".h"), overlay):
        if src.startswith("lib/backends"):
            continue
        data = _read_relative(src, overlay)
        for e in reg["entries"]:
            if e["id"].encode() in data:
                raise GateError(f"core purity: {src} names backend implementation ID {e['id']} "
                                "(the core never selects an implementation)")


def run_gate(reg, overlay=None):
    check_structure(reg)
    check_identities(reg, overlay)
    check_default_deny(reg, overlay)
    check_consumers(reg, overlay)
    check_resolver(reg)
    check_coupling(reg, overlay)
    check_verifiers(reg)
    check_tracked_to_zero(reg, overlay)
    check_core_purity(reg, overlay)


def build_probes(reg):
    """The biting probe matrix: name -> (needle, mutate, overlay). Shared by --selftest
    (runs all) and --probe <name> (runs one, for the  tamperProbes wiring)."""
    src = "lib/backends/postgres/model/PostgresModel.cpp"
    model = open(os.path.join(REPO, src), "rb").read()
    ri = model.index(b"pgddl::RawSql quorumAcceptRevoke(")

    def entry(r, i):
        return next(e for e in r["entries"] if e["id"] == i)

    def rebank_closures(r, ov):
        for e in r["entries"]:
            if e["form"] == "reviewed-generator":
                e["closureSha256"] = closure_sha256(e["closureFiles"], ov)

    def rebank_all(r, ov):
        """A 'legitimately reviewed' re-bank: closure AND region hashes recomputed over the
        overlay — the adversarial point is that identity binding must survive even this."""
        rebank_closures(r, ov)
        for e in r["entries"]:
            if e["form"] == "reviewed-generator":
                try:
                    _p2, region = site_region(e, ov)
                    e["regionSha256"] = sha256_bytes(region)
                except GateError:
                    pass

    renamed = {src: model.replace(b"PgFunction buildQuorumAcceptGate(",
                                  b"PgFunction buildQuorumAdmitGate(", 1)}
    cloned_in = {src: model + b"\n" + model[ri:ri + 400] + b"\n}\n"}

    def drop_temporal(r):
        r["entries"][:] = [e for e in r["entries"] if "TEMPORAL" not in e["id"]]
        r["resolver"][:] = [w for w in r["resolver"] if "TEMPORAL" not in w["implementation"]]

    probes = {
        "remove-registry-entry": ("default-deny",
            lambda r: r["entries"].__setitem__(
                slice(None), [e for e in r["entries"] if e["id"] != "SOL-QUORUM-BLOB"]), None),
        "unclaimed-generator-site": ("unclaimed reviewed-generator site", drop_temporal, None),
        "blob-hash-drift": ("identity drift",
            lambda r: entry(r, "SOL-QUORUM-BLOB").update(identitySha256="0" * 64), None),
        "identity-or-region-hash-drift": ("implementation-region drift",
            lambda r: entry(r, "PG-QUORUM-SINGLE").update(regionSha256="0" * 64), None),
        "rename-site-anchor-miss": ("renamed/moved/cloned",
            lambda r: rebank_closures(r, renamed), renamed),
        "clone-inside-closure": ("renamed/moved/cloned",
            lambda r: rebank_closures(r, cloned_in), cloned_in),
        "clone-new-site": ("unclaimed reviewed-generator site", None,
            {"lib/backends/postgres/PostgresModelClone.cpp": model[ri:ri + 400]}),
        #  R4: a duplicate closure-file basename in a second role dir must
        # make include resolution AMBIGUOUS (fail closed), so the gate can never
        # hash a different file than the compiler's -I binds. generated/ already
        # holds PostgresPrinterHandlers.inc; injecting a leaf/ twin must bite.
        "ambiguous-sibling-role-include": ("ambiguous package include", None,
            {"lib/backends/postgres/leaf/PostgresPrinterHandlers.inc":
             b"// duplicate basename planted in a second role dir\n"}),
        "new-unregistered-blob": ("default-deny", None,
            {"lib/backends/postgres/Rogue.sql.inc": b"-- rogue reviewed body\n"}),
        "wrong-variant-revoke-routing": ("wrong-variant coupling",
            lambda r: entry(r, "PG-QUORUM-TEMPORAL")["revokeCoupling"].update(
                dependency="PG-QUORUM-SINGLE-REVOKE"), None),
        "drop-revoke-coupling": ("requires revokeCoupling",
            lambda r: entry(r, "PG-QUORUM-TEMPORAL").pop("revokeCoupling"), None),
        "drop-output-verifier": ("missing=",
            lambda r: entry(r, "PG-QUORUM-SINGLE").pop("outputVerifier"), None),
        "resolver-zero-match": ("zero-match",
            lambda r: r["resolver"].__setitem__(
                slice(None), [w for w in r["resolver"]
                              if w["implementation"] != "PG-QUORUM-TEMPORAL"]), None),
        "resolver-zero-or-duplicate-match": ("duplicate-match",
            lambda r: r["resolver"].append(
                {"target": "postgres", "finalizedKind": "QuorumAcceptance.Single",
                 "implementation": "PG-QUORUM-TEMPORAL"}), None),
        "wildcard-scope-widening": ("wildcard/overbroad",
            lambda r: r["entries"].append(dict(
                entry(r, "SOL-QUORUM-BLOB"), id="SOL-ANY",
                artifact="lib/backends/solidity/*")), None),
        "consumer-set-mismatch": ("consumer set mismatch",
            lambda r: entry(r, "SOL-QUORUM-BLOB")["allowedConsumers"].append(
                "lib/backends/solidity/SolidityEmit.cpp"), None),
        "domain-specific-caller": ("consumer set mismatch", None,
            {"lib/backends/solidity/DomainCaller.cpp":
             b'#include "ThresholdQuorumAcceptance.sol.inc"\n'}),
        "outside-reviewed-region": (None, None,
            {"lib/backends/postgres/leaf/PgSqlSyntax.cpp":
             open(os.path.join(REPO, "lib/backends/postgres/leaf/PgSqlSyntax.cpp"), "rb").read()
             + b"\n// ordinary non-security closure edit\n"}),
        "unauthorized-generator-caller": ("generator caller set mismatch", None,
            {"lib/backends/postgres/EvilCaller.cpp":
             b"void evil() { (void)buildQuorumAcceptGate; buildQuorumAcceptGate(x, y, z); }\n"}),
        "rebanked-wrong-function": ("does not emit its revoked function identity",
            None, None),  # constructed below: needs the mutated overlay before rebank
        "inert-output-verifier": ("inert evidence",
            lambda r: entry(r, "PG-QUORUM-SINGLE").update(outputVerifier=[
                {"path": "lib/backends/postgres/EXTRACTION.md",
                 "invocation": {"surface": "lib/backends/postgres/CMakeLists.txt",
                                "marker": "PostgresModel.cpp"}}]), None),
        "unregistered-verifier": ("invocation marker",
            lambda r: entry(r, "PG-QUORUM-SINGLE").update(outputVerifier=[
                {"path": "test/backend-guard/oracle_delivery/quorum_fail_closed_db_test.sh",
                 "invocation": {"surface": "Makefile",
                                "marker": "quorum_fail_closed_db_test.sh"}}]), None),
        "masquerading-registered-verifier": ("cannot be its own evidence",
            lambda r: entry(r, "PG-QUORUM-SINGLE").update(outputVerifier=[
                {"path": "scripts/gates/check_security_primitive_carveout.py",
                 "invocation": {"surface": "cmake/NeutrinoTests.cmake",
                                "marker": "check_security_primitive_carveout.py"}}]), None),
        # A genuinely REGISTERED verifier (its invocation marker is present in a live surface) that
        # nonetheless does not reference THIS primitive's identity must be rejected at the content
        # check, not the earlier marker-presence check. Pinned to golden_diff.cmake — the stable,
        # always-invoked golden harness (cmake/NeutrinoArtifactTests.cmake:110). (Was
        # fields_security.cmake, whose sole invocation — the merchant_sponsored_installment security
        # golden — was retired when that domain was externalized in /be5d2a61, leaving the marker
        # orphaned; see .)
        "unrelated-registered-verifier": ("does not reference this primitive's output identity",
            lambda r: entry(r, "PG-QUORUM-SINGLE").update(outputVerifier=[
                {"path": "test/cmake/golden_diff.cmake",
                 "invocation": {"surface": "cmake/NeutrinoArtifactTests.cmake",
                                "marker": "golden_diff.cmake"}}]), None),
        "resolver-target-mismatch": ("target/backend mismatch",
            lambda r: ([w.update(implementation=("PG-EXECUTION-ENVELOPE"
                                                  if w["implementation"] == "SOL-EXECUTION-ENVELOPE"
                                                  else "SOL-EXECUTION-ENVELOPE"))
                        for w in r["resolver"]
                        if w["finalizedKind"] == "CoordinationEnvelope.Digest"], None)[1], None),
        "empty-security-tests": ("at least one requiredSecurityTests",
            lambda r: entry(r, "SOL-EXECUTION-ENVELOPE").update(requiredSecurityTests=[]), None),
        "final-with-pending": ("non-empty pendingClassification",
            lambda r: (r.update(status="tier2-final"),
                       r["pendingClassification"].append(
                           {"artifact": "lib/backends/postgres/CoordinationEnvelope.sql.inc",
                            "identitySha256": "9ef77a1d27611bbb45a40b1502c4c6da5e3869957f4bf48ac453ad6dea3b971d",
                            "consumers": [],
                            "question": "probe: a lingering pending record in a final registry"})), None),
        "final-tracked-to-zero-present": ("still present",
            lambda r: (r.update(status="tier2-final"),
                       r["trackedToZero"].append(
                           {"artifact": "probe: synthetic residue",
                            "disposition": "probe: mechanism must bite on a present residue",
                            "issueRef": "probe",
                            "absenceProbes": ["pgddl::RawSql quorumAcceptRevoke("]})), None),
    }
    # rebanked-wrong-function: rename the revoked function inside the single-revoke region to
    # evil_, then LEGITIMATELY re-bank every closure/region hash over the mutated tree — the
    # gate must still fail because the region no longer emits the coupled function identity.
    ri2 = model.index(b"pgddl::RawSql quorumAcceptRevoke(")
    rj2 = model.index(b"\n}\n", ri2) + 3
    evil_region = model[ri2:rj2].replace(b"accept_", b"evil_")
    evil_overlay = {src: model[:ri2] + evil_region + model[rj2:]}
    probes["rebanked-wrong-function"] = (
        "does not emit its revoked function identity",
        lambda r: rebank_all(r, evil_overlay), evil_overlay)
    # round-3: the GUARD emits accept_evil_<name> while the trailer still revokes
    # accept_<name>; every hash legitimately re-banked — the construction binding must bite.
    gi = model.index(b'gate.name = "accept_" + name;')
    diverged = {src: model[:gi] + b'gate.name = "accept_evil_" + name;'
                + model[gi + len(b'gate.name = "accept_" + name;'):]}
    probes["rebanked-guard-name-divergence"] = (
        "guard name construction",
        lambda r: rebank_all(r, diverged), diverged)
    inside = {
        src: model.replace(b'gate.name = "accept_" + name;',
                           b'gate.name = "accept_mutated_" + name;', 1)
    }
    probes["inside-reviewed-region"] = (
        "implementation-region drift", None, inside)
    return probes


def run_probe(reg, name, needle, mutate, overlay):
    r = copy.deepcopy(reg)
    if mutate:
        mutate(r)
    try:
        run_gate(r, overlay)
        if needle is None:
            return True, "passed as required"
        return False, "unexpectedly passed"
    except GateError as err:
        if needle is None:
            return False, str(err)
        return needle in str(err), str(err)


def selftest(reg):
    cases = []
    for name, (needle, mutate, overlay) in build_probes(reg).items():
        bit, detail = run_probe(reg, name, needle, mutate, overlay)
        cases.append((name, bit, detail[:90]))
    ok = all(p for _n, p, _d in cases)
    for name, passed, detail in cases:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}: {detail}")
    print(f"SELFTEST: {'PASS' if ok else 'FAIL'} ({len(cases)} probes)")
    return 0 if ok else 1


def main():
    # : the closure derivation spans the build tree, so the gate needs the
    # configured build directory. Same argv style as the rest of this gate.
    global BUILD_DIR
    if "--build-dir" in sys.argv:
        BUILD_DIR = sys.argv[sys.argv.index("--build-dir") + 1]
    else:
        BUILD_DIR = os.environ.get("NEUTRINO_BUILD_DIR", "")
    if not BUILD_DIR:
        raise GateError(
            "--build-dir is required (or $NEUTRINO_BUILD_DIR): since  the "
            "generated .inc are build products, and deriving a closure without "
            "them would silently shrink it rather than fail")
    with open(REGISTRY) as f:
        reg = json.load(f)
    if "--probe" in sys.argv:
        name = sys.argv[sys.argv.index("--probe") + 1]
        probes = build_probes(reg)
        if name not in probes:
            print(f"unknown probe {name!r}", file=sys.stderr)
            return 2
        run_gate(reg)  # the live gate must hold before a tamper means anything
        needle, mutate, overlay = probes[name]
        bit, detail = run_probe(reg, name, needle, mutate, overlay)
        if bit:
            print(f"probe-failed-as-expected:{name} ({detail[:100]})")
            return 1
        print(f"probe DID NOT bite for the intended reason: {name}: {detail[:160]}",
              file=sys.stderr)
        return 0
    if "--selftest" in sys.argv:
        run_gate(reg)
        return selftest(reg)
    run_gate(reg)
    print(f"PASS: carve-out registry OK ({len(reg['entries'])} entries; "
          f"{len(reg['pendingClassification'])} pending [{reg['status']}]; resolver "
          f"{len(reg['resolver'])} rows; identities/regions, default-deny blob+site sweep, "
          "exact consumers, signature-level guard->REVOKE coupling, core purity verified)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except GateError as err:
        print(f"BLOCK: {err}", file=sys.stderr)
        sys.exit(1)

#!/usr/bin/env python3
""" deterministic below-waist semantic-authority hard gate.

The live tree must have an empty finding set. Discovery and all negative
controls fail closed.

The governed backend denominator is derived from TargetRegistry.def:
scenario-bearing value-lowering targets are exactly (gated && !scenarioFree),
and their committed target profiles must reconcile.  Security exceptions are
not duplicated here: the exact  registry is verified and its exact-body
artifacts / anchored reviewed-generator regions are the only excluded bytes.
"""

import argparse
import glob
import importlib.util
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TARGET_REGISTRY = "include/Neutrino/TargetRegistry.def"
PROFILE_DIR = "examples/target-profiles"
EXTERNAL_BACKEND_MANIFESTS = {
    "solidity": "packaging/solidity/extraction-manifest.json",
}
CARVEOUT_GATE = "scripts/gates/check_security_primitive_carveout.py"
CARVEOUT_REGISTRY = "docs/security-primitive-carveout-registry.json"
REPORT_SCHEMA = "docs/schemas/semantic-authority-report.schema.json"

_ORDINARY_ROW = re.compile(
    r'^\s*NEUTRINO_TARGET\(\s*"([^"]+)"\s*,\s*([A-Za-z_]\w*|nullptr)\s*,'
    r'\s*/\*gated=\*/\s*(true|false)\s*,'
    r'\s*/\*scenarioFree=\*/\s*(true|false)\s*\)\s*$')
_DRIVER_ROW = re.compile(
    r'^\s*NEUTRINO_TARGET_DRIVER\(\s*"([^"]+)"\s*,'
    r'\s*/\*gated=\*/\s*(true|false)\s*,'
    r'\s*/\*scenarioFree=\*/\s*(true|false)\s*\)\s*$')
_SOURCE_EXTS = (".c", ".cc", ".cpp", ".h", ".hh", ".hpp", ".inc", ".td")
_COMMENTS = re.compile(r"//[^\n]*|/\*[\s\S]*?\*/")

_PLAN_TYPES = {
    "AttestationPolicy", "LifecycleTransitionPolicy", "PlanEffect",
    "PlanEffectGroup",
}
_SEMANTIC_FIELD_PATTERN = (
    r"applicationMode|balanceAssertions|canonicalization|"
    r"compensationObligations|evidenceStyle|executionMode|fallback|"
    r"finalizedKind|gateMode|gated|guardKind|ledgerPostings|memo|"
    r"mustBalance|policies|primitiveObligations|projectedLifecycleRoles|"
    r"quorumM|replayRequired|rollbackRequired|terminalKind|workflowKey"
)
_SEMANTIC_CONDITION = re.compile(
    rf"\b(?:{_SEMANTIC_FIELD_PATTERN})\b", re.IGNORECASE)
_SEMANTIC_FIELD_ACCESS = re.compile(
    rf"(?:\.|->)\s*(?:{_SEMANTIC_FIELD_PATTERN})\b", re.IGNORECASE)
_CONTROL_WRAPPER_CALL = re.compile(
    r"\b(?:(?:[A-Za-z_]\w*)::)*projection_driver::"
    r"(?:when|choose|require)\s*\(")
_HARNESS_ROLE = re.compile(
    r"set_source_files_properties\(\s*([A-Za-z0-9_./+-]+)\s+PROPERTIES\s+"
    r"NEUTRINO_SEMANTIC_AUTHORITY_ROLE\s+"
    r"(?:scenario-harness|test-harness)\s*\)", re.MULTILINE)
_DOMAIN_DISPATCH = re.compile(
    r"\b(?:if|switch|while)\s*\([^)]*\b(?:concept|domain|feature|semantic)"
    r"(?:Id|Name|Kind)?\b[^)]*\)|"
    r"\b(?:concept|domain|feature|semantic)(?:Id|Name|Kind)?\b\s*"
    r"(?:==|!=|\.compare\s*\()",
    re.IGNORECASE,
)
_TABLE_DECISION = re.compile(
    r"\b(?:class|def)\s+\w*(?:Decision|Fallback|Selector|SemanticDispatch)\w*\b",
    re.IGNORECASE,
)
_TABLE_TYPED_FIELD = re.compile(
    r"\b(?:bit|string|int|list\s*<[^>]+>)\s+([A-Za-z_]\w*)")
_TABLE_FIELD_ASSIGNMENT = re.compile(r"\b([A-Za-z_]\w*)\s*=")
_TABLE_SEMANTIC_NAME = re.compile(
    r"(?:attest|balance|commit|compensat|concept|direction|domain|effect|"
    r"evidence|fallback|gate|guard|ledger|lifecycle|memo|obligation|policy|"
    r"primitive|quorum|replay|semantic|terminal|workflow)",
    re.IGNORECASE,
)
PROBES = (
    "direct-plan-read",
    "plan-auto-alias",
    "plan-type-alias",
    "backend-semantic-branch",
    "projected-local-alias",
    "projected-helper-alias",
    "projected-control-wrapper",
    "authenticated-harness-role",
    "nontest-executable-scanned",
    "registered-target-adapter",
    "adapter-helper-return",
    "flattened-parameter-flow",
    "domain-concept-dispatch",
    "decision-in-table",
    "neutral-table-fields",
    "omitted-backend",
    "copied-moved-carveout",
    "empty-discovery",
    "optional-slot-handwritten-presence",
    "tainted-guard-selects-value",
    "tainted-continue-suppresses-emission",
)


class DiscoveryError(RuntimeError):
    pass


def _disk_read(rel):
    with open(os.path.join(REPO, rel), encoding="utf-8", errors="replace") as f:
        return f.read()


class SourceTree:
    """A tiny overlay filesystem used by the detector self-tests."""

    def __init__(self, overlay=None):
        self.overlay = dict(overlay or {})

    def exists(self, rel):
        if rel in self.overlay:
            return self.overlay[rel] is not None
        return os.path.isfile(os.path.join(REPO, rel))

    def read(self, rel):
        if rel in self.overlay:
            if self.overlay[rel] is None:
                raise FileNotFoundError(rel)
            return self.overlay[rel]
        return _disk_read(rel)

    def files(self, prefix, extensions):
        found = {
            os.path.relpath(p, REPO).replace(os.sep, "/")
            for p in glob.glob(os.path.join(REPO, prefix, "**"), recursive=True)
            if os.path.isfile(p) and p.endswith(extensions)
        }
        for rel, value in self.overlay.items():
            if rel.startswith(prefix.rstrip("/") + "/") and rel.endswith(extensions):
                if value is None:
                    found.discard(rel)
                else:
                    found.add(rel)
        return sorted(found)


def parse_registry(tree):
    rows = []
    for raw in tree.read(TARGET_REGISTRY).splitlines():
        m = _ORDINARY_ROW.match(raw)
        if m:
            rows.append({
                "target": m.group(1), "entryPoint": m.group(2),
                "gated": m.group(3) == "true",
                "scenarioFree": m.group(4) == "true",
                "driverSerialized": False,
            })
            continue
        m = _DRIVER_ROW.match(raw)
        if m:
            rows.append({
                "target": m.group(1), "entryPoint": None,
                "gated": m.group(2) == "true",
                "scenarioFree": m.group(3) == "true",
                "driverSerialized": True,
            })
            continue
        stripped = raw.strip()
        if (stripped.startswith(("NEUTRINO_TARGET(", "NEUTRINO_TARGET_DRIVER("))
                and '"' in stripped):
            raise DiscoveryError(f"unparsed target registry row: {stripped}")
    if not rows:
        raise DiscoveryError("target registry discovery is empty")
    names = [r["target"] for r in rows]
    if len(names) != len(set(names)):
        raise DiscoveryError("target registry contains duplicate target rows")
    return rows


def governed_backends(tree):
    rows = parse_registry(tree)
    for target, rel in sorted(EXTERNAL_BACKEND_MANIFESTS.items()):
        try:
            manifest = json.loads(tree.read(rel))
        except (ValueError, TypeError, FileNotFoundError) as exc:
            raise DiscoveryError(f"invalid external backend manifest {rel}: {exc}")
        expected_kind = f"neutrino.{target}-extraction-manifest/1"
        if manifest.get("kind") != expected_kind:
            raise DiscoveryError(
                f"external backend manifest kind mismatch: {rel}")
        profile = f"{PROFILE_DIR}/{target}.target-profile.json"
        owned = {
            entry.get("path")
            for entry in manifest.get("groups", {}).get("testsAndFixtures", [])
            if isinstance(entry, dict)
        }
        if profile not in owned:
            raise DiscoveryError(
                f"external backend manifest omits exact profile: {profile}")
        if any(row["target"] == target for row in rows):
            raise DiscoveryError(
                f"external backend also has a built-in registry row: {target}")
        rows.append({
            "target": target,
            "entryPoint": None,
            "gated": True,
            "scenarioFree": False,
            "driverSerialized": True,
            "externalPackage": True,
        })
    governed = [r for r in rows if r["gated"] and not r["scenarioFree"]]
    if not governed:
        raise DiscoveryError("governed backend discovery is empty")
    profile_files = tree.files(PROFILE_DIR, (".target-profile.json",))
    profiles = {}
    for rel in profile_files:
        try:
            obj = json.loads(tree.read(rel))
        except (ValueError, TypeError) as exc:
            raise DiscoveryError(f"invalid target profile {rel}: {exc}")
        target = obj.get("target")
        stem = os.path.basename(rel).removesuffix(".target-profile.json")
        if target != stem:
            raise DiscoveryError(f"profile target mismatch: {rel}")
        if target in profiles:
            raise DiscoveryError(f"duplicate target profile: {target}")
        profiles[target] = rel
    expected = {r["target"] for r in governed}
    if set(profiles) != expected:
        raise DiscoveryError(
            f"profile/registry drift: profiles={sorted(profiles)} "
            f"governed={sorted(expected)}")
    for row in governed:
        row = dict(row)
        row["profile"] = profiles[row["target"]]
        yield row


def _load_carveout_module():
    path = os.path.join(REPO, CARVEOUT_GATE)
    spec = importlib.util.spec_from_file_location("_semantic_authority_carveout", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verified_carveouts(tree):
    """Return exact excluded byte regions after the authoritative  gate passes."""
    gate = _load_carveout_module()
    registry = json.loads(tree.read(CARVEOUT_REGISTRY))
    overlay = {
        rel: (None if value is None else value.encode())
        for rel, value in tree.overlay.items()
        if rel.startswith("lib/backends/")
    }
    gate.run_gate(registry, overlay or None)
    whole_files = set()
    regions = {}
    for entry in registry["entries"]:
        if entry["form"] == "exact-body":
            whole_files.add(entry["artifact"])
            continue
        rel, region = gate.site_region(entry, overlay or None)
        regions.setdefault(rel, []).append(region.decode("utf-8", errors="replace"))
    return registry, whole_files, regions


def _without_comments(text):
    return _COMMENTS.sub(lambda m: "\n" * m.group(0).count("\n"), text)


def _without_carveout_regions(rel, text, regions):
    for region in regions.get(rel, ()):
        if text.count(region) != 1:
            raise DiscoveryError(f" region identity is not unique in {rel}")
        text = text.replace(region, "\n" * region.count("\n"), 1)
    return text


def _symbol_at(text, offset):
    prefix = text[:offset]
    signatures = list(re.finditer(
        r"(?:^|\n)\s*(?:[\w:<>,*&]+\s+)+([A-Za-z_]\w*(?:::\w+)*)\s*"
        r"\([^;{}]*\)\s*(?:const\s*)?\{", prefix))
    return signatures[-1].group(1) if signatures else "<file>"


def _evidence(text, start, end):
    return re.sub(r"\s+", " ", text[start:end].strip())[:180]


def _finding(authority_class, rel, symbol, rule, evidence):
    return {
        "authorityClass": authority_class,
        "path": rel,
        "symbol": symbol,
        "rule": rule,
        "evidence": evidence,
    }


def _mask_cpp_literals(text):
    chars = list(text)
    quote = None
    escaped = False
    for index, char in enumerate(text):
        if quote is None:
            if char in {'"', "'"}:
                quote = char
                chars[index] = " "
            continue
        if char != "\n":
            chars[index] = " "
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == quote:
            quote = None
    return "".join(chars)


def _function_regions(code):
    masked = _mask_cpp_literals(code)
    signature = re.compile(
        r"(?:^|\n)\s*(?:[\w:<>,*&]+\s+)+"
        r"([A-Za-z_]\w*(?:::\w+)*)\s*\([^;{}]*\)\s*"
        r"(?:const\s*)?(?:noexcept\s*)?\{")
    regions = []
    for match in signature.finditer(masked):
        start = match.end() - 1
        depth = 0
        end = None
        for offset in range(start, len(masked)):
            if masked[offset] == "{":
                depth += 1
            elif masked[offset] == "}":
                depth -= 1
                if depth == 0:
                    end = offset + 1
                    break
        if end is not None:
            regions.append((match.group(1), start, end, masked[start:end]))
    return regions


def _function_definitions(rel, text):
    code = _without_comments(text)
    masked = _mask_cpp_literals(code)
    signature = re.compile(
        r"(?:^|\n)\s*(?:[\w:<>,*&]+\s+)+"
        r"([A-Za-z_]\w*(?:::\w+)*)\s*\(([^;{}]*)\)\s*"
        r"(?:const\s*)?(?:noexcept\s*)?\{")
    definitions = []
    for match in signature.finditer(masked):
        body_start = match.end() - 1
        depth = 0
        body_end = None
        for offset in range(body_start, len(masked)):
            if masked[offset] == "{":
                depth += 1
            elif masked[offset] == "}":
                depth -= 1
                if depth == 0:
                    body_end = offset + 1
                    break
        if body_end is None:
            continue
        parameters = []
        parameter_types = []
        for raw in match.group(2).split(","):
            raw = raw.split("=", 1)[0].strip()
            names = re.findall(r"\b([A-Za-z_]\w*)\b", raw)
            if names and names[-1] not in {"const", "void"}:
                parameters.append(names[-1])
                parameter_types.append(raw[:raw.rfind(names[-1])])
            else:
                parameters.append(None)
                parameter_types.append(raw)
        definitions.append({
            "rel": rel,
            "name": match.group(1),
            "parameters": parameters,
            "parameterTypes": parameter_types,
            "signatureStart": match.start(),
            "bodyStart": body_start,
            "bodyEnd": body_end,
            "code": code,
            "masked": masked,
        })
    return definitions


def _semantic_helpers(texts):
    regions = [
        region
        for text in texts
        for region in _function_regions(_without_comments(text))
    ]
    helpers = {
        name for name, _start, _end, body in regions
        if _SEMANTIC_FIELD_ACCESS.search(body)
    }
    changed = True
    while changed:
        changed = False
        spellings = {name for helper in helpers
                     for name in (helper, helper.rsplit("::", 1)[-1])}
        for name, _start, _end, body in regions:
            if name in helpers:
                continue
            if any(re.search(rf"\b{re.escape(helper)}\s*\(", body)
                   for helper in spellings):
                helpers.add(name)
                changed = True
    return {
        name for helper in helpers
        for name in (helper, helper.rsplit("::", 1)[-1])
    }


def _projection_return_helpers(prepared):
    """Find helpers whose return value carries projection-derived control."""
    definitions = [
        definition
        for rel, text in prepared
        for definition in _function_definitions(rel, text)
    ]
    helpers = set()
    changed = True
    while changed:
        changed = False
        spellings = {
            name for helper in helpers
            for name in (helper, helper.rsplit("::", 1)[-1])
        }
        for definition in definitions:
            name = definition["name"]
            if name in helpers:
                continue
            code = definition["code"]
            body_start = definition["bodyStart"]
            body_end = definition["bodyEnd"]
            function = code[definition["signatureStart"]:body_end]
            projection_vars = _projection_vars(
                function, _projection_type_names(code))
            body = code[body_start:body_end]
            for returned in re.finditer(r"\breturn\s+([^;]+);", body):
                expression = returned.group(1)
                prefix = body[:returned.start()]
                locals_ = _projection_tainted_locals(
                    prefix, projection_vars)
                direct = any(re.search(
                    rf"\b{re.escape(var)}\s*(?:\.|->)\s*"
                    r"[A-Za-z_]\w*", expression)
                    for var in projection_vars)
                alias = any(re.search(
                    rf"\b{re.escape(item)}\b", expression)
                    for item in locals_)
                helper = any(re.search(
                    rf"\b{re.escape(item)}\s*\(", expression)
                    for item in spellings)
                if direct or alias or helper:
                    helpers.add(name)
                    changed = True
                    break
    return {
        name for helper in helpers
        for name in (helper, helper.rsplit("::", 1)[-1])
    }


def _tainted_locals(prefix, helpers, seeds=()):
    assignments = list(re.finditer(
        r"\b([A-Za-z_]\w*)\s*=(?!=)\s*([^;]+);", prefix))
    tainted = set(seeds)
    changed = True
    while changed:
        changed = False
        for match in assignments:
            name, rhs = match.group(1), match.group(2)
            if name in tainted:
                continue
            direct = bool(_SEMANTIC_FIELD_ACCESS.search(rhs))
            helper = any(re.search(rf"\b{re.escape(item)}\s*\(", rhs)
                         for item in helpers)
            alias = any(re.search(rf"\b{re.escape(item)}\b", rhs)
                        for item in tainted)
            if direct or helper or alias:
                tainted.add(name)
                changed = True
    return tainted


def _projection_type_names(code):
    cpp_type_name = r"(?:::)?(?:[A-Za-z_]\w*::)*[A-Za-z_]\w*"
    types = {"BackendProjectionGraph", "CoordinationPlan"}
    aliases = re.findall(
        rf"\busing\s+([A-Za-z_]\w*)\s*=\s*({cpp_type_name})\s*;", code)
    aliases += [
        (alias, source) for source, alias in re.findall(
            rf"\btypedef\s+({cpp_type_name})\s+([A-Za-z_]\w*)\s*;", code)
    ]
    changed = True
    while changed:
        changed = False
        for alias, source in aliases:
            if (source in types
                    or source.rsplit("::", 1)[-1] in types):
                if alias not in types:
                    types.add(alias)
                    changed = True
    return types


def _projection_vars(code, type_names=None):
    variables = set()
    for typename in type_names or _projection_type_names(code):
        variables |= set(re.findall(
            rf"\b(?:const\s+)?(?:[A-Za-z_]\w*::)*"
            rf"{re.escape(typename)}\s*"
            r"(?:const\s*)?[&*]+\s*([A-Za-z_]\w*)", code))
    aliases = re.findall(
        r"\b(?:const\s+)?auto\s*(?:const\s*)?(?:[&*]+\s*)?"
        r"([A-Za-z_]\w*)\s*=\s*&?\s*([A-Za-z_]\w*)\s*;", code)
    changed = True
    while changed:
        changed = False
        for alias, source in aliases:
            if source in variables and alias not in variables:
                variables.add(alias)
                changed = True
    return variables


def _projection_tainted_locals(prefix, projection_vars, seeds=()):
    assignments = list(re.finditer(
        r"\b([A-Za-z_]\w*)\s*=(?!=)\s*([^;]+);", prefix))
    tainted = set(seeds)
    changed = True
    while changed:
        changed = False
        for match in assignments:
            name, rhs = match.group(1), match.group(2)
            if name in tainted:
                continue
            direct = any(re.search(
                rf"\b{re.escape(var)}\s*(?:\.|->)\s*[A-Za-z_]\w*", rhs)
                for var in projection_vars)
            alias = any(re.search(rf"\b{re.escape(item)}\b", rhs)
                        for item in tainted)
            if direct or alias:
                tainted.add(name)
                changed = True
    return tainted


def _first_call_argument(code, masked, open_paren):
    """Return the first argument and complete call extent for a balanced call."""
    parens = 1
    brackets = 0
    braces = 0
    first_end = None
    for offset in range(open_paren + 1, len(masked)):
        char = masked[offset]
        if char == "(":
            parens += 1
        elif char == ")":
            parens -= 1
            if parens == 0:
                end = first_end if first_end is not None else offset
                return code[open_paren + 1:end], offset + 1
        elif char == "[":
            brackets += 1
        elif char == "]":
            brackets = max(0, brackets - 1)
        elif char == "{":
            braces += 1
        elif char == "}":
            braces = max(0, braces - 1)
        elif (char == "," and parens == 1 and brackets == 0
              and braces == 0 and first_end is None):
            first_end = offset
    return None, None


def _call_arguments(code, masked, open_paren):
    parens = 1
    brackets = 0
    braces = 0
    starts = [open_paren + 1]
    arguments = []
    for offset in range(open_paren + 1, len(masked)):
        char = masked[offset]
        if char == "(":
            parens += 1
        elif char == ")":
            parens -= 1
            if parens == 0:
                arguments.append(code[starts[-1]:offset])
                return arguments, offset + 1
        elif char == "[":
            brackets += 1
        elif char == "]":
            brackets = max(0, brackets - 1)
        elif char == "{":
            braces += 1
        elif char == "}":
            braces = max(0, braces - 1)
        elif char == "," and parens == 1 and brackets == 0 and braces == 0:
            arguments.append(code[starts[-1]:offset])
            starts.append(offset + 1)
    return None, None


def _semantic_expression(
        expression, locals_, helpers, allow_semantic_names=True):
    return (
        bool(_SEMANTIC_FIELD_ACCESS.search(expression))
        or (allow_semantic_names
            and bool(_SEMANTIC_CONDITION.search(expression)))
        or any(re.search(rf"\b{re.escape(item)}\b", expression)
               for item in locals_)
        or any(re.search(rf"\b{re.escape(item)}\s*\(", expression)
               for item in helpers)
    )


def _leads_to_refusal(masked):
    """True iff the controlled branch's complete effect is a diagnostic/refusal
    and it selects no target node/value: a bounds/precondition guard that fails
    closed by RETURNING an error. Recognized STRUCTURALLY (the refusal idiom),
    not by whitelisting any function, symbol, or backend path. A branch that
    returns/stores a selected target node or value is not a refusal, and nor is
    a bare `break;`/`continue;`: a control transfer can CONDITIONALLY SUPPRESS a
    later emission, so a tainted guard onto it is a real authority. To be a
    refusal the guard must RETURN the diagnostic directly.

    A `return` branch is a refusal only when EVERY return yields an
    error/diagnostic (`…Error(…)` / `.takeError()`)."""
    returns = re.findall(r"\breturn\b([^;]*);", masked)
    if not returns:
        return False
    diagnostic = re.compile(r"\b\w*[Ee]rror\s*\(|\.\s*takeError\s*\(")
    if not all(diagnostic.search(value) for value in returns):
        return False
    if re.search(
            r"(?:\.|->)\s*(?:append|emplace(?:_back)?|insert|push_back)"
            r"\s*\(", masked):
        return False
    return True


def _semantic_control_use(
        condition, controlled, locals_, helpers, seeds, wrapper=False,
        textual_return=False):
    if not _semantic_expression(
            condition, locals_, helpers,
            allow_semantic_names=not seeds):
        return False
    masked = _mask_cpp_literals(controlled)
    # A guard whose complete branch only produces a diagnostic/refusal selects no
    # semantic behavior (a bounds/precondition check that fails closed), even when
    # its condition is over a projection-derived size. Narrow: only a fully
    # refusing branch is exempt; a branch that selects a node/value is not.
    if _leads_to_refusal(masked):
        return False
    if not seeds or wrapper:
        return True
    if _SEMANTIC_FIELD_ACCESS.search(condition):
        return True
    if re.search(
            r"(?:\.|->)\s*(?:append|emplace(?:_back)?|insert|push_back)"
            r"\s*\(", masked):
        return True
    if (textual_return
            and re.fullmatch(r"\s*return\b[^;]+;\s*", masked)):
        return False
    if re.search(r"\breturn\s*;", controlled):
        return True
    if re.search(r"\breturn\b", masked) and not textual_return:
        return True
    calls = [
        match.group(1)
        for match in re.finditer(
            r"\b([A-Za-z_]\w*(?:::\w+)*)\s*\(", masked)
        if match.group(1) not in {"if", "sizeof", "switch", "while"}
    ]
    return any(
        not call.startswith("std::")
        and call.rsplit("::", 1)[-1]
        not in {"assert", "fail", "llvm_unreachable"}
        for call in calls)


def _controlled_statement(code, masked, start, limit):
    def one_statement(offset):
        while offset < limit and masked[offset].isspace():
            offset += 1
        if offset >= limit:
            return offset
        if masked[offset] != "{":
            semicolon = masked.find(";", offset, limit)
            return limit if semicolon < 0 else semicolon + 1
        depth = 0
        for cursor in range(offset, limit):
            if masked[cursor] == "{":
                depth += 1
            elif masked[cursor] == "}":
                depth -= 1
                if depth == 0:
                    return cursor + 1
        return limit

    end = one_statement(start)
    cursor = end
    while cursor < limit and masked[cursor].isspace():
        cursor += 1
    if masked.startswith("else", cursor):
        end = one_statement(cursor + len("else"))
    return code[start:end]


def _returns_text(definition):
    if definition is None:
        return False
    signature = definition["code"][
        definition["signatureStart"]:definition["bodyStart"]]
    return bool(re.search(r"\b(?:StringRef|std::string|string)\b", signature))


def _tainted_parameters(prepared, helpers):
    definitions = [
        definition
        for rel, text in prepared
        for definition in _function_definitions(rel, text)
    ]
    by_leaf = {}
    for definition in definitions:
        by_leaf.setdefault(
            definition["name"].rsplit("::", 1)[-1], []).append(definition)
    tainted = {
        (definition["rel"], definition["name"]): set()
        for definition in definitions
    }
    calls = []
    call_pattern = re.compile(
        r"\b([A-Za-z_]\w*(?:::\w+)*)\s*\(")
    for rel, text in prepared:
        code = _without_comments(text)
        masked = _mask_cpp_literals(code)
        projection_vars = _projection_vars(code)
        file_definitions = [d for d in definitions if d["rel"] == rel]
        for match in call_pattern.finditer(masked):
            leaf = match.group(1).rsplit("::", 1)[-1]
            callees = by_leaf.get(leaf, ())
            if not callees:
                continue
            open_paren = match.end() - 1
            if any(
                    definition["signatureStart"] <= match.start()
                    < definition["bodyStart"]
                    for definition in file_definitions):
                continue
            arguments, _call_end = _call_arguments(
                code, masked, open_paren)
            if arguments is None:
                continue
            caller = next(
                (definition for definition in file_definitions
                 if definition["bodyStart"] <= match.start()
                 < definition["bodyEnd"]), None)
            calls.append((
                rel, match.start(), arguments, caller, callees, code,
                projection_vars))

    changed = True
    while changed:
        changed = False
        for (_rel, offset, arguments, caller, callees, code,
             projection_vars) in calls:
            caller_seeds = (
                tainted[(caller["rel"], caller["name"])]
                if caller is not None else set())
            prefix_start = caller["bodyStart"] if caller is not None else 0
            locals_ = _projection_tainted_locals(
                code[prefix_start:offset], projection_vars, caller_seeds)
            for callee in callees:
                key = (callee["rel"], callee["name"])
                for index, argument in enumerate(arguments):
                    if index >= len(callee["parameters"]):
                        break
                    parameter = callee["parameters"][index]
                    if (parameter is not None
                            and parameter not in tainted[key]
                            and (
                                any(re.search(
                                    rf"\b{re.escape(var)}\s*(?:\.|->)\s*"
                                    r"[A-Za-z_]\w*", argument)
                                    for var in projection_vars)
                                or any(re.search(
                                    rf"\b{re.escape(item)}\b", argument)
                                    for item in locals_))):
                        tainted[key].add(parameter)
                        changed = True
    return tainted


def scan_cpp(rel, text, semantic_helpers=None, tainted_parameters=None,
             projection_return_helpers=None, external_framing=False):
    findings = []
    code = _without_comments(text)
    helpers = set(semantic_helpers or ()) | _semantic_helpers([text])
    parameter_taint = tainted_parameters or {}
    regions = _function_regions(code)
    definitions = _function_definitions(rel, text)
    masked_code = _mask_cpp_literals(code)
    semantic_surface = bool(re.search(
        r"\b(?:BackendProjectionGraph|CoordinationPlan)\b", code))
    # Resolve simple type aliases before variables.  This is deliberately a
    # fixed point: `using P = CoordinationPlan; using Q = P; const Q &q` is the
    # same authority as the literal spelling, and typedef chains are equivalent.
    cpp_type_name = r"(?:::)?(?:[A-Za-z_]\w*::)*[A-Za-z_]\w*"
    plan_types = {"CoordinationPlan"}
    type_aliases = []
    type_aliases += re.findall(
        rf"\busing\s+([A-Za-z_]\w*)\s*=\s*({cpp_type_name})\s*;", code)
    type_aliases += [
        (alias, source) for source, alias in re.findall(
            rf"\btypedef\s+({cpp_type_name})\s+([A-Za-z_]\w*)\s*;", code)
    ]
    changed = True
    while changed:
        changed = False
        for alias, source in type_aliases:
            source_is_plan = (
                source in plan_types
                or source.rsplit("::", 1)[-1] == "CoordinationPlan"
            )
            if source_is_plan and alias not in plan_types:
                plan_types.add(alias)
                changed = True

    plan_vars = set()
    for typename in sorted(plan_types, key=len, reverse=True):
        escaped = re.escape(typename)
        plan_vars |= set(re.findall(
            rf"\b(?:const\s+)?{escaped}\s*(?:const\s*)?[&*]+\s*"
            r"([A-Za-z_]\w*)", code))

    # Propagate value aliases (including auto references/pointers) to a fixed
    # point. `&p` and `p` are both accepted RHS spellings; chained aliases are
    # handled on later iterations.
    value_aliases = re.findall(
        r"\b(?:const\s+)?auto\s*(?:const\s*)?(?:[&*]+\s*)?"
        r"([A-Za-z_]\w*)\s*=\s*&?\s*([A-Za-z_]\w*)\s*;", code)
    changed = True
    while changed:
        changed = False
        for alias, source in value_aliases:
            if source in plan_vars and alias not in plan_vars:
                plan_vars.add(alias)
                changed = True

    if not external_framing:
        for var in sorted(plan_vars):
            pat = re.compile(
                rf"\b{re.escape(var)}\s*(?:\.|->)\s*([A-Za-z_]\w*)")
            for match in pat.finditer(code):
                field = match.group(1)
                findings.append(_finding(
                    "direct-plan-read", rel, _symbol_at(code, match.start()),
                    "below-waist CoordinationPlan field read",
                    f"{var}.{field}"))
    # A carrier type is not authority by itself: adapters may construct the
    # exact input shape consumed by a reviewed primitive. Reading through a
    # carrier reference/pointer is authority and remains forbidden.
    if semantic_surface and not external_framing:
        for typename in sorted(_PLAN_TYPES):
            carrier_vars = set(re.findall(
                rf"\b(?:const\s+)?{typename}\s*(?:const\s*)?[&*]+\s*"
                r"([A-Za-z_]\w*)", code))
            for var in sorted(carrier_vars):
                for match in re.finditer(
                        rf"\b{re.escape(var)}\s*(?:\.|->)\s*"
                        r"([A-Za-z_]\w*)", code):
                    findings.append(_finding(
                        "direct-plan-read", rel,
                        _symbol_at(code, match.start()),
                        "below-waist semantic carrier field read",
                        f"{var}.{match.group(1)}"))

    source_vars = set()
    for typename in (
            "ProcedureView", "Scenario", "L2DomainArtifact",
            "DomainSemanticsArtifact"):
        source_vars |= set(re.findall(
            rf"\b{typename}\s*(?:const\s*)?[&*]\s*([A-Za-z_]\w*)", code))
        source_vars |= set(re.findall(
            rf"\bconst\s+{typename}\s*[&*]\s*([A-Za-z_]\w*)", code))
    for var in sorted(source_vars):
        for match in re.finditer(
                rf"\b{re.escape(var)}\s*(?:\.|->)\s*"
                r"(attestation\w*|concept\w*|domain\w*|effects?|"
                r"evidence\w*|lifecycle\w*|obligations?|reductions?|"
                r"semantics?\w*)", code, re.IGNORECASE):
            findings.append(_finding(
                "source-or-l2-read", rel, _symbol_at(code, match.start()),
                "below-waist source/scenario field read",
                _evidence(code, match.start(), match.end())))
    for match in re.finditer(
            r"\b(?:L2DomainArtifact|DomainSemanticsArtifact|"
            r"l2DomainSemantics)\b", code):
        findings.append(_finding(
            "source-or-l2-read", rel, _symbol_at(code, match.start()),
            "below-waist source/L2 carrier access", match.group(0)))

    for match in _DOMAIN_DISPATCH.finditer(code):
        findings.append(_finding(
            "domain-concept-dispatch", rel, _symbol_at(code, match.start()),
            "domain/concept identity controls backend behavior",
            _evidence(code, match.start(), match.end())))

    # Projection selection is governed wherever a production source consumes
    # the shared semantic graph/coordination plan. Pure syntax and external-framing helpers
    # do not become semantic surfaces merely because their validation messages
    # contain words such as "memo" or "policy".
    branch = re.compile(r"\b(?:if|while|switch)\s*\(")
    for match in branch.finditer(code):
        containing = next(
            (region for region in regions
             if region[1] <= match.start() < region[2]), None)
        seeds = (
            parameter_taint.get((rel, containing[0]), set())
            if containing is not None else set())
        if semantic_surface or seeds:
            condition, condition_end = _first_call_argument(
                code, masked_code, match.end() - 1)
            if condition is None:
                continue
            prefix = (
                code[containing[1]:match.start()]
                if containing is not None else code[:match.start()])
            expression_helpers = (
                set(projection_return_helpers or ())
                if external_framing else helpers)
            locals_ = _tainted_locals(
                prefix, expression_helpers, seeds)
            controlled_end = (
                containing[2] if containing is not None else len(code))
            controlled = _controlled_statement(
                code, masked_code, condition_end,
                min(controlled_end, condition_end + 1200))
            containing_definition = next(
                (definition for definition in definitions
                 if definition["bodyStart"] <= match.start()
                 < definition["bodyEnd"]), None)
            if _semantic_control_use(
                    condition, controlled, locals_, expression_helpers,
                    seeds,
                    textual_return=_returns_text(containing_definition)):
                findings.append(_finding(
                    "backend-semantic-branch", rel,
                    _symbol_at(code, match.start()),
                    "handwritten branch selects semantic behavior",
                    _evidence(condition, 0, len(condition))))
    for match in re.finditer(r"\?", code):
        containing = next(
            (region for region in regions
             if region[1] <= match.start() < region[2]), None)
        seeds = (
            parameter_taint.get((rel, containing[0]), set())
            if containing is not None else set())
        if semantic_surface or seeds:
            start = max(
                code.rfind(";", 0, match.start()),
                code.rfind("{", 0, match.start()),
                code.rfind("}", 0, match.start()),
            ) + 1
            condition = code[start:match.end()]
            prefix = (
                code[containing[1]:match.start()]
                if containing is not None else code[:match.start()])
            # Ternaries often spell target syntax from an already-finalized
            # helper result. Preserve direct/local projected taint without
            # treating every helper-produced syntax value as semantic control.
            expression_helpers = (
                set(projection_return_helpers or ())
                if external_framing else helpers)
            locals_ = _tainted_locals(prefix, set(), seeds)
            controlled_end = (
                containing[2] if containing is not None else len(code))
            semicolon = masked_code.find(
                ";", match.end(), controlled_end)
            expression_end = (
                controlled_end if semicolon < 0 else semicolon + 1)
            controlled = code[match.start():expression_end]
            containing_definition = next(
                (definition for definition in definitions
                 if definition["bodyStart"] <= match.start()
                 < definition["bodyEnd"]), None)
            if _semantic_control_use(
                    condition, controlled, locals_, expression_helpers,
                    seeds,
                    textual_return=_returns_text(containing_definition)):
                findings.append(_finding(
                    "backend-semantic-branch", rel,
                    _symbol_at(code, match.start()),
                    "handwritten conditional selects semantic behavior",
                    _evidence(condition, 0, len(condition))))
    for match in _CONTROL_WRAPPER_CALL.finditer(masked_code):
        containing = next(
            (region for region in regions
             if region[1] <= match.start() < region[2]), None)
        seeds = (
            parameter_taint.get((rel, containing[0]), set())
            if containing is not None else set())
        if semantic_surface or seeds:
            condition, call_end = _first_call_argument(
                code, masked_code, match.end() - 1)
            if condition is None:
                continue
            prefix = (
                code[containing[1]:match.start()]
                if containing is not None else code[:match.start()])
            expression_helpers = (
                set(projection_return_helpers or ())
                if external_framing else helpers)
            locals_ = _tainted_locals(
                prefix, expression_helpers, seeds)
            if _semantic_control_use(
                    condition, code[match.start():call_end], locals_,
                    expression_helpers, seeds, wrapper=True):
                findings.append(_finding(
                    "backend-semantic-branch", rel,
                    _symbol_at(code, match.start()),
                    "handwritten control wrapper selects semantic behavior",
                    _evidence(code, match.start(), call_end)))
    return findings


def scan_table(rel, text):
    findings = []
    code = _without_comments(text)
    for match in _TABLE_DECISION.finditer(code):
        findings.append(_finding(
            "decision-bearing-table", rel, "<tablegen>",
            "target table carries semantic selection authority",
            _evidence(code, match.start(), match.end())))
    record_starts = list(re.finditer(r"\b(?:class|def)\s+[A-Za-z_]\w*", code))
    for match in _TABLE_TYPED_FIELD.finditer(code):
        name = match.group(1)
        if not _TABLE_SEMANTIC_NAME.search(name):
            continue
        record = next(
            (item for item in reversed(record_starts)
             if item.start() < match.start()), None)
        header = code[record.start():match.end()] if record else ""
        if re.search(r"\bTargetIdiomRecipe\s*<", header):
            continue
        findings.append(_finding(
            "decision-bearing-table", rel, "<tablegen>",
            "semantic typed field is not an approved finalized recipe input",
            name))
    for match in _TABLE_FIELD_ASSIGNMENT.finditer(code):
        name = match.group(1)
        if not _TABLE_SEMANTIC_NAME.search(name):
            continue
        findings.append(_finding(
            "decision-bearing-table", rel, "<tablegen>",
            "target table assigns semantic control or a semantic default",
            name))
    return findings


def _backend_harness_sources(tree, backend):
    root = f"lib/backends/{backend}"
    cmake_rel = f"{root}/CMakeLists.txt"
    if not tree.exists(cmake_rel):
        raise DiscoveryError(f"missing backend build graph: {cmake_rel}")
    cmake = _without_comments(tree.read(cmake_rel))
    roles = {
        f"{root}/{match.group(1)}"
        for match in _HARNESS_ROLE.finditer(cmake)
    }
    #  latent-finding hardening (): the add_executable-derived exclusion is
    # constrained to test/-path sources ONLY. A file can be listed in BOTH an
    # add_library and a test add_executable, so a non-test production .cpp named in
    # an add_executable block must NOT be silently dropped from the  hard gate.
    # Such a non-test source is excluded only when it carries the explicit
    # NEUTRINO_SEMANTIC_AUTHORITY_ROLE property (the authenticated `roles` mechanism
    # above, which already covers the two legitimate non-test harness renderers
    # GenSolidityTest.cpp / PostgresDbTest.cpp). Everything else in an add_executable
    # is only auto-excluded when it actually lives under a test/ path.
    executable_sources = {
        f"{root}/{source}"
        for block in re.findall(
            r"\badd_executable\s*\(([\s\S]*?)\)", cmake)
        for source in re.findall(
            r"\b(?:[A-Za-z0-9_./+-]+)\.(?:c|cc|cpp|h|hh|hpp)\b", block)
        if "test" in source.split("/")
    }
    declared = roles | executable_sources
    missing = sorted(rel for rel in declared if not tree.exists(rel))
    if missing:
        raise DiscoveryError(
            f"backend harness build graph names missing sources: {missing}")
    return declared


def backend_surfaces(tree, backend, entry_point, external_package=False):
    root = f"lib/backends/{backend}"
    errors = []
    try:
        harness_sources = _backend_harness_sources(tree, backend)
    except DiscoveryError as exc:
        harness_sources = set()
        errors.append(_finding(
            "backend-discovery", f"{root}/CMakeLists.txt", "<discovery>",
            "backend harness roles must come from the build graph", str(exc)))
    sources = [
        rel for rel in tree.files(root, _SOURCE_EXTS)
        if rel not in harness_sources
    ]
    target_hits = []
    alternate_hits = []
    if not external_package:
        for rel in tree.files("lib/targets", (".cpp", ".h")):
            text = tree.read(rel)
            if entry_point and re.search(rf"\b{re.escape(entry_point)}\b", text):
                target_hits.append(rel)
            elif (backend.lower() in os.path.basename(rel).lower()
                  or re.search(
                      rf"\bemit{re.escape(backend.title())}[A-Za-z_]\w*\s*\(",
                      _without_comments(text))):
                # Alternate target entries cannot hide merely by avoiding the
                # authoritative EmitFn symbol.
                alternate_hits.append(rel)
    legacy_root = f"lib/{backend}"
    legacy = tree.files(legacy_root, _SOURCE_EXTS)
    if not sources:
        errors.append(_finding(
            "backend-discovery", f"lib/backends/{backend}", "<discovery>",
            "governed backend has no production surface", backend))
    if not external_package and (not entry_point or len(target_hits) != 1):
        errors.append(_finding(
            "backend-discovery", "lib/targets", "<discovery>",
            "governed backend entry is missing, duplicated, or driver-only",
            f"{backend}:{entry_point or '<driver>'}"))
    if alternate_hits:
        errors.append(_finding(
            "backend-discovery", "lib/targets", "<discovery>",
            "alternate legacy target entry remains",
            ",".join(alternate_hits)))
    if legacy:
        errors.append(_finding(
            "backend-discovery", legacy_root, "<discovery>",
            "alternate legacy backend surface remains",
            backend))
    return sorted(set(
        sources + target_hits + alternate_hits + legacy)), errors


def build_report(tree=None, report_only=False):
    # The live CLI no longer exposes report-only mode. Keep the explicit
    # enforcing argument accepted for the convergence gate's classifier API.
    if report_only:
        raise DiscoveryError("report-only semantic authority is retired")
    tree = tree or SourceTree()
    try:
        backends = list(governed_backends(tree))
    except DiscoveryError as exc:
        return {
            "kind": "neutrino.semantic-authority-report",
            "schemaVersion": 1,
            "mode": "enforce",
            "governedBackends": [],
            "carveoutRegistry": CARVEOUT_REGISTRY,
            "backends": {
                "<discovery>": {
                    "profile": None,
                    "surfaces": [],
                    "findings": {
                        "backend-discovery": [{
                            "path": TARGET_REGISTRY, "symbol": "<discovery>",
                            "rule": "governed backend discovery must be non-empty and exact",
                            "evidence": str(exc),
                        }]
                    },
                }
            },
        }

    carveout_error = None
    try:
        _registry, whole_files, regions = verified_carveouts(tree)
    except Exception as exc:  # the imported gate has its own precise GateError
        whole_files, regions = set(), {}
        carveout_error = str(exc)

    grouped = {}
    for backend in sorted(backends, key=lambda item: item["target"]):
        name = backend["target"]
        surfaces, findings = backend_surfaces(
            tree, name, backend["entryPoint"],
            backend.get("externalPackage", False))
        if carveout_error:
            findings.append(_finding(
                "carveout-integrity", CARVEOUT_REGISTRY, "<>",
                "the exact  registry rejected the live/overlay tree",
                carveout_error))
        prepared = []
        for rel in surfaces:
            if rel in whole_files:
                continue
            text = _without_carveout_regions(rel, tree.read(rel), regions)
            prepared.append((rel, text))
        helpers = _semantic_helpers(
            text for rel, text in prepared if not rel.endswith(".td"))
        cpp_prepared = [
            (rel, text) for rel, text in prepared if not rel.endswith(".td")]
        parameter_taint = _tainted_parameters(cpp_prepared, helpers)
        return_helpers = _projection_return_helpers(cpp_prepared)
        for rel, text in prepared:
            findings.extend(
                scan_table(rel, text) if rel.endswith(".td")
                else scan_cpp(
                    rel, text, helpers, parameter_taint,
                    return_helpers,
                    external_framing=rel.startswith("lib/targets/")))
        by_class = {}
        unique = {}
        for finding in findings:
            key = tuple(finding[k] for k in
                        ("authorityClass", "path", "symbol", "rule", "evidence"))
            unique[key] = finding
        for finding in sorted(
                unique.values(),
                key=lambda f: (f["authorityClass"], f["path"], f["symbol"],
                               f["rule"], f["evidence"])):
            item = dict(finding)
            authority_class = item.pop("authorityClass")
            by_class.setdefault(authority_class, []).append(item)
        grouped[name] = {
            "profile": backend["profile"],
            "surfaces": surfaces,
            "findings": {k: by_class[k] for k in sorted(by_class)},
        }
    return {
        "kind": "neutrino.semantic-authority-report",
        "schemaVersion": 1,
        "mode": "enforce",
        "governedBackends": [b["target"] for b in
                             sorted(backends, key=lambda item: item["target"])],
        "carveoutRegistry": CARVEOUT_REGISTRY,
        "backends": grouped,
    }


def finding_classes(report):
    return {
        authority_class
        for backend in report["backends"].values()
        for authority_class, findings in backend["findings"].items()
        if findings
    }


def has_findings(report):
    return bool(finding_classes(report))


def validate_report_shape(report):
    if set(report) != {
            "kind", "schemaVersion", "mode", "governedBackends",
            "carveoutRegistry", "backends"}:
        raise DiscoveryError("report top-level shape drift")
    if report["kind"] != "neutrino.semantic-authority-report":
        raise DiscoveryError("report kind drift")
    if report["schemaVersion"] != 1 or report["mode"] != "enforce":
        raise DiscoveryError("report version/mode drift")
    if sorted(report["governedBackends"]) != sorted(report["backends"]):
        raise DiscoveryError("report backend grouping does not equal discovery")


def _append(tree, rel, addition):
    original = tree.read(rel) if tree.exists(rel) else ""
    overlay = dict(tree.overlay)
    overlay[rel] = original + addition
    return overlay


def selftest(selected=None):
    base = SourceTree()
    cases = []

    def run(name, overlay, expected_class, markers, absent_markers=()):
        if selected is not None and name != selected:
            return
        report = build_report(SourceTree(overlay))
        markers = [markers] if isinstance(markers, str) else list(markers)
        candidates = [
            item for backend in report["backends"].values()
            for authority_class, findings in backend["findings"].items()
            if authority_class == expected_class for item in findings
        ]
        matches = [
            item for item in candidates
            if any(marker in json.dumps(item, sort_keys=True)
                   for marker in markers)
        ]
        bit = all(any(marker in json.dumps(item, sort_keys=True)
                      for item in candidates) for marker in markers)
        bit = bit and all(
            not any(marker in json.dumps(item, sort_keys=True)
                    for item in candidates)
            for marker in absent_markers)
        cases.append((name, bit, [
            f"{expected_class}:{item['path']}:{item['evidence']}" for item in matches
        ]))

    run("direct-plan-read", _append(
        base, "lib/backends/solidity/S0DirectRead.cpp",
        '\nvoid s0(const CoordinationPlan &p) { (void)p.effects; }\n'
        'void s1(const BackendProjectionGraph &, const PlanEffect &effect) { '
        '(void)effect.memo; }\n'),
        "direct-plan-read", ["p.effects", "effect.memo"])
    run("plan-auto-alias", _append(
        base, "lib/backends/solidity/S0AutoAlias.cpp",
        '\nvoid s0(const CoordinationPlan &p) { const auto &q = p; '
        'const auto *r = &p; (void)q.effects; (void)r->effects; }\n'),
        "direct-plan-read", ["q.effects", "r.effects"])
    run("plan-type-alias", _append(
        base, "lib/backends/solidity/S0TypeAlias.cpp",
        '\nusing P = CoordinationPlan;\n'
        'typedef P Q;\n'
        'using QualifiedUsing = neutrino::CoordinationPlan;\n'
        'typedef neutrino::CoordinationPlan QualifiedTypedef;\n'
        'using GlobalUsing = ::neutrino::CoordinationPlan;\n'
        'typedef ::neutrino::CoordinationPlan GlobalTypedef;\n'
        'void s0(const P &p, const Q &q, '
        'const QualifiedUsing &qualifiedUsing, '
        'const QualifiedTypedef &qualifiedTypedef, '
        'const GlobalUsing &globalUsing, '
        'const GlobalTypedef &globalTypedef) { '
        '(void)p.effects; (void)q.effects; '
        '(void)qualifiedUsing.effects; '
        '(void)qualifiedTypedef.effects; '
        '(void)globalUsing.effects; '
        '(void)globalTypedef.effects; }\n'),
        "direct-plan-read", [
            "p.effects", "q.effects", "qualifiedUsing.effects",
            "qualifiedTypedef.effects", "globalUsing.effects",
            "globalTypedef.effects",
        ])
    run("backend-semantic-branch", _append(
        base, "lib/backends/solidity/S0SemanticBranch.cpp",
        '\nvoid s0(const BackendProjectionGraph &proj) { '
        'if (proj.replayRequired) return; }\n'),
        "backend-semantic-branch", "S0SemanticBranch.cpp")
    # : the optional-slot presence extent moved into the generated recipe
    # module; the equivalent HANDWRITTEN read in a provider (memo / guardKind
    # ternary) must still be rejected — so the generated path is not a loophole
    # and the scanner was not weakened when the provider stopped branching.
    run("optional-slot-handwritten-presence", _append(
        base, "lib/backends/solidity/S0OptionalPresence.cpp",
        # A provider file (semantic surface — it names BackendProjectionGraph)
        # that re-adds the handwritten presence read the generator now owns.
        '\nvoid surface(const BackendProjectionGraph &) {}\n'
        'unsigned s0(const projection::FinalizedPostingProjection &posting) '
        '{ return posting.memo.has_value() ? 1u : 0u; }\n'
        'unsigned s1(const projection::FinalizedPostingProjection &posting) '
        '{ return posting.guardKind == '
        'projection::FinalizedPostingGuardKind::Direct ? 1u : 0u; }\n'),
        "backend-semantic-branch", ["posting.memo", "posting.guardKind"])
    # The refusal-recognition exemption is NARROW: a bounds-SHAPED tainted
    # condition whose branch SELECTS a target node/value (not a diagnostic) must
    # still be reported. Only a fully-refusing branch (return recipeError/
    # takeError) is exempt; this one selects an extent, so it must bite — proving
    # the exemption is not a loophole.
    run("tainted-guard-selects-value", _append(
        base, "lib/backends/solidity/S0GuardSelects.cpp",
        '\nvoid surface(const BackendProjectionGraph &) {}\n'
        'unsigned s0(const BackendProjectionGraph &graph, unsigned index) { '
        'if (index >= graph.balanceAssertions.size()) '
        'return graph.balanceAssertions.size(); '
        'return 0u; }\n'),
        "backend-semantic-branch", "graph.balanceAssertions.size()")
    # A tainted `continue` is NOT a refusal: it CONDITIONALLY SUPPRESSES the
    # emission after it (the push_back is skipped on the tainted branch), which
    # is a target-selection authority. It must bite — proving the removed
    # break/continue exemption cannot mask a suppress-by-transfer.
    run("tainted-continue-suppresses-emission", _append(
        base, "lib/backends/solidity/S0ContinueSuppresses.cpp",
        '\nvoid surface(const BackendProjectionGraph &) {}\n'
        'void s0(const BackendProjectionGraph &graph, '
        'std::vector<unsigned> &out) { '
        'for (unsigned i = 0; i < out.size(); ++i) { '
        'if (graph.balanceAssertions[i].suppressed) continue; '
        'out.push_back(i); } }\n'),
        "backend-semantic-branch", "graph.balanceAssertions[i].suppressed")
    run("projected-local-alias", _append(
        base, "lib/backends/solidity/S0LocalAlias.cpp",
        '\nvoid s0(const BackendProjectionGraph &graph) { '
        'bool temporal = graph.executionMode == ExecutionMode::Temporal; '
        'const bool selected = temporal; if (selected) return; '
        'auto rail = selected ? temporalRail() : effectfulRail(); '
        '(void)rail; }\n'),
        "backend-semantic-branch",
        ["selected", "auto rail = selected ?"])
    run("projected-helper-alias", {
        "lib/backends/solidity/S0HelperAlias.cpp":
            '\nbool isTemporal(const BackendProjectionGraph &graph) { '
            'return graph.executionMode == ExecutionMode::Temporal; }\n'
            'bool selectsRail(const BackendProjectionGraph &graph) { '
            'return isTemporal(graph); }\n',
        "lib/backends/solidity/S0HelperCaller.cpp":
            '\nvoid s0(const BackendProjectionGraph &graph) { '
            'if (selectsRail(graph)) return; }\n',
    },
        "backend-semantic-branch", "selectsRail(graph)")
    run("projected-control-wrapper", {
        "lib/backends/solidity/S0ControlHelper.cpp":
            '\nbool selectsRail(const BackendProjectionGraph &graph) { '
            'return graph.executionMode == ExecutionMode::Temporal; }\n',
        "lib/backends/solidity/S0ControlWrapper.cpp":
            '\nvoid s0(const BackendProjectionGraph &graph) { '
            'bool balanced = !graph.balanceAssertions.empty(); '
            'projection_driver::when(balanced, [] { emitBalance(); }); '
            'auto x = projection_driver::choose('
            'graph.executionMode == ExecutionMode::Temporal, '
            'temporal(), effectful()); '
            'projection_driver::require(selectsRail(graph), '
            '[] { failRail(); }); (void)x; }\n',
    },
        "backend-semantic-branch",
        ["projection_driver::when(balanced",
         "projection_driver::choose(",
         "projection_driver::require(selectsRail(graph)"])
    harness_overlay = _append(
        base, "lib/backends/solidity/ProductionTest.cpp",
        '\nvoid production(const BackendProjectionGraph &graph) { '
        'if (graph.executionMode == ExecutionMode::Temporal) return; }\n')
    harness_overlay = _append(
        SourceTree(harness_overlay),
        "lib/backends/solidity/harness/GenSolidityTest.cpp",
        '\nvoid harness(const BackendProjectionGraph &graph) { '
        'if (graph.executionMode == ExecutionMode::Temporal) return; }\n')
    run("authenticated-harness-role", harness_overlay,
        "backend-semantic-branch", "ProductionTest.cpp",
        absent_markers=("GenSolidityTest.cpp",))
    # : a NON-test production source listed in an add_executable block must
    # stay on the scanned surface — the test/-path-constrained exclusion must NOT
    # drop it. This bites for that reason specifically: ProductionExec.cpp is a
    # backend-root (non-test, unauthenticated) file, so with the hardening it is
    # scanned and its direct-plan-read finding is emitted; un-constraining the
    # add_executable exclusion would exclude it and this probe would go silent.
    run("nontest-executable-scanned", {
        "lib/backends/solidity/CMakeLists.txt":
            base.read("lib/backends/solidity/CMakeLists.txt")
            + "\nadd_executable(solidity-production-probe ProductionExec.cpp)\n",
        "lib/backends/solidity/ProductionExec.cpp":
            "\nvoid s0(const CoordinationPlan &p) { (void)p.effects; }\n",
    },
        "direct-plan-read", ["ProductionExec.cpp"])
    run("registered-target-adapter", {
        "lib/targets/SolidityTarget.cpp":
            base.read("lib/targets/SolidityTarget.cpp")
            + '\nvoid targetProbe(const BackendProjectionGraph &graph) { '
              'if (graph.executionMode == ExecutionMode::Temporal) return; }\n',
        "lib/targets/PostgresTarget.cpp":
            base.read("lib/targets/PostgresTarget.cpp")
            + '\nvoid targetProbe(const BackendProjectionGraph &graph) { '
              'if (graph.executionMode == ExecutionMode::Temporal) return; }\n',
    }, "backend-semantic-branch",
        ["lib/targets/PostgresTarget.cpp"])
    run("adapter-helper-return", {
        "lib/backends/solidity/S2AdapterHelper.cpp":
            '\nusing G = ::neutrino::BackendProjectionGraph; '
            'using ChainedG = G;\n'
            'bool adapterRailUsing(const ChainedG &graph) { '
            'return graph.replayRequired; }\n',
        "lib/backends/postgres/S2AdapterHelper.cpp":
            '\ntypedef neutrino::BackendProjectionGraph G; '
            'typedef G ChainedG;\n'
            'bool adapterRailTypedef(const ChainedG &graph) { '
            'return graph.replayRequired; }\n',
        "lib/targets/SolidityTarget.cpp":
            base.read("lib/targets/SolidityTarget.cpp")
            + '\nusing G = ::neutrino::BackendProjectionGraph;\n'
              'void targetHelperUsingProbe(const G &graph) { '
              'if (adapterRailUsing(graph)) return; }\n',
        "lib/targets/PostgresTarget.cpp":
            base.read("lib/targets/PostgresTarget.cpp")
            + '\ntypedef neutrino::BackendProjectionGraph G;\n'
              'void targetHelperTypedefProbe(const G &graph) { '
              'if (adapterRailTypedef(graph)) return; }\n',
    }, "backend-semantic-branch",
        ["lib/targets/PostgresTarget.cpp",
         "adapterRailTypedef(graph)"])
    run("flattened-parameter-flow", {
        "lib/backends/solidity/S0FlattenedCaller.cpp":
            '\nvoid call(const BackendProjectionGraph &graph) { '
            'emitMode(static_cast<int>(graph.executionMode)); '
            'selectMode(graph.executionMode); '
            'buildStringMode(toString(graph.executionMode)); '
            'returnStringMode(toString(graph.executionMode)); }\n',
        "lib/backends/solidity/S0FlattenedInteger.cpp":
            '\nvoid emitMode(int mode) { '
            'switch (mode) { default: emitModeRail(); } }\n',
        "lib/backends/solidity/S0FlattenedEnum.cpp":
            '\nvoid selectMode(ExecutionMode mode) { '
            'if (mode == ExecutionMode::Temporal) emitTemporalRail(); }\n',
        "lib/backends/solidity/S0FlattenedStringBuild.cpp":
            '\nvoid buildStringMode(const std::string &mode) { '
            'if (mode == "temporal") buildTemporal(); '
            'else assembleEvidence(); }\n',
        "lib/backends/solidity/S0FlattenedStringReturn.cpp":
            '\nvoid returnStringMode(const std::string &mode) { '
            'if (mode == "temporal") return; '
            'buildDefault(); }\n',
    }, "backend-semantic-branch",
        ["S0FlattenedInteger.cpp",
         "S0FlattenedEnum.cpp",
         "S0FlattenedStringBuild.cpp",
         "S0FlattenedStringReturn.cpp"])
    run("domain-concept-dispatch", _append(
        base, "lib/backends/solidity/S0Concept.cpp",
        '\nvoid s0(std::string conceptId) { if (conceptId == "invoice") return; }\n'),
        "domain-concept-dispatch", "S0Concept.cpp")
    run("decision-in-table", _append(
        base, "lib/backends/solidity/model/SolidityTargetNodes.td",
        '\nclass S0Decision<bit decision>;\ndef S0Fallback : S0Decision<1>;\n'),
        "decision-bearing-table", "S0Decision")
    run("neutral-table-fields", _append(
        base, "lib/backends/solidity/model/SolidityTargetNodes.td",
        '\nclass TargetIdiomRecipe<list<int> ledgerPostings, '
        'bit mustBalance>;\n'
        'class UnregisteredRecipe<string lifecycleMode>;\n'
        'class RecipeFallback<bit predicate>;\n'
        'def BadFallback : RecipeFallback<1> { '
        'let replayRequired = 1; }\n'),
        "decision-bearing-table",
        ["lifecycleMode", "RecipeFallback", "BadFallback", "replayRequired"],
        absent_markers=("ledgerPostings", "mustBalance"))

    registry = base.read(TARGET_REGISTRY)
    insert = (
        '\nNEUTRINO_TARGET("s0missing", emitS0MissingProject, '
        '/*gated=*/true, /*scenarioFree=*/false)\n')
    profile = json.dumps({
        "kind": "neutrino.target-profile", "schemaVersion": 1,
        "profileId": "target.s0missing.v1", "target": "s0missing",
        "semanticProfile": {"id": "semantic.core.v1", "version": 1,
                            "features": []},
    })
    run("omitted-backend", {
        TARGET_REGISTRY: registry + insert,
        f"{PROFILE_DIR}/s0missing.target-profile.json": profile,
    }, "backend-discovery", "s0missing")

    carveout = _load_carveout_module()
    reg = json.loads(base.read(CARVEOUT_REGISTRY))
    reviewed = next(e for e in reg["entries"] if e["form"] == "reviewed-generator")
    rel, region = carveout.site_region(reviewed, None)
    run("copied-moved-carveout", _append(
        base, rel, "\n" + region.decode("utf-8", errors="replace")),
        "carveout-integrity", reviewed["id"])

    no_governed = re.sub(
        r"(/\*gated=\*/\s*)true(\s*,\s*/\*scenarioFree=\*/\s*)false",
        r"\1false\2false", registry)
    run("empty-discovery", {
        TARGET_REGISTRY: no_governed,
        EXTERNAL_BACKEND_MANIFESTS["solidity"]: None,
    },
        "backend-discovery", "invalid external backend manifest")

    for name, passed, classes in cases:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}: {classes}")
    expected = 1 if selected is not None else len(PROBES)
    ok = len(cases) == expected and all(
        passed for _name, passed, _classes in cases)
    if selected is not None:
        if ok:
            print(f"probe-failed-as-expected:{selected}")
            return 1
        print(f"probe unexpectedly passed:{selected}")
        return 0
    print(f"SELFTEST: {'PASS' if ok else 'FAIL'} ({len(PROBES)} probes)")
    return 0 if ok else 1


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--probe", choices=PROBES)
    parser.add_argument("--output", help="write deterministic JSON report here")
    args = parser.parse_args(argv)
    if args.selftest:
        return selftest()
    if args.probe:
        return selftest(args.probe)
    report = build_report()
    validate_report_shape(report)
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as out:
            out.write(payload)
    else:
        sys.stdout.write(payload)
    if has_findings(report):
        print("semantic-authority: non-carve-out authority remains", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Check the manifest-defined frozen pairs against canonical semantics."""

import json
import hashlib
import copy
from pathlib import Path
import re
import subprocess
import sys
import tempfile


CORE_REGISTERED = set()
RENDER_MISMATCH_PROBE = sys.argv[1:] == ["--probe-render-mismatch"]
if RENDER_MISMATCH_PROBE:
    GEN = EXAMPLES = MANIFEST = DIAGNOSTIC_TAXONOMY = REPORT = None
    REPO = PROFILE_DIR = TARGET_REGISTRY = MEMBERS = None
else:
    GEN = Path(sys.argv[1]).resolve()
    EXAMPLES = Path(sys.argv[2]).resolve()
    MANIFEST = Path(sys.argv[3]).resolve()
    DIAGNOSTIC_TAXONOMY = Path(sys.argv[4]).resolve()
    REPORT = Path(sys.argv[5]).resolve() if len(sys.argv) > 5 else None
    REPO = EXAMPLES.parent
    PROFILE_DIR = EXAMPLES / "target-profiles"
    TARGET_REGISTRY = REPO / "include" / "Neutrino" / "TargetRegistry.def"
    MEMBERS = None
TARGET_ROW = re.compile(
    r'NEUTRINO_TARGET\(\s*"([^"]+)"\s*,\s*\w+\s*,'
    r'\s*/\*gated=\*/\s*(true|false)\s*,'
    r'\s*/\*scenarioFree=\*/\s*(true|false)\s*\)'
)


class CheckError(RuntimeError):
    pass


def run(args, *, expect_success=True, timeout=None):
    try:
        result = subprocess.run([str(arg) for arg in args], text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                timeout=timeout)
    except subprocess.TimeoutExpired as error:
        raise CheckError(f"command exceeded {timeout}s canonicalization bound: "
                         f"{' '.join(map(str, args))}") from error
    if expect_success and result.returncode:
        raise CheckError(f"command failed ({result.returncode}): {' '.join(map(str, args))}\n"
                         f"{result.stdout}{result.stderr}")
    if not expect_success and not result.returncode:
        raise CheckError(f"command unexpectedly passed: {' '.join(map(str, args))}")
    return result


def domain(name):
    if MEMBERS is None or name not in MEMBERS:
        raise CheckError(f"curated member {name!r} was not pack-hydrated")
    return MEMBERS[name].root


def emit_plan_artifact(input_path, out, *, from_spec=False):
    args = [GEN, "--target=coordination-plan"]
    if from_spec:
        args.append("--from-spec")
    args.extend([input_path, "-o", out])
    run(args)
    return json.loads((out / "coordination-plan.json").read_text())


def emit_plan(input_path, out, *, from_spec=False):
    return emit_plan_artifact(input_path, out, from_spec=from_spec)["semantics"]


def canonical_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def digest(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def governed_targets():
    rows = []
    for line in TARGET_REGISTRY.read_text().splitlines():
        match = TARGET_ROW.fullmatch(line.strip())
        if match:
            rows.append(
                (match.group(1), match.group(2) == "true", match.group(3) == "true")
            )
    if len(rows) < 7 or len({row[0] for row in rows}) != len(rows):
        raise CheckError("authoritative target registry is malformed or vacuous")
    registry_names = {name for name, _gated, _sf in rows}
    targets = [
        name for name, gated, scenario_free in rows if gated and not scenario_free
    ]
    # A governed value-lowering backend may be core-registered OR an externally
    # discovered verified package ( retired core Solidity dispatch), so the
    # authoritative surface is the catalog the tool actually discovers. Both
    # directions still bite, without inferring externality by set subtraction:
    #   - every target profile must name a target the catalog really exposes
    #     (no orphan profile for a target nothing can lower to);
    #   - every core-registered gated value-lowering target must have a profile.
    catalog = set(
        subprocess.run(
            [str(GEN), "--list-targets"], capture_output=True, text=True, check=True
        ).stdout.split()
    )
    profiles = {
        path.name.removesuffix(".target-profile.json"): path
        for path in PROFILE_DIR.glob("*.target-profile.json")
    }
    orphan_profiles = sorted(set(profiles) - catalog)
    if orphan_profiles:
        raise CheckError(
            f"target profile(s) name no discoverable target: {orphan_profiles}; "
            f"catalog={sorted(catalog)}"
        )
    ungoverned = sorted(set(targets) - set(profiles))
    if ungoverned:
        raise CheckError(
            f"core-registered gated target(s) without a profile: {ungoverned}"
        )
    # Governance covers every profiled target the catalog exposes. CORE_REGISTERED
    # records where a caller-supplied --profile is still accepted: an external
    # target is bound to its verified package profile and refuses the override.
    global CORE_REGISTERED
    CORE_REGISTERED = registry_names
    targets = sorted(set(profiles))
    return targets, profiles


def snake_case(value):
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    return re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").lower()


def label_variants(value):
    snake = snake_case(value)
    words = [word for word in snake.split("_") if word]
    pascal = "".join(word[:1].upper() + word[1:] for word in words)
    camel = pascal[:1].lower() + pascal[1:] if pascal else ""
    variants = [
        (value, "raw"),
        (snake, "snake"),
        (pascal, "pascal"),
        (camel, "camel"),
        (snake.upper(), "upper"),
    ]
    result = []
    seen = set()
    for variant, style in variants:
        if variant and variant not in seen:
            seen.add(variant)
            result.append((variant, style))
    return result


def input_index(value):
    if isinstance(value, str):
        match = re.fullmatch(r"(?:ref:)?input:(\d+)", value)
        if match:
            return int(match.group(1))
    return None


def map_guard_inputs(source, canonical, ranks):
    if not isinstance(source, dict) or not isinstance(canonical, dict):
        return
    if source.get("kind") == "var" and canonical.get("kind") == "value":
        index = input_index(canonical.get("value"))
        if index is not None:
            ranks[source["name"]] = index
        return
    source_children = [
        source.get(key) for key in ("lhs", "rhs", "left", "right")
        if isinstance(source.get(key), dict)
    ]
    canonical_children = [
        canonical.get(key) for key in ("lhs", "rhs", "left", "right")
        if isinstance(canonical.get(key), dict)
    ]
    for left, right in zip(source_children, canonical_children):
        map_guard_inputs(left, right, ranks)


def semantic_label_ranks(spec, semantics):
    ranks = {
        "effect": {},
        "input": {},
        "ledger": {},
        "owner": {},
        "participant": {},
        "org": {},
        "role": {},
    }
    effects = spec.get("effects", [])
    canonical_effects = semantics.get("effects", [])
    if len(effects) != len(canonical_effects):
        raise CheckError("source/canonical effect cardinality differs")
    actor_by_effect = {
        binding["effect"]: binding["actor"]
        for binding in semantics["authorizationTopology"]["effectBindings"]
    }
    participant_by_name = {
        participant["name"]: participant
        for participant in spec.get("participants", [])
    }
    for index, (effect, canonical) in enumerate(zip(effects, canonical_effects)):
        ranks["effect"][effect["name"]] = index
        ranks["ledger"][effect["ledger"]] = int(canonical["ledger"])
        for field in ("amount", "currency", "party"):
            source_ref = effect.get(field)
            canonical_ref = input_index(canonical.get(field))
            if isinstance(source_ref, dict) and canonical_ref is not None:
                ranks["input"][source_ref["value"]] = canonical_ref
        if effect.get("when"):
            map_guard_inputs(
                effect["when"].get("ast"), canonical.get("guard"), ranks["input"]
            )
        actor = actor_by_effect.get(index, index)
        if effect.get("owner"):
            ranks["owner"][effect["owner"]] = actor
        participant_name = effect.get("participant")
        if participant_name:
            ranks["participant"][participant_name] = actor
            participant = participant_by_name.get(participant_name, {})
            if participant.get("org"):
                ranks["org"][participant["org"]] = actor
            if participant.get("role"):
                ranks["role"][participant["role"]] = actor

    workflow_index = input_index(semantics.get("workflowKey"))
    key_fields = (spec.get("lifecycle") or {}).get("instanceKey", {}).get("fields", [])
    if workflow_index is not None and len(key_fields) == 1:
        ranks["input"][key_fields[0]] = workflow_index

    canonical_inputs = semantics.get("inputs", [])
    remaining_by_shape = {}
    for item in canonical_inputs:
        remaining_by_shape.setdefault((item["category"], item["type"]), []).append(
            item["id"]
        )
    for index in ranks["input"].values():
        for values in remaining_by_shape.values():
            if index in values:
                values.remove(index)
    for item in spec.get("inputs", []):
        if item["name"] in ranks["input"]:
            continue
        shape = (item["category"], item["type"])
        candidates = remaining_by_shape.get(shape, [])
        if not candidates:
            raise CheckError(f"cannot map source input label {item['name']!r}")
        ranks["input"][item["name"]] = candidates.pop(0)
    return ranks


def permitted_label_groups(spec, semantics):
    policies = spec.get("attestationPolicies") or []
    lifecycle = spec.get("lifecycle") or {}
    groups = {
        "procedure": [spec["procedure"]],
        "procedure_display": [snake_case(spec["procedure"]).split("_")[-1]],
        "input": [item["name"] for item in spec.get("inputs", [])],
        "effect": [item["name"] for item in spec.get("effects", [])],
        "ledger": sorted(
            {item["ledger"] for item in spec.get("effects", []) if item.get("ledger")}
        ),
        "owner": sorted(
            {item["owner"] for item in spec.get("effects", []) if item.get("owner")}
        ),
        "participant": [item["name"] for item in spec.get("participants", [])],
        "org": sorted(
            {item["org"] for item in spec.get("participants", []) if item.get("org")}
        ),
        "role": sorted(
            {item["role"] for item in spec.get("participants", []) if item.get("role")}
        ),
        "compute": [item["name"] for item in spec.get("computes", [])],
        "policy": [item["name"] for item in policies],
        "state": [item["name"] for item in lifecycle.get("states", [])],
        "operation": sorted(
            {item["name"] for item in lifecycle.get("transitions", [])}
        ),
    }
    return groups, semantic_label_ranks(spec, semantics)


def replacement_value(prefix, index, style):
    snake = f"{prefix}_{index}"
    pascal = "".join(word[:1].upper() + word[1:] for word in snake.split("_"))
    if style == "pascal":
        return pascal
    if style == "camel":
        return pascal[:1].lower() + pascal[1:]
    if style == "upper":
        return snake.upper()
    return snake


def normalize_parameter_order(text, target):
    # Source declaration order is a representation identity erased by the
    # compiler-owned semantic projection. Reorder only the generated execute
    # signature, using the canonical input IDs already recovered above. Event
    # identifiers and argument names are display labels; event order, types,
    # arity, and every use site remain part of the compared bytes.
    if target == "solidity":
        pattern = re.compile(r"(function execute\()([^)]*)(\) external)")
    elif target == "postgres":
        pattern = re.compile(
            r"(CREATE OR REPLACE FUNCTION execute_[^(]+\()([^)]*)(\))"
        )
    else:
        return text

    def canonicalize(match):
        parameters = [item.strip() for item in match.group(2).split(",") if item.strip()]

        def key(parameter):
            found = re.search(r"(?:u_|p_)?input_(\d+)", parameter)
            return int(found.group(1)) if found else len(parameters)

        return match.group(1) + ", ".join(sorted(parameters, key=key)) + match.group(3)

    text = pattern.sub(canonicalize, text)
    if target == "solidity":
        event_pattern = re.compile(r"(\bevent\s+\w+\()([^)]*)(\);)")

        def normalize_event(match):
            parameters = [
                re.sub(r"\b[A-Za-z_]\w*$", f"arg_{index}", item.strip())
                for index, item in enumerate(match.group(2).split(","))
                if item.strip()
            ]
            return match.group(1) + ", ".join(parameters) + match.group(3)

        text = event_pattern.sub(normalize_event, text)
    return text


def normalize_render(out, spec, semantics, target):
    # Alpha-normalize only labels present in the verified source spec (plus
    # Solidity event display identifiers). Ranks come from canonical semantics,
    # so topology/effect direction/guard/ledger association cannot be made
    # equal by choosing a convenient source order. The normalized production
    # artifact bytes—not the capability spec—are what the pair proof compares.
    files = {
        path.relative_to(out).as_posix(): path.read_text(encoding="utf-8")
        for path in out.rglob("*")
        # backend-dispatch-receipt.json is provenance about THIS invocation
        # (artifact/projection/receipt digests of one render), not rendered
        # semantics. It differs between any two pair members by construction, so
        # comparing it would make the pair proof unsatisfiable rather than
        # stricter. The rendered artifacts it attests are still compared below.
        if path.is_file() and path.name not in {
            "diagnostics.json", "manifest.json", "backend-dispatch-receipt.json"
        }
    }
    if not files:
        raise CheckError(f"{out}: governed backend emitted no production artifacts")
    joined = "\n".join(f"{path}\0{text}" for path, text in sorted(files.items()))
    replacements = {}
    groups, semantic_ranks = permitted_label_groups(spec, semantics)
    if target == "solidity":
        groups["event"] = list(
            dict.fromkeys(re.findall(r"\bevent\s+([A-Za-z_]\w*)\s*\(", joined))
        )
    for prefix, labels in groups.items():
        unique = list(dict.fromkeys(label for label in labels if label))
        ranked = []
        for label in unique:
            variants = (
                [(f"u_{snake_case(label)}", "u_input"),
                 (f"p_{snake_case(label)}", "p_input")]
                if prefix == "input"
                else label_variants(label)
            )
            positions = [
                joined.find(variant)
                for variant, _ in variants
                if variant in joined
            ]
            rank = semantic_ranks.get(prefix, {}).get(label)
            ranked.append(
                (
                    (0, rank)
                    if rank is not None
                    else (1, min(positions) if positions else len(joined)),
                    label,
                )
            )
        for index, (_, label) in enumerate(sorted(ranked)):
            variants = (
                [(f"u_{snake_case(label)}", "u_input"),
                 (f"p_{snake_case(label)}", "p_input")]
                if prefix == "input"
                else label_variants(label)
            )
            for variant, style in variants:
                if style == "u_input":
                    replacements[variant] = f"u_input_{index}"
                elif style == "p_input":
                    replacements[variant] = f"p_input_{index}"
                else:
                    replacements[variant] = replacement_value(
                        prefix, index, style
                    )

    ordered = sorted(replacements.items(), key=lambda item: (-len(item[0]), item[0]))

    def replace(text):
        sentinels = {}
        for index, (before, after) in enumerate(ordered):
            sentinel = f"__NEUTRINO_LABEL_{index}__"
            if before in text:
                text = text.replace(before, sentinel)
                sentinels[sentinel] = after
        for sentinel, after in sentinels.items():
            text = text.replace(sentinel, after)
        return text

    normalized = {
        replace(path): normalize_parameter_order(replace(text), target)
        for path, text in files.items()
    }
    artifact_records = [
        {"path": path, "sha256": hashlib.sha256(text.encode()).hexdigest()}
        for path, text in sorted(normalized.items())
    ]
    return {
        "sha256": digest(artifact_records),
        "artifacts": artifact_records,
        "_normalized": normalized,
    }


def require_render_equality(pair_id, target, left, right):
    if left["_normalized"] != right["_normalized"]:
        raise CheckError(
            f"{pair_id} {target} render differs modulo permitted labels: "
            f"{first_difference(left['_normalized'], right['_normalized'])!r}"
        )


def render_pair_evidence(pair, specs, targets, profiles, work):
    evidence = []
    for target in targets:
        normalized = {}
        for endpoint in ("a", "b"):
            name = pair[endpoint]
            out = work / pair["id"] / target / name
            command = [GEN, f"--target={target}", "--from-spec"]
            # An external target refuses a caller-supplied profile; its verified
            # package profile is authoritative and already governs the render.
            if target in CORE_REGISTERED:
                command.append(f"--profile={profiles[target]}")
            command += [
                domain(name) / "generated" / "capability-spec" / "capability-spec.json",
                "-o",
                out,
            ]
            run(command)
            normalized[endpoint] = normalize_render(
                out, specs[name], specs[name]["_canonicalSemantics"], target
            )
        require_render_equality(
            pair["id"], target, normalized["a"], normalized["b"]
        )
        evidence.append(
            {
                "target": target,
                "normalizedSha256": normalized["a"]["sha256"],
                "artifacts": normalized["a"]["artifacts"],
            }
        )
    return evidence


def probe_render_pair_mismatch():
    global run, domain, normalize_render

    run = lambda *_args, **_kwargs: None
    domain = lambda name: Path("/probe") / name

    def fake_normalize(out, _spec, _semantics, _target):
        endpoint = out.name
        return {
            "sha256": hashlib.sha256(endpoint.encode()).hexdigest(),
            "artifacts": [{"path": "artifact", "sha256": "0" * 64}],
            "_normalized": {"artifact": endpoint},
        }

    normalize_render = fake_normalize
    render_pair_evidence(
        {"id": "probe-pair", "a": "left", "b": "right"},
        {
            "left": {"_canonicalSemantics": {}},
            "right": {"_canonicalSemantics": {}},
        },
        ["probe-target"],
        {"probe-target": Path("/probe/profile.json")},
        Path("/probe/work"),
    )


def resign(spec):
    semantic_core = {key: value for key, value in spec.items()
                     if key not in {"identity", "sourceMap", "targetRequirements",
                                    "kind", "schemaVersion"}}
    spec["identity"] = {"capabilityHash": digest(semantic_core)}
    spec_hash_body = dict(spec)
    spec_hash_body["identity"] = {
        "capabilityHash": spec["identity"]["capabilityHash"]}
    spec["identity"]["specHash"] = digest(spec_hash_body)


def first_difference(left, right, path="$"):
    if type(left) is not type(right):
        return path, type(left).__name__, type(right).__name__
    if isinstance(left, dict):
        for key in sorted(set(left) | set(right)):
            if key not in left:
                return f"{path}.{key}", "<missing>", right[key]
            if key not in right:
                return f"{path}.{key}", left[key], "<missing>"
            difference = first_difference(left[key], right[key], f"{path}.{key}")
            if difference:
                return difference
    elif isinstance(left, list):
        if len(left) != len(right):
            return f"{path}.length", len(left), len(right)
        for index, (a, b) in enumerate(zip(left, right)):
            difference = first_difference(a, b, f"{path}[{index}]")
            if difference:
                return difference
    elif left != right:
        return path, left, right
    return None


def load_manifest():
    data = json.loads(MANIFEST.read_text())
    if data.get("kind") != "neutrino.m6-curated-example-corpus" or \
            data.get("schemaVersion") != 2:
        raise CheckError("unsupported curated corpus manifest identity")
    examples = data.get("examples")
    pairs = data.get("variancePairs")
    if not isinstance(examples, list) or not isinstance(pairs, list) or len(pairs) != 3:
        raise CheckError("curated manifest must carry its seven members and three frozen pairs")
    for pair in pairs:
        if set(pair) != {"id", "a", "b"} or pair["a"] not in examples or pair["b"] not in examples:
            raise CheckError(f"invalid frozen pair: {pair!r}")
    return data


def main():
    global MEMBERS
    manifest = load_manifest()
    sys.path.insert(0, str(REPO / "scripts" / "gates"))
    import m6_pack_resolver

    MEMBERS = m6_pack_resolver.resolve_members(manifest, repo=REPO)
    targets, profiles = governed_targets()
    root_fields = {
        "schemaVersion", "inputs", "authorizationTopology", "workflowKey",
        "explicitInstanceKey", "evidenceOnly", "balanced", "replay", "effects",
        "effectGroups", "computes", "attestations", "lifecycle",
    }
    with tempfile.TemporaryDirectory(prefix="canonical-semantics.") as td:
        work = Path(td)
        semantics = {}
        specs = {}
        for name in sorted({endpoint for pair in manifest["variancePairs"]
                            for endpoint in (pair["a"], pair["b"]) }):
            source = domain(name) / "source" / f"{name}.neu"
            spec = domain(name) / "generated" / "capability-spec" / "capability-spec.json"
            direct_artifact = emit_plan_artifact(source, work / f"{name}-direct")
            direct = direct_artifact["semantics"]
            rebuilt = emit_plan(spec, work / f"{name}-from-spec", from_spec=True)
            if canonical_bytes(direct) != canonical_bytes(rebuilt):
                raise CheckError(f"{name}: source/from-spec canonical semantics differ: "
                                 f"{first_difference(direct, rebuilt)!r}")
            if set(direct) != root_fields:
                raise CheckError(f"{name}: incomplete canonical semantics root fields: "
                                 f"missing={sorted(root_fields - set(direct))}, "
                                 f"extra={sorted(set(direct) - root_fields)}")
            topology = direct["authorizationTopology"]
            if len(topology["actors"]) != 2 or len(topology["effectBindings"]) != 2 or \
                    len(topology["allowedOrgEdges"]) != 1:
                raise CheckError(f"{name}: authorization topology was erased: {topology!r}")
            semantics[name] = direct
            specs[name] = json.loads(spec.read_text())
            specs[name]["_canonicalSemantics"] = direct

        pair_evidence = []
        for pair in manifest["variancePairs"]:
            left = semantics[pair["a"]]
            right = semantics[pair["b"]]
            if canonical_bytes(left) != canonical_bytes(right):
                raise CheckError(
                    f"{pair['id']} {pair['a']} != {pair['b']}; first divergent typed field: "
                    f"{first_difference(left, right)!r}")
            pair_evidence.append(
                {
                    "id": pair["id"],
                    "a": pair["a"],
                    "b": pair["b"],
                    "semanticSha256": digest(left),
                    "backends": render_pair_evidence(
                        pair, specs, targets, profiles, work / "pair-renders"
                    ),
                }
            )

        # Lifecycle representation identities are not semantic. Reordering
        # transition records must leave canonical semantics unchanged, while changing the
        # distinguished initial state must bite.
        pair = manifest["variancePairs"][0]
        name = pair["a"]
        spec_path = domain(name) / "generated" / "capability-spec" / "capability-spec.json"
        original_spec = json.loads(spec_path.read_text())
        reordered_spec = copy.deepcopy(original_spec)
        reordered_spec["lifecycle"]["transitions"][:2] = \
            reversed(reordered_spec["lifecycle"]["transitions"][:2])
        resign(reordered_spec)
        reordered_path = work / f"{name}-reordered-transitions.json"
        reordered_path.write_text(json.dumps(reordered_spec))
        reordered = emit_plan(reordered_path, work / "reordered-plan", from_spec=True)
        if canonical_bytes(reordered) != canonical_bytes(semantics[name]):
            raise CheckError("transition declaration order changed canonical semantics: "
                             f"{first_difference(semantics[name], reordered)!r}")

        initial_spec = copy.deepcopy(original_spec)
        old_initial = initial_spec["lifecycle"]["initialState"]
        new_initial = initial_spec["lifecycle"]["transitions"][0]["to"]
        if new_initial == old_initial:
            raise CheckError("initial-state mutation did not select a distinct declared state")
        initial_spec["lifecycle"]["initialState"] = new_initial
        resign(initial_spec)
        initial_path = work / f"{name}-changed-initial.json"
        initial_path.write_text(json.dumps(initial_spec))
        changed_initial = emit_plan(initial_path, work / "changed-initial-plan",
                                    from_spec=True)
        if canonical_bytes(changed_initial) == canonical_bytes(semantics[name]):
            raise CheckError("changed lifecycle initial state did not bite canonical semantics")

        # External schemas do not bound state count. Seven indistinguishable,
        # isolated states would require 7! exact label permutations, so the
        # projection must reject before entering the factorial search.
        over_limit_spec = copy.deepcopy(original_spec)
        over_limit_spec["lifecycle"]["states"].extend(
            {"name": f"EXTRA_STATE_{index}", "terminal": False}
            for index in range(7))
        resign(over_limit_spec)
        over_limit_path = work / f"{name}-canonical-limit.json"
        over_limit_path.write_text(json.dumps(over_limit_spec))
        over_limit_out = work / "canonical-limit-plan"
        rejected = run([GEN, "--target=coordination-plan", "--from-spec",
                        over_limit_path, "-o", over_limit_out],
                       expect_success=False, timeout=3)
        diagnostics = json.loads((over_limit_out / "diagnostics.json").read_text())
        rejection_codes = [entry.get("code") for entry in diagnostics.get("diagnostics", [])]
        if rejection_codes != ["spec.ast"]:
            raise CheckError("over-limit lifecycle did not fail exactly with spec.ast: "
                             f"{rejection_codes!r}")
        taxonomy = json.loads(DIAGNOSTIC_TAXONOMY.read_text())
        registered = {entry["code"]: entry for entry in taxonomy.get("codes", [])}
        diagnostic = registered.get("spec.ast")
        if not diagnostic or diagnostic.get("status") != "active" or \
                diagnostic.get("emitter") not in {"cpp", "both"}:
            raise CheckError("over-limit lifecycle diagnostic is not an active C++ taxonomy code")
        if (over_limit_out / "coordination-plan.json").exists():
            raise CheckError("over-limit lifecycle fabricated a coordination-plan artifact")

        # Independent add-obligation witness: add one more balanced posting pair
        # to a valid external spec, re-sign it, and require both canonical semantics and
        # each governed production rendering to change.
        spec = copy.deepcopy(original_spec)
        if len(spec["effects"]) != 2 or {item.get("kind") for item in spec["effects"]} != \
                {"debit", "credit"}:
            raise CheckError("obligation probe requires exactly one balanced debit/credit pair")
        added = copy.deepcopy(spec["effects"])
        for effect in added:
            effect["name"] += "_additional_obligation"
        spec["effects"].extend(added)

        resign(spec)
        mutated = work / f"{name}-additional-obligation.json"
        mutated.write_text(json.dumps(spec))
        changed = emit_plan(mutated, work / "mutated-plan", from_spec=True)
        difference = first_difference(semantics[name], changed)
        if not difference or len(changed["effects"]) != len(semantics[name]["effects"]) + 2:
            raise CheckError(f"add-obligation probe did not bite: {difference!r}")
        for target in targets:
            baseline = work / f"{target}-baseline"
            mutation = work / f"{target}-mutated"
            # External targets refuse a caller-supplied profile (their verified
            # package profile governs), so only core-registered targets take one.
            profile = ([f"--profile={profiles[target]}"]
                       if target in CORE_REGISTERED else [])
            run([GEN, f"--target={target}", "--from-spec", *profile,
                 spec_path, "-o", baseline])
            run([GEN, f"--target={target}", "--from-spec", *profile,
                 mutated, "-o", mutation])
            if target == "solidity":
                before = {path.name: path.read_bytes() for path in (baseline / "src").glob("*.sol")}
                after = {path.name: path.read_bytes() for path in (mutation / "src").glob("*.sol")}
            else:
                before = {"procedure.sql": (baseline / "procedure.sql").read_bytes()}
                after = {"procedure.sql": (mutation / "procedure.sql").read_bytes()}
            if before == after:
                raise CheckError(f"{target}: add-obligation render witness did not change")

        if REPORT:
            REPORT.parent.mkdir(parents=True, exist_ok=True)
            REPORT.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "kind": "neutrino.canonical-plan-render-evidence",
                        "pairs": pair_evidence,
                        "mutation": {
                            "kind": "add-balanced-posting-obligation",
                            "semanticChanged": True,
                            "renderChangedTargets": targets,
                        },
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n"
            )

    print("canonical semantics OK: all 3 frozen pairs byte-equal; transition reorder is "
          "invariant; governed backend renders are equal modulo permitted labels; "
          "initial-state and posting-obligation mutations bite")


if __name__ == "__main__":
    try:
        if RENDER_MISMATCH_PROBE:
            probe_render_pair_mismatch()
        else:
            main()
    except CheckError as error:
        print(f"canonical semantics FAILED: {error}", file=sys.stderr)
        sys.exit(1)

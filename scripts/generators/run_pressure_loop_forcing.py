#!/usr/bin/env python3
""" representation-neutral pressure-loop forcing harness.

The fixture describes inputs plus expected observations. It never supplies a
register row as output authority: accepted/unresolved rows are derived only
after this runner observes the existing compiler seams.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
VALIDATOR = REPO / "scripts/validators/validate_pressure_loop_register.py"
KIND = "neutrino.pressure-loop-register"
SCHEMA_VERSION = 2
FIXTURE_VERSION = 1
ALLOWED_PATHS = {
    "representable",
    "failed-reduction",
    "orthogonal",
    "refusal",
    "orchestration-overload",
    "pay-for-result",
    "tooling-gap",
}
COMMON_FIXTURE_FIELDS = {"fixtureId", "requirement", "provenance", "owner", "path"}
PATH_FIELDS = {
    "representable": COMMON_FIXTURE_FIELDS | {"inputs", "expectedObservation"},
    "failed-reduction": COMMON_FIXTURE_FIELDS | {"inputs", "expectedObservation"},
    "orthogonal": COMMON_FIXTURE_FIELDS | {"expectedObservation"},
    "refusal": COMMON_FIXTURE_FIELDS | {"inputs", "expectedObservation"},
    "orchestration-overload": COMMON_FIXTURE_FIELDS | {"inputs", "expectedObservation", "authority"},
    "pay-for-result": COMMON_FIXTURE_FIELDS | {"inputs", "expectedObservation", "authority"},
    "tooling-gap": COMMON_FIXTURE_FIELDS | {"expectedObservation"},
}
DIAGNOSTIC_MAP = {
    "l2.unregistered_feature": {
        "class": "3",
        "disposition": "LANGUAGE_DECISION_REQUIRED",
        "operation": None,
        "failureTemplate": "unregistered feature {anchor}",
        "minimalCounterexampleTemplate": "A domain feature requests closed-waist feature {anchor}, which is not in the semantic vocabulary.",
        "linkedDecision": "neutrino-",
    },
    "usage.unsupported_target": {
        "class": "2",
        "disposition": "UNSUPPORTED_REFUSED",
        "operation": None,
        "failureTemplate": "unsupported target {anchor}",
    },
    # Composite, harness-derived (NOT parsed from a single tool output): emitted only
    # by observe_orchestration_overload when its full closed conjunction holds. A
    # generic front-end diagnostic never reaches this on its own ( scope call).
    "forcing.missing_orchestration_stratum": {
        "class": "3",
        "disposition": "LAYER_DECISION_REQUIRED",
        "operation": None,
    },
}


class Harness:
    def __init__(
        self,
        *,
        neutrino_gen: Path | None,
        neutrino_emit: Path | None,
        tool_dir: Path | None,
        work_dir: Path,
        evidence_dir: Path,
    ):
        self.neutrino_gen = neutrino_gen
        self.neutrino_emit = neutrino_emit
        self.tool_dir = tool_dir
        self.work_dir = work_dir
        self.evidence_dir = evidence_dir
        self.observed_proofs: dict[str, tuple[Path, dict[str, Any]]] = {}
        self.evidence_dir.mkdir(parents=True, exist_ok=True)

    def tool(self, name: str) -> str:
        explicit = self.neutrino_gen if name == "neutrino-gen" else self.neutrino_emit if name == "neutrino-emit" else None
        if explicit is not None:
            if explicit.is_file() and os.access(explicit, os.X_OK):
                return str(explicit)
            raise ValueError(f"configured tool {explicit} is not executable")
        candidates: list[Path] = []
        if self.tool_dir is not None:
            candidates.append(self.tool_dir / name)
        env_dir = os.environ.get("NEUTRINO_TOOL_DIR")
        if env_dir:
            candidates.append(Path(env_dir) / name)
        candidates.extend([
            REPO / "out" / "tools" / name / name,
            REPO / "build" / "tools" / name / name,
        ])
        for candidate in candidates:
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)
        resolved = shutil.which(name)
        if resolved:
            return resolved
        raise ValueError(f"required tool {name!r} not found; pass --{name.replace('-', '_')} or --tool-dir")

    def run(self, argv: list[str], *, expect_ok: bool, ctx: str) -> subprocess.CompletedProcess[str]:
        proc = subprocess.run(argv, cwd=REPO, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if expect_ok and proc.returncode != 0:
            raise ValueError(f"{ctx} failed with exit {proc.returncode}:\n{proc.stdout}")
        if not expect_ok and proc.returncode == 0:
            raise ValueError(f"{ctx} unexpectedly succeeded")
        return proc


def die(message: str) -> int:
    print(f"pressure-loop forcing: {message}", file=sys.stderr)
    return 1


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def repo_path(value: str, ctx: str) -> Path:
    p = Path(value)
    if p.is_absolute():
        raise ValueError(f"{ctx} must be repository-relative")
    resolved = (REPO / p).resolve()
    if not str(resolved).startswith(str(REPO.resolve()) + os.sep):
        raise ValueError(f"{ctx} escapes the repository")
    return resolved


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def rel_argv(argv: list[str]) -> list[str]:
    # Committed evidence must be reproducible: relativize any argv element that
    # resolves under the repository (tool + input paths), leave the rest verbatim.
    out: list[str] = []
    for part in argv:
        candidate = Path(part)
        if candidate.is_absolute() and str(candidate.resolve()).startswith(str(REPO.resolve()) + os.sep):
            out.append(rel(candidate))
        else:
            out.append(part)
    return out


def require_nonempty_string(obj: dict[str, Any], key: str, ctx: str) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{ctx}.{key} must be a non-empty string")
    return value


def require_obj(obj: dict[str, Any], key: str, ctx: str) -> dict[str, Any]:
    value = obj.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"{ctx}.{key} must be an object")
    return value


def validate_pay_for_result_execution_gap(proof: dict[str, Any], companion_row_id: str, ctx: str) -> dict[str, str]:
    if proof.get("kind") != "pay-for-result-proof" or proof.get("rowId") != companion_row_id:
        raise ValueError(f"{ctx}: evidence is not companion pay-for-result proof {companion_row_id!r}")
    reduction = require_obj(proof, "reduction", ctx)
    attestation = require_obj(reduction, "attestation", f"{ctx}.reduction")
    replay = require_obj(reduction, "replay", f"{ctx}.reduction")
    gap = require_obj(proof, "executionGap", ctx)
    deadline = require_obj(gap, "deadline", f"{ctx}.executionGap")
    second = require_obj(gap, "secondInvocation", f"{ctx}.executionGap")

    deadline_declared = {"timeout": attestation.get("timeout"), "fallback": attestation.get("fallback")}
    if deadline.get("declared") != deadline_declared or deadline.get("behaviorallyExecuted") is not False:
        raise ValueError(f"{ctx}: deadline execution gap drifted from the observed attestation contract")
    if deadline.get("reason") != "coordination-trace CLI exposes no clock/deadline event":
        raise ValueError(f"{ctx}: deadline execution gap lacks the observed clock/deadline reason")

    second_declared = {
        "idempotent": replay.get("idempotent"),
        "allTransitionsReject": replay.get("allTransitionsReject"),
        "key": replay.get("key"),
    }
    if second.get("declared") != second_declared or second.get("behaviorallyExecuted") is not False:
        raise ValueError(f"{ctx}: second-invocation execution gap drifted from the observed replay contract")
    if replay.get("idempotent") is not True or replay.get("allTransitionsReject") is not True or not isinstance(replay.get("key"), str):
        raise ValueError(f"{ctx}: companion proof lacks the declared replay facts")
    if second.get("reason") != "coordination-trace CLI exposes no prior-state input for a second invocation":
        raise ValueError(f"{ctx}: second-invocation execution gap lacks the observed prior-state reason")

    return {
        "failedVerifierObligation": "The coordination evaluator cannot execute a deadline event or a second invocation from prior state, so late-result and duplicate-settlement behavior is not executable evidence.",
        "minimalCounterexample": f"The coordination-trace CLI accepts one scenario and exposes neither a clock/deadline event nor prior-state input for replaying {replay['key']} J-1.",
    }


def base_row(fixture: dict[str, Any]) -> dict[str, Any]:
    provenance = require_obj(fixture, "provenance", "fixture")
    return {
        "rowId": require_nonempty_string(fixture, "fixtureId", "fixture"),
        "requirement": require_nonempty_string(fixture, "requirement", "fixture"),
        "provenance": {
            "source": require_nonempty_string(provenance, "source", "fixture.provenance"),
            "authorityWeightTier": require_nonempty_string(provenance, "authorityWeightTier", "fixture.provenance"),
        },
        "owner": require_nonempty_string(fixture, "owner", "fixture"),
        "minimalCounterexample": None,
        "linkedDecision": None,
    }


def contains_fragment(value: Any, fragment: Any) -> bool:
    if isinstance(fragment, dict):
        return isinstance(value, dict) and all(k in value and contains_fragment(value[k], v) for k, v in fragment.items())
    if isinstance(fragment, list):
        return isinstance(value, list) and all(any(contains_fragment(v, f) for v in value) for f in fragment)
    return value == fragment


def require_trace_fragments(trace: dict[str, Any], expected: dict[str, Any], ctx: str) -> None:
    if trace.get("outcome") != expected.get("outcome"):
        raise ValueError(f"{ctx}: outcome {trace.get('outcome')!r} != expected {expected.get('outcome')!r}")
    for idx, fragment in enumerate(expected.get("traceContains", [])):
        if not any(contains_fragment(obs, fragment) for obs in trace.get("trace", [])):
            raise ValueError(f"{ctx}: missing trace fragment {idx}: {fragment!r}")
    for idx, fragment in enumerate(expected.get("nextBalances", [])):
        balances = trace.get("nextState", {}).get("balances", [])
        if not any(contains_fragment(balance, fragment) for balance in balances):
            raise ValueError(f"{ctx}: missing nextState balance {idx}: {fragment!r}")
    for key, value in expected.get("keyStatus", {}).items():
        actual = trace.get("nextState", {}).get("keyStatus", {}).get(key)
        if actual != value:
            raise ValueError(f"{ctx}: keyStatus[{key!r}] {actual!r} != {value!r}")
    for posted in expected.get("postedKeys", []):
        if posted not in trace.get("nextState", {}).get("postedKeys", []):
            raise ValueError(f"{ctx}: missing posted key {posted!r}")


def proof_ref(harness: Harness, row_id: str, proof: dict[str, Any]) -> dict[str, str]:
    proof_path = harness.evidence_dir / f"{row_id}.proof.json"
    write_json(proof_path, proof)
    if not proof_path.is_file():
        raise ValueError(f"{row_id}: generated evidence target missing: {proof_path}")
    return {"type": "executable" if proof.get("kind") == "representable-proof" else "refusal", "ref": rel(proof_path)}


def observe_representable(fixture: dict[str, Any], row_id: str, harness: Harness) -> tuple[str, dict[str, str]]:
    inputs = require_obj(fixture, "inputs", row_id)
    expected = require_obj(fixture, "expectedObservation", row_id)
    source = repo_path(require_nonempty_string(inputs, "source", f"{row_id}.inputs"), f"{row_id}.inputs.source")
    scenario = repo_path(require_nonempty_string(inputs, "scenario", f"{row_id}.inputs"), f"{row_id}.inputs.scenario")
    if not source.is_file():
        raise ValueError(f"{row_id}.inputs.source does not exist: {rel(source)}")
    if not scenario.is_file():
        raise ValueError(f"{row_id}.inputs.scenario does not exist: {rel(scenario)}")
    operation = require_nonempty_string(expected, "operation", f"{row_id}.expectedObservation")
    gen = harness.tool("neutrino-gen")
    direct_dir = harness.work_dir / row_id / "direct"
    spec_dir = harness.work_dir / row_id / "spec"
    from_spec_dir = harness.work_dir / row_id / "from-spec"

    direct_cmd = [gen, "--target=coordination-trace", "--scenario", str(scenario), str(source), "-o", str(direct_dir)]
    harness.run(direct_cmd, expect_ok=True, ctx=f"{row_id} coordination-trace direct")
    direct_trace_path = direct_dir / "coordination-trace.json"
    direct_trace = load_json(direct_trace_path)

    spec_cmd = [gen, "--target=capability-spec", str(source), "-o", str(spec_dir)]
    harness.run(spec_cmd, expect_ok=True, ctx=f"{row_id} capability-spec generation")
    spec_path = spec_dir / "capability-spec.json"
    from_spec_cmd = [gen, "--target=coordination-trace", "--from-spec", "--scenario", str(scenario), str(spec_path), "-o", str(from_spec_dir)]
    harness.run(from_spec_cmd, expect_ok=True, ctx=f"{row_id} coordination-trace from-spec")
    from_spec_trace_path = from_spec_dir / "coordination-trace.json"
    from_spec_trace = load_json(from_spec_trace_path)
    if direct_trace != from_spec_trace:
        raise ValueError(f"{row_id}: direct and from-spec coordination traces diverged")
    require_trace_fragments(direct_trace, expected, row_id)
    proof = {
        "kind": "representable-proof",
        "rowId": row_id,
        "operation": operation,
        "commands": [
            {"argv": direct_cmd, "artifact": str(direct_trace_path), "sha256": sha256(direct_trace_path)},
            {"argv": spec_cmd, "artifact": str(spec_path), "sha256": sha256(spec_path)},
            {"argv": from_spec_cmd, "artifact": str(from_spec_trace_path), "sha256": sha256(from_spec_trace_path)},
        ],
        "canonicalTraceSha256": sha256(direct_trace_path),
    }
    return operation, proof_ref(harness, row_id, proof)


def requested_target(argv: list[str]) -> str | None:
    for idx, arg in enumerate(argv):
        if arg == "--target" and idx + 1 < len(argv):
            return argv[idx + 1]
        if arg.startswith("--target="):
            return arg.split("=", 1)[1]
    return None


def parse_diagnostic(stdout: str, *, unsupported_anchor: str | None = None) -> tuple[str, str]:
    if "unregistered feature" in stdout:
        return "l2.unregistered_feature", stdout.split("unregistered feature", 1)[1].strip().split()[0]
    registered = re.search(r"l1_feature ['\"]([^'\"]+)['\"] is not a registered semantic feature", stdout)
    if registered:
        return "l2.unregistered_feature", registered.group(1)
    if "--target must be" in stdout or "unsupported target" in stdout:
        found = re.search(r"unsupported target ['\"]?([^'\"\\s:]+)", stdout)
        anchor = found.group(1) if found else unsupported_anchor
        if not anchor:
            raise ValueError(f"unsupported-target diagnostic lacks an observable target anchor:\n{stdout}")
        return "usage.unsupported_target", anchor
    raise ValueError(f"unknown diagnostic output:\n{stdout}")


def observe_failed_reduction(fixture: dict[str, Any], row_id: str, harness: Harness) -> dict[str, Any]:
    inputs = require_obj(fixture, "inputs", row_id)
    expected = require_obj(fixture, "expectedObservation", row_id)
    emit = harness.tool("neutrino-emit")
    inp = repo_path(require_nonempty_string(inputs, "input", f"{row_id}.inputs"), f"{row_id}.inputs.input")
    reduce_against = repo_path(require_nonempty_string(inputs, "reduceAgainst", f"{row_id}.inputs"), f"{row_id}.inputs.reduceAgainst")
    cmd = [emit, "--kind=domain-reduction", str(inp), "--reduce-against", str(reduce_against)]
    proc = harness.run(cmd, expect_ok=False, ctx=f"{row_id} reduction failure")
    code, anchor = parse_diagnostic(proc.stdout)
    if code != expected.get("diagnosticCode") or anchor != expected.get("anchor"):
        raise ValueError(f"{row_id}: observed diagnostic {(code, anchor)!r} != expected {(expected.get('diagnosticCode'), expected.get('anchor'))!r}")
    mapped = DIAGNOSTIC_MAP.get(code)
    if not mapped:
        raise ValueError(f"{row_id}: unknown diagnostic code {code!r}")
    proof_path = harness.evidence_dir / f"{row_id}.reduction-diagnostic.json"
    write_json(proof_path, {"kind": "reduction-diagnostic", "rowId": row_id, "argv": rel_argv(cmd), "exitCode": proc.returncode, "code": code, "anchor": anchor, "output": proc.stdout})
    out = dict(mapped)
    out.update({"code": code, "anchor": anchor, "evidence": {"type": "refusal", "ref": rel(proof_path)}})
    return out


def observe_refusal(fixture: dict[str, Any], row_id: str, harness: Harness) -> dict[str, Any]:
    inputs = require_obj(fixture, "inputs", row_id)
    expected = require_obj(fixture, "expectedObservation", row_id)
    cmd = inputs.get("command")
    if not isinstance(cmd, list) or not cmd:
        raise ValueError(f"{row_id}.inputs.command must be a non-empty array")
    argv: list[str] = []
    for idx, part in enumerate(cmd):
        if not isinstance(part, str) or not part:
            raise ValueError(f"{row_id}.inputs.command[{idx}] must be a non-empty string")
        argv.append(part)
    if "backend-dispatch" in inputs:
        raise ValueError(f"{row_id}: refusal fixture crossed backend dispatch")
    observed_target = requested_target(argv)
    if not observed_target:
        raise ValueError(f"{row_id}: refusal command must carry an explicit --target anchor")
    argv[0] = harness.tool(argv[0])
    proc = harness.run(argv, expect_ok=False, ctx=f"{row_id} refusal dispatch")
    code, anchor = parse_diagnostic(proc.stdout, unsupported_anchor=observed_target)
    if code != expected.get("diagnosticCode") or anchor != expected.get("anchor"):
        raise ValueError(f"{row_id}: observed refusal {(code, anchor)!r} != expected {(expected.get('diagnosticCode'), expected.get('anchor'))!r}")
    mapped = DIAGNOSTIC_MAP.get(code)
    if not mapped or mapped["disposition"] != "UNSUPPORTED_REFUSED":
        raise ValueError(f"{row_id}: diagnostic {code!r} does not map to UNSUPPORTED_REFUSED")
    proof = {"kind": "refusal-proof", "rowId": row_id, "argv": rel_argv(argv), "exitCode": proc.returncode, "code": code, "anchor": anchor, "output": proc.stdout}
    return {**mapped, "code": code, "anchor": anchor, "evidence": proof_ref(harness, row_id, proof)}


ORDERING_EDGE_KEYS = {
    "after", "depends", "dependson", "dependency", "precede", "precededby",
    "order", "ordering", "stage", "stages", "sequence", "successor", "predecessor", "next",
}


def all_keys(obj: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            keys.add(str(k).lower())
            keys |= all_keys(v)
    elif isinstance(obj, list):
        for v in obj:
            keys |= all_keys(v)
    return keys


def dir_artifacts(path: Path) -> list[str]:
    if not path.exists():
        return []
    return sorted(rel(p) for p in path.rglob("*") if p.is_file())


def redact_output_dir(argv: list[str]) -> list[str]:
    # Ephemeral run-local paths (`-o <workdir>`, `--reduce-against <generated-spec>`)
    # are not part of the reproducible witness.
    out = list(argv)
    redacted = {"-o": "<workdir>", "--reduce-against": "<leaf-spec>"}
    for idx, part in enumerate(out):
        if part in redacted and idx + 1 < len(out):
            out[idx + 1] = redacted[part]
    return out


def reproducible_argv(argv: list[str]) -> list[str]:
    out = redact_output_dir(rel_argv(argv))
    out = ["<spec>" if Path(part).is_absolute() and Path(part).name == "capability-spec.json" else part for part in out]
    if out and Path(out[0]).name in {"neutrino-gen", "neutrino-emit"}:
        tool = Path(out[0]).name
        out[0] = f"out/tools/{tool}/{tool}"
    return out


def relativize_repo_paths(text: str) -> str:
    # Committed tool-output evidence must not embed the absolute worktree prefix.
    return text.replace(str(REPO.resolve()) + os.sep, "").replace(str(REPO) + os.sep, "")


def require_refused_no_dispatch(harness: Harness, cmd: list[str], out_dir: Path, ctx: str) -> subprocess.CompletedProcess[str]:
    # A front-end refusal that fabricates no dispatch: no coordination-plan/trace/spec/backend
    # artifact, and a manifest that positively records ok=false with empty artifacts.
    proc = harness.run(cmd, expect_ok=False, ctx=ctx)
    metadata = {"diagnostics.json", "manifest.json"}
    fabricated = [a for a in dir_artifacts(out_dir) if Path(a).name not in metadata]
    if fabricated:
        raise ValueError(f"{ctx}: rejected path fabricated dispatch artifact(s) {fabricated}")
    manifest_path = out_dir / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError(f"{ctx}: rejected path wrote no manifest to witness no-dispatch")
    manifest = load_json(manifest_path)
    if manifest.get("ok") is not False or manifest.get("artifacts"):
        raise ValueError(f"{ctx}: rejected manifest must record ok=false with empty artifacts, got ok={manifest.get('ok')!r} artifacts={manifest.get('artifacts')!r}")
    return proc


def trace_ledger_deltas(trace: dict[str, Any]) -> list[dict[str, Any]]:
    return [obs for obs in trace.get("trace", []) if "delta" in obs]


def diag_code(out_dir: Path) -> str | None:
    p = out_dir / "diagnostics.json"
    if not p.is_file():
        return None
    ds = load_json(p).get("diagnostics", [])
    return ds[0].get("code") if ds and isinstance(ds[0], dict) else None


def terminal_states(coordination_plan: dict[str, Any]) -> dict[str, str]:
    return {k: v for k, v in (coordination_plan.get("terminal") or {}).items() if v}


def observe_orchestration_overload(fixture: dict[str, Any], row_id: str, harness: Harness) -> dict[str, Any]:
    """Composite forcing ( / ADR M6_L2_BRIDGE §7).

    Derives `forcing.missing_orchestration_stratum` (Class 3 / LAYER_DECISION_REQUIRED)
    ONLY when this exact closed conjunction holds against the real tool. The Class-3
    row rests on AUTHORITATIVE L2 reducer evidence, not source->coordination-plan output alone:
      1. the leaf stages reduce through the L2 bridge (`neutrino-emit
         --kind=domain-reduction ... --reduce-against`) to the exact expected binding
         multiset, AND the domain-semantics edge records match exactly INCLUDING
         lossiness (the reduction projection alone omits lossiness);
      2. the stage-permuted twin reduces to a byte-identical graph — this proves only
         DECLARATION-ORDER invariance; the semantic ordering loss is witnessed by (3);
      3. an explicit recursive stage->stage CYCLE is refused by the reducer, pinned as
         its exact stable tuple (op + verifier obligation + anchor + nonzero exit) —
         l2.reduce edges must target L1 features, so concept->concept staging has no
         representation;
      4. the source-level ordered variant is refused before dispatch with a pinned
         structured code + anchor, fabricating no coordination-plan/trace/backend/effect;
      5. the bounded stage has explicit accept/refuse terminals with the exact declared
         values, and an unmet quorum posts NO partial effect. The declared
         timeout/fallback (read from the stage's capability-spec) and replay-idempotency
         are recorded but NOT behaviorally executed — the single-transition trace CLI
         cannot drive a deadline event or a second execution, a separate tooling gap
         that does NOT gate this row;
      6. the fixture pins architectural authority (ADR §7 +  + ).
    A generic parse/type/IO refusal never earns the layer decision — the classification
    is this whole conjunction, verified against the authoritative bridge.
    """
    inputs = require_obj(fixture, "inputs", row_id)
    expected = require_obj(fixture, "expectedObservation", row_id)
    authority = require_obj(fixture, "authority", row_id)
    # (6) authority pinned — fail closed if the pre-registered rule is not cited.
    for key in ("adr", "decision", "layerRule"):
        require_nonempty_string(authority, key, f"{row_id}.authority")
    if "581" not in authority["layerRule"] or "691" not in authority["decision"]:
        raise ValueError(f"{row_id}: authority must pin  (layerRule) and  (decision)")

    def src(name: str) -> Path:
        p = repo_path(require_nonempty_string(inputs, name, f"{row_id}.inputs"), f"{row_id}.inputs.{name}")
        if not p.is_file():
            raise ValueError(f"{row_id}.inputs.{name} does not exist: {rel(p)}")
        return p

    leaf, ordered = src("leafControl"), src("orderedVariant")
    l2_domain, l2_permuted, l2_recursive = src("l2Domain"), src("l2DomainPermuted"), src("l2DomainRecursive")
    stage, met_scn, miss_scn = src("failureStage"), src("metScenario"), src("missScenario")
    gen, emit = harness.tool("neutrino-gen"), harness.tool("neutrino-emit")
    expected_attests = expected.get("leafAttestations")
    if not isinstance(expected_attests, list) or len(expected_attests) < 2:
        raise ValueError(f"{row_id}.expectedObservation.leafAttestations must list >= 2 gates")
    anchor = require_nonempty_string(expected, "orderingAnchor", f"{row_id}.expectedObservation")
    token = require_nonempty_string(expected, "orderingToken", f"{row_id}.expectedObservation")
    ordered_code = require_nonempty_string(expected, "orderedRefusalCode", f"{row_id}.expectedObservation")
    recursive_op = require_nonempty_string(expected, "recursiveOp", f"{row_id}.expectedObservation")
    recursive_obligation = require_nonempty_string(expected, "recursiveObligation", f"{row_id}.expectedObservation")
    recursive_anchor = require_nonempty_string(expected, "recursiveAnchor", f"{row_id}.expectedObservation")
    expected_bindings = expected.get("l2Bindings")
    if not isinstance(expected_bindings, list) or len(expected_bindings) < 2:
        raise ValueError(f"{row_id}.expectedObservation.l2Bindings must list >= 2 bindings")
    expected_reductions = expected.get("l2Reductions")
    if not isinstance(expected_reductions, list) or len(expected_reductions) < 2 or not all("lossiness" in r for r in expected_reductions):
        raise ValueError(f"{row_id}.expectedObservation.l2Reductions must list >= 2 edge records carrying lossiness")
    expected_terminals = require_obj(expected, "terminals", f"{row_id}.expectedObservation")
    for k in ("success", "aborted"):
        require_nonempty_string(expected_terminals, k, f"{row_id}.expectedObservation.terminals")
    stage_timeout = require_nonempty_string(expected, "stageTimeout", f"{row_id}.expectedObservation")
    stage_fallback = require_nonempty_string(expected, "stageFallback", f"{row_id}.expectedObservation")

    # --- leaf coordination-plan (corroborating waist reduction + terminals) ---
    leaf_dir = harness.work_dir / row_id / "leaf"
    leaf_cmd = [gen, "--target=coordination-plan", str(leaf), "-o", str(leaf_dir)]
    harness.run(leaf_cmd, expect_ok=True, ctx=f"{row_id} leaf-control reduction")
    coordination_plan_path = leaf_dir / "coordination-plan.json"
    if not coordination_plan_path.is_file():
        raise ValueError(f"{row_id}: leaf-control reduction produced no coordination-plan.json")
    coordination_plan = load_json(coordination_plan_path)
    attests = coordination_plan.get("attestationPolicies")
    if not isinstance(attests, list) or not all(isinstance(a, str) for a in attests):
        raise ValueError(f"{row_id}: coordination-plan attestationPolicies must be a flat list of gate names")
    if sorted(attests) != sorted(expected_attests):
        raise ValueError(f"{row_id}: leaf attestations {attests!r} != expected {expected_attests!r}")
    ordering_edges = sorted(all_keys(coordination_plan) & ORDERING_EDGE_KEYS)
    if ordering_edges:
        raise ValueError(f"{row_id}: reduced coordination plan carries ordering edge(s) {ordering_edges!r}; loss witness absent")

    # (1) AUTHORITATIVE L2 reduction: the leaf's spec induces the closed requirement
    # set; both stage concepts reduce through the domain-reduction bridge.
    spec_dir = harness.work_dir / row_id / "leaf-spec"
    harness.run([gen, "--target=capability-spec", str(leaf), "-o", str(spec_dir)], expect_ok=True, ctx=f"{row_id} leaf capability-spec")
    spec = spec_dir / "capability-spec.json"
    red_cmd = [emit, "--kind=domain-reduction", str(l2_domain), "--reduce-against", str(spec)]
    red = harness.run(red_cmd, expect_ok=True, ctx=f"{row_id} L2 domain-reduction")
    bindings = json.loads(red.stdout).get("bindings", [])
    # Fail closed on the FULL binding multiset (concept, feature, relation, inducedBy,
    # edge) — not just the concept names — so a wrong feature/relation cannot earn the row.
    canon = lambda bs: sorted((json.dumps(b, sort_keys=True) for b in bs))
    if canon(bindings) != canon(expected_bindings):
        raise ValueError(f"{row_id}: L2 reduction bindings {bindings!r} != expected {expected_bindings!r}")
    # The reduction projection omits lossiness, so bind the row ALSO to the verified
    # domain-semantics edge records, which carry lossiness — the full semantic edge.
    sem_cmd = [emit, "--kind=domain-semantics", str(l2_domain)]
    sem = harness.run(sem_cmd, expect_ok=True, ctx=f"{row_id} L2 domain-semantics")
    reductions = json.loads(sem.stdout).get("reductions", [])
    if canon(reductions) != canon(expected_reductions):
        raise ValueError(f"{row_id}: domain-semantics reductions {reductions!r} != expected {expected_reductions!r}")

    # (2) declaration-order invariance: the stage-permuted twin (same edges, opposite
    # declaration order) reduces to a byte-identical canonical requirement graph. NB:
    # this proves the reduction is declaration-order-invariant; the semantic ordering
    # loss is witnessed separately by the concept-target refusal in (3).
    perm_cmd = [emit, "--kind=domain-reduction", str(l2_permuted), "--reduce-against", str(spec)]
    perm = harness.run(perm_cmd, expect_ok=True, ctx=f"{row_id} L2 domain-reduction (permuted)")
    if json.loads(perm.stdout).get("bindings", []) != bindings:
        raise ValueError(f"{row_id}: stage permutation changed the reduced graph; declaration-order invariance fails")

    # (3) a recursive stage->stage CYCLE is refused by the reducer. Pin the exact
    # stable refusal tuple this tool emits (op identity + verifier obligation + anchor
    # + nonzero exit) — no invented diagnostic code.
    rec_cmd = [emit, "--kind=domain-semantics", str(l2_recursive)]
    rec = harness.run(rec_cmd, expect_ok=False, ctx=f"{row_id} recursive-stage refusal")
    rec_expected = f"'{recursive_op}' op {recursive_obligation} '{recursive_anchor}'"
    if rec_expected not in rec.stdout:
        raise ValueError(f"{row_id}: recursive-stage refusal must match {rec_expected!r}; got:\n{rec.stdout}")

    # (4) source-level ordered variant refused before dispatch, pinned code + anchor,
    # no fabricated execution.
    ordered_dir = harness.work_dir / row_id / "ordered-rejected"
    ordered_cmd = [gen, "--target=coordination-plan", str(ordered), "-o", str(ordered_dir)]
    proc = require_refused_no_dispatch(harness, ordered_cmd, ordered_dir, f"{row_id} ordered-variant refusal")
    observed_code = diag_code(ordered_dir)
    if observed_code != ordered_code:
        raise ValueError(f"{row_id}: ordered refusal code {observed_code!r} != pinned {ordered_code!r}")
    if f"entry '{anchor}' guard references '{token}'" not in proc.stdout:
        raise ValueError(f"{row_id}: ordered refusal must name entry {anchor!r} + ordering token {token!r}; got:\n{proc.stdout}")

    # (5) terminal completeness (explicit accept + refuse) and the ONE behaviorally
    # observable runtime obligation the single-transition trace CLI can express: an
    # unmet quorum posts NO partial effect. The MET control makes it non-vacuous.
    terminals = terminal_states(coordination_plan)
    if terminals.get("success") != expected_terminals["success"] or terminals.get("aborted") != expected_terminals["aborted"]:
        raise ValueError(f"{row_id}: terminals {terminals!r} != expected accept/refuse {dict(expected_terminals)!r}")
    met_dir = harness.work_dir / row_id / "stage-met"
    harness.run([gen, "--target=coordination-trace", "--scenario", str(met_scn), str(stage), "-o", str(met_dir)], expect_ok=True, ctx=f"{row_id} stage met")
    met_trace = load_json(met_dir / "coordination-trace.json")
    if not trace_ledger_deltas(met_trace):
        raise ValueError(f"{row_id}: stage MET control posted no effect; miss-suppression would be vacuous")
    miss_dir = harness.work_dir / row_id / "stage-miss"
    harness.run([gen, "--target=coordination-trace", "--scenario", str(miss_scn), str(stage), "-o", str(miss_dir)], expect_ok=True, ctx=f"{row_id} stage miss")
    miss_trace = load_json(miss_dir / "coordination-trace.json")
    miss_deltas = trace_ledger_deltas(miss_trace)
    miss_balances = miss_trace.get("nextState", {}).get("balances", [])
    if miss_deltas or miss_balances:
        raise ValueError(f"{row_id}: unmet quorum fabricated a partial effect (deltas={len(miss_deltas)}, balances={miss_balances})")

    # The declared (NOT behaviorally executed) runtime facts: the attest carries a
    # PT72H timeout + fallback=abort, and the coordination plan is replay-idempotent
    # with every transition idempotency=reject. The single-transition coordination-trace CLI
    # exposes neither a clock/deadline event nor a prior-state input, so the timeout
    # -> fallback transition and a second-execution replay CANNOT be driven here. That
    # is recorded honestly as a separate runtime/tooling gap, NOT asserted as verified,
    # and does NOT gate the layer row (which rests on the L2-orchestration evidence).
    stage_cp_dir = harness.work_dir / row_id / "stage-coordination-plan"
    harness.run([gen, "--target=coordination-plan", str(stage), "-o", str(stage_cp_dir)], expect_ok=True, ctx=f"{row_id} stage coordination-plan")
    stage_coordination_plan = load_json(stage_cp_dir / "coordination-plan.json")
    lts = stage_coordination_plan.get("lifecycleTransitions", [])
    met_posted = met_trace.get("nextState", {}).get("postedKeys", [])
    # Derive the declared timeout/fallback from the stage's OWN capability-spec (the
    # single-attestation stage is safe for capability-spec) and require exact values —
    # never a hard-coded literal. Changing them in the source must break this.
    stage_spec_dir = harness.work_dir / row_id / "stage-spec"
    harness.run([gen, "--target=capability-spec", str(stage), "-o", str(stage_spec_dir)], expect_ok=True, ctx=f"{row_id} stage capability-spec")
    stage_atts = load_json(stage_spec_dir / "capability-spec.json").get("attestations", [])
    if not stage_atts or stage_atts[0].get("timeout") != stage_timeout or stage_atts[0].get("fallback") != stage_fallback:
        raise ValueError(f"{row_id}: stage timeout/fallback {stage_atts[:1]!r} != expected {(stage_timeout, stage_fallback)!r}")

    proof_path = harness.evidence_dir / f"{row_id}.orchestration-overload.json"
    write_json(proof_path, {
        "kind": "orchestration-overload-proof",
        "rowId": row_id,
        "leafReduction": {"argv": reproducible_argv(leaf_cmd), "exitCode": 0, "attestationPolicies": attests, "coordinationPlanSha256": sha256(coordination_plan_path)},
        "l2Reduction": {"argv": reproducible_argv(red_cmd), "exitCode": red.returncode, "bindings": bindings, "bindingsSha256": hashlib.sha256(json.dumps(bindings, sort_keys=True).encode()).hexdigest()},
        "l2SemanticEdges": {"argv": reproducible_argv(sem_cmd), "reductions": reductions},
        "declarationOrderInvariance": {"argv": reproducible_argv(perm_cmd), "canonicalGraphIdentical": True, "note": "proves declaration-order invariance; semantic ordering loss is witnessed by recursiveRefusal"},
        "recursiveRefusal": {"argv": reproducible_argv(rec_cmd), "exitCode": rec.returncode, "op": recursive_op, "obligation": recursive_obligation, "anchor": recursive_anchor, "output": relativize_repo_paths(rec.stdout)},
        "orderedRefusal": {"argv": reproducible_argv(ordered_cmd), "exitCode": proc.returncode, "code": observed_code, "anchor": anchor, "token": token, "output": relativize_repo_paths(proc.stdout), "noDispatch": {"ok": False, "artifacts": []}},
        "terminals": terminals,
        "unmetQuorumNoEffect": {"metDeltas": len(trace_ledger_deltas(met_trace)), "missDeltas": len(miss_deltas), "missBalances": miss_balances, "missOutcome": miss_trace.get("outcome")},
        "runtimeDisciplineDeclaredNotExecuted": {
            "timeoutFallback": {"declared": {"timeout": stage_atts[0].get("timeout"), "fallback": stage_atts[0].get("fallback")}, "source": "stage capability-spec attestations[0]", "behaviorallyExecuted": False, "reason": "coordination-trace CLI exposes no clock/deadline event"},
            "replayIdempotency": {"declared": {"idempotent": stage_coordination_plan.get("replay", {}).get("idempotent"), "allTransitionsReject": all(t.get("idempotency") == "reject" for t in lts), "metPostedKeys": met_posted}, "behaviorallyExecuted": False, "reason": "coordination-trace CLI exposes no prior-state input for a second execution"},
        },
        "authority": {k: authority[k] for k in ("adr", "decision", "layerRule")},
    })
    n = len(attests)
    return {
        "code": "forcing.missing_orchestration_stratum",
        "class": "3",
        "disposition": "LAYER_DECISION_REQUIRED",
        "failedVerifierObligation": "L2 cannot preserve the required assessor-before-reviewer dependency through reduction",
        "minimalCounterexample": (
            f"The {n} review stages reduce to a canonical requirement graph whose bindings are fixed and "
            "declaration-order invariant, and an explicit recursive stage->stage relation is refused by the "
            "reducer (l2.reduce edges must target L1 features, so concept->concept staging has no "
            "representation); the bounded assessor-before-reviewer dependency therefore cannot be expressed, "
            "and a single L2 must carry both the per-stage coordination and the cross-stage orchestration "
            "(ADR M6_L2_BRIDGE §7 overload)."
        ),
        "linkedDecision": f"{authority['decision']}; {authority['adr']}; {authority['layerRule']}",
        "evidence": {"type": "refusal", "ref": rel(proof_path)},
    }


def observe_pay_for_result(fixture: dict[str, Any], row_id: str, harness: Harness) -> dict[str, Any]:
    """Observe the executable subset of the pay-for-result contract.

    The accepted row is deliberately partial: this observer executes atomic guarded
    settlement and rejection suppression, while deadline and second-invocation behavior
    remain an explicit Class-1 sibling because coordination-trace has no clock or prior
    state input.
    """
    inputs = require_obj(fixture, "inputs", row_id)
    expected = require_obj(fixture, "expectedObservation", row_id)
    authority = require_obj(fixture, "authority", row_id)
    for key in ("adr", "decision", "layerRule"):
        require_nonempty_string(authority, key, f"{row_id}.authority")
    if "581" not in authority["layerRule"] or "692" not in authority["decision"]:
        raise ValueError(f"{row_id}: authority must pin  (layerRule) and  (decision)")

    def src(name: str) -> Path:
        p = repo_path(require_nonempty_string(inputs, name, f"{row_id}.inputs"), f"{row_id}.inputs.{name}")
        if not p.is_file():
            raise ValueError(f"{row_id}.inputs.{name} does not exist: {rel(p)}")
        return p

    source, l2_domain = src("source"), src("l2Domain")
    mixed_guard = src("mixedGuardVariant")
    accepted_scn, rejected_scn = src("acceptedScenario"), src("rejectedScenario")
    gen, emit = harness.tool("neutrino-gen"), harness.tool("neutrino-emit")
    result_guard = require_nonempty_string(expected, "resultGuard", f"{row_id}.expectedObservation")
    guard_key = require_nonempty_string(expected, "guardKey", f"{row_id}.expectedObservation")
    settlement_key = require_nonempty_string(expected, "settlementKey", f"{row_id}.expectedObservation")
    balance_anchor = require_nonempty_string(expected, "balanceRuleAnchor", f"{row_id}.expectedObservation")
    expected_terminals = require_obj(expected, "terminals", f"{row_id}.expectedObservation")
    for k in ("success", "aborted"):
        require_nonempty_string(expected_terminals, k, f"{row_id}.expectedObservation.terminals")
    expected_attestation = require_obj(expected, "attestation", f"{row_id}.expectedObservation")
    expected_effects = expected.get("effects")
    if not isinstance(expected_effects, list) or len(expected_effects) != 2 or not all(isinstance(e, dict) for e in expected_effects):
        raise ValueError(f"{row_id}.expectedObservation.effects must contain the exact debit and credit")
    expected_features = expected.get("l2Features")
    if not isinstance(expected_features, list) or len(expected_features) != len(set(expected_features)) or not all(isinstance(f, str) and f for f in expected_features):
        raise ValueError(f"{row_id}.expectedObservation.l2Features must be a unique non-empty feature list")

    # The direct coordination artifact must expose exactly two typed effects in one balanced group.
    cp_dir = harness.work_dir / row_id / "reduce"
    cp_cmd = [gen, "--target=coordination-plan", str(source), "-o", str(cp_dir)]
    harness.run(cp_cmd, expect_ok=True, ctx=f"{row_id} pay-for-result reduction")
    coordination_plan = load_json(cp_dir / "coordination-plan.json")
    if coordination_plan.get("balanced") is not True:
        raise ValueError(f"{row_id}: coordination plan is not balanced: {coordination_plan.get('balanced')!r}")
    expected_coordination_effects = [
        {
            "attestation": "",
            "gateMode": "temporal-suppress",
            "gatePolicy": expected_attestation.get("input"),
            "guard": result_guard,
            "guardKey": guard_key,
            "index": e.get("index"),
            "kind": e.get("kind"),
            "name": e.get("name"),
        }
        for e in expected_effects
    ]
    coordination_effects = coordination_plan.get("effects")
    if coordination_effects != expected_coordination_effects:
        raise ValueError(f"{row_id}: exact typed coordination effects differ: {coordination_effects!r} != {expected_coordination_effects!r}")
    expected_group = {
        "attestation": "",
        "credits": 1,
        "debits": 1,
        "effects": [e["index"] for e in expected_effects],
        "firstIndex": expected_effects[0]["index"],
        "gateMode": "temporal-suppress",
        "gatePolicy": expected_attestation.get("input"),
        "guard": result_guard,
        "guardKey": guard_key,
        "mustBalance": True,
    }
    if coordination_plan.get("effectGroups") != [expected_group]:
        raise ValueError(f"{row_id}: exact balanced effect group differs: {coordination_plan.get('effectGroups')!r}")
    if coordination_plan.get("attestationPolicies") != [expected_attestation.get("input")]:
        raise ValueError(f"{row_id}: wrong attestation policy association: {coordination_plan.get('attestationPolicies')!r}")
    terminals = terminal_states(coordination_plan)
    if terminals.get("success") != expected_terminals["success"] or terminals.get("aborted") != expected_terminals["aborted"]:
        raise ValueError(f"{row_id}: terminals {terminals!r} != expected {dict(expected_terminals)!r}")
    lts = coordination_plan.get("lifecycleTransitions", [])
    replay = coordination_plan.get("replay", {})
    if not (
        replay == {"idempotent": True, "key": settlement_key}
        and coordination_plan.get("workflowKey") == settlement_key
        and lts
        and all(t.get("idempotency") == "reject" for t in lts)
    ):
        raise ValueError(f"{row_id}: exactly-once discipline missing (replay={replay!r})")

    # The capability-spec must carry the exact value bindings, typed guard AST, and
    # attestation contract. This closes dropped/extra/wrong-leg and policy drift.
    spec_dir = harness.work_dir / row_id / "spec"
    spec_cmd = [gen, "--target=capability-spec", str(source), "-o", str(spec_dir)]
    harness.run(spec_cmd, expect_ok=True, ctx=f"{row_id} capability-spec")
    spec_path = spec_dir / "capability-spec.json"
    capability_spec = load_json(spec_path)
    if capability_spec.get("attestations") != [expected_attestation]:
        raise ValueError(f"{row_id}: exact attestation contract differs: {capability_spec.get('attestations')!r}")

    expected_when = {
        "ast": {
            "args": [{"dtype": "evidence", "kind": "var", "name": expected_attestation.get("input")}],
            "dtype": "extension",
            "kind": "call",
            "name": "accepted",
        },
        "expr": result_guard,
    }
    expected_spec_effects = []
    for e in expected_effects:
        expected_spec_effects.append(
            {
                "amount": {"kind": "ref", "value": e.get("amountInput")},
                "currency": {"kind": "ref", "value": e.get("currencyInput")},
                "idempotencyKey": {"kind": "ref", "value": e.get("idempotencyInput")},
                "kind": e.get("kind"),
                "ledger": e.get("ledger"),
                "name": e.get("name"),
                "owner": e.get("owner"),
                "participant": e.get("participant"),
                "party": {"kind": "ref", "value": e.get("partyInput")},
                "when": expected_when,
            }
        )
    if capability_spec.get("effects") != expected_spec_effects:
        raise ValueError(f"{row_id}: exact capability-spec effects differ: {capability_spec.get('effects')!r}")
    if capability_spec.get("lifecycle", {}).get("instanceKey") != {"declared": settlement_key, "fields": [settlement_key]}:
        raise ValueError(f"{row_id}: stable job identity is not exact: {capability_spec.get('lifecycle', {}).get('instanceKey')!r}")

    # Direct and from-spec coordination artifacts must be byte-semantically identical.
    spec_coordination_dir = harness.work_dir / row_id / "coordination-from-spec"
    spec_coordination_cmd = [gen, "--target=coordination-plan", "--from-spec", str(spec_path), "-o", str(spec_coordination_dir)]
    harness.run(spec_coordination_cmd, expect_ok=True, ctx=f"{row_id} from-spec coordination reconstruction")
    if load_json(spec_coordination_dir / "coordination-plan.json") != coordination_plan:
        raise ValueError(f"{row_id}: direct and from-spec coordination reconstructions diverged")

    # The source-neutral L2 model covers every normalized requirement and yields
    # the same canonical reduction against source and capability-spec coordination.
    l2_source_cmd = [emit, "--kind=domain-reduction", str(l2_domain), "--reduce-against", str(source)]
    l2_source = harness.run(l2_source_cmd, expect_ok=True, ctx=f"{row_id} L2 reduction against source")
    l2_spec_cmd = [emit, "--kind=domain-reduction", str(l2_domain), "--reduce-against", str(spec_path)]
    l2_spec = harness.run(l2_spec_cmd, expect_ok=True, ctx=f"{row_id} L2 reduction against spec")
    source_reduction, spec_reduction = json.loads(l2_source.stdout), json.loads(l2_spec.stdout)
    if source_reduction != spec_reduction:
        raise ValueError(f"{row_id}: source/L2/spec normalized requirement reductions diverged")
    bindings = source_reduction.get("bindings", [])
    binding_features = [b.get("feature") for b in bindings]
    if sorted(binding_features) != sorted(expected_features) or len(bindings) != len(expected_features):
        raise ValueError(f"{row_id}: L2 normalized requirements {binding_features!r} != expected {expected_features!r}")
    if any(not all(isinstance(b.get(k), str) and b[k] for k in ("concept", "edge", "feature", "inducedBy", "relation")) for b in bindings):
        raise ValueError(f"{row_id}: L2 binding is incomplete: {bindings!r}")
    l2_sem_cmd = [emit, "--kind=domain-semantics", str(l2_domain)]
    l2_sem = harness.run(l2_sem_cmd, expect_ok=True, ctx=f"{row_id} L2 domain-semantics")
    reductions = json.loads(l2_sem.stdout).get("reductions", [])
    if sorted(r.get("to") for r in reductions) != sorted(expected_features) or any(r.get("lossiness") != "lossless" for r in reductions):
        raise ValueError(f"{row_id}: source-neutral L2 edges do not exactly cover lossless requirements: {reductions!r}")

    # Accepted result: derive the expected key and ledger deltas from the scenario,
    # then require the trace exactly (not merely a zero sum or arbitrary posted key).
    accepted_inputs = require_obj(load_json(accepted_scn), "inputs", f"{row_id}.acceptedScenario")
    expected_posted = [accepted_inputs.get(settlement_key)]
    if not isinstance(expected_posted[0], str) or not expected_posted[0]:
        raise ValueError(f"{row_id}: accepted scenario has no concrete {settlement_key!r}")
    expected_deltas = []
    for e in expected_effects:
        amount = accepted_inputs.get(e.get("amountInput"))
        if type(amount) not in {int, float}:
            raise ValueError(f"{row_id}: scenario amount {e.get('amountInput')!r} is not numeric")
        expected_deltas.append(
            {
                "currency": accepted_inputs.get(e.get("currencyInput")),
                "delta": -amount if e.get("kind") == "debit" else amount,
                "effect": e.get("name"),
                "kind": "ledger-delta",
                "ledger": e.get("ledger"),
                "party": accepted_inputs.get(e.get("partyInput")),
            }
        )
    acc_dir = harness.work_dir / row_id / "accepted"
    acc_cmd = [gen, "--target=coordination-trace", "--scenario", str(accepted_scn), str(source), "-o", str(acc_dir)]
    harness.run(acc_cmd, expect_ok=True, ctx=f"{row_id} accepted settlement")
    acc_trace = load_json(acc_dir / "coordination-trace.json")
    settle_deltas = trace_ledger_deltas(acc_trace)
    terminal_trace = [o for o in acc_trace.get("trace", []) if o.get("kind") == "terminal"]
    if acc_trace.get("outcome") != "terminal" or terminal_trace != [{"kind": "terminal", "state": expected_terminals["success"]}]:
        raise ValueError(f"{row_id}: accepted result did not reach the exact success terminal")
    if settle_deltas != expected_deltas:
        raise ValueError(f"{row_id}: exact accepted settlement deltas differ: {settle_deltas!r} != {expected_deltas!r}")
    posted = acc_trace.get("nextState", {}).get("postedKeys", [])
    if posted != expected_posted:
        raise ValueError(f"{row_id}: accepted result posted key {posted!r} != scenario-derived {expected_posted!r}")
    fs_dir = harness.work_dir / row_id / "from-spec"
    fs_cmd = [gen, "--target=coordination-trace", "--from-spec", "--scenario", str(accepted_scn), str(spec_path), "-o", str(fs_dir)]
    harness.run(fs_cmd, expect_ok=True, ctx=f"{row_id} from-spec trace")
    if load_json(fs_dir / "coordination-trace.json") != acc_trace:
        raise ValueError(f"{row_id}: direct and from-spec settlement traces diverged")

    # A rejected/unaccepted result must agree through source and capability-spec
    # execution before its empty settlement state is accepted as evidence.
    rej_dir = harness.work_dir / row_id / "rejected"
    rej_cmd = [gen, "--target=coordination-trace", "--scenario", str(rejected_scn), str(source), "-o", str(rej_dir)]
    harness.run(rej_cmd, expect_ok=True, ctx=f"{row_id} rejected result")
    rej_trace = load_json(rej_dir / "coordination-trace.json")
    rej_fs_dir = harness.work_dir / row_id / "rejected-from-spec"
    rej_fs_cmd = [gen, "--target=coordination-trace", "--from-spec", "--scenario", str(rejected_scn), str(spec_path), "-o", str(rej_fs_dir)]
    harness.run(rej_fs_cmd, expect_ok=True, ctx=f"{row_id} rejected result from-spec")
    if load_json(rej_fs_dir / "coordination-trace.json") != rej_trace:
        raise ValueError(f"{row_id}: direct and from-spec unaccepted traces diverged")
    rej_deltas = trace_ledger_deltas(rej_trace)
    rej_balances = rej_trace.get("nextState", {}).get("balances", [])
    rej_posted = rej_trace.get("nextState", {}).get("postedKeys", [])
    if rej_deltas or rej_balances or rej_posted:
        raise ValueError(f"{row_id}: unaccepted result fabricated settlement state (deltas={len(rej_deltas)}, balances={rej_balances}, posted={rej_posted})")

    # This negative proves only the narrow rule it contains: an unguarded debit and
    # guarded credit do not balance. It is not evidence of a refund or timeout hook.
    mixed_dir = harness.work_dir / row_id / "mixed-guard-rejected"
    mixed_cmd = [gen, "--target=coordination-plan", str(mixed_guard), "-o", str(mixed_dir)]
    mixed_proc = require_refused_no_dispatch(harness, mixed_cmd, mixed_dir, f"{row_id} mixed-guard refusal")
    if balance_anchor not in mixed_proc.stdout:
        raise ValueError(f"{row_id}: mixed-guard partial transfer must be refused with {balance_anchor!r}; got:\n{mixed_proc.stdout}")

    operation = "reduce and execute atomic guarded pay-for-result settlement"
    proof_path = harness.evidence_dir / f"{row_id}.pay-for-result.json"
    all_transitions_reject = all(t.get("idempotency") == "reject" for t in lts)
    replay_observation = dict(replay, allTransitionsReject=all_transitions_reject)
    proof = {
        "kind": "pay-for-result-proof",
        "rowId": row_id,
        "reduction": {
            "argv": reproducible_argv(cp_cmd),
            "balanced": True,
            "effects": coordination_effects,
            "effectGroup": expected_group,
            "attestationPolicies": coordination_plan.get("attestationPolicies"),
            "attestation": expected_attestation,
            "terminals": terminals,
            "replay": replay_observation,
        },
        "parity": {
            "directPlanEqualsPlanFromSpec": True,
            "sourceReductionEqualsSpecReduction": True,
            "acceptedDirectTraceEqualsFromSpecTrace": True,
            "unacceptedDirectTraceEqualsFromSpecTrace": True,
            "l2Features": sorted(binding_features),
            "l2Bindings": bindings,
            "l2SourceArgv": reproducible_argv(l2_source_cmd),
            "l2SpecArgv": reproducible_argv(l2_spec_cmd),
        },
        "acceptedSettlement": {
            "argv": reproducible_argv(acc_cmd),
            "outcome": acc_trace.get("outcome"),
            "deltas": settle_deltas,
            "postedKeys": posted,
            "terminal": expected_terminals["success"],
        },
        "unacceptedNoSettlement": {
            "directArgv": reproducible_argv(rej_cmd),
            "fromSpecArgv": reproducible_argv(rej_fs_cmd),
            "deltas": rej_deltas,
            "balances": rej_balances,
            "postedKeys": rej_posted,
            "outcome": rej_trace.get("outcome"),
        },
        "mixedGuardBoundary": {
            "argv": reproducible_argv(mixed_cmd),
            "exitCode": mixed_proc.returncode,
            "anchor": balance_anchor,
            "output": relativize_repo_paths(mixed_proc.stdout),
            "note": "proves only that an unguarded debit plus guarded credit is refused; it does not claim a compensation/refund flow",
        },
        "executionGap": {
            "deadline": {"declared": {"timeout": expected_attestation.get("timeout"), "fallback": expected_attestation.get("fallback")}, "behaviorallyExecuted": False, "reason": "coordination-trace CLI exposes no clock/deadline event"},
            "secondInvocation": {"declared": {"idempotent": replay.get("idempotent"), "allTransitionsReject": all_transitions_reject, "key": replay.get("key")}, "behaviorallyExecuted": False, "reason": "coordination-trace CLI exposes no prior-state input for a second invocation"},
        },
        "authority": {k: authority[k] for k in ("adr", "decision", "layerRule")},
    }
    write_json(proof_path, proof)
    harness.observed_proofs[row_id] = (proof_path, proof)
    return {
        "operation": operation,
        "evidence": {"type": "executable", "ref": rel(proof_path)},
        "linkedDecision": f"{authority['decision']}; {authority['adr']}; {authority['layerRule']}",
    }


def emit_row(fixture: dict[str, Any], harness: Harness) -> dict[str, Any]:
    path = fixture.get("path")
    if path not in ALLOWED_PATHS:
        raise ValueError(f"{fixture.get('fixtureId', '<unknown>')}.path must be one of {sorted(ALLOWED_PATHS)}")
    unknown = sorted(set(fixture) - PATH_FIELDS[path])
    if unknown:
        raise ValueError(f"{fixture.get('fixtureId', '<unknown>')} has unknown field(s) {unknown}")
    row = base_row(fixture)
    row_id = row["rowId"]
    if path == "representable":
        operation, evidence = observe_representable(fixture, row_id, harness)
        row.update({
            "outcome": "accepted",
            "class": None,
            "disposition": "L1_CORE",
            "failedVerifierObligation": None,
            "supportStatus": "present",
            "currentArtifactOperation": operation,
            "evidenceRefs": [evidence],
        })
        return row
    if path == "failed-reduction":
        observed = observe_failed_reduction(fixture, row_id, harness)
        row.update({
            "outcome": "unresolved",
            "class": observed["class"],
            "disposition": observed["disposition"],
            "failedVerifierObligation": observed["failureTemplate"].format(anchor=observed["anchor"]),
            "minimalCounterexample": observed["minimalCounterexampleTemplate"].format(anchor=observed["anchor"]),
            "linkedDecision": observed["linkedDecision"],
            "supportStatus": "absent",
            "currentArtifactOperation": None,
            "evidenceRefs": [observed["evidence"]],
        })
        return row
    if path == "pay-for-result":
        observed = observe_pay_for_result(fixture, row_id, harness)
        row.update({
            "outcome": "accepted",
            "class": None,
            "disposition": "L1_CORE",
            "failedVerifierObligation": None,
            "supportStatus": "partial",
            "currentArtifactOperation": observed["operation"],
            "linkedDecision": observed["linkedDecision"],
            "evidenceRefs": [observed["evidence"]],
        })
        return row
    if path == "tooling-gap":
        expected = require_obj(fixture, "expectedObservation", row_id)
        klass = require_nonempty_string(expected, "class", f"{row_id}.expectedObservation")
        if klass != "1":
            raise ValueError(f"{row_id}.expectedObservation.class must be '1' for a tooling gap")
        disposition = require_nonempty_string(expected, "disposition", f"{row_id}.expectedObservation")
        if disposition not in {"L1_CORE", "L2_REFINEMENT"}:
            raise ValueError(f"{row_id}.expectedObservation.disposition must identify the blocked executable layer")
        companion_row_id = require_nonempty_string(expected, "companionRowId", f"{row_id}.expectedObservation")
        observed_companion = harness.observed_proofs.get(companion_row_id)
        if observed_companion is None:
            raise ValueError(f"{row_id}: companion proof {companion_row_id!r} was not observed in this run")
        evidence_ref = require_nonempty_string(expected, "evidenceRef", f"{row_id}.expectedObservation")
        cited_path = repo_path(evidence_ref, f"{row_id}.expectedObservation.evidenceRef")
        if not cited_path.is_file():
            raise ValueError(f"{row_id}: cited companion evidence does not exist: {evidence_ref}")
        cited_proof = load_json(cited_path)
        observed_proof = observed_companion[1]
        derived = validate_pay_for_result_execution_gap(observed_proof, companion_row_id, f"{row_id}.observedCompanion")
        validate_pay_for_result_execution_gap(cited_proof, companion_row_id, f"{row_id}.citedCompanion")
        for key in ("executionGap", "authority"):
            if cited_proof.get(key) != observed_proof.get(key):
                raise ValueError(f"{row_id}: cited companion {key} does not match the proof observed in this run")
        cited_reduction = require_obj(cited_proof, "reduction", f"{row_id}.citedCompanion")
        observed_reduction = require_obj(observed_proof, "reduction", f"{row_id}.observedCompanion")
        for key in ("attestation", "replay"):
            if cited_reduction.get(key) != observed_reduction.get(key):
                raise ValueError(f"{row_id}: cited companion reduction.{key} does not match the proof observed in this run")
        for key in ("failedVerifierObligation", "minimalCounterexample"):
            if expected.get(key) != derived[key]:
                raise ValueError(f"{row_id}.expectedObservation.{key} does not match the companion execution gap")
        authority = require_obj(observed_proof, "authority", f"{row_id}.observedCompanion")
        linked_decision = f"{require_nonempty_string(authority, 'decision', f'{row_id}.observedCompanion.authority')}; {require_nonempty_string(authority, 'layerRule', f'{row_id}.observedCompanion.authority')}"
        if expected.get("linkedDecision") != linked_decision:
            raise ValueError(f"{row_id}.expectedObservation.linkedDecision does not match the companion authority")
        row.update({
            "outcome": "unresolved",
            "class": klass,
            "disposition": disposition,
            "failedVerifierObligation": derived["failedVerifierObligation"],
            "minimalCounterexample": derived["minimalCounterexample"],
            "linkedDecision": linked_decision,
            "supportStatus": "absent",
            "currentArtifactOperation": None,
            "evidenceRefs": [{"type": "executable", "ref": evidence_ref}],
        })
        return row
    if path == "orchestration-overload":
        observed = observe_orchestration_overload(fixture, row_id, harness)
        row.update({
            "outcome": "unresolved",
            "class": observed["class"],
            "disposition": observed["disposition"],
            "failedVerifierObligation": observed["failedVerifierObligation"],
            "minimalCounterexample": observed["minimalCounterexample"],
            "linkedDecision": observed["linkedDecision"],
            "supportStatus": "absent",
            "currentArtifactOperation": None,
            "evidenceRefs": [observed["evidence"]],
        })
        return row
    if path == "orthogonal":
        expected = require_obj(fixture, "expectedObservation", row_id)
        disposition = require_nonempty_string(expected, "disposition", f"{row_id}.expectedObservation")
        if disposition not in {"L3_RUNTIME", "DESCRIPTIVE_ONLY"}:
            raise ValueError(f"{row_id}.expectedObservation.disposition must be L3_RUNTIME or DESCRIPTIVE_ONLY")
        row.update({
            "outcome": "accepted",
            "class": None,
            "disposition": disposition,
            "failedVerifierObligation": None,
            "supportStatus": "absent",
            "currentArtifactOperation": None,
            "evidenceRefs": [],
        })
        return row
    observed = observe_refusal(fixture, row_id, harness)
    row.update({
        "outcome": "unresolved",
        "class": observed["class"],
        "disposition": observed["disposition"],
        "failedVerifierObligation": observed["failureTemplate"].format(anchor=observed["anchor"]),
        "supportStatus": "absent",
        "currentArtifactOperation": None,
        "evidenceRefs": [observed["evidence"]],
    })
    return row


def emit_register(fixture_doc: dict[str, Any], harness: Harness) -> dict[str, Any]:
    if fixture_doc.get("kind") != "neutrino.pressure-loop-forcing-fixtures":
        raise ValueError("fixture kind must be neutrino.pressure-loop-forcing-fixtures")
    if fixture_doc.get("schemaVersion") != FIXTURE_VERSION:
        raise ValueError("fixture schemaVersion must be 1")
    fixtures = fixture_doc.get("fixtures")
    if not isinstance(fixtures, list) or not fixtures:
        raise ValueError("fixtures must contain at least one fixture")
    rows = [emit_row(copy.deepcopy(f), harness) for f in fixtures]
    rows.sort(key=lambda r: (r["rowId"], r["requirement"]))
    seen: set[str] = set()
    for row in rows:
        if row["rowId"] in seen:
            raise ValueError(f"duplicate fixture rowId {row['rowId']!r}")
        seen.add(row["rowId"])
    return {"kind": KIND, "schemaVersion": SCHEMA_VERSION, "rows": rows}


def validate_register_file(path: Path) -> None:
    proc = subprocess.run([sys.executable, str(VALIDATOR), str(path), "--json"], cwd=REPO, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if proc.returncode != 0:
        raise ValueError(f"emitted register failed v2 validation:\n{proc.stdout}")


def validated_text(reg: dict[str, Any], tmp_dir: Path) -> str:
    out = tmp_dir / "register.json"
    write_json(out, reg)
    validate_register_file(out)
    return out.read_text(encoding="utf-8")


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def make_stub_tools(td: Path, *, tamper_trace: bool = False, fail_representable: bool = False, reduction_succeeds: bool = False) -> Path:
    tool_dir = td / "tools"
    tool_dir.mkdir(parents=True)
    trace = {
        "outcome": "terminal",
        "trace": [{"kind": "authorization"}, {"name": "bonus_amount"}, {"effect": "pay_out", "delta": -1000}, {"effect": "bonus_in", "delta": 1001}],
        "nextState": {
            "balances": [{"ledger": "a.src", "party": "buyer-1", "currency": "EUR", "balance": -2001}, {"ledger": "b.dst", "party": "seller-1", "currency": "EUR", "balance": 2001}],
            "keyStatus": {"F-1": "CLOSED"},
            "keyClaim": {},
            "committedGroups": {},
            "postedKeys": [] if tamper_trace else ["F-1"],
        },
    }
    gen = tool_dir / "neutrino-gen"
    gen.write_text(f"""#!/usr/bin/env python3
import json, os, sys
args=sys.argv[1:]
target=args[args.index('--target')+1] if '--target' in args else ''
for a in args:
    if a.startswith('--target='): target=a.split('=',1)[1]
if target=='capability-spec':
    out=args[args.index('-o')+1]; os.makedirs(out, exist_ok=True); json.dump({{"kind":"capability-spec"}}, open(os.path.join(out,'capability-spec.json'),'w')); sys.exit(0)
if target=='coordination-trace':
    {'print("forced representable failure"); sys.exit(7)' if fail_representable else ''}
    out=args[args.index('-o')+1]; os.makedirs(out, exist_ok=True); json.dump({trace!r}, open(os.path.join(out,'coordination-trace.json'),'w'), indent=2, sort_keys=True); sys.exit(0)
print('--target must be known')
sys.exit(2)
""", encoding="utf-8")
    emit = tool_dir / "neutrino-emit"
    emit.write_text(f"""#!/usr/bin/env python3
import sys
if '--kind=domain-reduction' in sys.argv:
    {'print("ok"); sys.exit(0)' if reduction_succeeds else 'print("error: unregistered feature totally:madeup"); sys.exit(4)'}
print("error: unsupported dispatch boundary")
sys.exit(2)
""", encoding="utf-8")
    for tool in (gen, emit):
        tool.chmod(0o755)
    return tool_dir


def make_orchestration_stub(td: Path, *, mode: str = "ok") -> Path:
    """A neutrino-gen mock for the orchestration-overload composite observer.

    Default: leaf reduces to a coordination plan carrying both gates as an unordered
    set (no ordering edge); the ordered variant is refused before dispatch (manifest
    ok=false, no coordination-plan). `mode` injects exactly one broken conjunction
    element so each non-vacuity probe proves the row is withheld.
    """
    tool_dir = td / "tools"
    tool_dir.mkdir(parents=True, exist_ok=True)
    gen = tool_dir / "neutrino-gen"
    gen.write_text(f"""#!/usr/bin/env python3
import json, os, sys
mode = {mode!r}
args = sys.argv[1:]
def opt(name):
    for i, a in enumerate(args):
        if a == name and i + 1 < len(args): return args[i + 1]
        if a.startswith(name + '='): return a.split('=', 1)[1]
    return ''
target = opt('--target')
scn = opt('--scenario')
src = next((a for a in args if a.endswith('.neu')), '')
out = opt('-o') or '.'
os.makedirs(out, exist_ok=True)
def w(name, obj): json.dump(obj, open(os.path.join(out, name), 'w'))
def refuse(msg):
    w('manifest.json', {{'ok': False, 'artifacts': []}}); w('diagnostics.json', {{'diagnostics': [{{'code': 'source.parse'}}]}}); print(msg); sys.exit(4)
kind = 'ordered' if 'ordered' in src else 'stage' if 'stage' in src else 'leaf'

if target == 'capability-spec':
    spec = {{'kind': 'capability-spec'}}
    if 'stage' in src:
        tmo = 'PT1H' if mode == 'timeout-drift' else 'PT72H'
        spec['attestations'] = [{{'timeout': tmo, 'fallback': 'abort', 'quorum': {{'threshold': 1}}}}]
    w('capability-spec.json', spec); w('manifest.json', {{'ok': True, 'artifacts': ['capability-spec.json']}}); sys.exit(0)
if target == 'coordination-trace':
    if 'miss' in scn and mode != 'miss-posts':
        w('coordination-trace.json', {{'outcome': 'no-progress', 'trace': [], 'nextState': {{'balances': []}}}}); sys.exit(0)
    w('coordination-trace.json', {{'outcome': 'terminal', 'trace': [{{'effect': 'award_out', 'delta': -1000}}, {{'effect': 'award_in', 'delta': 1000}}], 'nextState': {{'balances': [{{'ledger': 'board.reserve', 'balance': -1000}}], 'postedKeys': ['C-1']}}}}); sys.exit(0)

# coordination-plan
if kind == 'ordered':
    if mode == 'ordered-succeeds':
        w('coordination-plan.json', {{'attestationPolicies': ['assessor_report', 'reviewer_signoff']}}); w('manifest.json', {{'ok': True, 'artifacts': ['coordination-plan.json']}}); sys.exit(0)
    if mode == 'dispatch-on-reject':
        w('coordination-plan.json', {{'attestationPolicies': ['assessor_report', 'reviewer_signoff']}})
    refuse("entry 'award_out' guard references 'after', which is not a declared input or computed value")
if kind == 'stage':
    lts = [{{'from': 'A', 'to': 'B', 'name': 'X', 'idempotency': 'reject'}} for _ in range(12)]
    replay = {{'idempotent': (mode != 'replay-unsafe'), 'key': 'case_id'}}
    w('coordination-plan.json', {{'attestationPolicies': ['assessor_report'], 'replay': replay, 'lifecycleTransitions': lts, 'terminal': {{'success': 'CLOSED', 'aborted': 'REJECTED'}}}}); w('manifest.json', {{'ok': True, 'artifacts': ['coordination-plan.json']}}); sys.exit(0)
# leaf
if mode == 'leaf-fails':
    w('manifest.json', {{'ok': False, 'artifacts': []}}); print('forced leaf reduction failure'); sys.exit(4)
if mode == 'terminal-missing':
    terminal = {{'success': 'CLOSED'}}
elif mode == 'wrong-terminal':
    terminal = {{'success': 'CLOSED', 'aborted': 'WRONGSTATE'}}
else:
    terminal = {{'success': 'CLOSED', 'aborted': 'REJECTED'}}
leaf_cp = {{'attestationPolicies': ['assessor_report', 'reviewer_signoff'], 'balanced': True, 'terminal': terminal}}
if mode == 'loss-witness':
    leaf_cp['order'] = ['assessor_report', 'reviewer_signoff']
w('coordination-plan.json', leaf_cp); w('manifest.json', {{'ok': True, 'artifacts': ['coordination-plan.json']}}); sys.exit(0)
""", encoding="utf-8")
    emit = tool_dir / "neutrino-emit"
    emit.write_text(f"""#!/usr/bin/env python3
import json, sys
mode = {mode!r}
args = sys.argv[1:]
src = next((a for a in args if a.endswith('.mlir')), '')
if '--kind=domain-reduction' in args:
    if mode == 'l2-fails':
        print("error: l1_feature 'x' is not a registered semantic feature"); sys.exit(1)
    bindings = {{'domain': 'coordinate.review_chain', 'bindings': [
        {{'concept': 'assessor_review', 'edge': 'r_assessor', 'feature': 'attestation:quorum', 'inducedBy': 'attestation policy', 'relation': 'expands'}},
        {{'concept': 'reviewer_signoff', 'edge': 'r_reviewer', 'feature': 'attestation:quorum', 'inducedBy': 'attestation policy', 'relation': 'expands'}}]}}
    if mode == 'wrong-binding':  # concept names unchanged, one feature/relation changed
        bindings['bindings'][0]['feature'] = 'effect:debit'
    if 'permuted' in src and mode == 'permutation-mismatch':
        bindings['bindings'][0]['edge'] = 'r_reviewer_first'  # declaration order survived -> different graph
    print(json.dumps(bindings)); sys.exit(0)
if '--kind=domain-semantics' in args:
    if 'recursive' in src:  # the recursive stage->stage cycle domain
        if mode == 'recursive-succeeds':
            print('{{}}'); sys.exit(0)
        print("error: 'l2.reduce' op reduction edge targets undeclared L1 feature 'stage_b'"); sys.exit(2)
    loss = 'lossy' if mode == 'lossiness-drift' else 'lossless'
    print(json.dumps({{'reductions': [
        {{'from': 'assessor_review', 'id': 'r_assessor', 'lossiness': loss, 'relation': 'expands', 'to': 'attestation:quorum'}},
        {{'from': 'reviewer_signoff', 'id': 'r_reviewer', 'lossiness': 'lossless', 'relation': 'expands', 'to': 'attestation:quorum'}}]}})); sys.exit(0)
print('unknown emit kind'); sys.exit(2)
""", encoding="utf-8")
    for tool in (gen, emit):
        tool.chmod(0o755)
    return tool_dir


def selftest_orchestration(td: Path, failures: list[str]) -> None:
    fixture = REPO / "examples/pressure-loop-forcing/s7-review-chain-fixtures.json"

    def emit(name: str, tool_dir: Path, mutator=None) -> dict[str, Any]:
        obj = load_json(fixture)
        if mutator:
            mutator(obj)
        return emit_register(obj, Harness(neutrino_gen=None, neutrino_emit=None, tool_dir=tool_dir, work_dir=td / f"owork-{name}", evidence_dir=td / f"oevidence-{name}"))

    try:
        reg = emit("positive", make_orchestration_stub(td / "ok", mode="ok"))
        validated_text(reg, td / "ovalidate")
        row = reg["rows"][0]
        if row["disposition"] != "LAYER_DECISION_REQUIRED" or row["class"] != "3":
            failures.append(f"orchestration positive: wrong disposition/class {row['disposition']}/{row['class']}")
        proof = load_json(
            td / "oevidence-positive"
            / "plf-s7-review-chain-overload.orchestration-overload.json"
        )
        proof_text = json.dumps(proof, sort_keys=True)
        if str(td.resolve()) in proof_text:
            failures.append(
                "orchestration positive: out-of-tree build path leaked into evidence"
            )
        for section in (
            "leafReduction",
            "l2Reduction",
            "l2SemanticEdges",
            "declarationOrderInvariance",
            "recursiveRefusal",
            "orderedRefusal",
        ):
            argv0 = proof.get(section, {}).get("argv", [""])[0]
            tool = Path(argv0).name
            if argv0 != f"out/tools/{tool}/{tool}":
                failures.append(
                    f"orchestration positive: {section} tool argv is not canonical: "
                    f"{argv0!r}"
                )
    except Exception as exc:  # noqa: BLE001
        failures.append(f"orchestration positive failed: {exc}")

    def expect_fail(name: str, mode: str, needle: str, mutator=None) -> None:
        try:
            emit(name, make_orchestration_stub(td / name, mode=mode), mutator)
            failures.append(f"orchestration {name}: expected failure, got success")
        except ValueError as exc:
            if needle not in str(exc):
                failures.append(f"orchestration {name}: expected {needle!r}, got {exc}")

    # Each probe breaks exactly one conjunction element; the row must be withheld.
    expect_fail("leaf-fails", "leaf-fails", "failed with exit")
    expect_fail("l2-reduction-fails", "l2-fails", "failed with exit")
    expect_fail("wrong-binding", "wrong-binding", "L2 reduction bindings")
    expect_fail("lossiness-drift", "lossiness-drift", "domain-semantics reductions")
    expect_fail("permutation-mismatch", "permutation-mismatch", "declaration-order invariance fails")
    expect_fail("recursive-succeeds", "recursive-succeeds", "unexpectedly succeeded")
    expect_fail("ordered-succeeds", "ordered-succeeds", "unexpectedly succeeded")
    expect_fail("loss-witness-absent", "loss-witness", "loss witness absent")
    expect_fail("dispatch-on-reject", "dispatch-on-reject", "fabricated dispatch artifact")
    expect_fail("terminal-missing", "terminal-missing", "!= expected accept/refuse")
    expect_fail("wrong-terminal", "wrong-terminal", "!= expected accept/refuse")
    expect_fail("timeout-drift", "timeout-drift", "timeout/fallback")
    expect_fail("anchor-drift", "ok", "name entry", lambda o: o["fixtures"][0]["expectedObservation"].__setitem__("orderingToken", "sequencedAfter"))
    expect_fail("ordered-code-drift", "ok", "!= pinned", lambda o: o["fixtures"][0]["expectedObservation"].__setitem__("orderedRefusalCode", "type.check"))
    expect_fail("recursive-anchor-drift", "ok", "recursive-stage refusal must match", lambda o: o["fixtures"][0]["expectedObservation"].__setitem__("recursiveAnchor", "some_other_stage"))
    expect_fail("recursive-obligation-drift", "ok", "recursive-stage refusal must match", lambda o: o["fixtures"][0]["expectedObservation"].__setitem__("recursiveObligation", "some other obligation"))
    expect_fail("authority-missing", "ok", "authority", lambda o: o["fixtures"][0].pop("authority"))
    expect_fail("miss-posts-effect", "miss-posts", "fabricated a partial effect")


def make_pay_for_result_stub(td: Path, *, mode: str = "ok") -> Path:
    """Tool mocks for the S8 pay-for-result fail-closed conjunction."""
    tool_dir = td / "tools"
    tool_dir.mkdir(parents=True, exist_ok=True)
    gen = tool_dir / "neutrino-gen"
    gen.write_text("""#!/usr/bin/env python3
import json, os, sys
mode = __MODE__
args = sys.argv[1:]
def opt(name):
    for i, a in enumerate(args):
        if a == name and i + 1 < len(args): return args[i + 1]
        if a.startswith(name + '='): return a.split('=', 1)[1]
    return ''
target = opt('--target'); scn = opt('--scenario'); fromspec = '--from-spec' in args
src = next((a for a in args if a.endswith('.neu') or a.endswith('.json')), '')
out = opt('-o') or '.'
os.makedirs(out, exist_ok=True)
def w(name, obj): json.dump(obj, open(os.path.join(out, name), 'w'))
def refuse(msg):
    w('manifest.json', {{'ok': False, 'artifacts': []}}); w('diagnostics.json', {{'diagnostics': [{{'code': 'source.parse'}}]}}); print(msg); sys.exit(4)
mixed_guard = 'two_phase' in src

attestation = {{
    'input': 'result_proof',
    'quorum': {{'threshold': 2}},
    'observerSet': {{'ref': 'result_validators', 'role': None, 'assurance': 'A3', 'independence': 'independent'}},
    'canonicalization': {{'mode': 'exact', 'tolerance': None}},
    'timeout': 'PT48H',
    'fallback': 'abort',
}}
spec_effects = [
    {{'amount': {{'kind': 'ref', 'value': 'bounty'}}, 'currency': {{'kind': 'ref', 'value': 'currency'}}, 'idempotencyKey': {{'kind': 'ref', 'value': 'job_id'}}, 'kind': 'debit', 'ledger': 'requester.escrow', 'name': 'bounty_out', 'owner': 'requester', 'participant': 'Requester', 'party': {{'kind': 'ref', 'value': 'requester_id'}}, 'when': {{'ast': {{'args': [{{'dtype': 'evidence', 'kind': 'var', 'name': 'result_proof'}}], 'dtype': 'extension', 'kind': 'call', 'name': 'accepted'}}, 'expr': 'accepted(result_proof)'}}}},
    {{'amount': {{'kind': 'ref', 'value': 'bounty'}}, 'currency': {{'kind': 'ref', 'value': 'currency'}}, 'idempotencyKey': {{'kind': 'ref', 'value': 'job_id'}}, 'kind': 'credit', 'ledger': 'worker.wallet', 'name': 'bounty_in', 'owner': 'worker', 'participant': 'Worker', 'party': {{'kind': 'ref', 'value': 'worker_id'}}, 'when': {{'ast': {{'args': [{{'dtype': 'evidence', 'kind': 'var', 'name': 'result_proof'}}], 'dtype': 'extension', 'kind': 'call', 'name': 'accepted'}}, 'expr': 'accepted(result_proof)'}}}},
]

if target == 'capability-spec':
    if mode == 'attestation-drift': attestation['observerSet']['assurance'] = 'A1'
    w('capability-spec.json', {{'kind': 'capability-spec', 'attestations': [attestation], 'effects': spec_effects, 'lifecycle': {{'instanceKey': {{'declared': 'job_id', 'fields': ['job_id']}}}}}}); w('manifest.json', {{'ok': True, 'artifacts': ['capability-spec.json']}}); sys.exit(0)

if target == 'coordination-trace':
    rejected = 'rejected' in scn
    if rejected and mode != 'rejected-settles':
        trace = {{'outcome': 'no-progress', 'trace': [], 'nextState': {{'balances': []}}}}
        if mode == 'rejected-trace-parity-diverge' and fromspec: trace['nextState']['postedKeys'] = ['J-2']
        w('coordination-trace.json', trace); sys.exit(0)
    settle = {{'outcome': 'terminal', 'trace': [
        {{'currency': 'EUR', 'delta': -1000, 'effect': 'bounty_out', 'kind': 'ledger-delta', 'ledger': 'requester.escrow', 'party': 'req-1'}},
        {{'currency': 'EUR', 'delta': 1000, 'effect': 'bounty_in', 'kind': 'ledger-delta', 'ledger': 'worker.wallet', 'party': 'wrk-1'}},
        {{'kind': 'terminal', 'state': 'CLOSED'}}], 'nextState': {{'balances': [{{'ledger': 'worker.wallet', 'balance': 1000}}], 'postedKeys': ['J-1']}}}}
    if mode == 'accepted-no-settle' and not fromspec and not rejected:
        settle = {{'outcome': 'no-progress', 'trace': [], 'nextState': {{'balances': [], 'postedKeys': []}}}}
    if mode == 'trace-parity-diverge' and fromspec:
        settle = json.loads(json.dumps(settle)); settle['nextState']['postedKeys'] = ['J-2']
    if mode == 'wrong-posted-key' and not rejected:
        settle['nextState']['postedKeys'] = ['J-2']
    if mode == 'wrong-effect' and not rejected:
        settle['trace'][0]['effect'] = 'other_out'
    w('coordination-trace.json', settle); sys.exit(0)

# coordination-plan
if mixed_guard:
    if mode == 'mixed-guard-accepted':
        w('coordination-plan.json', {{'balanced': True}}); w('manifest.json', {{'ok': True, 'artifacts': ['coordination-plan.json']}}); sys.exit(0)
    refuse("error: 'neutrino.credit' op [kernel.balance.unbalanced] guarded legs are not balanced under the same guard ()")
if mode == 'reduce-fails':
    w('manifest.json', {{'ok': False, 'artifacts': []}}); print('forced reduction failure'); sys.exit(4)
guard = 'accepted(other)' if mode == 'guard-mismatch' else 'accepted(result_proof)'
effects = [
    {{'attestation': '', 'gateMode': 'temporal-suppress', 'gatePolicy': 'result_proof', 'guard': guard, 'guardKey': '(accepted $result_proof)', 'index': 0, 'kind': 'debit', 'name': 'bounty_out'}},
    {{'attestation': '', 'gateMode': 'temporal-suppress', 'gatePolicy': 'result_proof', 'guard': guard, 'guardKey': '(accepted $result_proof)', 'index': 1, 'kind': 'credit', 'name': 'bounty_in'}},
]
if mode == 'dropped-leg': effects.pop()
if mode == 'extra-leg': effects.append(dict(effects[-1], index=2, name='extra_in'))
cp = {{
    'balanced': (mode != 'unbalanced'),
    'effects': effects,
    'effectGroups': [{{'attestation': '', 'credits': 1, 'debits': 1, 'effects': [0, 1], 'firstIndex': 0, 'gateMode': 'temporal-suppress', 'gatePolicy': 'result_proof', 'guard': 'accepted(result_proof)', 'guardKey': '(accepted $result_proof)', 'mustBalance': True}}],
    'attestationPolicies': ['other_policy'] if mode == 'wrong-policy' else ['result_proof'],
    'terminal': {{'success': 'CLOSED', 'aborted': ('WRONG' if mode == 'terminal-wrong' else 'REJECTED')}},
    'replay': {{'idempotent': (mode != 'replay-missing'), 'key': 'job_id'}},
    'workflowKey': 'job_id',
    'lifecycleTransitions': [{{'from': 'A', 'to': 'B', 'name': 'X', 'idempotency': 'reject'}} for _ in range(10)],
}}
if mode == 'coordination-parity-diverge' and fromspec: cp['workflowKey'] = 'other_id'
w('coordination-plan.json', cp); w('manifest.json', {{'ok': True, 'artifacts': ['coordination-plan.json']}}); sys.exit(0)
""".replace("{{", "{").replace("}}", "}").replace("__MODE__", repr(mode)), encoding="utf-8")
    emit = tool_dir / "neutrino-emit"
    emit.write_text("""#!/usr/bin/env python3
import json, sys
mode = __MODE__
args = sys.argv[1:]
features = ['attestation:quorum', 'authorization:explicit', 'effect:credit', 'effect:debit', 'guard:conditional', 'identity:explicit_instance_key', 'invariant:balanced', 'replay:idempotent', 'terminal:aborted', 'terminal:success']
if '--kind=domain-reduction' in args:
    bindings = [{{'concept': 'concept_' + str(i), 'edge': 'edge_' + str(i), 'feature': feature, 'inducedBy': 'induced_' + str(i), 'relation': 'protects'}} for i, feature in enumerate(features)]
    if mode == 'l2-parity-diverge' and any(a.endswith('.json') for a in args): bindings[0]['inducedBy'] = 'different'
    if mode == 'l2-feature-drift': bindings[0]['feature'] = 'effect:unknown'
    print(json.dumps({{'domain': 'coordinate.pay_for_result', 'bindings': bindings})); sys.exit(0)
if '--kind=domain-semantics' in args:
    reductions = [{{'from': 'concept_' + str(i), 'id': 'edge_' + str(i), 'lossiness': ('lossy' if mode == 'lossiness-drift' and i == 0 else 'lossless'), 'relation': 'protects', 'to': feature}} for i, feature in enumerate(features)]
    print(json.dumps({{'reductions': reductions}})); sys.exit(0)
print('unknown emit kind'); sys.exit(2)
""".replace("{{", "{").replace("}}", "}").replace("__MODE__", repr(mode)), encoding="utf-8")
    for tool in (gen, emit):
        tool.chmod(0o755)
    return tool_dir


def selftest_pay_for_result(td: Path, failures: list[str]) -> None:
    fixture = REPO / "examples/pressure-loop-forcing/s8-pay-for-result-fixtures.json"

    def emit(name: str, tool_dir: Path, mutator=None) -> dict[str, Any]:
        obj = load_json(fixture)
        if mutator:
            mutator(obj)
        return emit_register(obj, Harness(neutrino_gen=None, neutrino_emit=None, tool_dir=tool_dir, work_dir=td / f"pwork-{name}", evidence_dir=td / f"pevidence-{name}"))

    try:
        reg = emit("positive", make_pay_for_result_stub(td / "pok", mode="ok"))
        validated_text(reg, td / "pvalidate")
        rows = {row["rowId"]: row for row in reg["rows"]}
        core = rows["plf-s8-pay-for-result-core"]
        gap = rows["plf-s8-pay-for-result-execution-gap"]
        runtime = rows["plf-s8-pay-for-result-runtime"]
        if core["disposition"] != "L1_CORE" or core["outcome"] != "accepted" or core["supportStatus"] != "partial":
            failures.append(f"pay-for-result positive: wrong core classification {core!r}")
        if gap["class"] != "1" or gap["outcome"] != "unresolved" or gap["supportStatus"] != "absent":
            failures.append(f"pay-for-result positive: wrong tooling-gap classification {gap!r}")
        if runtime["disposition"] != "L3_RUNTIME" or runtime["outcome"] != "accepted":
            failures.append(f"pay-for-result positive: wrong runtime classification {runtime!r}")
    except Exception as exc:  # noqa: BLE001
        failures.append(f"pay-for-result positive failed: {exc}")

    def expect_fail(name: str, mode: str, needle: str, mutator=None) -> None:
        try:
            emit(name, make_pay_for_result_stub(td / name, mode=mode), mutator)
            failures.append(f"pay-for-result {name}: expected failure, got success")
        except ValueError as exc:
            if needle not in str(exc):
                failures.append(f"pay-for-result {name}: expected {needle!r}, got {exc}")

    expect_fail("reduce-fails", "reduce-fails", "failed with exit")
    expect_fail("unbalanced", "unbalanced", "not balanced")
    expect_fail("guard-mismatch", "guard-mismatch", "exact typed coordination effects differ")
    expect_fail("dropped-leg", "dropped-leg", "exact typed coordination effects differ")
    expect_fail("extra-leg", "extra-leg", "exact typed coordination effects differ")
    expect_fail("wrong-policy", "wrong-policy", "wrong attestation policy association")
    expect_fail("terminal-wrong", "terminal-wrong", "terminals")
    expect_fail("replay-missing", "replay-missing", "exactly-once discipline")
    expect_fail("attestation-drift", "attestation-drift", "exact attestation contract differs")
    expect_fail("coordination-parity-diverge", "coordination-parity-diverge", "coordination reconstructions diverged")
    expect_fail("l2-parity-diverge", "l2-parity-diverge", "normalized requirement reductions diverged")
    expect_fail("l2-feature-drift", "l2-feature-drift", "L2 normalized requirements")
    expect_fail("lossiness-drift", "lossiness-drift", "source-neutral L2 edges")
    expect_fail("accepted-no-settle", "accepted-no-settle", "did not reach the exact success terminal")
    expect_fail("trace-parity-diverge", "trace-parity-diverge", "settlement traces diverged")
    expect_fail("rejected-trace-parity-diverge", "rejected-trace-parity-diverge", "unaccepted traces diverged")
    expect_fail("wrong-posted-key", "wrong-posted-key", "scenario-derived")
    expect_fail("wrong-effect", "wrong-effect", "exact accepted settlement deltas differ")
    expect_fail("rejected-settles", "rejected-settles", "fabricated settlement state")
    expect_fail("mixed-guard-accepted", "mixed-guard-accepted", "unexpectedly succeeded")
    expect_fail("balance-anchor-drift", "ok", "must be refused with", lambda o: o["fixtures"][0]["expectedObservation"].__setitem__("balanceRuleAnchor", "kernel.other.thing"))
    expect_fail("authority-missing", "ok", "authority", lambda o: o["fixtures"][0].pop("authority"))
    expect_fail("tooling-gap-missing-ref", "ok", "does not exist", lambda o: o["fixtures"][1]["expectedObservation"].__setitem__("evidenceRef", "does/not/exist.json"))
    expect_fail("tooling-gap-wrong-companion", "ok", "not companion pay-for-result proof", lambda o: o["fixtures"][1]["expectedObservation"].__setitem__("evidenceRef", "examples/pressure-loop-forcing/evidence/plf-s7-review-chain-overload.orchestration-overload.json"))

    positive_proof_path = td / "pevidence-positive/plf-s8-pay-for-result-core.pay-for-result.json"
    if positive_proof_path.is_file():
        try:
            proof = load_json(positive_proof_path)
            proof["executionGap"]["deadline"]["behaviorallyExecuted"] = True
            validate_pay_for_result_execution_gap(proof, "plf-s8-pay-for-result-core", "execution-gap-drift")
            failures.append("pay-for-result execution-gap-drift: expected failure, got success")
        except ValueError as exc:
            if "deadline execution gap drifted" not in str(exc):
                failures.append(f"pay-for-result execution-gap-drift: expected deadline drift, got {exc}")


def selftest() -> int:
    fixture = REPO / "examples/pressure-loop-forcing/fixtures.json"
    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="pressure_loop_forcing.") as raw:
        td = Path(raw)
        tool_dir = make_stub_tools(td)
        harness = Harness(neutrino_gen=None, neutrino_emit=None, tool_dir=tool_dir, work_dir=td / "work", evidence_dir=td / "evidence")
        try:
            reg = emit_register(load_json(fixture), harness)
            validated_text(reg, td)
        except Exception as exc:
            return die(f"selftest positive failed: {exc}")

        def expect_fail(name: str, mutator, needle: str, **tool_opts: Any) -> None:
            obj = load_json(fixture)
            mutator(obj)
            tdir = make_stub_tools(td / name, **tool_opts)
            try:
                reg2 = emit_register(obj, Harness(neutrino_gen=None, neutrino_emit=None, tool_dir=tdir, work_dir=td / f"work-{name}", evidence_dir=td / f"evidence-{name}"))
                validated_text(reg2, td / f"validate-{name}")
                failures.append(f"{name}: expected failure, got success")
            except ValueError as exc:
                if needle not in str(exc):
                    failures.append(f"{name}: expected {needle!r}, got {exc}")

        expect_fail("unknown-version", lambda o: o.__setitem__("schemaVersion", 99), "schemaVersion")
        expect_fail("zero-fixtures", lambda o: o.__setitem__("fixtures", []), "at least one")
        expect_fail("missing-source", lambda o: o["fixtures"][0]["inputs"].__setitem__("source", "missing.neu"), "does not exist")
        expect_fail("tampered-trace", lambda o: None, "missing posted key", tamper_trace=True)
        expect_fail("representable-fails", lambda o: None, "failed with exit", fail_representable=True)
        expect_fail("reduction-succeeds", lambda o: None, "unexpectedly succeeded", reduction_succeeds=True)
        expect_fail("wrong-diagnostic", lambda o: o["fixtures"][1]["expectedObservation"].__setitem__("diagnosticCode", "wrong.code"), "observed diagnostic")
        expect_fail("wrong-anchor", lambda o: o["fixtures"][1]["expectedObservation"].__setitem__("anchor", "wrong"), "observed diagnostic")
        expect_fail(
            "wrong-refusal-target",
            lambda o: o["fixtures"][3]["inputs"]["command"].__setitem__(1, "--target=unsupported-different-target"),
            "observed refusal",
        )
        expect_fail("backend-dispatch-refusal", lambda o: o["fixtures"][3]["inputs"].__setitem__("backend-dispatch", True), "backend dispatch")
        expect_fail("orthogonal-artifact", lambda o: o["fixtures"][2].__setitem__("currentArtifactOperation", "fake"), "unknown field")
        expect_fail("stdout-invalid", lambda o: o["fixtures"][1]["provenance"].__setitem__("authorityWeightTier", "9"), "emitted register failed v2 validation")

        # The committed command identity is independent of build-tree location.
        # The external path is also the biting regression shape: rel_argv would
        # leave it absolute and the orchestration evidence check above would fail.
        tool_tail = Path("tools/neutrino-gen/neutrino-gen")
        in_repo = REPO / "out" / tool_tail
        out_of_tree = td / "external-build" / tool_tail
        suffix = ["--target=coordination-plan", "test/ir/l2/Inputs/review_chain_leaf.neu"]
        inside = reproducible_argv([str(in_repo), *suffix])
        outside = reproducible_argv([str(out_of_tree), *suffix])
        expected = ["out/tools/neutrino-gen/neutrino-gen", *suffix]
        if inside != expected or outside != expected or inside != outside:
            failures.append(
                "build-path normalization: in-repo and out-of-tree tool argv differ "
                f"(inside={inside!r}, outside={outside!r})"
            )
        selftest_orchestration(td, failures)
        selftest_pay_for_result(td, failures)
    if failures:
        print("pressure-loop forcing selftest FAILED:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    print("pressure-loop forcing selftest PASS (observed paths + composite orchestration conjunction + real-output validation + fail-closed negatives)")
    return 0


def default_evidence_dir(out: str | None, tmp: Path) -> Path:
    if out:
        p = Path(out).resolve()
        return p.parent / (p.stem + ".evidence")
    return tmp / "evidence"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Emit a v2 pressure-loop register from representation-neutral forcing fixtures")
    ap.add_argument("fixtures", nargs="?", default=str(REPO / "examples/pressure-loop-forcing/fixtures.json"))
    ap.add_argument("--out", help="write emitted register JSON to this path after validation")
    ap.add_argument("--tool-dir", help="directory containing neutrino-gen and neutrino-emit")
    ap.add_argument("--neutrino-gen", help="explicit neutrino-gen executable")
    ap.add_argument("--neutrino-emit", help="explicit neutrino-emit executable")
    ap.add_argument("--evidence-dir", help="directory for runner-produced evidence artifacts")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    try:
        if not args.out and not args.evidence_dir:
            raise ValueError("stdout mode requires --evidence-dir so evidence refs remain durable after process exit")
        with tempfile.TemporaryDirectory(prefix="pressure_loop_forcing.") as raw:
            tmp = Path(raw)
            harness = Harness(
                neutrino_gen=Path(args.neutrino_gen).resolve() if args.neutrino_gen else None,
                neutrino_emit=Path(args.neutrino_emit).resolve() if args.neutrino_emit else None,
                tool_dir=Path(args.tool_dir).resolve() if args.tool_dir else None,
                work_dir=tmp / "work",
                evidence_dir=Path(args.evidence_dir).resolve() if args.evidence_dir else default_evidence_dir(args.out, tmp),
            )
            text = validated_text(emit_register(load_json(Path(args.fixtures)), harness), tmp)
            if args.out:
                atomic_write(Path(args.out), text)
            else:
                print(text, end="")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return die(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

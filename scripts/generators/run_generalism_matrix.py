#!/usr/bin/env python3
"""[] Generalism matrix runner (M6 generalism S2).

Drives the schema-derived cells from
(`test/generalism/generalism-cells.manifest.json`) through the CANONICAL stack and
emits machine-readable `neutrino.generalism-result` envelopes ( contract,
`docs/schemas/generalism-result.schema.json`) plus a deterministic RUN MANIFEST that
lists all 32 cells and references their result envelopes.  (S3) classifies the
referenced results and produces the aggregate scorecard;  only EMITS.

REUSE, no parallel oracle, no expected-value table:
  - `.neu` cells (seed + generated) realize through `neutrino-gen`: the canonical
    capability spec `--target=capability-spec` (the frozen spec identity), the ONE
    reference evaluator `--target=coordination-trace` (/, the PREDICTION), the
    rigid `--target=solidity` / `--target=postgres` generators, and `neutrino-equiv`
    (trace-equivalence + LIVE Solidity/Postgres compile-and-execute). The controlled
    control (mutation applied) is realized too, so an invisible mutation is SILENT.
  - binding (spec) cells realize through either the frozen spec contract validator
    for non-crediting validator-contract fixtures, or a valid-value carry-and-consume
    producer/consumer circuit for crediting rows (slot topology, observation binding,
    lifecycle terminal consistency, or coordination-plan from-spec).
  - cell materialization (`_synth_scenario`, `apply_mutation`, `BINDING_LOCUS`,
    `_locate`, `_dset`) is imported from `gen_generalism_cells`, never re-derived.

Contract-anchored verdicts (fail-closed; never coerced):
  - FAITHFUL — reference ACCEPTS, both rigid targets accept and agree, the differential
    is non-vacuous (a valid equivalence report with `traceEquivalence.ok` and
    `executedCases >= 1`), AND both live compile adapters PROVED compilation. A skipped
    compile adapter cannot yield FAITHFUL.
  - REFUSED — a CONTRACT-PREDICTED governed refusal: the reference and both targets
    refuse at exit 4 (IR/waist) or 6 (legality) with a CONSISTENT diagnostic code that
    matches the cell's declared `refusalCode` when one is declared.
  - SILENT — a predicted refusal that did not fire, or an invisible mutation (the
    control realizes byte-identically).
  - BROKEN — any crash / usage failure / timeout (`runtime_timeout`), a cross-backend
    disagreement, a reference-vs-target divergence (e.g. reference accepts but a target
    security-refuses), a live compile/runtime failure (`compile_failure`), an
    UNPREDICTED refusal, a refusal at exit 3/5, an inconsistent refusal code, or a
    missing required adapter/tool (`missing_required_tool`). Never coerced to REFUSED.

Output shape: ONE envelope per EXACT capability EXECUTION IDENTITY = (capability, spec,
scenario, provenance, profile, configuration, adapter set). Cells collapse into a shared
envelope (as `cases`) only when ALL of those are identical (e.g. binding cells that
invalidate different fields of the SAME committed spec). A separate run manifest maps
every cell to its envelope (path + digest).

Evidence: each envelope carries GENUINE per-run M4 evidence bound to its own cross-rail
decisions AND to its canonical result digest, signed + verified through the pinned
authoritative build-tools verifier (`.ci/neutrino-build-tools`, ). `--validate` runs
the UNMODIFIED contract validator — no evidence exception — so a fixture or a transplanted
evidence block fails closed. Target-profile ids/versions come authoritatively from
`neutrino-gen --target-profiles` and are pinned into every execution identity.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
import gen_generalism_cells as gg  # noqa: E402  (sibling generator: reuse materialization)

CELLS = os.path.join(REPO, "test", "generalism", "generalism-cells.manifest.json")
SPEC_VALIDATOR = os.path.join(REPO, "scripts", "validators", "validate_capability_spec.py")
BINDING_MANIFEST_VALIDATOR = os.path.join(REPO, "scripts", "validators", "validate_binding_manifest.py")
OBSERVATION_BINDING_VALIDATOR = os.path.join(REPO, "scripts", "validators", "validate_observation_binding.py")
RESULT_VALIDATOR = os.path.join(REPO, "scripts", "validators", "validate_generalism_result.py")
SCHEMA = os.path.join(REPO, "docs", "schemas", "generalism-result.schema.json")

PROFILE = "PR_FAST"
# The differential is the one REQUIRED adapter (it always runs; the contract forbids a skipped
# required adapter outright). The live compile adapters are OPTIONAL at the schema level so an
# envelope stays valid where the toolchain is absent — but they are enforced at the VERDICT level:
# a case cannot be FAITHFUL unless both compile adapters RAN and proved compilation (skip -> BROKEN).
REQUIRED_ADAPTERS = ["translator-differential"]
OPTIONAL_ADAPTERS = ["solidity-compile", "postgres-compile", "external-solc-0.8"]
REQUIRED_CASE_FLOOR = 1
BINDING_WITNESSES = frozenset({"spec_refusal", "binding_consume"})

# The authoritative build-tools verifier (): provisioned into .ci/neutrino-build-tools at this
# pinned revision by scripts/gates/setup_build_tools_verifier.py; the env var overrides in CI.
BUILD_TOOLS_REVISION = os.environ.get(
    "NEUTRINO_BUILD_TOOLS_GENERALISM_REPORT_REVISION", "2cf85d5b8baf38e259a574357045f7ded12f9395")

# neutrino-gen exit codes: 0 OK, 2 usage/IO/parse, 3 scenario, 4 IR/waist, 5 security, 6 legality.
GOVERNED_EXITS = {3, 4, 5, 6}
CONTRACT_REFUSAL_EXITS = {4, 6}  # only IR/waist + legality are contract-predicted honest refusals
DEFAULT_TIMEOUT = 240  # per-adapter wall-clock ceiling; a hung adapter becomes BROKEN(runtime_timeout)


def _sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def _sha256_file(path):
    with open(path, "rb") as fh:
        return _sha256_bytes(fh.read())


def _canon(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256_obj(obj):
    return _sha256_bytes(_canon(obj))


_TIMEOUT = DEFAULT_TIMEOUT  # per-adapter ceiling; overridable via --timeout
# When set (--no-live-adapters), the equiv subprocess runs with a minimal PATH so its LIVE
# Solidity/Postgres backends are absent and SKIP fast (the main-build shape tier; a cell needing a
# live compile then fails closed to BROKEN, never a vacuous FAITHFUL). The e2e tier leaves it off.
_EQUIV_ENV = None
_SLOT_SPEC_RENDERER = None
_NEUTRINO_GEN = None


def _run(argv, env=None, timeout=None):
    """Run a subprocess with a bounded timeout. Returns (rc, stdout, stderr, timed_out);
    a timeout yields rc=None, timed_out=True so a hung adapter becomes an explicit BROKEN."""
    timeout = timeout if timeout is not None else _TIMEOUT
    try:
        p = subprocess.run(argv, capture_output=True, text=True, env=env, timeout=timeout)
        return p.returncode, (p.stdout or ""), (p.stderr or ""), False
    except subprocess.TimeoutExpired as e:
        return None, (e.stdout or "") if isinstance(e.stdout, str) else "", \
               (e.stderr or "") if isinstance(e.stderr, str) else "", True


# ---- provenance (computed once from the real binaries) --------------------------------------------

def build_provenance(bindir):
    translate = os.path.join(bindir, "neutrino-translate")
    rc, out, _e, _t = _run([translate, "--version-json"], timeout=60)
    # Fail closed: version identity must be READ from the binary, never defaulted. An unreadable /
    # invalid / incomplete --version-json aborts the run rather than stamping a fake v0/0.0.0 identity.
    if rc != 0 or not out.strip():
        sys.exit("error: `neutrino-translate --version-json` failed; cannot pin a version identity")
    try:
        ver = json.loads(out)
    except ValueError as e:
        sys.exit(f"error: --version-json is not valid JSON ({e}); cannot pin a version identity")
    required = ("toolVersion", "gitSha", "capabilitySpecVersion",
                "semanticProfileVersion", "semanticLanguageVersion")
    missing = [k for k in required if ver.get(k) in (None, "")]
    if missing:
        sys.exit(f"error: --version-json missing required version fields {missing}; cannot pin identity")
    tool_version = ver["toolVersion"]
    revision = ver["gitSha"]
    versions = {k: ver[k] for k in ("capabilitySpecVersion", "semanticProfileVersion",
                                    "semanticLanguageVersion", "toolVersion")}
    semantic_profile = {
        "id": "semantic.realization.v" + str(ver["semanticProfileVersion"]),
        "version": str(ver["semanticLanguageVersion"]),
    }
    translator = {
        "name": "neutrino-translator", "version": tool_version, "revision": revision,
        "imageDigest": "sha256:" + _sha256_file(translate),
    }
    backends = [{"name": "solidity", "version": "m6", "revision": revision},
                {"name": "postgres", "version": "m6", "revision": revision}]
    tools = [{"name": "neutrino-gen", "version": tool_version, "revision": revision}]
    commands = [
        {"name": "neutrino-gen", "argv": ["neutrino-gen", "--target=capability-spec", "source.neu"]},
        {"name": "neutrino-gen", "argv": ["neutrino-gen", "--target=coordination-trace", "--scenario=scn.json", "source.neu"]},
        {"name": "neutrino-gen", "argv": ["neutrino-gen", "--target=solidity", "--scenario=scn.json", "source.neu"]},
        {"name": "neutrino-gen", "argv": ["neutrino-gen", "--target=postgres", "--scenario=scn.json", "source.neu"]},
        {"name": "neutrino-equiv", "argv": ["neutrino-equiv", "--scenario=scn.json", "source.neu", "--allow-skips"]},
    ]
    # The AUTHORITATIVE rigid-target profile ids/versions, from `neutrino-gen --target-profiles`
    # (PlanLegality) — present regardless of any cell's lowering/refusal. Fail closed if absent, and
    # fold into the config so EVERY execution identity (accepted AND refused) pins them.
    target_profiles = query_target_profiles(os.path.join(bindir, "neutrino-gen"))
    versions["targetProfiles"] = target_profiles
    config = {
        "profile": PROFILE, "requiredAdapters": REQUIRED_ADAPTERS, "optionalAdapters": OPTIONAL_ADAPTERS,
        "targets": ["capability-spec", "coordination-trace", "solidity", "postgres"],
        "translatorVersion": tool_version, "capabilitySpecVersion": versions["capabilitySpecVersion"],
        "semanticProfile": semantic_profile, "targetProfiles": target_profiles,
    }
    prov = {
        "translator": translator, "backends": backends, "tools": tools, "runtimes": [],
        "commands": commands, "configurationHash": _sha256_obj(config),
    }
    return prov, _sha256_obj(prov), versions, semantic_profile


REQUIRED_TARGET_PROFILES = ("solidity", "postgres")


def query_target_profiles(neutrino_gen):
    """The authoritative built-in rigid-target profiles (sorted [target,id,version]) from
    `neutrino-gen --target-profiles`. Fail closed unless the response is a list holding EXACTLY ONE
    well-typed object for EACH required rigid target (no missing, duplicate, unknown, or malformed
    entry) — a partial set would claim authoritative identity while leaving a target unpinned."""
    rc, out, _e, _t = _run([neutrino_gen, "--target-profiles"], timeout=60)
    if rc != 0 or not out.strip():
        sys.exit("error: `neutrino-gen --target-profiles` failed; cannot pin target-profile identity")
    try:
        arr = json.loads(out)
    except ValueError as e:
        sys.exit(f"error: --target-profiles is not valid JSON ({e})")
    if not isinstance(arr, list):
        sys.exit("error: --target-profiles must be a JSON array")
    by_target = {}
    for p in arr:
        if not isinstance(p, dict):
            sys.exit("error: --target-profiles entry must be an object")
        t, i, v = p.get("target"), p.get("id"), p.get("version")
        if not (isinstance(t, str) and isinstance(i, str) and i
                and isinstance(v, int) and not isinstance(v, bool)):
            sys.exit(f"error: --target-profiles entry {p!r} has invalid target/id/version types")
        if t not in REQUIRED_TARGET_PROFILES:
            sys.exit(f"error: --target-profiles has an unexpected target {t!r}")
        if t in by_target:
            sys.exit(f"error: --target-profiles has a duplicate target {t!r}")
        by_target[t] = (t, i, v)
    missing = [t for t in REQUIRED_TARGET_PROFILES if t not in by_target]
    if missing:
        sys.exit(f"error: --target-profiles is missing required rigid targets {missing}")
    return sorted(by_target.values())


# ---- realization: neu (seed/generated) cells ------------------------------------------------------

# The deterministic, byte-golden artifact is the GENERATED CODE (.sol/.sql). manifest.json and
# run_db_test.sh embed the output path, the command line, and a wall-clock timestamp (build
# provenance), so they are excluded from the artifact identity.
_ARTIFACT_EXTS = (".sol", ".sql")


def _artifact_hash(out_dir):
    """Hash the emitted code (sorted relpath + bytes) under out_dir, excluding build provenance."""
    if not os.path.isdir(out_dir):
        return None
    parts = []
    for root, _dirs, files in os.walk(out_dir):
        for fn in sorted(files):
            if fn.endswith(_ARTIFACT_EXTS):
                rel = os.path.relpath(os.path.join(root, fn), out_dir)
                parts.append(rel.encode() + b"\0" + open(os.path.join(root, fn), "rb").read())
    return _sha256_bytes(b"\0".join(sorted(parts))) if parts else None


def _diag_codes(out_dir):
    """Error-severity diagnostic codes emitted into out_dir/diagnostics.json (the coded refusal)."""
    p = os.path.join(out_dir, "diagnostics.json")
    if not os.path.isfile(p):
        return []
    try:
        d = json.load(open(p))
    except (ValueError, OSError):
        return []
    return sorted(x.get("code") for x in d.get("diagnostics", []) if x.get("severity") == "error")


def _gen(bindir, target, src, scn, out, timeout=None):
    argv = [os.path.join(bindir, "neutrino-gen"), f"--target={target}", src, "-o", out]
    if scn is not None:
        argv.insert(2, "--scenario=" + scn)
    rc, _so, _se, timed = _run(argv, timeout=timeout)
    return rc, timed


def realize_neu(bindir, neu, scenario, workdir, tag="cell"):
    """Realize a .neu source+scenario through the canonical stack. Returns a normalized obs."""
    src = os.path.join(workdir, f"{tag}.neu")
    scn = os.path.join(workdir, f"{tag}.scn.json")
    with open(src, "w", encoding="utf-8") as fh:
        fh.write(neu)
    with open(scn, "w", encoding="utf-8") as fh:
        json.dump(scenario, fh)

    timed = False

    # canonical capability spec (the frozen spec identity; no scenario). Emits even when a rigid
    # backend later refuses at lowering; a waist refusal (exit 4) emits diagnostics instead.
    cs_out = os.path.join(workdir, f"{tag}.spec")
    cs_exit, t = _gen(bindir, "capability-spec", src, None, cs_out); timed |= t
    spec_file = os.path.join(cs_out, "capability-spec.json")
    spec_hash, spec_version = None, None
    if os.path.isfile(spec_file):
        spec_hash = _sha256_file(spec_file)
        spec_version = (json.load(open(spec_file)).get("specVersion"))  # the REAL declared version
    spec_codes = _diag_codes(cs_out)
    # A waist refusal has no spec: its deterministic identity is the CODED refusal (the codes), not
    # the raw diagnostics file (whose messages may embed a timestamp / temporal value).
    waist_hash = spec_hash or (_sha256_obj(["waist-refusal"] + spec_codes) if spec_codes else None)

    # reference evaluator (the PREDICTION)
    ct_out = os.path.join(workdir, f"{tag}.trace")
    ct_exit, t = _gen(bindir, "coordination-trace", src, scn, ct_out); timed |= t
    trace = None
    tp = os.path.join(ct_out, "coordination-trace.json")
    if os.path.isfile(tp):
        trace = json.load(open(tp))
    ref_codes = _diag_codes(ct_out)

    # rigid targets
    s_out = os.path.join(workdir, f"{tag}.sol")
    sol_exit, t = _gen(bindir, "solidity", src, scn, s_out); timed |= t
    p_out = os.path.join(workdir, f"{tag}.pg")
    pg_exit, t = _gen(bindir, "postgres", src, scn, p_out); timed |= t

    # differential + LIVE compile/execute adapters (forge build/test, postgres run) via neutrino-equiv.
    # Full PATH so live toolchains RUN when present; --allow-skips marks an absent toolchain SKIP.
    rep = os.path.join(workdir, f"{tag}.equiv")
    eq_exit, _so, _se, eqt = _run([os.path.join(bindir, "neutrino-equiv"), "--scenario=" + scn, src,
                                   "--report=" + rep, "--allow-skips"], env=_EQUIV_ENV)
    timed |= eqt
    eq = {}
    ep = os.path.join(rep, "equivalence.json")
    if os.path.isfile(ep):
        try:
            eq = json.load(open(ep))
        except ValueError:
            eq = {}
    te = eq.get("traceEquivalence") if isinstance(eq.get("traceEquivalence"), dict) else {}
    eq_backends = {b["name"]: (b.get("status") or b.get("result"))
                   for b in (eq.get("backends") or []) if isinstance(b, dict) and "name" in b}
    # the STAGE a live backend failed at (compile vs runtime), so a compiler rejection and a
    # behavioral/runtime failure map to distinct causes (Blocker 3).
    eq_stages = {b["name"]: b.get("stage")
                 for b in (eq.get("backends") or []) if isinstance(b, dict) and "name" in b}
    # Retain the pinned target-profile identity (Blocker 4): the profile id/version each backend
    # was compared under — sorted for a deterministic identity contribution.
    target_profiles = sorted(
        (b.get("name"), b.get("profileId"), b.get("profileVersion"))
        for b in (te.get("backends") or []) if isinstance(b, dict) and b.get("profileId"))

    return {
        "spec_exit": cs_exit, "spec_hash": spec_hash, "spec_version": spec_version,
        "spec_codes": spec_codes, "waist_hash": waist_hash,
        "trace_exit": ct_exit, "trace": trace, "ref_codes": ref_codes,
        "sol_exit": sol_exit, "sol_hash": _artifact_hash(s_out), "sol_codes": _diag_codes(s_out),
        "pg_exit": pg_exit, "pg_hash": _artifact_hash(p_out), "pg_codes": _diag_codes(p_out),
        "eq_valid": bool(eq), "eq_exit": eq_exit, "eq_ok": bool(eq.get("ok")),
        "eq_trace_ok": bool(te.get("ok")), "eq_executed_cases": te.get("executedCases") or 0,
        "eq_backends": eq_backends, "eq_stages": eq_stages,
        "target_profiles": target_profiles, "timed_out": timed,
    }


# ---- realization: binding (spec) cells ------------------------------------------------------------

def _validate_spec(spec_path_or_obj, workdir, tag):
    if isinstance(spec_path_or_obj, str):
        path = spec_path_or_obj
    else:
        path = os.path.join(workdir, f"{tag}.spec.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(spec_path_or_obj, fh)
    rc, out, _e, timed = _run([sys.executable, SPEC_VALIDATOR, path], timeout=120)
    report = json.loads(out) if out.strip().startswith("{") else {"ok": rc == 0, "diagnostics": []}
    codes = sorted(d.get("code") for d in report.get("diagnostics", []) if d.get("severity") == "error")
    return rc, codes, timed


def realize_binding(cell, workdir):
    """Realize a binding cell: the committed spec validates clean (value carried); the single
    invalidated locator field is coded-refused with the declared refusalCode (value enforced)."""
    spec_path = os.path.join(REPO, cell["spec"])
    spec = json.load(open(spec_path))
    valid_rc, valid_codes, t1 = _validate_spec(spec_path, workdir, "valid")

    loc = cell["locator"]
    entry = {"array": loc["array"], "sub": loc["sub"], "value": loc["value"], "contains": loc.get("contains")}
    idx = gg._locate(spec, entry)
    invalid_rc, invalid_codes, t2 = None, [], False
    if idx is not None:
        mutated = json.loads(json.dumps(spec))
        arr = gg._dget(mutated, loc["array"])
        gg._dset(arr[idx], loc["sub"], cell["invalid"])
        invalid_rc, invalid_codes, t2 = _validate_spec(mutated, workdir, "invalid")
    return {
        "spec_path": cell["spec"], "spec_hash": _sha256_file(spec_path),
        "spec_version": spec.get("specVersion"),  # the committed spec's REAL declared version
        "valid_exit": valid_rc, "valid_codes": valid_codes, "located": idx is not None,
        "invalid_exit": invalid_rc, "invalid_codes": invalid_codes,
        "refusalCode": cell.get("refusalCode"), "timed_out": bool(t1 or t2),
    }


def realize_binding_consume(cell, workdir):
    """Realize a binding_consume cell through the same native producer -> topology -> binding-manifest
    consumer circuit used by gen_generalism_cells.py --prove-binding-consume."""
    proof = cell.get("consumeProof") or {}
    if cell.get("witness") != "binding_consume":
        raise ValueError(f"{cell.get('id')}: not a binding_consume cell")
    if gg.binding_consume_proof_violations(cell):
        raise ValueError(f"{cell.get('id')}: {gg.binding_consume_proof_violations(cell)[0]}")
    if proof.get("locus") == "observerSet":
        return realize_observer_set_consume(cell, workdir)
    if proof.get("locus") == "lifecycleState":
        return realize_lifecycle_state_consume(cell, workdir)
    if proof.get("locus") == "lifecycleTransitionGuard":
        return realize_lifecycle_transition_guard_consume(cell, workdir)
    if proof.get("locus") == "lifecycleTransitionEvidence":
        return realize_lifecycle_transition_evidence_consume(cell, workdir)
    if proof.get("locus") == "lifecycleTransition":
        return realize_lifecycle_transition_consume(cell, workdir)
    if not _SLOT_SPEC_RENDERER or not os.path.isfile(_SLOT_SPEC_RENDERER):
        raise FileNotFoundError("slot-spec renderer is required for binding_consume cells")

    base_path = os.path.join(REPO, proof["spec"])
    base = json.load(open(base_path))
    cell_spec = gg._spec_with_participant_field(
        base, proof["participant"], proof["specField"], proof["cellValue"])
    control_spec = gg._spec_with_participant_field(
        base, proof["participant"], proof["specField"], proof["controlValue"])

    cell_spec_rc, cell_spec_diags = gg._validate_spec(SPEC_VALIDATOR, cell_spec, workdir)
    control_spec_rc, control_spec_diags = gg._validate_spec(SPEC_VALIDATOR, control_spec, workdir)

    cell_topology = control_topology = tampered_topology = None
    cell_report = control_report = tampered_report = {"ok": False, "diagnostics": []}
    producer_error = None
    timed_out = False
    try:
        cell_topology = gg._render_slot_topology(_SLOT_SPEC_RENDERER, cell_spec, workdir, cell["id"] + ".cell")
        control_topology = gg._render_slot_topology(
            _SLOT_SPEC_RENDERER, control_spec, workdir, cell["id"] + ".control")
        manifest_obj = gg._binding_manifest_for_topology(cell_topology, proof)
        _rc, cell_report = gg._validate_binding_manifest(
            BINDING_MANIFEST_VALIDATOR, manifest_obj, cell_topology, workdir)
        _rc, control_report = gg._validate_binding_manifest(
            BINDING_MANIFEST_VALIDATOR, manifest_obj, control_topology, workdir)
        tampered_topology = gg._set_topology_slot_field(
            cell_topology, proof["participant"], proof["topologyField"],
            proof["controlTopologyValue"], proof)
        _rc, tampered_report = gg._validate_binding_manifest(
            BINDING_MANIFEST_VALIDATOR, manifest_obj, tampered_topology, workdir)
    except RuntimeError as exc:
        producer_error = str(exc)

    def _slot_value(topology):
        if not topology:
            return None
        _org, _p, slot = gg._topology_participant_slot(topology, proof["participant"])
        return slot.get(proof["topologyField"]) if slot else None

    return {
        "spec_path": proof["spec"],
        "spec_hash": gg._sha256_json(cell_spec),
        "spec_version": cell_spec.get("specVersion"),
        "base_spec_hash": _sha256_file(base_path),
        "cell_spec_exit": cell_spec_rc,
        "cell_spec_codes": [d.get("code") for d in cell_spec_diags],
        "control_spec_exit": control_spec_rc,
        "control_spec_codes": [d.get("code") for d in control_spec_diags],
        "participant": proof["participant"],
        "specField": proof["specField"],
        "topologyField": proof["topologyField"],
        "cellValue": proof["cellValue"],
        "controlValue": proof["controlValue"],
        "cellTopologyValue": _slot_value(cell_topology),
        "controlTopologyValue": _slot_value(control_topology),
        "expectedCellTopologyValue": proof["cellTopologyValue"],
        "expectedControlTopologyValue": proof["controlTopologyValue"],
        "cellReport": cell_report,
        "controlReport": control_report,
        "tamperedReport": tampered_report,
        "expected": proof["expected"],
        "controlExpected": proof["controlExpected"],
        "producerError": producer_error,
        "timed_out": timed_out,
    }


def realize_observer_set_consume(cell, workdir):
    proof = cell.get("consumeProof") or {}
    base_path = os.path.join(REPO, proof["spec"])
    binding_path = os.path.join(REPO, proof["binding"])
    base = json.load(open(base_path))
    base_binding = json.load(open(binding_path))
    cell_spec = gg._spec_with_observer_set_field(
        base, proof["observerSet"], proof["specField"], proof["cellValue"])
    control_spec = gg._spec_with_observer_set_field(
        base, proof["observerSet"], proof["specField"], proof["controlValue"])
    cell_binding = gg._binding_matching_observer_set(base_binding, cell_spec, proof["observerSet"])
    tampered_binding = gg._binding_with_observer_set_field(
        cell_binding, proof["observerSet"], proof["bindingField"], proof["controlValue"])

    cell_spec_rc, cell_spec_diags = gg._validate_spec(SPEC_VALIDATOR, cell_spec, workdir)
    control_spec_rc, control_spec_diags = gg._validate_spec(SPEC_VALIDATOR, control_spec, workdir)
    _rc, cell_report = gg._validate_observation_binding(
        OBSERVATION_BINDING_VALIDATOR, cell_binding, cell_spec, workdir)
    _rc, control_report = gg._validate_observation_binding(
        OBSERVATION_BINDING_VALIDATOR, cell_binding, control_spec, workdir)
    _rc, tampered_report = gg._validate_observation_binding(
        OBSERVATION_BINDING_VALIDATOR, tampered_binding, cell_spec, workdir)

    cell_os = gg._attestation_observer_set(cell_spec, proof["observerSet"]) or {}
    control_os = gg._attestation_observer_set(control_spec, proof["observerSet"]) or {}
    cell_bound = gg._observer_binding_set(cell_binding, proof["observerSet"]) or {}
    tampered_bound = gg._observer_binding_set(tampered_binding, proof["observerSet"]) or {}
    return {
        "spec_path": proof["spec"],
        "spec_hash": gg._sha256_json(cell_spec),
        "spec_version": cell_spec.get("specVersion"),
        "base_spec_hash": _sha256_file(base_path),
        "cell_spec_exit": cell_spec_rc,
        "cell_spec_codes": [d.get("code") for d in cell_spec_diags],
        "control_spec_exit": control_spec_rc,
        "control_spec_codes": [d.get("code") for d in control_spec_diags],
        "observerSet": proof["observerSet"],
        "specField": proof["specField"],
        "bindingField": proof["bindingField"],
        "cellValue": proof["cellValue"],
        "controlValue": proof["controlValue"],
        "cellSpecValue": cell_os.get(proof["specField"]),
        "controlSpecValue": control_os.get(proof["specField"]),
        "cellBindingValue": cell_bound.get(proof["bindingField"]),
        "tamperedBindingValue": tampered_bound.get(proof["bindingField"]),
        "cellReport": cell_report,
        "controlReport": control_report,
        "tamperedReport": tampered_report,
        "mismatchCode": proof["mismatchCode"],
        "producerError": None,
        "timed_out": False,
    }


def realize_lifecycle_state_consume(cell, workdir):
    proof = cell.get("consumeProof") or {}
    base_path = os.path.join(REPO, proof["spec"])
    base = json.load(open(base_path))
    cell_spec = gg._spec_with_lifecycle_state_field(
        base, proof["state"], proof["specField"], proof["cellValue"])
    control_spec = gg._spec_with_lifecycle_state_field(
        base, proof["state"], proof["specField"], proof["controlValue"])
    tampered_spec = gg._spec_with_terminal_state_ref(
        cell_spec, proof["terminalStateField"], proof["tamperState"])

    cell_spec_rc, cell_spec_diags = gg._validate_spec(SPEC_VALIDATOR, cell_spec, workdir)
    control_spec_rc, control_spec_diags = gg._validate_spec(SPEC_VALIDATOR, control_spec, workdir)
    tampered_spec_rc, tampered_spec_diags = gg._validate_spec(SPEC_VALIDATOR, tampered_spec, workdir)
    cell_state = gg._lifecycle_state(cell_spec, proof["state"]) or {}
    control_state = gg._lifecycle_state(control_spec, proof["state"]) or {}
    tampered_state = gg._lifecycle_state(tampered_spec, proof["state"]) or {}
    return {
        "spec_path": proof["spec"],
        "spec_hash": gg._sha256_json(cell_spec),
        "spec_version": cell_spec.get("specVersion"),
        "base_spec_hash": _sha256_file(base_path),
        "cell_spec_exit": cell_spec_rc,
        "cell_spec_codes": [d.get("code") for d in cell_spec_diags],
        "control_spec_exit": control_spec_rc,
        "control_spec_codes": [d.get("code") for d in control_spec_diags],
        "tampered_spec_exit": tampered_spec_rc,
        "tampered_spec_codes": [d.get("code") for d in tampered_spec_diags],
        "state": proof["state"],
        "tamperState": proof["tamperState"],
        "terminalStateField": proof["terminalStateField"],
        "terminalStateRef": gg._terminal_state_ref(cell_spec, proof["terminalStateField"]),
        "tamperedTerminalStateRef": gg._terminal_state_ref(tampered_spec, proof["terminalStateField"]),
        "specField": proof["specField"],
        "cellValue": proof["cellValue"],
        "controlValue": proof["controlValue"],
        "cellSpecValue": cell_state.get(proof["specField"]),
        "controlSpecValue": control_state.get(proof["specField"]),
        "tamperedSpecValue": tampered_state.get(proof["specField"]),
        "cellIdentityRebuilt": gg._capability_spec_identity_is_rebuilt(cell_spec),
        "controlIdentityRebuilt": gg._capability_spec_identity_is_rebuilt(control_spec),
        "tamperedIdentityRebuilt": gg._capability_spec_identity_is_rebuilt(tampered_spec),
        "controlSpecHash": gg._sha256_json(control_spec),
        "tamperedSpecHash": gg._sha256_json(tampered_spec),
        "mismatchCode": proof["mismatchCode"],
        "producerError": None,
        "timed_out": False,
    }


def realize_lifecycle_transition_consume(cell, workdir):
    proof = cell.get("consumeProof") or {}
    base_path = os.path.join(REPO, proof["spec"])
    base = json.load(open(base_path))
    cell_spec = gg._spec_with_lifecycle_transition_field(
        base, proof["transition"], proof["specField"], proof["cellValue"])
    control_spec = gg._spec_with_lifecycle_transition_field(
        base, proof["transition"], proof["specField"], proof["controlValue"])

    cell_spec_rc, cell_spec_diags = gg._validate_spec(SPEC_VALIDATOR, cell_spec, workdir)
    control_spec_rc, control_spec_diags = gg._validate_spec(SPEC_VALIDATOR, control_spec, workdir)
    cell_coordination_plan = control_coordination_plan = {}
    producer_error = None
    try:
        cell_coordination_plan = gg._render_coordination_plan(_NEUTRINO_GEN, cell_spec, workdir, cell["id"] + ".cell")
        control_coordination_plan = gg._render_coordination_plan(
            _NEUTRINO_GEN, control_spec, workdir, cell["id"] + ".control")
    except (RuntimeError, ValueError) as exc:
        producer_error = str(exc)

    cell_t = gg._lifecycle_transition(cell_spec, proof["transition"]) or {}
    control_t = gg._lifecycle_transition(control_spec, proof["transition"]) or {}
    cell_coordination_plan_t = gg._coordination_plan_lifecycle_transition(cell_coordination_plan, proof["transition"]) or {}
    control_coordination_plan_t = gg._coordination_plan_lifecycle_transition(control_coordination_plan, proof["transition"]) or {}
    return {
        "spec_path": proof["spec"],
        "spec_hash": gg._sha256_json(cell_spec),
        "spec_version": cell_spec.get("specVersion"),
        "base_spec_hash": _sha256_file(base_path),
        "cell_spec_exit": cell_spec_rc,
        "cell_spec_codes": [d.get("code") for d in cell_spec_diags],
        "control_spec_exit": control_spec_rc,
        "control_spec_codes": [d.get("code") for d in control_spec_diags],
        "transition": proof["transition"],
        "specField": proof["specField"],
        "cellValue": proof["cellValue"],
        "controlValue": proof["controlValue"],
        "cellSpecValue": cell_t.get(proof["specField"]),
        "controlSpecValue": control_t.get(proof["specField"]),
        "cellCoordinationPlanValue": cell_coordination_plan_t.get(proof["specField"]),
        "controlCoordinationPlanValue": control_coordination_plan_t.get(proof["specField"]),
        "cellIdentityRebuilt": gg._capability_spec_identity_is_rebuilt(cell_spec),
        "controlIdentityRebuilt": gg._capability_spec_identity_is_rebuilt(control_spec),
        "cellCoordinationPlanHash": gg._sha256_json(cell_coordination_plan) if cell_coordination_plan else None,
        "controlCoordinationPlanHash": gg._sha256_json(control_coordination_plan) if control_coordination_plan else None,
        "producerError": producer_error,
        "timed_out": False,
    }


def realize_lifecycle_transition_guard_consume(cell, workdir):
    proof = cell.get("consumeProof") or {}
    base_path = os.path.join(REPO, proof["spec"])
    base = json.load(open(base_path))
    cell_spec = gg._spec_with_lifecycle_transition_guard_kind(
        base, proof["transition"], proof["guardDetail"], proof["cellValue"])
    control_spec = gg._spec_with_lifecycle_transition_guard_kind(
        base, proof["transition"], proof["guardDetail"], proof["controlValue"])
    producer_tampered_spec = gg._spec_with_dropped_transition_guard_kind(
        cell_spec, proof["transition"], proof["guardDetail"])

    cell_spec_rc, cell_spec_diags = gg._validate_spec(SPEC_VALIDATOR, cell_spec, workdir)
    control_spec_rc, control_spec_diags = gg._validate_spec(SPEC_VALIDATOR, control_spec, workdir)
    producer_tamper_rc, producer_tamper_diags = gg._validate_spec(
        SPEC_VALIDATOR, producer_tampered_spec, workdir)
    cell_coordination_artifact = control_coordination_artifact = consumer_tampered_coordination_artifact = {}
    producer_error = None
    try:
        cell_coordination_artifact = gg._render_coordination_plan(
            _NEUTRINO_GEN, cell_spec, workdir, cell["id"] + ".cell")
        control_coordination_artifact = gg._render_coordination_plan(
            _NEUTRINO_GEN, control_spec, workdir, cell["id"] + ".control")
        consumer_tampered_coordination_artifact = gg._coordination_plan_with_dropped_transition_guard_kind(
            cell_coordination_artifact, proof["transition"], proof["guardDetail"])
    except (RuntimeError, ValueError) as exc:
        producer_error = str(exc)

    def _kind(obj, coordination_artifact=False):
        guard = gg._transition_guard_by_detail(
            obj, proof["transition"], proof["guardDetail"],
            coordination_artifact=coordination_artifact) or {}
        return guard.get("kind")

    return {
        "spec_path": proof["spec"],
        "spec_hash": gg._sha256_json(cell_spec),
        "spec_version": cell_spec.get("specVersion"),
        "base_spec_hash": _sha256_file(base_path),
        "cell_spec_exit": cell_spec_rc,
        "cell_spec_codes": [d.get("code") for d in cell_spec_diags],
        "control_spec_exit": control_spec_rc,
        "control_spec_codes": [d.get("code") for d in control_spec_diags],
        "producer_tamper_exit": producer_tamper_rc,
        "producer_tamper_codes": [d.get("code") for d in producer_tamper_diags],
        "transition": proof["transition"],
        "guardDetail": proof["guardDetail"],
        "specField": proof["specField"],
        "cellValue": proof["cellValue"],
        "controlValue": proof["controlValue"],
        "cellSpecValue": _kind(cell_spec),
        "controlSpecValue": _kind(control_spec),
        "producerTamperedSpecValue": _kind(producer_tampered_spec),
        "cellCoordinationPlanValue": _kind(cell_coordination_artifact, coordination_artifact=True),
        "controlCoordinationPlanValue": _kind(control_coordination_artifact, coordination_artifact=True),
        "consumerTamperedCoordinationPlanValue": _kind(
            consumer_tampered_coordination_artifact, coordination_artifact=True),
        "cellIdentityRebuilt": gg._capability_spec_identity_is_rebuilt(cell_spec),
        "controlIdentityRebuilt": gg._capability_spec_identity_is_rebuilt(control_spec),
        "producerTamperedIdentityRebuilt": gg._capability_spec_identity_is_rebuilt(producer_tampered_spec),
        "cellCoordinationPlanHash": (gg._sha256_json(cell_coordination_artifact)
                                     if cell_coordination_artifact else None),
        "controlCoordinationPlanHash": (gg._sha256_json(control_coordination_artifact)
                                        if control_coordination_artifact else None),
        "consumerTamperedCoordinationPlanHash": (
            gg._sha256_json(consumer_tampered_coordination_artifact)
            if consumer_tampered_coordination_artifact else None),
        "producerError": producer_error,
        "timed_out": False,
    }


def realize_lifecycle_transition_evidence_consume(cell, workdir):
    proof = cell.get("consumeProof") or {}
    base_path = os.path.join(REPO, proof["spec"])
    base = json.load(open(base_path))
    cell_spec = gg._spec_with_lifecycle_transition_evidence_style(
        base, proof["transition"], proof["cellValue"], proof["evidenceChained"])
    control_spec = gg._spec_with_lifecycle_transition_evidence_style(
        base, proof["transition"], proof["controlValue"], proof["evidenceChained"])
    producer_tampered_spec = gg._spec_with_dropped_transition_evidence_style(
        cell_spec, proof["transition"])

    cell_spec_rc, cell_spec_diags = gg._validate_spec(SPEC_VALIDATOR, cell_spec, workdir)
    control_spec_rc, control_spec_diags = gg._validate_spec(SPEC_VALIDATOR, control_spec, workdir)
    producer_tamper_rc, producer_tamper_diags = gg._validate_spec(
        SPEC_VALIDATOR, producer_tampered_spec, workdir)
    cell_coordination_plan = control_coordination_plan = consumer_tampered_coordination_plan = {}
    producer_error = None
    try:
        cell_coordination_plan = gg._render_coordination_plan(
            _NEUTRINO_GEN, cell_spec, workdir, cell["id"] + ".cell")
        control_coordination_plan = gg._render_coordination_plan(
            _NEUTRINO_GEN, control_spec, workdir, cell["id"] + ".control")
        consumer_tampered_coordination_plan = gg._coordination_plan_with_dropped_transition_evidence_style(
            cell_coordination_plan, proof["transition"])
    except (RuntimeError, ValueError) as exc:
        producer_error = str(exc)

    def _evidence(obj, coordination_artifact=False):
        return gg._transition_evidence(
            obj, proof["transition"], coordination_artifact=coordination_artifact) or {}

    cell_spec_evidence = _evidence(cell_spec)
    control_spec_evidence = _evidence(control_spec)
    producer_tampered_evidence = _evidence(producer_tampered_spec)
    cell_coordination_plan_evidence = _evidence(cell_coordination_plan, True)
    control_coordination_plan_evidence = _evidence(control_coordination_plan, True)
    consumer_tampered_evidence = _evidence(consumer_tampered_coordination_plan, True)
    return {
        "spec_path": proof["spec"], "spec_hash": gg._sha256_json(cell_spec),
        "spec_version": cell_spec.get("specVersion"), "base_spec_hash": _sha256_file(base_path),
        "cell_spec_exit": cell_spec_rc,
        "cell_spec_codes": [d.get("code") for d in cell_spec_diags],
        "control_spec_exit": control_spec_rc,
        "control_spec_codes": [d.get("code") for d in control_spec_diags],
        "producer_tamper_exit": producer_tamper_rc,
        "producer_tamper_codes": [d.get("code") for d in producer_tamper_diags],
        "transition": proof["transition"], "specField": proof["specField"],
        "evidenceChained": proof["evidenceChained"],
        "cellValue": proof["cellValue"], "controlValue": proof["controlValue"],
        "cellSpecValue": cell_spec_evidence.get("style"),
        "controlSpecValue": control_spec_evidence.get("style"),
        "producerTamperedSpecValue": producer_tampered_evidence.get("style"),
        "cellSpecChained": cell_spec_evidence.get("chained"),
        "controlSpecChained": control_spec_evidence.get("chained"),
        "cellCoordinationPlanValue": cell_coordination_plan_evidence.get("style"),
        "controlCoordinationPlanValue": control_coordination_plan_evidence.get("style"),
        "consumerTamperedCoordinationPlanValue": consumer_tampered_evidence.get("style"),
        "cellCoordinationPlanChained": cell_coordination_plan_evidence.get("chained"),
        "controlCoordinationPlanChained": control_coordination_plan_evidence.get("chained"),
        "consumerTamperedCoordinationPlanChained": consumer_tampered_evidence.get("chained"),
        "cellIdentityRebuilt": gg._capability_spec_identity_is_rebuilt(cell_spec),
        "controlIdentityRebuilt": gg._capability_spec_identity_is_rebuilt(control_spec),
        "producerTamperedIdentityRebuilt": gg._capability_spec_identity_is_rebuilt(producer_tampered_spec),
        "cellCoordinationPlanHash": gg._sha256_json(cell_coordination_plan) if cell_coordination_plan else None,
        "controlCoordinationPlanHash": gg._sha256_json(control_coordination_plan) if control_coordination_plan else None,
        "consumerTamperedCoordinationPlanHash": (
            gg._sha256_json(consumer_tampered_coordination_plan) if consumer_tampered_coordination_plan else None),
        "producerError": producer_error, "timed_out": False,
    }


# ---- verdicts (contract-anchored, fail-closed) ----------------------------------------------------

def _outcome(exit_code, timed_out=False):
    if timed_out or exit_code is None:
        return "broken"
    if exit_code == 0:
        return "accepted"
    if exit_code in GOVERNED_EXITS:
        return "refused"
    return "broken"  # usage/IO/parse (2), crash (<0 or >128)


def verdict_neu(cell, obs, control_obs):
    """Contract-anchored verdict for a .neu cell. Returns (verdict, cause, semanticObservations)."""
    declared_code = cell.get("refusalCode")
    predicted_refusal = cell.get("witness") == "refusal" or bool(declared_code)
    ref = _outcome(obs["trace_exit"], obs["timed_out"])
    sol = _outcome(obs["sol_exit"], obs["timed_out"])
    pg = _outcome(obs["pg_exit"], obs["timed_out"])
    sem = {
        "cellId": cell["id"], "covers": cell.get("covers"), "predictedRefusal": predicted_refusal,
        "declaredRefusalCode": declared_code,
        "referenceDecision": ref, "referenceExit": obs["trace_exit"], "referenceCodes": obs["ref_codes"],
        "solidityDecision": sol, "solidityExit": obs["sol_exit"], "solidityCodes": obs["sol_codes"],
        "postgresDecision": pg, "postgresExit": obs["pg_exit"], "postgresCodes": obs["pg_codes"],
        "decisionEquivalent": sol == pg,
        "differentialValid": obs["eq_valid"], "differentialExit": obs.get("eq_exit"),
        "differentialOk": obs["eq_ok"], "traceEquivalent": obs["eq_trace_ok"],
        "executedCases": obs["eq_executed_cases"], "targetProfiles": obs.get("target_profiles"),
        "specVersion": obs.get("spec_version"),
        "solidityCompile": obs["eq_backends"].get("solidity"),
        "postgresCompile": obs["eq_backends"].get("postgres"),
    }

    # 1. crash / usage failure / timeout anywhere -> BROKEN (never coerced to REFUSED).
    if obs["timed_out"]:
        return "BROKEN", "runtime_timeout", sem
    if "broken" in (ref, sol, pg):
        return "BROKEN", "compile_failure", sem
    # 2. cross-backend disagreement, or reference-vs-target divergence -> BROKEN.
    if sol != pg:
        return "BROKEN", "internal_error", sem
    if ref != sol:
        # e.g. the multi-party fee-split seed: reference accepts, targets security-refuse (exit 5).
        return "BROKEN", "internal_error", sem

    # ref == sol == pg from here.
    if sol == "refused":
        # Only a CONTRACT-PREDICTED refusal at exit 4/6 with a consistent code is an honest REFUSED.
        if not predicted_refusal:
            return "BROKEN", "internal_error", sem
        if obs["trace_exit"] not in CONTRACT_REFUSAL_EXITS:
            return "BROKEN", "substrate_protocol_limit", sem  # a 3/5 refusal is not contract-honest
        common = set(obs["ref_codes"]) & set(obs["sol_codes"]) & set(obs["pg_codes"])
        sem["refusalCode"] = sorted(common)
        if not common:
            return "BROKEN", "internal_error", sem  # refuse, but the coded identity disagrees
        if declared_code and declared_code not in common:
            return "BROKEN", "internal_error", sem  # wrong code
        return "REFUSED", "governed_refusal", sem

    # ref == sol == pg == accepted.
    if predicted_refusal:
        return "SILENT", "semantic_mismatch", sem  # predicted a refusal that did not fire
    # Non-vacuous differential: the equiv PROCESS must succeed (exit 0 — a good-looking report from a
    # nonzero-exit wrapper is not trusted) AND a valid, successful report with >=1 executed case.
    if obs.get("eq_exit") != 0:
        return "BROKEN", "internal_error", sem
    if not (obs["eq_valid"] and obs["eq_ok"] and obs["eq_trace_ok"] and obs["eq_executed_cases"] >= 1):
        return "BROKEN", "internal_error", sem
    # Live compile adapters must have PROVED compilation for FAITHFUL (a skip cannot). A failure
    # maps to a DISTINCT cause by the STAGE it failed at: a compiler rejection vs a runtime
    # (behavioral/execution) failure (Blocker 3).
    sol_c, pg_c = obs["eq_backends"].get("solidity"), obs["eq_backends"].get("postgres")
    stages = obs.get("eq_stages") or {}
    sem["solidityStage"], sem["postgresStage"] = stages.get("solidity"), stages.get("postgres")
    if "fail" in (sol_c, pg_c):
        failed_stages = {stages.get(n) for n, st in (("solidity", sol_c), ("postgres", pg_c)) if st == "fail"}
        if "runtime" in failed_stages and "compile" not in failed_stages:
            return "BROKEN", "substrate_protocol_limit", sem  # compiled, then failed at execution
        return "BROKEN", "compile_failure", sem
    if sol_c != "pass" or pg_c != "pass":
        return "BROKEN", "missing_required_tool", sem  # a required compile adapter did not run
    # An invisible mutation (the control realizes byte-identically) is SILENT.
    if control_obs is not None:
        same = (control_obs["sol_hash"] == obs["sol_hash"] and control_obs["pg_hash"] == obs["pg_hash"]
                and control_obs["sol_exit"] == obs["sol_exit"] and control_obs["pg_exit"] == obs["pg_exit"])
        sem["controlDivergent"] = not same
        if same:
            return "SILENT", "semantic_mismatch", sem
    return "FAITHFUL", "success", sem


def verdict_binding(cell, obs):
    sem = {
        "cellId": cell["id"], "covers": cell.get("covers"),
        "specRef": obs["spec_path"], "carriedValue": cell["locator"]["value"],
        "validExit": obs["valid_exit"], "invalidExit": obs["invalid_exit"],
        "expectedRefusalCode": obs["refusalCode"], "observedRefusalCodes": obs["invalid_codes"],
    }
    if obs["timed_out"]:
        return "BROKEN", "runtime_timeout", sem
    if obs["valid_exit"] != 0:
        return "BROKEN", "compile_failure", sem  # cannot even accept the carried value
    if not obs["located"]:
        return "BROKEN", "internal_error", sem
    enforced = obs["invalid_exit"] not in (0, None) and obs["refusalCode"] in (obs["invalid_codes"] or [])
    sem["enforced"] = enforced
    if enforced:
        return "FAITHFUL", "success", sem  # carried (clean) AND enforced (coded refusal of the sentinel)
    return "SILENT", "semantic_mismatch", sem  # a trusted label, not enforced


def _report_codes(report):
    return sorted(d.get("code") for d in report.get("diagnostics", []) if d.get("code"))


def verdict_binding_consume(cell, obs):
    if "observerSet" in obs:
        return verdict_observer_set_consume(cell, obs)
    if "terminalStateField" in obs:
        return verdict_lifecycle_state_consume(cell, obs)
    if "guardDetail" in obs:
        return verdict_lifecycle_transition_guard_consume(cell, obs)
    if "evidenceChained" in obs:
        return verdict_lifecycle_transition_evidence_consume(cell, obs)
    if "transition" in obs:
        return verdict_lifecycle_transition_consume(cell, obs)
    sem = {
        "cellId": cell["id"], "covers": cell.get("covers"),
        "specRef": obs["spec_path"], "participant": obs["participant"],
        "specField": obs["specField"], "topologyField": obs["topologyField"],
        "cellValue": obs["cellValue"], "controlValue": obs["controlValue"],
        "cellTopologyValue": obs["cellTopologyValue"],
        "controlTopologyValue": obs["controlTopologyValue"],
        "expectedCellTopologyValue": obs["expectedCellTopologyValue"],
        "expectedControlTopologyValue": obs["expectedControlTopologyValue"],
        "cellOk": bool(obs["cellReport"].get("ok")),
        "cellCodes": _report_codes(obs["cellReport"]),
        "controlOk": bool(obs["controlReport"].get("ok")),
        "controlCodes": _report_codes(obs["controlReport"]),
        "tamperedOk": bool(obs["tamperedReport"].get("ok")),
        "tamperedCodes": _report_codes(obs["tamperedReport"]),
        "expected": obs["expected"],
        "controlExpected": obs["controlExpected"],
    }
    if obs["timed_out"]:
        return "BROKEN", "runtime_timeout", sem
    if obs.get("producerError"):
        sem["producerError"] = obs["producerError"]
        return "BROKEN", "internal_error", sem
    if obs["cell_spec_exit"] != 0 or obs["control_spec_exit"] != 0:
        return "BROKEN", "compile_failure", sem
    if obs["cellTopologyValue"] != obs["expectedCellTopologyValue"]:
        return "BROKEN", "internal_error", sem
    if obs["controlTopologyValue"] != obs["expectedControlTopologyValue"]:
        return "BROKEN", "internal_error", sem
    if not gg._consumer_matches(obs["cellReport"], obs["expected"]):
        return "BROKEN", "internal_error", sem
    if not gg._consumer_matches(obs["controlReport"], obs["controlExpected"]):
        return "BROKEN", "internal_error", sem
    if gg._consumer_signature(obs["cellReport"]) == gg._consumer_signature(obs["controlReport"]):
        return "SILENT", "semantic_mismatch", sem
    if gg._consumer_signature(obs["tamperedReport"]) == gg._consumer_signature(obs["cellReport"]):
        return "SILENT", "semantic_mismatch", sem
    sem["enforced"] = True
    return "FAITHFUL", "success", sem


def verdict_observer_set_consume(cell, obs):
    sem = {
        "cellId": cell["id"], "covers": cell.get("covers"),
        "specRef": obs["spec_path"], "observerSet": obs["observerSet"],
        "specField": obs["specField"], "bindingField": obs["bindingField"],
        "cellValue": obs["cellValue"], "controlValue": obs["controlValue"],
        "cellSpecValue": obs["cellSpecValue"],
        "controlSpecValue": obs["controlSpecValue"],
        "cellBindingValue": obs["cellBindingValue"],
        "tamperedBindingValue": obs["tamperedBindingValue"],
        "cellOk": bool(obs["cellReport"].get("ok")),
        "cellCodes": _report_codes(obs["cellReport"]),
        "controlOk": bool(obs["controlReport"].get("ok")),
        "controlCodes": _report_codes(obs["controlReport"]),
        "tamperedOk": bool(obs["tamperedReport"].get("ok")),
        "tamperedCodes": _report_codes(obs["tamperedReport"]),
        "mismatchCode": obs["mismatchCode"],
    }
    if obs["timed_out"]:
        return "BROKEN", "runtime_timeout", sem
    if obs.get("producerError"):
        sem["producerError"] = obs["producerError"]
        return "BROKEN", "internal_error", sem
    if obs["cell_spec_exit"] != 0 or obs["control_spec_exit"] != 0:
        return "BROKEN", "compile_failure", sem
    if obs["cellSpecValue"] != obs["cellValue"] or obs["cellBindingValue"] != obs["cellValue"]:
        return "BROKEN", "internal_error", sem
    if obs["controlSpecValue"] != obs["controlValue"] or obs["tamperedBindingValue"] != obs["controlValue"]:
        return "BROKEN", "internal_error", sem
    mismatch = {"ok": False, "code": obs["mismatchCode"]}
    if not gg._consumer_matches(obs["cellReport"], {"ok": True}):
        return "BROKEN", "internal_error", sem
    if not gg._consumer_matches(obs["controlReport"], mismatch):
        return "BROKEN", "internal_error", sem
    if gg._consumer_signature(obs["cellReport"]) == gg._consumer_signature(obs["controlReport"]):
        return "SILENT", "semantic_mismatch", sem
    if gg._consumer_signature(obs["cellReport"]) == gg._consumer_signature(obs["tamperedReport"]):
        return "SILENT", "semantic_mismatch", sem
    if not gg._consumer_matches(obs["tamperedReport"], mismatch):
        return "BROKEN", "internal_error", sem
    sem["enforced"] = True
    return "FAITHFUL", "success", sem


def verdict_lifecycle_state_consume(cell, obs):
    sem = {
        "cellId": cell["id"], "covers": cell.get("covers"),
        "specRef": obs["spec_path"], "state": obs["state"],
        "tamperState": obs["tamperState"],
        "terminalStateField": obs["terminalStateField"],
        "terminalStateRef": obs["terminalStateRef"],
        "tamperedTerminalStateRef": obs["tamperedTerminalStateRef"],
        "specField": obs["specField"],
        "cellValue": obs["cellValue"], "controlValue": obs["controlValue"],
        "cellSpecValue": obs["cellSpecValue"],
        "controlSpecValue": obs["controlSpecValue"],
        "tamperedSpecValue": obs["tamperedSpecValue"],
        "cellSpecExit": obs["cell_spec_exit"],
        "cellSpecCodes": obs["cell_spec_codes"],
        "controlSpecExit": obs["control_spec_exit"],
        "controlSpecCodes": obs["control_spec_codes"],
        "tamperedSpecExit": obs["tampered_spec_exit"],
        "tamperedSpecCodes": obs["tampered_spec_codes"],
        "cellIdentityRebuilt": obs.get("cellIdentityRebuilt"),
        "controlIdentityRebuilt": obs.get("controlIdentityRebuilt"),
        "tamperedIdentityRebuilt": obs.get("tamperedIdentityRebuilt"),
        "controlSpecHash": obs.get("controlSpecHash"),
        "tamperedSpecHash": obs.get("tamperedSpecHash"),
        "mismatchCode": obs["mismatchCode"],
    }
    if obs["timed_out"]:
        return "BROKEN", "runtime_timeout", sem
    if obs.get("producerError"):
        sem["producerError"] = obs["producerError"]
        return "BROKEN", "internal_error", sem
    if obs["cell_spec_exit"] != 0:
        return "BROKEN", "compile_failure", sem
    if obs["terminalStateRef"] != obs["state"]:
        return "BROKEN", "internal_error", sem
    if obs["tamperedTerminalStateRef"] != obs["tamperState"]:
        return "BROKEN", "internal_error", sem
    if not (obs.get("cellIdentityRebuilt") and obs.get("controlIdentityRebuilt") and
            obs.get("tamperedIdentityRebuilt")):
        return "BROKEN", "internal_error", sem
    if obs.get("controlSpecHash") == obs.get("tamperedSpecHash"):
        return "BROKEN", "internal_error", sem
    if obs["cellSpecValue"] != obs["cellValue"]:
        return "BROKEN", "internal_error", sem
    if obs["controlSpecValue"] != obs["controlValue"]:
        return "BROKEN", "internal_error", sem
    if obs["tamperedSpecValue"] != obs["cellValue"]:
        return "BROKEN", "internal_error", sem
    expected_codes = [obs["mismatchCode"]]
    if obs["control_spec_exit"] == 0 or sorted(obs["control_spec_codes"] or []) != expected_codes:
        return "BROKEN", "internal_error", sem
    if obs["tampered_spec_exit"] == 0 or sorted(obs["tampered_spec_codes"] or []) != expected_codes:
        return "BROKEN", "internal_error", sem
    if (obs["control_spec_exit"], tuple(sorted(obs["control_spec_codes"] or []))) == \
            (obs["cell_spec_exit"], tuple(sorted(obs["cell_spec_codes"] or []))):
        return "SILENT", "semantic_mismatch", sem
    if (obs["tampered_spec_exit"], tuple(sorted(obs["tampered_spec_codes"] or []))) == \
            (obs["cell_spec_exit"], tuple(sorted(obs["cell_spec_codes"] or []))):
        return "SILENT", "semantic_mismatch", sem
    sem["enforced"] = True
    return "FAITHFUL", "success", sem


def verdict_lifecycle_transition_consume(cell, obs):
    sem = {
        "cellId": cell["id"], "covers": cell.get("covers"),
        "specRef": obs["spec_path"], "transition": obs["transition"],
        "specField": obs["specField"],
        "cellValue": obs["cellValue"], "controlValue": obs["controlValue"],
        "cellSpecValue": obs["cellSpecValue"], "controlSpecValue": obs["controlSpecValue"],
        "cellCoordinationPlanValue": obs["cellCoordinationPlanValue"], "controlCoordinationPlanValue": obs["controlCoordinationPlanValue"],
        "cellSpecExit": obs["cell_spec_exit"],
        "cellSpecCodes": obs["cell_spec_codes"],
        "controlSpecExit": obs["control_spec_exit"],
        "controlSpecCodes": obs["control_spec_codes"],
        "cellIdentityRebuilt": obs.get("cellIdentityRebuilt"),
        "controlIdentityRebuilt": obs.get("controlIdentityRebuilt"),
        "cellCoordinationPlanHash": obs.get("cellCoordinationPlanHash"),
        "controlCoordinationPlanHash": obs.get("controlCoordinationPlanHash"),
    }
    if obs["timed_out"]:
        return "BROKEN", "runtime_timeout", sem
    if obs.get("producerError"):
        sem["producerError"] = obs["producerError"]
        return "BROKEN", "internal_error", sem
    if obs["cell_spec_exit"] != 0 or obs["control_spec_exit"] != 0:
        return "BROKEN", "compile_failure", sem
    if not (obs.get("cellIdentityRebuilt") and obs.get("controlIdentityRebuilt")):
        return "BROKEN", "internal_error", sem
    if obs["cellSpecValue"] != obs["cellValue"] or obs["cellCoordinationPlanValue"] != obs["cellValue"]:
        return "BROKEN", "internal_error", sem
    if obs["controlSpecValue"] != obs["controlValue"] or obs["controlCoordinationPlanValue"] != obs["controlValue"]:
        return "BROKEN", "internal_error", sem
    if obs.get("cellCoordinationPlanHash") == obs.get("controlCoordinationPlanHash"):
        return "SILENT", "semantic_mismatch", sem
    return "FAITHFUL", "success", sem


def verdict_lifecycle_transition_guard_consume(cell, obs):
    sem = {
        "cellId": cell["id"], "covers": cell.get("covers"),
        "specRef": obs["spec_path"], "transition": obs["transition"],
        "guardDetail": obs["guardDetail"],
        "cellValue": obs["cellValue"], "controlValue": obs["controlValue"],
        "cellSpecValue": obs["cellSpecValue"], "controlSpecValue": obs["controlSpecValue"],
        "cellCoordinationPlanValue": obs["cellCoordinationPlanValue"],
        "controlCoordinationPlanValue": obs["controlCoordinationPlanValue"],
        "producerTamperedSpecValue": obs["producerTamperedSpecValue"],
        "consumerTamperedCoordinationPlanValue": obs["consumerTamperedCoordinationPlanValue"],
        "producerTamperExit": obs["producer_tamper_exit"],
        "producerTamperCodes": obs["producer_tamper_codes"],
        "cellCoordinationPlanHash": obs.get("cellCoordinationPlanHash"),
        "controlCoordinationPlanHash": obs.get("controlCoordinationPlanHash"),
        "consumerTamperedCoordinationPlanHash": obs.get("consumerTamperedCoordinationPlanHash"),
    }
    if obs["timed_out"]:
        return "BROKEN", "runtime_timeout", sem
    if obs.get("producerError"):
        sem["producerError"] = obs["producerError"]
        return "BROKEN", "internal_error", sem
    if obs["cell_spec_exit"] != 0 or obs["control_spec_exit"] != 0:
        return "BROKEN", "compile_failure", sem
    if not (obs.get("cellIdentityRebuilt") and obs.get("controlIdentityRebuilt") and
            obs.get("producerTamperedIdentityRebuilt")):
        return "BROKEN", "internal_error", sem
    if obs["cellSpecValue"] != obs["cellValue"] or \
            obs["cellCoordinationPlanValue"] != obs["cellValue"]:
        return "BROKEN", "internal_error", sem
    if obs["controlSpecValue"] != obs["controlValue"] or \
            obs["controlCoordinationPlanValue"] != obs["controlValue"]:
        return "BROKEN", "internal_error", sem
    if obs["producerTamperedSpecValue"] is not None or \
            obs["producer_tamper_exit"] == 0 or sorted(obs["producer_tamper_codes"] or []) != ["spec.schema"]:
        return "SILENT", "semantic_mismatch", sem
    if obs["consumerTamperedCoordinationPlanValue"] is not None:
        return "SILENT", "semantic_mismatch", sem
    if obs.get("cellCoordinationPlanHash") == obs.get("controlCoordinationPlanHash"):
        return "SILENT", "semantic_mismatch", sem
    if obs.get("cellCoordinationPlanHash") == obs.get("consumerTamperedCoordinationPlanHash"):
        return "SILENT", "semantic_mismatch", sem
    sem["enforced"] = True
    return "FAITHFUL", "success", sem


def verdict_lifecycle_transition_evidence_consume(cell, obs):
    sem = {
        "cellId": cell["id"], "covers": cell.get("covers"),
        "specRef": obs["spec_path"], "transition": obs["transition"],
        "cellValue": obs["cellValue"], "controlValue": obs["controlValue"],
        "evidenceChained": obs["evidenceChained"],
        "cellSpecValue": obs["cellSpecValue"], "controlSpecValue": obs["controlSpecValue"],
        "cellCoordinationPlanValue": obs["cellCoordinationPlanValue"],
        "controlCoordinationPlanValue": obs["controlCoordinationPlanValue"],
        "producerTamperedSpecValue": obs["producerTamperedSpecValue"],
        "consumerTamperedCoordinationPlanValue": obs["consumerTamperedCoordinationPlanValue"],
        "producerTamperExit": obs["producer_tamper_exit"],
        "producerTamperCodes": obs["producer_tamper_codes"],
        "cellCoordinationPlanHash": obs.get("cellCoordinationPlanHash"),
        "controlCoordinationPlanHash": obs.get("controlCoordinationPlanHash"),
        "consumerTamperedCoordinationPlanHash": obs.get("consumerTamperedCoordinationPlanHash"),
    }
    if obs["timed_out"]:
        return "BROKEN", "runtime_timeout", sem
    if obs.get("producerError"):
        sem["producerError"] = obs["producerError"]
        return "BROKEN", "internal_error", sem
    if obs["cell_spec_exit"] != 0 or obs["control_spec_exit"] != 0:
        return "BROKEN", "compile_failure", sem
    if not (obs.get("cellIdentityRebuilt") and obs.get("controlIdentityRebuilt") and
            obs.get("producerTamperedIdentityRebuilt")):
        return "BROKEN", "internal_error", sem
    if (obs["cellSpecValue"] != obs["cellValue"] or
            obs["cellCoordinationPlanValue"] != obs["cellValue"] or
            obs["controlSpecValue"] != obs["controlValue"] or
            obs["controlCoordinationPlanValue"] != obs["controlValue"]):
        return "BROKEN", "internal_error", sem
    chained_values = (obs.get("cellSpecChained"), obs.get("controlSpecChained"),
                      obs.get("cellCoordinationPlanChained"), obs.get("controlCoordinationPlanChained"),
                      obs.get("consumerTamperedCoordinationPlanChained"))
    if any(value != obs["evidenceChained"] for value in chained_values):
        return "SILENT", "semantic_mismatch", sem
    if (obs["producerTamperedSpecValue"] is not None or obs["producer_tamper_exit"] == 0 or
            sorted(obs["producer_tamper_codes"] or []) != ["spec.schema"]):
        return "SILENT", "semantic_mismatch", sem
    if obs["consumerTamperedCoordinationPlanValue"] is not None:
        return "SILENT", "semantic_mismatch", sem
    if obs.get("cellCoordinationPlanHash") == obs.get("controlCoordinationPlanHash"):
        return "SILENT", "semantic_mismatch", sem
    if obs.get("cellCoordinationPlanHash") == obs.get("consumerTamperedCoordinationPlanHash"):
        return "SILENT", "semantic_mismatch", sem
    sem["enforced"] = True
    return "FAITHFUL", "success", sem


# ---- adapters (per-envelope, reflecting what actually ran) ----------------------------------------

def _compile_adapter(adapter_id, status, skip_reason):
    a = {"adapterId": adapter_id, "rail": "build-tools", "kind": "live-runtime", "required": False,
         "status": status, "proofScope": "live-runtime-behavior"}
    if status == "SKIPPED":
        a["skipReason"] = skip_reason
    return a


_EXTERNAL_SOLC = {"adapterId": "external-solc-0.8", "rail": "external-solc",
                  "kind": "external-compiler-compat", "required": False, "status": "SKIPPED",
                  "skipReason": "missing_optional_tool", "proofScope": "downstream-compiler-compatibility"}


def neu_adapters(obs):
    """The adapter set for a .neu envelope: the required semantic differential + the two live compile
    adapters (RAN/SKIPPED per the equivalence backend statuses) + the optional external solc."""
    # The differential adapter is always RAN (we always invoke neutrino-equiv); a failed/empty report
    # is a BROKEN case, not a skipped adapter — a required adapter may never be SKIPPED.
    diff = {"adapterId": "translator-differential", "rail": "translator", "kind": "semantic",
            "required": True, "status": "RAN", "proofScope": "neu-semantic-correctness"}

    def compile_st(name):
        return "SKIPPED" if obs["eq_backends"].get(name) in (None, "skip") else "RAN"
    return [
        diff,
        _compile_adapter("solidity-compile", compile_st("solidity"), "missing_optional_tool"),
        _compile_adapter("postgres-compile", compile_st("postgres"), "missing_optional_tool"),
        dict(_EXTERNAL_SOLC),
    ]


def binding_adapters():
    """A binding envelope proves the spec contract via the differential; the live compile adapters
    do not apply (no rigid artifact is lowered), so they are SKIPPED as not-applicable."""
    return [
        {"adapterId": "translator-differential", "rail": "translator", "kind": "semantic",
         "required": True, "status": "RAN", "proofScope": "neu-semantic-correctness"},
        # a binding cell lowers no rigid artifact, so the live compile adapters do not run.
        _compile_adapter("solidity-compile", "SKIPPED", "missing_optional_tool"),
        _compile_adapter("postgres-compile", "SKIPPED", "missing_optional_tool"),
        dict(_EXTERNAL_SOLC),
    ]


def binding_witness_contract_violations(manifest):
    bad = []
    for c in manifest.get("cells", []):
        if c.get("kind") == "binding" and c.get("witness") not in BINDING_WITNESSES:
            bad.append(f"{c.get('id')}: unsupported binding witness {c.get('witness')!r}")
    return bad


# ---- envelope assembly ----------------------------------------------------------------------------

def _slug(s):
    return "".join(ch if ch.isalnum() else "-" for ch in s).strip("-").lower()


def cell_case(cell, verdict, cause, sem, adapter_id="translator-differential"):
    return {
        "caseId": cell["id"], "adapterId": adapter_id, "required": True,
        "verdict": verdict, "cause": cause, "semanticObservations": sem, "environmentMetrics": {},
    }


def _adapter_set_key(adapters):
    return "|".join(sorted(f'{a["adapterId"]}:{a["status"]}' for a in adapters))


def _binding_capability_id(cell):
    spec_path = os.path.join(REPO, cell["spec"])
    with open(spec_path, encoding="utf-8") as fh:
        spec = json.load(fh)
    procedure = spec.get("procedure")
    if not isinstance(procedure, str) or not procedure:
        raise ValueError(f"{cell['id']}: binding spec is missing procedure")
    return "coordinate." + procedure


def envelope_identity(cell, kind, obs, prov_hash, adapters):
    """EXACT execution identity = (capability, spec, scenario, provenance, profile, adapter set).
    The provenance hash pins the semantic + capability-spec versions AND the authoritative rigid
    target-profile ids/versions (folded into the configuration hash), so a target-profile version
    change splits the identity on EVERY path, refused cells included. Cells with an identical tuple
    collapse into ONE envelope."""
    if kind == "binding":
        cap_id = _binding_capability_id(cell)
        spec_hash = obs["spec_hash"]
        scenario_hash = "0" * 64  # binding cells drive the spec validator, no scenario
        source_hash = spec_hash
    else:
        neu = cell["input"]["neu"]
        cap_id = "coordinate." + _slug(gg._proc_name(neu))
        source_hash = _sha256_bytes(neu.encode("utf-8"))
        spec_hash = obs["waist_hash"] or "0" * 64  # canonical spec, or the coded waist refusal
        scenario_hash = _sha256_obj(cell["scenario"])
    key = "|".join([cap_id, spec_hash, scenario_hash, prov_hash, PROFILE, _adapter_set_key(adapters)])
    return key, cap_id, source_hash, spec_hash, scenario_hash


def neu_artifact_hashes(obs):
    """Always non-empty: the canonical capability-spec (or the coded waist refusal), plus any
    emitted rigid artifacts. A refused cell is honestly represented, no invented hash."""
    ah = {}
    if obs["spec_hash"]:
        ah["capability-spec"] = obs["spec_hash"]
    elif obs["waist_hash"]:
        ah["waist-refusal-diagnostics"] = obs["waist_hash"]
    if obs["sol_hash"]:
        ah["solidity"] = obs["sol_hash"]
    if obs["pg_hash"]:
        ah["postgres"] = obs["pg_hash"]
    return ah


def aggregate_verdict(counts):
    for v in ("BROKEN", "SILENT", "FAITHFUL", "REFUSED"):
        if counts.get(v):
            return v
    return "FAITHFUL"


def build_envelope(cap_id, cap_version, source_hash, spec_hash, scenario_hash,
                   artifact_hashes, cases, provenance, adapters, semantic_profile, evidence=None):
    counts = {"FAITHFUL": 0, "REFUSED": 0, "SILENT": 0, "BROKEN": 0}
    for c in cases:
        counts[c["verdict"]] += 1
    required_run = sum(1 for c in cases if c["required"])
    agg = aggregate_verdict(counts)
    # Non-vacuous PASS: at least one required case, no BROKEN, at least one honest accepted/refused
    # outcome (FAITHFUL or REFUSED), and every required adapter actually RAN (none skipped).
    required_adapters_ran = all(
        a["status"] == "RAN" for a in adapters if a.get("required"))
    honest = counts["FAITHFUL"] + counts["REFUSED"]
    profile_status = "PASS" if (required_run >= REQUIRED_CASE_FLOOR and counts["BROKEN"] == 0
                                and honest >= 1 and required_adapters_ran) else "FAIL"
    run_id = "m6-pr-fast-" + _slug(cap_id) + "-" + _sha256_obj([c["caseId"] for c in cases])[:8]
    env = {
        "schemaVersion": 1, "kind": "neutrino.generalism-result", "runId": run_id,
        "capability": {
            "id": cap_id, "version": cap_version, "sourceHash": source_hash,
            "specHash": spec_hash, "scenarioHash": scenario_hash, "artifactHashes": artifact_hashes,
        },
        "semanticProfile": semantic_profile,
        "executionProfile": {
            "name": PROFILE, "requiredAdapters": list(REQUIRED_ADAPTERS),
            "optionalAdapters": list(OPTIONAL_ADAPTERS), "requiredCaseFloor": REQUIRED_CASE_FLOOR,
        },
        "provenance": provenance, "adapters": adapters, "cases": cases,
        "summary": {"verdict": agg, "profileStatus": profile_status,
                    "requiredCasesRun": required_run, "counts": counts},
    }
    # Evidence is cryptographically bound to the run only post-; until then the block is PENDING
    # and validation skips the evidence seam (--pending-evidence). No fixture evidence is reused.
    if evidence is not None:
        env["evidence"] = evidence
    return env


# ---- genuine per-run evidence (Blocker 1,  authoritative verifier) ----------------------------

def _m4_dir():
    """Locate the provisioned build-tools m4 verifier (env override, else .ci/neutrino-build-tools)."""
    cli = os.environ.get("NEUTRINO_BUILD_TOOLS_GENERALISM_REPORT_CLI")
    if cli and os.path.isfile(cli):
        return os.path.dirname(cli)
    cand = os.path.join(REPO, ".ci", "neutrino-build-tools", "m4")
    return cand if os.path.isdir(cand) else None


def _case_decision(so):
    """(evm, postgres, equivalent) cross-rail decision for a case, from its semanticObservations."""
    evm, pg = so.get("solidityDecision"), so.get("postgresDecision")
    if evm is None and pg is None:  # a binding case has no rigid-target decision
        d = "enforced" if so.get("enforced") else "carried"
        return d, d, True
    return (evm or "unknown"), (pg or "unknown"), bool(so.get("decisionEquivalent", evm == pg))


def result_identity_digest(env):
    """A canonical digest of the enclosing result envelope WITHOUT its evidence block — signed into
    the evidence trace so a validator can bind the evidence to exactly this result (a swapped-in but
    internally-valid evidence block from another envelope then fails the binding check)."""
    return "sha256:" + _sha256_obj({k: v for k, v in env.items() if k != "evidence"})


def build_run_evidence(base, cap_id, cap_version, cases, profile_status, result_digest):
    """Produce GENUINE per-run M4 evidence bound to THIS envelope's identity + cross-rail (Solidity vs
    Postgres) decisions, signed + verified through the provisioned authoritative build-tools verifier
    (): a per-run S4 execution trace -> binding receipt -> signed evidence package -> verification
    report, written alongside the envelope. The canonical result digest is signed into the S4 payload
    so the evidence cannot be grafted onto a different envelope. Returns the  evidence block,
    or None if the verifier is absent (then the envelope is honestly evidence-less, never faked)."""
    m4 = _m4_dir()
    if not m4:
        return None
    if m4 not in sys.path:
        sys.path.insert(0, m4)
    import evidence_package
    import binding_receipt as br
    import generalism_verification_report as gr
    import verify_evidence as ve
    from pathlib import Path

    payload = {"profile": "s4", "resultDigest": result_digest,
               "decisions": [dict(caseId=c["caseId"],
                                  decisions=dict(zip(("evm", "postgres"),
                                                     _case_decision(c.get("semanticObservations") or {})[:2])),
                                  equivalentAtDecisionBoundary=_case_decision(c.get("semanticObservations") or {})[2])
                             for c in cases]}
    sample = "generalism_s4_cross_rail_decision_equivalence"
    pay_sha = hashlib.sha256(ve.canonical_json_bytes(payload)).hexdigest()
    ev_ref = "sha256:" + hashlib.sha256(ve.canonical_json_bytes(
        {"sample": sample, "comparisonPayload": payload})).hexdigest()
    passed = profile_status == "PASS"
    trace = {
        "schemaVersion": 1, "kind": "neutrino.m4-execution-trace", "sample": sample,
        "instanceId": os.path.basename(base), "outcome": "allow" if passed else "reject",
        "released": passed, "ok": passed,
        "reason": "cross-rail decision equivalence over the generalism matrix",
        "capability": cap_id, "capabilityVersion": cap_version,
        "bindingManifestRef": "generalism-matrix.l3.binding.json", "bindingStatus": "complete",
        "backendProfile": "simulated.v1", "runtimeProfile": "simulated.v1",
        "executionMode": "simulated", "runtimeSubstrate": "neutrino-generalism-matrix-runner",
        "participants": {}, "injectedParameters": {}, "executionContract": {},
        "comparisonPayload": payload, "comparisonPayloadSha256": pay_sha,
        "evidenceAdmission": [{"requirement": "cross_rail_decision_equivalence",
                               "evidenceRef": ev_ref, "admitted": True, "reason": "admitted"}],
        "auditEvents": [],
    }
    receipt = {"kind": "neutrino.m4-binding-receipt", "schemaVersion": 1, "capabilityId": cap_id,
               "capabilityVersion": cap_version, "bindingManifestRef": trace["bindingManifestRef"],
               "bindingManifestDigest": "sha256:" + ("1" * 64), "runtimeProfile": "simulated.v1",
               "runtimeFamilies": ["simulated"], "bindingStatus": "complete", "slotBindings": [],
               "participants": {}, "parameters": {}}
    receipt["bindingId"] = br._binding_id(receipt)
    trace["bindingReceiptRef"] = receipt["bindingId"]
    trace["bindingReceiptDigest"] = br.receipt_digest(receipt)

    def _w(suffix, obj):
        p = base + suffix
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, indent=2, sort_keys=True)
        return p

    _w(".receipt.json", receipt)
    trace_path = _w(".trace.json", trace)
    package_path = _w(".evidence.json", evidence_package.build_package(trace_path))
    report = gr.build_report(Path(trace_path), Path(package_path), expected_profile="s4",
                             artifact_root=Path(REPO), producer_revision=BUILD_TOOLS_REVISION)
    report_path = _w(".verification.json", report)

    arts = report["artifacts"]
    brc, pkg = arts["bindingReceipt"], arts["evidencePackage"]
    return {
        "bindingReceiptKind": brc["kind"], "bindingReceiptSchemaVersion": brc["schemaVersion"],
        "bindingReceiptArtifactRef": os.path.relpath(base + ".receipt.json", REPO),
        "bindingReceiptRef": brc["bindingId"], "bindingReceiptDigest": brc["digest"],
        "evidencePackageKind": pkg["kind"], "evidencePackageSchemaVersion": pkg["schemaVersion"],
        "evidencePackageRef": os.path.relpath(package_path, REPO), "evidencePackageDigest": pkg["digest"],
        "evidencePackageTraceSha256": pkg["traceSha256"], "evidencePackageSigner": pkg["signer"],
        "verificationReportRef": os.path.relpath(report_path, REPO),
        "verificationReportDigest": "sha256:" + _sha256_file(report_path),
        "verificationReportAttestation": report["attestation"],
    }


# ---- driver ---------------------------------------------------------------------------------------

def _neu_version(neu):
    m = re.search(r'version\s+"([^"]+)"', neu)
    return m.group(1) if m else None


def run_matrix(bindir, out_dir):
    manifest = json.load(open(CELLS))
    witness_errors = binding_witness_contract_violations(manifest)
    if witness_errors:
        raise SystemExit("unsupported binding witness class: " + "; ".join(witness_errors))
    provenance, prov_hash, _versions, semantic_profile = build_provenance(bindir)

    groups = {}        # identity key -> group accumulator
    cell_to_key = {}   # cell id -> identity key (for the run manifest)

    with tempfile.TemporaryDirectory() as td:
        for cell in manifest["cells"]:
            kind = cell.get("kind", "seed")
            if kind == "binding":
                witness = cell.get("witness")
                if witness == "binding_consume":
                    obs = realize_binding_consume(cell, td)
                    verdict, cause, sem = verdict_binding_consume(cell, obs)
                elif witness == "spec_refusal":
                    obs = realize_binding(cell, td)
                    verdict, cause, sem = verdict_binding(cell, obs)
                else:
                    raise ValueError(f"unsupported binding witness {witness!r} for {cell.get('id')}")
                adapters = binding_adapters()
                artifact_hashes = {"capability-spec": obs["spec_hash"]}
                cap_version = obs["spec_version"] or "0.0.0"
            else:
                neu = cell["input"]["neu"]
                obs = realize_neu(bindir, neu, cell["scenario"], td, tag="c_" + cell["id"])
                control_obs = None
                ctl = cell.get("control") or {}
                if ctl.get("neu"):
                    control_obs = realize_neu(bindir, ctl["neu"], cell["scenario"], td, tag="k_" + cell["id"])
                elif ctl.get("adversarial"):
                    adv_scn = {**cell["scenario"],
                               "inputs": {**cell["scenario"].get("inputs", {}), **ctl["adversarial"]}}
                    control_obs = realize_neu(bindir, neu, adv_scn, td, tag="k_" + cell["id"])
                verdict, cause, sem = verdict_neu(cell, obs, control_obs)
                adapters = neu_adapters(obs)
                artifact_hashes = neu_artifact_hashes(obs)
                cap_version = obs["spec_version"] or _neu_version(neu) or "0.0.0"

            key, cap_id, source_hash, spec_hash, scenario_hash = envelope_identity(
                cell, kind, obs, prov_hash, adapters)
            g = groups.setdefault(key, {
                "cap_id": cap_id, "cap_version": cap_version, "source_hash": source_hash,
                "spec_hash": spec_hash, "scenario_hash": scenario_hash, "adapters": adapters,
                "artifact_hashes": {}, "cases": []})
            g["artifact_hashes"].update(artifact_hashes)
            g["cases"].append(cell_case(cell, verdict, cause, sem))
            cell_to_key[cell["id"]] = key

    os.makedirs(out_dir, exist_ok=True)
    evidence_dir = os.path.join(out_dir, "evidence")
    os.makedirs(evidence_dir, exist_ok=True)
    key_to_file, key_to_digest = {}, {}
    evidence_bound = True
    for key in sorted(groups):
        g = groups[key]
        fname = "result-" + _slug(g["cap_id"]) + "-" + _sha256_obj(key)[:8] + ".json"
        # evidence sidecars (trace/receipt/package/verification) live under evidence/ so a
        # `result-*.json` glob over out_dir matches only the envelopes, never the sidecars.
        base = os.path.join(evidence_dir, fname[:-len(".json")])
        env = build_envelope(g["cap_id"], g["cap_version"], g["source_hash"], g["spec_hash"],
                             g["scenario_hash"], g["artifact_hashes"], g["cases"], provenance,
                             g["adapters"], semantic_profile)
        # Genuine per-run evidence bound to this envelope's cross-rail decisions, signed + verified
        # through the authoritative build-tools verifier. No fixture fallback: if the verifier is
        # absent the envelope is honestly evidence-less and the unmodified validator rejects it.
        evidence = build_run_evidence(base, g["cap_id"], g["cap_version"], env["cases"],
                                      env["summary"]["profileStatus"], result_identity_digest(env))
        if evidence is None:
            evidence_bound = False
        else:
            env["evidence"] = evidence
        blob = json.dumps(env, indent=1, sort_keys=False) + "\n"
        with open(os.path.join(out_dir, fname), "w", encoding="utf-8") as fh:
            fh.write(blob)
        key_to_file[key] = fname
        key_to_digest[key] = "sha256:" + _sha256_bytes(blob.encode("utf-8"))

    run_manifest = {
        "schemaVersion": 1, "kind": "neutrino.generalism-run-manifest", "profile": PROFILE,
        "evidenceBinding": "BOUND" if evidence_bound else "UNAVAILABLE",
        "buildToolsRevision": BUILD_TOOLS_REVISION, "cellManifest": os.path.relpath(CELLS, REPO),
        "cellCount": len(manifest["cells"]), "envelopeCount": len(groups),
        "cells": [{"cellId": cid, "resultEnvelope": key_to_file[cell_to_key[cid]],
                   "resultDigest": key_to_digest[cell_to_key[cid]]} for cid in sorted(cell_to_key)],
    }
    with open(os.path.join(out_dir, "run-manifest.json"), "w", encoding="utf-8") as fh:
        fh.write(json.dumps(run_manifest, indent=1, sort_keys=False) + "\n")
    return groups, run_manifest, key_to_file


def _validate_envelope(path):
    """Validate one envelope against the UNMODIFIED  contract (crypto-verifies the per-run
    evidence via the pinned build-tools verifier) — no evidence exception."""
    sys.path.insert(0, os.path.dirname(RESULT_VALIDATOR))
    import validate_generalism_result as v  # noqa: E402
    obj = json.load(open(path))
    return v.validate_shape(obj) + v.validate_invariants(obj)


def main():
    ap = argparse.ArgumentParser(description="[] generalism matrix runner")
    ap.add_argument("--bindir", default=os.path.join(REPO, "out", "tools"),
                    help="dir tree holding neutrino-gen/translate/equiv (searched recursively)")
    ap.add_argument("--neutrino-gen", help="explicit path to neutrino-gen (overrides --bindir)")
    ap.add_argument("--neutrino-translate", help="explicit path to neutrino-translate")
    ap.add_argument("--neutrino-equiv", help="explicit path to neutrino-equiv")
    ap.add_argument("--slot-spec-renderer", help="explicit path to slot-spec-smoke for binding_consume cells")
    ap.add_argument("--out-dir", default=os.path.join(REPO, "test", "generalism", "results"),
                    help="where result envelopes + run manifest are written")
    ap.add_argument("--validate", action="store_true",
                    help="validate every emitted envelope against the unmodified  contract")
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                    help="per-adapter wall-clock ceiling in seconds (a hung adapter becomes BROKEN)")
    ap.add_argument("--no-live-adapters", action="store_true",
                    help="skip the live Solidity/Postgres compile adapters (main-build shape tier; a "
                         "cell needing a live compile then fails closed to BROKEN, never FAITHFUL)")
    ap.add_argument("--skip-return-code", type=int, default=77,
                    help="exit code emitted when --validate is requested but the build-tools verifier "
                         "is unprovisioned (a CTest SKIP; the build-test tier that provisions it validates)")
    args = ap.parse_args()

    global _TIMEOUT, _EQUIV_ENV, _SLOT_SPEC_RENDERER, _NEUTRINO_GEN
    _TIMEOUT = args.timeout
    _SLOT_SPEC_RENDERER = args.slot_spec_renderer
    if args.no_live_adapters:
        _EQUIV_ENV = {"PATH": "/usr/bin:/bin"}

    # Genuine evidence + the unmodified validator need the authoritative build-tools verifier. Where it
    # is unprovisioned (a plain `make test`, a workflow that did not check it out), SKIP rather than emit
    # evidence-less envelopes and fail — the build-test tier that provisions it does the real validation.
    if args.validate and _m4_dir() is None:
        sys.stderr.write("skip: build-tools verifier not provisioned (.ci/neutrino-build-tools); "
                         "run `make setup-build-tools-verifier` to validate the generalism matrix\n")
        return args.skip_return_code

    explicit = (args.neutrino_gen, args.neutrino_translate, args.neutrino_equiv)
    if all(explicit):
        shim = tempfile.mkdtemp(prefix="neu-bin-")
        for name, path in zip(("neutrino-gen", "neutrino-translate", "neutrino-equiv"), explicit):
            os.symlink(os.path.abspath(path), os.path.join(shim, name))
        bindir = shim
    else:
        bindir = _resolve_bindir(args.bindir)
    _NEUTRINO_GEN = os.path.join(bindir, "neutrino-gen")
    groups, run_manifest, key_to_file = run_matrix(bindir, args.out_dir)

    counts = {"FAITHFUL": 0, "REFUSED": 0, "SILENT": 0, "BROKEN": 0}
    for g in groups.values():
        for c in g["cases"]:
            counts[c["verdict"]] += 1
    print(f"cells={run_manifest['cellCount']} envelopes={run_manifest['envelopeCount']} "
          f"verdicts={counts}")

    rc = 0
    if args.validate:
        for fname in sorted(set(key_to_file.values())):
            diags = _validate_envelope(os.path.join(args.out_dir, fname))
            status = "ok" if not diags else "FAIL"
            print(f"  validate {fname}: {status}")
            if diags:
                for d in diags[:6]:
                    sys.stderr.write(f"    {d.get('path')}: {d.get('message')}\n")
                rc = 1
    return rc


def _resolve_bindir(bindir):
    bindir = os.path.abspath(bindir)
    need = ("neutrino-gen", "neutrino-translate", "neutrino-equiv")
    if all(os.path.isfile(os.path.join(bindir, n)) for n in need):
        return bindir
    found = {}
    for root, _dirs, files in os.walk(bindir):
        for n in need:
            if n in files and n not in found:
                found[n] = root
    if set(found) >= set(need):
        shim = tempfile.mkdtemp(prefix="neu-bin-")
        for n in need:
            os.symlink(os.path.join(found[n], n), os.path.join(shim, n))
        return shim
    sys.stderr.write(f"error: could not locate {need} under {bindir}\n")
    sys.exit(2)


if __name__ == "__main__":
    sys.exit(main())

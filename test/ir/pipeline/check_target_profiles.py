"""[77] M5 WP4 (): target profiles + fail-closed spec-legality gate. Ported verbatim from the retired
run_cpp_tests.sh [77] block (). The stdlib profile validator mirrors the normative
target-profile.schema.json; both real profiles (solidity + postgres) validate clean while 7 committed
negatives hit their exact profile.* codes; every scenario-bearing sample spec is legal against BOTH
real profiles while source-only specs (identified by absence of a committed scenario) have every
primitive explicitly supported or unsupported; a profile missing a needed feature fails closed with a
diagnostic naming the feature, its originating primitive, and its source; advisory vs fail_closed
fallback behaves correctly on an optional unmet feature; and a malformed profile/spec fails closed with
structured legality.bad_input JSON (both in-process and via the check_spec_legality.py CLI), never a crash.

Usage: check_target_profiles.py <examples-dir>
"""
import json
import os
import pathlib
import sys
import glob
import copy
import shutil
import tempfile

EXAMPLES = sys.argv[1]
repo = os.path.dirname(os.path.abspath(EXAMPLES))

sys.path.insert(0, os.path.join(repo, "test", "ir", "pipeline"))
from pipeline_inputs import (Fixture, PipelineInputError,  # noqa: E402
                             resolve_pipeline_inputs)

try:
    sys.path.insert(0, os.path.join(repo, "scripts", "validators"))
    sys.path.insert(0, os.path.join(repo, "scripts", "gates"))
    sys.path.insert(0, os.path.join(repo, "scripts", "samples"))
    import validate_target_profile as VP
    import check_spec_legality as CL
    import spec_feature_matrix as SFM

    # 0. schema alignment: the stdlib profile validator mirrors the normative schema.
    sch = json.load(open(os.path.join(repo, "docs", "schemas", "target-profile.schema.json")))
    assert set(sch["required"]) == VP.FIELDS, "profile field set"
    assert sch["properties"]["schemaVersion"]["const"] == VP.SCHEMA_VERSION, "schemaVersion const"
    assert sch["properties"]["profileId"]["pattern"] == VP.PROFILE_ID_RE.pattern, "profileId pattern"
    assert sch["$defs"]["feature"]["pattern"] == VP.FEATURE_RE.pattern, "feature pattern"
    assert set(sch["properties"]["runtimeFamily"]["enum"]) == VP.RUNTIME_FAMILIES, "runtimeFamily enum"
    assert set(sch["properties"]["executionMode"]["enum"]) == VP.EXEC_MODES, "executionMode enum"
    assert set(sch["properties"]["fallbackPolicy"]["enum"]) == VP.FALLBACK, "fallbackPolicy enum"

    # 1. both real profiles validate clean.
    profs = {}
    for f in glob.glob(os.path.join(repo, "examples", "target-profiles", "*.target-profile.json")):
        p = json.load(open(f)); profs[p["target"]] = p
        assert not [d for d in VP.validate(p) if d["severity"] == "error"], (f, VP.validate(p))
    assert {"solidity", "postgres"} <= set(profs), profs.keys()

    # 2. committed profile negatives -> the exact code.
    negs = {"bad_profile_id.json": "profile.bad_profile_id",
            "profile_version_mismatch.json": "profile.profile_version_mismatch",
            "conflicting_feature.json": "profile.conflicting_feature",
            "unknown_field.json": "profile.unknown_field",
            "bad_feature.json": "profile.bad_feature",
            "bad_semantic_feature.json": "profile.unknown_semantic_feature",
            "bad_semantic_version.json": "profile.profile_version_mismatch"}
    for fn, code in negs.items():
        p = json.load(open(os.path.join(repo, "examples", "target-profiles", "negatives", fn)))
        assert code in {d["code"] for d in VP.validate(p)}, (fn, VP.validate(p))

    # 3. Scenario-bearing fixtures promise backend realizability and must be legal against BOTH
    # real profiles. A source-only fixture is classified solely by the absence of a committed
    # scenario; it need not be legal, but every primitive must be explicitly accounted for by
    # every profile as supported or unsupported. Both classes and the explicit-denial path have
    # floors so deleting scenarios or unsupported accounting cannot create a vacuous pass.
    # : this portfolio used to be a glob over `examples/domains/*`. Every
    # production domain now lives in a published pack, so the glob returned [] and
    # the bare `assert len(specs) >= 10` fired with no message. The specs are
    # production-domain content, so they come from the receipt-verifying resolver at
    # the manifest's pinned coordinates -- and every assert below now carries the
    # diagnostic the empty glob swallowed.
    fixtures = [fixture for fixture in resolve_pipeline_inputs(repo).values()
                if fixture.capability_spec is not None]
    specs = [str(fixture.capability_spec) for fixture in fixtures]
    assert len(specs) >= 10, (
        "receipt-verified capability-spec portfolio collapsed to %d specs (need >=10): "
        "%s" % (len(specs), sorted(fixture.name for fixture in fixtures)))

    def has_committed_scenario(fixture):
        scenario_dir = fixture.root / "scenario"
        return scenario_dir.is_dir() and any(scenario_dir.iterdir())

    def scenario_legality_failures(scenario_fixtures):
        failures = []
        checks = 0
        for fixture in scenario_fixtures:
            spec = json.load(open(fixture.capability_spec))
            for prof in profs.values():
                checks += 1
                errors = [diagnostic for diagnostic in CL.check(spec, prof)
                          if diagnostic["severity"] == "error"]
                if errors:
                    failures.append((fixture.name, prof["profileId"], errors))
        return failures, checks

    scenario_fixtures = [f for f in fixtures if has_committed_scenario(f)]
    source_only_fixtures = [f for f in fixtures if not has_committed_scenario(f)]
    assert scenario_fixtures, (
        "non-vacuous scenario-bearing fixture classification: no resolved fixture "
        "carries a committed scenario")
    assert source_only_fixtures, (
        "non-vacuous source-only fixture classification: every resolved fixture "
        "carries a scenario, so the source-only legality class is untested")
    failures, scenario_checks = scenario_legality_failures(scenario_fixtures)
    assert scenario_checks >= 2, (
        "non-vacuous scenario-bearing profile cross-product: only %d (spec x profile) "
        "legality checks ran" % scenario_checks)
    assert not failures, failures

    for fixture in source_only_fixtures:
        spec = json.load(open(fixture.capability_spec))
        features = {requirement["feature"]
                    for requirement in spec["targetRequirements"]["requirements"]}
        for prof in profs.values():
            supported = set(prof["supportedFeatures"])
            unsupported = set(prof["unsupportedConstructs"])
            assert features <= supported | unsupported, (
                fixture.name, prof["profileId"], sorted(features - supported - unsupported))
    assert all("value_category:extension" in prof["unsupportedConstructs"]
               for prof in profs.values()), "unknown extensions must remain explicitly unsupported"

    # The temporal source-only witness carries the narrow temporal extension rather than the
    # generic fail-closed extension, and EACH file profile supports it.
    # : `1f16e44a` renamed this witness to `core_deadline_transfer` while
    # externalizing the domain, but the identity the published pack declares -- and
    # therefore the only one that can be resolved -- is `deadline_guarded_transfer`.
    temporal_fixture = next(
        (f for f in source_only_fixtures if f.name == "deadline_guarded_transfer"), None)
    assert temporal_fixture is not None, (
        "the temporal source-only witness `deadline_guarded_transfer` is not in the "
        "source-only class: %s" % sorted(f.name for f in source_only_fixtures))
    temporal_path = str(temporal_fixture.capability_spec)
    temporal_spec = json.load(open(temporal_path))
    temporal_features = {requirement["feature"]
                         for requirement in temporal_spec["targetRequirements"]["requirements"]}
    assert "value_extension:temporal" in temporal_features, temporal_features
    assert "value_category:extension" not in temporal_features, temporal_features
    for prof in profs.values():
        assert not [diagnostic for diagnostic in CL.check(temporal_spec, prof)
                    if diagnostic["severity"] == "error"], (prof["profileId"], CL.check(temporal_spec, prof))

    # Classification mutation: adding a complete scenario moves the same spec into the strict
    # backend-eligible portfolio, where the narrow feature remains legal for both profiles.
    with tempfile.TemporaryDirectory() as temp:
        domain = os.path.join(temp, "deadline_guarded_transfer")
        copied_spec = os.path.join(domain, "generated", "capability-spec", "capability-spec.json")
        os.makedirs(os.path.dirname(copied_spec))
        shutil.copyfile(temporal_path, copied_spec)
        scenario_dir = os.path.join(domain, "scenario")
        os.makedirs(scenario_dir)
        with open(os.path.join(scenario_dir, "deadline_guarded_transfer_happy_path.json"),
                  "w", encoding="utf-8") as handle:
            json.dump({
                "scenario": "deadline_guarded_transfer_happy_path",
                "procedure": "deadline_guarded_transfer",
                "inputs": {"transfer_id": "transfer-1", "payer": "payer-1",
                           "payee": "payee-1", "amount": 100, "currency": "EUR",
                           "now": 10, "deadline": 5},
                "expect": {},
            }, handle)
        # The mutation builds a throwaway on-disk fixture, so wrap it in the same
        # Fixture shape the classifier consumes -- the probe still measures that
        # *adding a scenario* is what reclassifies the spec.
        mutated = Fixture(name="deadline_guarded_transfer(+scenario)",
                          root=pathlib.Path(domain),
                          source=pathlib.Path(domain) / "source" / "unused.neu",
                          scenario=pathlib.Path(scenario_dir)
                          / "deadline_guarded_transfer_happy_path.json",
                          capability_spec=pathlib.Path(copied_spec),
                          test_realization=None)
        assert not has_committed_scenario(temporal_fixture), (
            "the temporal witness must start out source-only for this mutation to "
            "measure anything")
        assert has_committed_scenario(mutated), "scenario mutation did not reclassify fixture"
        mutation_failures, mutation_checks = scenario_legality_failures([mutated])
        assert mutation_checks == len(profs), mutation_checks
        assert not mutation_failures, mutation_failures

    # Removing the narrow capability fails closed at the originating temporal input.
    for prof in profs.values():
        tampered = copy.deepcopy(prof)
        tampered["supportedFeatures"].remove("value_extension:temporal")
        refusal = next((diagnostic for diagnostic in CL.check(temporal_spec, tampered)
                        if diagnostic.get("feature") == "value_extension:temporal"), None)
        assert refusal is not None, (prof["profileId"], CL.check(temporal_spec, tampered))
        assert refusal["code"] == "legality.unsupported_feature", refusal
        assert refusal["primitive"] == "input now", refusal
        assert isinstance(refusal["source"], dict) and refusal["source"]["line"] > 0, refusal

    # Unsupported-accounting mutation: removing the generic extension denial from every profile
    # makes a compiler-emittable unknown extension unglued and must be reported.
    tampered_profiles = copy.deepcopy(list(profs.values()))
    for prof in tampered_profiles:
        prof["unsupportedConstructs"] = [
            feature for feature in prof["unsupportedConstructs"]
            if feature != "value_category:extension"]
    known, supported = SFM.profile_vocabularies(tampered_profiles)
    sample_specs = SFM.sample_specs()
    sample_specs["synthetic_unknown_extension"] = {
        "features": ["value_category:extension"], "lowerings": [], "spec_path": "/dev/null"}
    glue_errors = SFM.check(known, sample_specs, SFM.build_matrix(known, sample_specs), supported)
    assert any("value_category:extension" in error and "unglued term" in error
               for error in glue_errors), glue_errors

    # 4. legality NEGATIVE: a profile missing a needed feature fails closed with a diagnostic that
    #    names the feature, the originating primitive, and its source line.
    topo_spec = next(json.load(open(p)) for p in specs if json.load(open(p))["topology"]["allowedOrgPairs"])
    crippled = copy.deepcopy(profs["solidity"])
    crippled["supportedFeatures"] = [f for f in crippled["supportedFeatures"] if f != "topology:org_coordination"]
    d = CL.check(topo_spec, crippled)
    viol = [x for x in d if x["code"] == "legality.unsupported_feature" and x["feature"] == "topology:org_coordination"]
    assert viol and viol[0]["primitive"].startswith("allow ") and isinstance(viol[0]["source"], dict), d

    # 5. advisory vs fail_closed fallback on an OPTIONAL unmet feature.
    adv_spec = copy.deepcopy(json.load(open(specs[0])))
    adv_spec["targetRequirements"]["requirements"].append(
        {"feature": "effect:reserve", "primitive": "reserve x", "source": None,
         "requirement": "optional", "fallback": None})
    adv_prof = copy.deepcopy(profs["solidity"]); adv_prof["fallbackPolicy"] = "advisory"
    fc_prof = copy.deepcopy(profs["solidity"]); fc_prof["fallbackPolicy"] = "fail_closed"
    assert not [x for x in CL.check(adv_spec, adv_prof) if x["severity"] == "error"], "advisory should allow optional"
    assert [x for x in CL.check(adv_spec, fc_prof) if x["code"] == "legality.unsupported_feature"], "fail_closed should reject"

    # 6. malformed profile/spec pieces FAIL CLOSED with legality.bad_input, never a traceback
    # a non-array-of-strings feature list, or an object-valued requirement
    #    feature, must not be silently coerced or crash the sort.
    good_spec = json.load(open(specs[0]))
    for bad in ({**copy.deepcopy(profs["solidity"]), "unsupportedConstructs": {}},
                {**copy.deepcopy(profs["solidity"]), "supportedFeatures": [{}]},
                {**copy.deepcopy(profs["solidity"]), "unsupportedConstructs": [{}]}):
        d = CL.check(good_spec, bad)
        assert d and d[0]["code"] == "legality.bad_input", ("malformed profile", d)
    bad_spec = copy.deepcopy(good_spec)
    bad_spec["targetRequirements"]["requirements"][0]["feature"] = {}
    assert any(x["code"] == "legality.bad_input" for x in CL.check(bad_spec, profs["solidity"])), "object feature"
    assert CL.check({}, profs["solidity"])[0]["code"] == "legality.bad_input"
    # CLI-level: the malformed case returns STRUCTURED fail-closed JSON (ok:false), not just exit 1.
    import subprocess, tempfile
    bpf = tempfile.mktemp(suffix=".json")
    json.dump({**copy.deepcopy(profs["solidity"]), "unsupportedConstructs": {}}, open(bpf, "w"))
    r = subprocess.run([sys.executable, os.path.join(repo, "scripts", "gates", "check_spec_legality.py"),
                        specs[0], "--profile", bpf], capture_output=True, text=True)
    j = json.loads(r.stdout)
    assert r.returncode == 1 and j["ok"] is False and j["diagnostics"][0]["code"] == "legality.bad_input", (r.returncode, r.stdout)
except PipelineInputError as e:
    print("[77] FAIL: target-profile / legality gate input: " + str(e), file=sys.stderr)
    sys.exit(1)
except AssertionError as e:
    print("[77] FAIL: target-profile / legality gate: " + str(e), file=sys.stderr)
    sys.exit(1)
print("[77] OK: profile validator mirrors schema; both profiles validate + 7 negatives hit exact codes; "
      "scenario-bearing specs legal vs solidity+postgres; source-only classification + explicit "
      "unsupported accounting bite; missing feature fails closed with feature+primitive+source; "
      "advisory vs fail_closed fallback; malformed profile/spec fail closed with structured "
      "legality.bad_input JSON, never a crash")

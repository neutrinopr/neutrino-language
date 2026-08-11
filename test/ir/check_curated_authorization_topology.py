#!/usr/bin/env python3
"""Verify 's frozen-pair authorization topology and tamper witnesses."""

import json
import pathlib
import subprocess
import sys
import tempfile


GEN = pathlib.Path(sys.argv[1]).resolve()
EXAMPLES = pathlib.Path(sys.argv[2]).resolve()
REPO = pathlib.Path(sys.argv[3]).resolve()
sys.path.insert(0, str(REPO / "scripts" / "gates"))
from m6_pack_resolver import resolve_members  # noqa: E402


def emit(source, target, out, scenario=None):
    cmd = [str(GEN), f"--target={target}"]
    if scenario is not None:
        cmd.append(f"--scenario={scenario}")
    cmd.extend([str(source), "-o", str(out)])
    return subprocess.run(cmd, text=True, capture_output=True)


def coordination_plan(name, members, out):
    result = emit(members[name].source_path, "coordination-plan", out)
    if result.returncode:
        raise AssertionError(f"{name}: coordination-plan generation failed\n{result.stdout}{result.stderr}")
    return json.loads((out / "coordination-plan.json").read_text())


def topology_witness(text, expected, out):
    probe = out.parent / f"{out.name}.neu"
    probe.write_text(text)
    result = emit(probe, "coordination-plan", out)
    if result.returncode:
        return False
    actual = json.loads((out / "coordination-plan.json").read_text())
    return actual["authorizationTopology"] == expected


def main():
    manifest = json.loads((REPO / "docs" / "m6-curated-example-corpus.json").read_text())
    members = resolve_members(manifest, repo=REPO)
    pairs = {p["id"]: (p["a"], p["b"]) for p in manifest["variancePairs"]}
    if not {"pair-2", "pair-3"} <= set(pairs):
        raise AssertionError("the architect-frozen pair set changed")
    pair2, pair3 = pairs["pair-2"], pairs["pair-3"]
    if pair2[1] != pair3[1]:
        raise AssertionError("pair-2/pair-3 no longer share the frozen reference endpoint")
    reference = pair2[1]
    endpoints = (pair2[0], pair3[0], reference)

    with tempfile.TemporaryDirectory(prefix="curated-auth-803.") as td:
        root = pathlib.Path(td)
        coordination_plans = {
            name: coordination_plan(name, members, root / f"member-{index}")
            for index, name in enumerate(endpoints)
        }
        expected = coordination_plans[reference]["authorizationTopology"]
        if expected != {
            "actors": [
                {"actor": 0, "org": 0, "role": 0},
                {"actor": 1, "org": 1, "role": 1},
            ],
            "allowedOrgEdges": [
                {"orgA": 0, "orgB": 1, "roleA": 0, "roleB": 1},
            ],
            "effectBindings": [
                {"actor": 0, "effect": 0},
                {"actor": 1, "effect": 1},
            ],
        }:
            raise AssertionError(f"unexpected sponsored-offer topology: {expected}")
        for pair, endpoint in (("pair-2", pair2[0]), ("pair-3", pair3[0])):
            if coordination_plans[endpoint]["authorizationTopology"] != expected:
                raise AssertionError(f"{pair}: canonical authorization topology differs")

        soa = members[reference].source_path
        text = soa.read_text()
        probes = {
            "missing-sponsor-binding": '        participant     = "Sponsor"\n',
            "missing-merchant-binding": '        participant     = "Merchant"\n',
            "missing-allowed-edge": '''    allow "sponsorco" with "acme" {
        "sponsorco" as "sponsor"
        "acme" as "merchant"
    }

''',
        }
        for name, needle in probes.items():
            if text.count(needle) != 1:
                raise AssertionError(f"{name}: non-vacuous source probe matched {text.count(needle)} times")
            if topology_witness(text.replace(needle, "", 1), expected, root / name):
                raise AssertionError(f"{name}: topology witness survived the deletion")

        domain = members[reference].root
        scenarios = sorted(members[reference].scenario_dir.glob("*.json"))
        if len(scenarios) != 1:
            raise AssertionError("reference pack must carry exactly one scenario")
        scenario = scenarios[0]
        security_out = root / "security"
        result = emit(soa, "security", security_out, scenario)
        if result.returncode:
            raise AssertionError(f"security generation failed\n{result.stdout}{result.stderr}")
        if (security_out / "security.json").read_bytes() != \
                (domain / "generated" / "security" / "security.json").read_bytes():
            raise AssertionError("security fixture is not production-regenerated")
        security = json.loads((security_out / "security.json").read_text())
        if not security["ok"] or security["advisories"] != 0:
            raise AssertionError("authorization topology did not improve the security result")

        views_out = root / "views"
        result = emit(soa, "views", views_out, scenario)
        if result.returncode:
            raise AssertionError(f"views generation failed\n{result.stdout}{result.stderr}")
        for actor in ("Sponsor", "Merchant"):
            if (views_out / f"{actor}.json").read_bytes() != \
                    (domain / "generated" / "views" / f"{actor}.json").read_bytes():
                raise AssertionError(f"{actor}: participant view is not production-regenerated")

    print(" curated authorization topology OK: pair-2 == pair-3; deletion probes bite")


if __name__ == "__main__":
    main()

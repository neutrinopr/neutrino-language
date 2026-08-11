#!/usr/bin/env python3
"""Exercise the CoordinationPlan authorization/topology seam."""

import argparse
import copy
import json
import pathlib
import subprocess


def run(cmd, *, ok=True, timeout=None):
    result = subprocess.run(cmd, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=timeout)
    if ok and result.returncode != 0:
        raise AssertionError(f"command failed: {cmd}\n{result.stdout}{result.stderr}")
    if not ok and result.returncode == 0:
        raise AssertionError(f"command unexpectedly passed: {cmd}")
    return result


def emit(gen, source, target, out, *, from_spec=False, ok=True, timeout=None):
    cmd = [gen, f"--target={target}"]
    if from_spec:
        cmd.append("--from-spec")
    cmd.extend([str(source), "-o", str(out)])
    return run(cmd, ok=ok, timeout=timeout)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--gen", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--tmp", required=True)
    args = parser.parse_args()

    root = pathlib.Path(args.tmp)
    direct = root / "direct"
    spec_dir = root / "spec"
    rebuilt = root / "rebuilt"
    emit(args.gen, args.source, "coordination-plan", direct)
    emit(args.gen, args.source, "capability-spec", spec_dir)
    spec_path = spec_dir / "capability-spec.json"
    emit(args.gen, spec_path, "coordination-plan", rebuilt, from_spec=True)

    direct_bytes = (direct / "coordination-plan.json").read_bytes()
    rebuilt_bytes = (rebuilt / "coordination-plan.json").read_bytes()
    if direct_bytes != rebuilt_bytes:
        raise AssertionError("source and from-spec authorization plans differ")

    plan = json.loads(direct_bytes)
    if len(plan["participants"]) != 2 or len(plan["allowedOrgPairs"]) != 1:
        raise AssertionError("authorization nodes or topology edge were dropped")
    if any(set(actor) != {"name", "org", "role"}
           for actor in plan["participants"]):
        raise AssertionError("realization-only binding metadata leaked into the plan")
    topology = plan["authorizationTopology"]
    if topology != {
        "actors": [
            {"actor": 0, "org": 0, "role": 0},
            {"actor": 1, "org": 1, "role": 1},
        ],
        "allowedOrgEdges": [{"orgA": 0, "orgB": 1, "roleA": 0, "roleB": 1}],
        "effectBindings": [
            {"actor": 0, "effect": 0},
            {"actor": 1, "effect": 1},
            {"actor": 0, "effect": 2},
            {"actor": 1, "effect": 3},
        ],
    }:
        raise AssertionError(f"unexpected canonical authorization topology: {topology}")

    original = json.loads(spec_path.read_text())

    def variant(name, mutate, *, ok, error=None, timeout=None):
        changed = copy.deepcopy(original)
        mutate(changed)
        path = root / f"{name}.json"
        path.write_text(json.dumps(changed))
        result = emit(args.gen, path, "coordination-plan", root / name,
                      from_spec=True, ok=ok, timeout=timeout)
        if error and error not in result.stderr + result.stdout:
            raise AssertionError(f"{name}: missing diagnostic {error!r}: "
                                 f"{result.stdout}{result.stderr}")
        return root / name / "coordination-plan.json"

    def relabel(spec):
        names = {"A": "actor_x", "B": "actor_y"}
        orgs = {"aco": "org_x", "bco": "org_y"}
        roles = {"buyer": "role_x", "seller": "role_y"}
        for actor in spec["participants"]:
            actor["name"] = names[actor["name"]]
            actor["org"] = orgs[actor["org"]]
            actor["role"] = roles[actor["role"]]
        for effect in spec["effects"]:
            effect["participant"] = names[effect["participant"]]
        for edge in spec["topology"]["allowedOrgPairs"]:
            edge["orgA"] = orgs[edge["orgA"]]
            edge["orgB"] = orgs[edge["orgB"]]
            edge["roleA"] = roles[edge["roleA"]]
            edge["roleB"] = roles[edge["roleB"]]

    relabeled_path = variant("relabeled", relabel, ok=True)
    relabeled = json.loads(relabeled_path.read_text())
    if relabeled["authorizationTopology"] != topology:
        raise AssertionError("display/source labels changed canonical topology")

    reordered_path = variant(
        "reordered-participants", lambda spec: spec["participants"].reverse(),
        ok=True)
    reordered = json.loads(reordered_path.read_text())
    if reordered["authorizationTopology"] != topology:
        raise AssertionError("participant declaration order changed canonical topology")

    def reverse_edges(spec):
        for edge in spec["topology"]["allowedOrgPairs"]:
            edge["orgA"], edge["orgB"] = edge["orgB"], edge["orgA"]
            edge["roleA"], edge["roleB"] = edge["roleB"], edge["roleA"]

    reversed_edge_path = variant("reversed-edge", reverse_edges, ok=True)
    reversed_edge = json.loads(reversed_edge_path.read_text())
    if reversed_edge["authorizationTopology"] != topology:
        raise AssertionError("symmetric edge orientation changed canonical topology")

    def add_tied_path(spec):
        for index in range(1, 5):
            spec["participants"].append({
                "name": f"U{index}",
                "org": f"unused_org_{index}",
                "role": f"unused_role_{index}",
                "capabilities": [],
                "binding": "fixed",
                "bindRuntimes": [],
                "bindMinAssurance": "",
            })
        for left in range(1, 4):
            spec["topology"]["allowedOrgPairs"].append({
                "orgA": f"unused_org_{left}",
                "orgB": f"unused_org_{left + 1}",
                "roleA": f"unused_role_{left}",
                "roleB": f"unused_role_{left + 1}",
            })

    tied_path = variant("tied-path", add_tied_path, ok=True)

    def permute_tied_path(spec):
        add_tied_path(spec)
        rank = {"U4": 0, "U2": 1, "U3": 2, "U1": 3}
        anchored = [p for p in spec["participants"] if p["name"] not in rank]
        unused = sorted((p for p in spec["participants"] if p["name"] in rank),
                        key=lambda p: rank[p["name"]])
        spec["participants"] = anchored + unused

    tied_path_permuted = variant(
        "tied-path-permuted", permute_tied_path, ok=True)
    tied_topology = json.loads(tied_path.read_text())["authorizationTopology"]
    permuted_topology = json.loads(
        tied_path_permuted.read_text())["authorizationTopology"]
    if tied_topology != permuted_topology:
        raise AssertionError(
            "tied-neighborhood declaration order changed canonical topology")

    def add_oversized_symmetric_cell(spec):
        for index in range(1, 10):
            spec["participants"].append({
                "name": f"S{index}",
                "org": f"symmetric_org_{index}",
                "role": f"symmetric_role_{index}",
                "capabilities": [],
                "binding": "fixed",
                "bindRuntimes": [],
                "bindMinAssurance": "",
            })

    variant("oversized-symmetric-cell", add_oversized_symmetric_cell,
            ok=False, error="exceeds canonical topology limit 8", timeout=2)

    no_edge_path = variant(
        "no-edge", lambda spec: spec["topology"].update(allowedOrgPairs=[]),
        ok=True)
    no_edge = json.loads(no_edge_path.read_text())
    if no_edge["authorizationTopology"] == topology:
        raise AssertionError("topology-erasing canonicalization ignored a dropped edge")

    variant("missing-binding",
            lambda spec: spec["effects"][0].update(participant=None),
            ok=False, error="missing its authorization participant")
    variant("undeclared-participant",
            lambda spec: spec["effects"][0].update(participant="ghost"),
            ok=False, error="undeclared authorization participant")
    variant("dangling-org",
            lambda spec: spec["topology"]["allowedOrgPairs"][0].update(orgB="ghost"),
            ok=False, error="does not resolve to a declared authorization actor")
    variant("dropped-actor", lambda spec: spec["participants"].pop(),
            ok=False, error="does not resolve to a declared authorization actor")
    variant("duplicate-actor",
            lambda spec: spec["participants"][1].update(name="A"),
            ok=False, error="duplicate authorization participant")
    variant("ambiguous-actor",
            lambda spec: spec["participants"][1].update(
                org=spec["participants"][0]["org"],
                role=spec["participants"][0]["role"]),
            ok=False, error="ambiguous authorization identity")
    variant("duplicate-edge",
            lambda spec: spec["topology"]["allowedOrgPairs"].append(
                copy.deepcopy(spec["topology"]["allowedOrgPairs"][0])),
            ok=False, error="duplicate allowed organization edge")

    print("coordination-plan authorization topology OK")


if __name__ == "__main__":
    main()

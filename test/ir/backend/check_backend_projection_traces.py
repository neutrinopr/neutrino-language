#!/usr/bin/env python3
# Assert each bound trace (docs/process/m6_backend_projection_traces.json) is
# reproduced by the REAL projector output (backend-projection.json emitted by
# neutrino-gen): every trace node + typed edge appears in the projection with
# matching kind, field values, and resolved endpoints.
#
# Traces are illustrative/partial (§9) — a trace lists a witness subset of the
# complete graph — so this is a SUBSET check (trace nodes/edges ⊆ projection);
# internal completeness + exact cardinalities are the verifier's job. Trace node
# `id`s are illustrative, so a trace node is matched to the projection node with
# the same EXACT (kind, sourceRef) — a unique, deterministic key that also makes
# source-map matching exact — and edges are checked through that mapping.
import json
import sys

# Fields that are compared but never used as identity.
IGNORE_FIELDS = {"id", "kind", "sourceRef"}
# Fields whose values are NODE IDS (illustrative in the trace) — compared by
# resolving each id through the node map, not literally.
ID_REF_FIELDS = {
    ("PrimitiveObligation", "typedOperands"),  # list of policy ids
    ("CommitState", "commitScope"),            # a policy id
}


def compare_trace(trace, proj):
    errs = []
    pedges = {(e["from"], e["name"], e["to"]) for e in proj["edges"]}
    # index projection nodes by their EXACT (kind, sourceRef). Because every
    # projected node carries a distinct source mapping, this key is unique; using
    # it both removes the earlier structural ambiguity (a node is matched by one
    # deterministic key, not by field-guessing + edge-chasing) and enforces exact
    # source-map matching (a wrong / missing sourceRef yields 0 — or, on a real
    # collision, >1 — candidates and fails).
    proj_by_ks = {}
    for pn in proj["nodes"]:
        proj_by_ks.setdefault((pn["kind"], pn.get("sourceRef")), []).append(pn)

    tmap = {}  # trace node id -> the unique projection node
    for tn in trace["nodes"]:
        key = (tn["kind"], tn.get("sourceRef"))
        cands = proj_by_ks.get(key, [])
        if len(cands) != 1:
            errs.append(f"{tn['kind']} {tn['id']} (sourceRef="
                        f"{tn.get('sourceRef')!r}): {len(cands)} projection "
                        f"node(s) with that exact (kind, sourceRef)")
            continue
        tmap[tn["id"]] = cands[0]

    # every remaining field must match; id-valued fields are resolved through
    # the node map (trace ids are illustrative), never compared literally.
    for tn in trace["nodes"]:
        pn = tmap.get(tn["id"])
        if pn is None:
            continue
        for f, v in tn.items():
            if f in IGNORE_FIELDS:
                continue
            if (tn["kind"], f) in ID_REF_FIELDS:
                ids = v if isinstance(v, list) else [v]
                resolved = [tmap[i]["id"] if i in tmap else None for i in ids]
                if None in resolved:
                    errs.append(f"{tn['kind']} {tn['id']}.{f}: unresolved id "
                                f"reference in {v!r}")
                    continue
                got = pn.get(f)
                got = got if isinstance(got, list) else [got]
                if sorted(resolved) != sorted(got):
                    errs.append(f"{tn['kind']} {tn['id']}.{f}: trace(resolved)="
                                f"{sorted(resolved)!r} projection={sorted(got)!r}")
                continue
            if pn.get(f) != v:
                errs.append(f"{tn['kind']} {tn['id']}.{f}: trace={v!r} "
                            f"projection={pn.get(f)!r}")

    # every trace edge resolves to a real projection edge through the map.
    for e in trace["edges"]:
        u, v = tmap.get(e["from"]), tmap.get(e["to"])
        if u is None or v is None:
            continue  # already reported as an unmapped node
        if (u["id"], e["name"], v["id"]) not in pedges:
            errs.append(f"edge {e['from']} --{e['name']}--> {e['to']}: "
                        f"absent in projection")
    return errs


def main(argv):
    if len(argv) < 3:
        sys.stderr.write(
            "usage: check_backend_projection_traces.py <traces.json> "
            "<trace-id>=<backend-projection.json> ...\n")
        return 2
    traces = {t["id"]: t for t in json.load(open(argv[1]))["traces"]}
    projections = {}
    for spec in argv[2:]:
        tid, _, path = spec.partition("=")
        projections[tid] = json.load(open(path))
    rc = 0
    checked = 0
    for tid, proj in projections.items():
        if tid not in traces:
            sys.stderr.write(f"[traces] unknown trace id {tid}\n")
            return 2
        errs = compare_trace(traces[tid], proj)
        checked += 1
        if errs:
            rc = 1
            sys.stderr.write(f"[traces] {tid}: {len(errs)} mismatch(es)\n")
            for e in errs:
                sys.stderr.write(f"    {e}\n")
        else:
            sys.stderr.write(
                f"[traces] {tid}: OK ({len(traces[tid]['nodes'])} nodes, "
                f"{len(traces[tid]['edges'])} edges reproduced)\n")
    if checked != len(traces):
        sys.stderr.write(
            f"[traces] only {checked}/{len(traces)} bound traces checked\n")
        return 1
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv))

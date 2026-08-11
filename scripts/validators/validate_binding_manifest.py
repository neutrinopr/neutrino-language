#!/usr/bin/env python3
"""T0/T2 — neutrino.binding-manifest validation against a slot binding-topology.

The Binding Manifest is the realized-translation input: it binds a capability's late-bound
(`to_be_bound`) slots to concrete runtimes. It is validated against the slot binding-topology
(D1b) so a realized environment cannot name something the capability never declared, or
exceed the declared late-binding policy. Fail-closed; standard library only.

Failures are normalized into the **Binding Manifest diagnostic taxonomy** (the source of
truth is docs/binding/BINDING_MANIFEST.md): every failure carries a stable `NEU-…` code, an
`ERR_NEU_…` symbol, a `category` (topology | security | runtime), a `severity`, a `message`,
and the target fields where available. Downstream consumers (CI, agents, network admission,
console) consume the machine-readable report rather than parsing prose.

  validate_binding_manifest.py --manifest FILE --binding-topology FILE [--json]

`--json` prints the structured report ({schemaVersion, ok, capability, diagnostics[]});
the default prints a human-readable summary derived from the same diagnostics.

Guarantee boundary: validation only proves the manifest is a structurally complete and
policy-admissible realization *input* — it does NOT guarantee real-world business execution.

Exit 0 ok / 1 validation failures / 2 usage or I/O.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ASSURANCE = {"A1": 1, "A2": 2, "A3": 3, "A4": 4}

# The diagnostic taxonomy: code -> (symbol, category, severity). Keep in lockstep with the
# table in docs/binding/BINDING_MANIFEST.md. NEU-3003 stays reserved for future runtime-viability
# diagnostics; NEU-3002 is now the L3 backend-profile diagnostic (). The NEU-4xxx family
# is the L3 / L2-parameter-binding layer ().
TAXONOMY = {
    # topological completeness
    "NEU-1001": ("ERR_NEU_MANIFEST_MALFORMED", "topology", "error"),
    "NEU-1002": ("ERR_NEU_CAPABILITY_MISMATCH", "topology", "error"),
    "NEU-1003": ("ERR_NEU_SLOT_OWNERSHIP", "topology", "error"),
    "NEU-1004": ("ERR_NEU_COVERAGE", "topology", "error"),
    # security / assurance
    "NEU-2001": ("ERR_NEU_ASSURANCE_BELOW_MINIMUM", "security", "error"),
    "NEU-2002": ("ERR_NEU_BINDER_UNAUTHORIZED", "security", "error"),
    "NEU-2003": ("ERR_NEU_ASSURANCE_INVALID", "security", "error"),
    # runtime viability
    "NEU-3000": ("ERR_NEU_RUNTIME_NOT_ALLOWED", "runtime", "error"),
    "NEU-3001": ("ERR_NEU_SLOT_NOT_BINDABLE", "runtime", "error"),
    "NEU-3002": ("ERR_NEU_PROFILE_UNSUPPORTED", "runtime", "error"),
    # L3 / L2 parameter binding ()
    "NEU-4001": ("ERR_NEU_PARAM_NOT_DECLARED", "l2-binding", "error"),
    "NEU-4002": ("ERR_NEU_PARAM_REQUIRED_MISSING", "l2-binding", "error"),
    "NEU-4003": ("ERR_NEU_PARAM_TYPE_MISMATCH", "l2-binding", "error"),
    "NEU-4004": ("ERR_NEU_UNTRACEABLE_SEMANTICS", "l2-binding", "error"),
    "NEU-4005": ("ERR_NEU_L2_CAPABILITY_MISMATCH", "l2-binding", "error"),
}

# L3 (schemaVersion 2) optional field surfaces — additive over the v1 core, so a v1 manifest
# stays byte-for-byte valid and existing consumers are unaffected.
_L3_TOP_FIELDS = {"l2Ref", "backendProfile"}
_L3_BINDING_FIELDS = {"parameterBindings", "derivedConcepts", "evidenceRefs",
                      "compensation", "observability", "retryTimeout", "deferred"}
_L3_HOOK_FIELDS = {"compensation", "observability", "retryTimeout"}


def _topology_malformed(topology: dict) -> bool:
    """True if organizations/participants/slots are not arrays of objects (so a valid-JSON
    but structurally-bad topology becomes a coded diagnostic, never a traceback)."""
    orgs = topology.get("organizations")
    if not isinstance(orgs, list):
        return True
    for org in orgs:
        if not isinstance(org, dict):
            return True
        parts = org.get("participants")
        if not isinstance(parts, list):
            return True
        for p in parts:
            if not isinstance(p, dict):
                return True
            slots = p.get("slots")
            if not isinstance(slots, list):
                return True
            if any(not isinstance(s, dict) for s in slots):
                return True
    return False


def _as_list(v):
    """The value if it is a list, else [] — so a missing OR `null`/non-list container does
    not crash iteration (`.get(k, [])` returns None when the key is present but null)."""
    return v if isinstance(v, list) else []


def _index_slots(topology: dict) -> dict:
    """slotId -> (organizationId, participantId, slot dict). Defensive: coerces any non-list
    container to [] and skips non-object entries, so a malformed/null topology yields an
    empty index instead of crashing (the malformation is reported separately as NEU-1001)."""
    out = {}
    for org in _as_list(topology.get("organizations")):
        if not isinstance(org, dict):
            continue
        for p in _as_list(org.get("participants")):
            if not isinstance(p, dict):
                continue
            for s in _as_list(p.get("slots")):
                if not isinstance(s, dict):
                    continue
                out[s.get("slotId")] = (org.get("organizationId"), p.get("participantId"), s)
    return out


class Report:
    """Collects coded diagnostics and renders them deterministically."""

    def __init__(self, capability=None):
        self.capability = capability
        self.diags: list[dict] = []
        # L3 machine-readable binding status (): complete | simulation-only | deferred |
        # invalid. None for a v1 manifest that declares no L3 surface.
        self.status = None

    def has_errors(self) -> bool:
        return any(d["severity"] == "error" for d in self.diags)

    def add(self, code, message, *, binding_index=None, capability=None,
            organization_id=None, participant_id=None, slot_id=None):
        symbol, category, severity = TAXONOMY[code]
        d = {
            "code": code,
            "symbol": symbol,
            "category": category,
            "severity": severity,
            "message": message,
        }
        # Target fields, only when known, so the report is precise about *where*.
        if capability is not None:
            d["capability"] = capability
        if organization_id is not None:
            d["organizationId"] = organization_id
        if participant_id is not None:
            d["participantId"] = participant_id
        if slot_id is not None:
            d["slotId"] = slot_id
        if binding_index is not None:
            d["bindingIndex"] = binding_index
        self.diags.append(d)

    def sorted_diags(self) -> list[dict]:
        # Byte-stable ordering for CI: manifest-level (no bindingIndex) first, then by
        # binding index, then by code, then by slotId.
        return sorted(
            self.diags,
            key=lambda d: (d.get("bindingIndex", -1), d["code"], d.get("slotId", "")),
        )

    def to_json(self) -> dict:
        out = {
            "schemaVersion": 1,
            "kind": "neutrino.binding-manifest-validation",
            "ok": not self.diags,
            "capability": self.capability,
            "diagnostics": self.sorted_diags(),
        }
        # Additive (): a downstream rail reads `status` directly instead of parsing prose.
        # Absent for a v1 manifest, so the v1 report shape is unchanged for existing consumers.
        if self.status is not None:
            out["status"] = self.status
        return out


def validate(m, topo, report: Report, *, l2=None, profiles=None) -> None:
    def nonempty(v):
        return isinstance(v, str) and v != ""

    def no_unknown(obj, allowed, *, binding_index=None, slot_id=None):
        if isinstance(obj, dict):
            for k in obj:
                if k not in allowed:
                    report.add("NEU-1001", f"unknown field {k!r}",
                               binding_index=binding_index, slot_id=slot_id)

    # --- manifest shape (NEU-1001) ---
    if not isinstance(m, dict):
        report.add("NEU-1001", "manifest must be a JSON object")
        return  # fatal: nothing further can be evaluated
    # schemaVersion 1 is the L1 core; 2 adds the optional L3 surface (). The allowed
    # field set widens for v2 so a v1 manifest is validated exactly as before.
    is_l3 = m.get("schemaVersion") == 2
    top_allowed = {"kind", "schemaVersion", "capability", "bindings"}
    binding_allowed = {"organizationId", "participantId", "slotId", "runtime", "assurance", "binder"}
    if is_l3:
        top_allowed = top_allowed | _L3_TOP_FIELDS
        binding_allowed = binding_allowed | _L3_BINDING_FIELDS
    no_unknown(m, top_allowed)
    if m.get("kind") != "neutrino.binding-manifest":
        report.add("NEU-1001", "kind must be 'neutrino.binding-manifest'")
    if m.get("schemaVersion") not in (1, 2):
        report.add("NEU-1001", "schemaVersion must be 1 or 2")
    if not isinstance(topo, dict) or topo.get("kind") != "neutrino.slot-binding-topology":
        report.add("NEU-1001", "binding-topology kind must be 'neutrino.slot-binding-topology'")
    if not isinstance(topo, dict):
        topo = {}
    elif _topology_malformed(topo):
        # Valid JSON but structurally bad topology — emit a coded diagnostic, not a crash.
        report.add("NEU-1001",
                   "binding-topology structure is malformed "
                   "(organizations/participants/slots must be arrays of objects)")

    # --- capability identity (NEU-1002) ---
    report.capability = m.get("capability") if nonempty(m.get("capability")) else None
    if not nonempty(m.get("capability")):
        report.add("NEU-1002", "manifest capability is required (non-empty string)")
    if not nonempty(topo.get("capability")):
        report.add("NEU-1002", "binding-topology capability is required (non-empty string)")
    if nonempty(m.get("capability")) and nonempty(topo.get("capability")) \
            and m["capability"] != topo["capability"]:
        report.add("NEU-1002",
                   f"manifest capability {m['capability']!r} != binding-topology "
                   f"capability {topo['capability']!r}", capability=m["capability"])

    slots = _index_slots(topo)
    bindings = m.get("bindings")
    if not isinstance(bindings, list) or not bindings:
        report.add("NEU-1001", "bindings must be a non-empty array")
        bindings = []

    # --- per-binding checks ---
    bound_slot_ids: list[str] = []
    for i, b in enumerate(bindings):
        if not isinstance(b, dict):
            report.add("NEU-1001", "binding must be an object", binding_index=i)
            continue
        no_unknown(b, binding_allowed, binding_index=i)
        sid = b.get("slotId")
        bound_slot_ids.append(sid)
        org_b, part_b = b.get("organizationId"), b.get("participantId")

        # Slot ownership (NEU-1003). An orphan slot SUPPRESSES the dependent per-slot policy
        # checks (runtime/assurance/binder) — they cannot be evaluated without a real slot.
        if sid not in slots:
            report.add("NEU-1003", f"slotId {sid!r} is not in the binding-topology",
                       binding_index=i, slot_id=sid, organization_id=org_b, participant_id=part_b)
            continue
        org_id, part_id, slot = slots[sid]
        if org_b != org_id:
            report.add("NEU-1003",
                       f"organizationId {org_b!r} != topology {org_id!r} for {sid}",
                       binding_index=i, slot_id=sid, organization_id=org_b, participant_id=part_b)
        if part_b != part_id:
            report.add("NEU-1003",
                       f"participantId {part_b!r} != topology {part_id!r} for {sid}",
                       binding_index=i, slot_id=sid, organization_id=org_b, participant_id=part_b)

        # A fixed (non-bindable) slot also SUPPRESSES the policy checks (nothing to bind).
        if slot.get("lateBindingMode") != "to_be_bound":
            report.add("NEU-3001",
                       f"slot {sid} is {slot.get('lateBindingMode')!r}, not 'to_be_bound' — "
                       "nothing to bind",
                       binding_index=i, slot_id=sid, organization_id=org_b, participant_id=part_b)
            continue

        # Runtime viability (NEU-3000) + security/assurance (NEU-20xx). All applicable
        # diagnostics for a viable slot are emitted (not short-circuited).
        runtime = b.get("runtime")
        if runtime not in (slot.get("allowedRuntimes") or []):
            report.add("NEU-3000",
                       f"runtime {runtime!r} not in allowedRuntimes {slot.get('allowedRuntimes')}",
                       binding_index=i, slot_id=sid, organization_id=org_b, participant_id=part_b)
        a = b.get("assurance")
        if a not in ASSURANCE:
            report.add("NEU-2003", f"assurance must be one of {sorted(ASSURANCE)}",
                       binding_index=i, slot_id=sid, organization_id=org_b, participant_id=part_b)
        elif ASSURANCE[a] < ASSURANCE.get(slot.get("minAssurance"), 1):
            report.add("NEU-2001",
                       f"assurance {a} is below the slot's minAssurance {slot.get('minAssurance')}",
                       binding_index=i, slot_id=sid, organization_id=org_b, participant_id=part_b)
        if b.get("binder") != slot.get("authorizedBinder"):
            report.add("NEU-2002",
                       f"binder {b.get('binder')!r} != authorizedBinder {slot.get('authorizedBinder')!r}",
                       binding_index=i, slot_id=sid, organization_id=org_b, participant_id=part_b)

    # --- coverage / completeness (NEU-1004) ---
    for sid in sorted(set(bound_slot_ids)):
        n = bound_slot_ids.count(sid)
        if n > 1:
            report.add("NEU-1004", f"slot {sid!r} is bound {n} times (must be once)", slot_id=sid)
    to_bind = {sid for sid, (_, _, s) in slots.items()
               if s.get("lateBindingMode") == "to_be_bound"}
    for sid in sorted(to_bind - set(bound_slot_ids)):
        report.add("NEU-1004", f"to_be_bound slot {sid!r} is not bound by the manifest",
                   slot_id=sid)

    # --- L3 layer (): parameter bindings, backend profile, traceability, status ---
    if is_l3:
        _validate_l3(m, bindings, report, l2, profiles)


def _l2_index(l2):
    """(param_name -> declared type, set(required names), set(traceable concepts)). A minimal
    view of the L2 interface — name/type/required + concept names — which is all L3 must trace.
    Reads both the minimal projection (string concepts) AND a real neutrino.l2-domain-semantics
    artifact (: parameters[{name,type,required}] match exactly; concepts are objects with a
    `name`), so the L3 validator consumes either without code change."""
    params, required, concepts = {}, set(), set()
    if not isinstance(l2, dict):
        return params, required, concepts
    for p in (l2.get("parameters") or []):
        if isinstance(p, dict) and nonempty_str(p.get("name")):
            params[p["name"]] = p.get("type")
            if p.get("required") is True:
                required.add(p["name"])
    for c in (l2.get("concepts") or []):
        if isinstance(c, str):
            concepts.add(c)                       # minimal projection
        elif isinstance(c, dict) and nonempty_str(c.get("name")):
            concepts.add(c["name"])               #  neutrino.l2-domain-semantics concept
    return params, required, concepts


def nonempty_str(v):
    return isinstance(v, str) and v != ""


def _validate_l3(m, bindings, report, l2, profiles) -> None:
    cap = m.get("capability")
    ref = m.get("l2Ref")
    # L2 linkage is mandatory for a v2 manifest: without it, parameter bindings are untraceable.
    if not isinstance(ref, dict) or not nonempty_str(ref.get("artifact")):
        report.add("NEU-1001", "an L3 (schemaVersion 2) manifest must declare 'l2Ref.artifact'")
    # The L2 reference must be capability-bound (NEU-4005), or parameter/concept traceability
    # could be satisfied by an L2 interface for a DIFFERENT capability. l2Ref.capability is
    # required and must equal the manifest capability; the loaded L2 artifact's own capability
    # (when it declares one — the minimal projection does) must match too.
    if isinstance(ref, dict):
        rc = ref.get("capability")
        if not nonempty_str(rc):
            report.add("NEU-4005",
                       "l2Ref.capability is required and must equal the manifest capability")
        elif nonempty_str(cap) and rc != cap:
            report.add("NEU-4005",
                       f"l2Ref.capability {rc!r} != manifest capability {cap!r}")
    if isinstance(l2, dict) and nonempty_str(l2.get("capability")) \
            and nonempty_str(cap) and l2["capability"] != cap:
        report.add("NEU-4005",
                   f"L2 interface capability {l2['capability']!r} != manifest capability {cap!r}")
    if l2 is None:
        report.add("NEU-4004",
                   "the L2 interface could not be resolved — L3 parameter bindings are "
                   "untraceable to L2 (declare a readable 'l2Ref.artifact')")
    params, required, concepts = _l2_index(l2)
    traceable = set(params) | concepts

    # Backend profile (NEU-3002): the catalog must load (else the profile is unvalidated — fail
    # closed, never report a clean status for an unresolved profile); the id must be cataloged; a
    # binding's runtime must match the profile's runtimeFamily; hook fields are constrained to
    # the profile's supportedFields.
    profile_id = m.get("backendProfile")
    profile = None
    if profiles is None:
        report.add("NEU-3002",
                   "the backend-profile catalog could not be loaded — a schemaVersion-2 "
                   "manifest's backendProfile cannot be validated")
    else:
        profile = next((p for p in (profiles.get("profiles") or [])
                        if isinstance(p, dict) and p.get("id") == profile_id), None)
        if profile is None:
            report.add("NEU-3002",
                       f"backendProfile {profile_id!r} is not in the backend-profile catalog")
    supported = set(profile.get("supportedFields") or []) if isinstance(profile, dict) else None
    runtime_family = profile.get("runtimeFamily") if isinstance(profile, dict) else None

    # Per-binding L3 checks. Required-parameter coverage is manifest-wide (the union of all
    # bindings' parameterBindings must cover every required L2 parameter).
    bound_params: set = set()
    for i, b in enumerate(bindings):
        if not isinstance(b, dict):
            continue
        sid = b.get("slotId")
        pbs = b.get("parameterBindings")
        if pbs is not None and isinstance(pbs, dict):
            for name, spec in pbs.items():
                bound_params.add(name)
                if name not in params:
                    report.add("NEU-4001",
                               f"parameter {name!r} is not declared by L2", binding_index=i, slot_id=sid)
                    continue
                want = params[name]
                got = spec.get("type") if isinstance(spec, dict) else None
                if want is not None and got != want:
                    report.add("NEU-4003",
                               f"parameter {name!r} bound as type {got!r} != L2-declared {want!r}",
                               binding_index=i, slot_id=sid)
        # Every derived concept must trace back to an L2 parameter or concept (NEU-4004).
        for c in (b.get("derivedConcepts") or []):
            if c not in traceable:
                report.add("NEU-4004",
                           f"derivedConcept {c!r} does not trace to any L2 parameter or concept",
                           binding_index=i, slot_id=sid)
        # The realized runtime must belong to the chosen profile's runtime family (NEU-3002) —
        # otherwise the L3 status would describe a different runtime than the binding uses. A
        # `deferred` binding is exempt: it has NOT pinned its concrete runtime/profile yet (that
        # is what deferred means), so a hybrid manifest can bind a concrete core under
        # `backendProfile` while deferring conventional adapters on a different runtime family.
        if runtime_family is not None and b.get("deferred") is not True \
                and b.get("runtime") != runtime_family:
            report.add("NEU-3002",
                       f"runtime {b.get('runtime')!r} does not match backend profile "
                       f"{profile_id!r} runtimeFamily {runtime_family!r}",
                       binding_index=i, slot_id=sid)
        # Hook fields must be supported by the chosen backend profile (NEU-3002).
        if supported is not None:
            for f in _L3_HOOK_FIELDS:
                if f in b and f not in supported:
                    report.add("NEU-3002",
                               f"field {f!r} is not supported by backend profile {profile_id!r}",
                               binding_index=i, slot_id=sid)

    for name in sorted(required - bound_params):
        report.add("NEU-4002", f"required L2 parameter {name!r} is not bound by the manifest")

    # --- machine-readable status () ---
    if report.has_errors():
        report.status = "invalid"
    elif any(isinstance(b, dict) and b.get("deferred") is True for b in bindings):
        report.status = "deferred"
    elif isinstance(profile, dict) and profile.get("maturity") == "simulation-only":
        report.status = "simulation-only"
    else:
        report.status = "complete"


def _load_optional(path, label):
    """Load a JSON file, or return None if it is absent/unreadable (a coded diagnostic is
    raised by the validator, never a traceback)."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--binding-topology", required=True)
    ap.add_argument("--json", action="store_true",
                    help="print the machine-readable diagnostic report instead of text")
    ap.add_argument("--repo-root", default=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                    help="root used to resolve an L3 manifest's l2Ref.artifact + the backend "
                         "profile catalog (default: the repo this script lives in)")
    ap.add_argument("--backend-catalog", default="examples/backend-profiles/catalog.json",
                    help="repo-relative path to the L3 backend-profile catalog ()")
    try:
        args = ap.parse_args()
    except SystemExit:
        return 2
    try:
        m = json.load(open(args.manifest, encoding="utf-8"))
        topo = json.load(open(args.binding_topology, encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"error: cannot read inputs: {exc}", file=sys.stderr)
        return 2

    # L3 context (): for a schemaVersion-2 manifest, resolve the L2 interface (via
    # l2Ref.artifact) and the backend-profile catalog against --repo-root. Missing/unreadable
    # inputs become coded diagnostics in validate(), not a hard error here.
    l2 = profiles = None
    if isinstance(m, dict) and m.get("schemaVersion") == 2:
        ref = m.get("l2Ref")
        if isinstance(ref, dict) and isinstance(ref.get("artifact"), str):
            l2 = _load_optional(os.path.join(args.repo_root, ref["artifact"]), "l2")
        profiles = _load_optional(os.path.join(args.repo_root, args.backend_catalog), "profiles")

    report = Report()
    validate(m, topo, report, l2=l2, profiles=profiles)

    if args.json:
        print(json.dumps(report.to_json(), indent=2))
    else:
        diags = report.sorted_diags()
        for d in diags:
            where = f" [{d['slotId']}]" if d.get("slotId") else ""
            print(f"  - {d['code']} {d['symbol']}{where}: {d['message']}")
        status = f" [status: {report.status}]" if report.status is not None else ""
        if diags:
            print(f"binding-manifest check: {len(diags)} diagnostic(s){status}")
        else:
            print(f"binding-manifest check: OK{status}")
    return 1 if report.diags else 0


if __name__ == "__main__":
    sys.exit(main())

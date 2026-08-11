#!/usr/bin/env python3
"""M5 oracle () — coordination↔guard claimId parity gate.

The THIRD oracle single-sourcing invariant, alongside cross-backend equivalence () and observer↔guard
parity (). / wired the generated coordination to the quorum guard: execute() proceeds only for
a claim the guard ACCEPTED, keyed by the coordination's WORKFLOW KEY (the spec's idempotency_key). That
makes `claimId ≡ workflowKey` a LIVE cross-artifact invariant — the id the guard accepts under must equal
the id execute() checks, or the guard accepts one id and the coordination reads another (isAccepted →
false forever → the coordination silently can't execute). It is fail-safe (a drift bricks liveness, never
bypasses quorum), but today it is enforced only by a doc comment; this gate pins it, single-sourced from
the spec, so it can't drift silently as the coordination/guard/observation renderers evolve.

Proven (fail-closed on any mismatch), from the RENDERED artifacts + the spec — no hardcoded copy:
  - workflow key: derived from the spec (the first effect's idempotency_key ref).
  - Solidity, two-sided: execute() derives `bytes32 _k = keccak256(bytes(u_<workflowKey>))` AND checks
    `acceptanceGuard.isAccepted(_k)` with THAT SAME variable; and the coordination's guard interface
    `isAccepted(bytes32 …)` matches the guard contract's actual accessor signature.
  - PostgreSQL, two-sided, procedure-namespaced (): acceptance identity is (procedure, claim_id), so
    accept_ RECORDS `quorum_acceptance(procedure, claim_id, …) VALUES ('<procedure>', p_<workflowKey>, …)`
    AND execute() CHECKS `quorum_acceptance WHERE claim_id = p_<workflowKey> AND procedure = '<procedure>'`
    — the SAME workflow key AND the SAME procedure namespace (== spec `procedure`); a right key under a
    foreign procedure is a parity break.
  - cross-rail: both rails key acceptance on the SAME spec workflow key (single-sourced).

Usage:
    check_coordination_guard_parity.py --solidity COORD.sol --guard GUARD.sol \
        --postgres procedure.sql --spec capability-spec.json
Exit 0 iff parity holds; non-zero + a coded reason otherwise.
"""
import argparse
import json
import re
import sys


def fail(reasons, code, msg):
    reasons.append(f"[{code}] {msg}")


def _find(pattern, text, group=1):
    m = re.search(pattern, text)
    return m.group(group) if m else None


def _function_body(sql: str, fname: str) -> str:
    # Isolate one plpgsql function body — `CREATE OR REPLACE FUNCTION <fname>(…) … AS $$ … $$;` — so a
    # per-function check can't be satisfied by a match in a DIFFERENT function. This matters because
    # accept_ (printed first) ALSO references `quorum_acceptance WHERE claim_id = p_<key>` in its replay
    # guard, so a whole-file search for the execute_ gate could read accept_'s occurrence and miss an
    # execute_-only drift ( review).
    m = re.search(r"FUNCTION\s+" + re.escape(fname) + r"\b.*?\$\$;", sql, re.S)
    return m.group(0) if m else None


def _split_top_level(s: str) -> list:
    # Split a SQL argument list on TOP-LEVEL commas only, so a nested subquery (e.g. the observer-count
    # `(SELECT count(...) FROM unnest(...))`) stays one element — lets an INSERT's columns be aligned to
    # its VALUES positionally.
    parts, depth, cur = [], 0, ""
    for ch in s:
        if ch == "(":
            depth += 1
            cur += ch
        elif ch == ")":
            depth -= 1
            cur += ch
        elif ch == "," and depth == 0:
            parts.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        parts.append(cur.strip())
    return parts


def temporal_groups_from_coordination_plan(coordination_plan: dict) -> dict:
    # The AUTHORITATIVE per-policy group mapping: the normalized coordination plan partitions effects by
    # guard structure (group order = first appearance) and the temporal legalizers key committedGroup /
    # committed_group on THAT ordinal (the effectGroups index). Return {ordinal: policy} for every
    # temporal-suppress group — the exact set of per-policy commit gates each rail MUST render.
    expected = {}
    for i, g in enumerate(coordination_plan.get("effectGroups") or []):
        if g.get("gateMode") == "temporal-suppress":
            expected[i] = g.get("gatePolicy")
    return expected


def _check_group_coverage(reasons, rail, expected, observed, written, dup):
    # `expected` {ordinal->policy} is the authoritative per-policy commit set (from the coordination plan); `observed`
    # {ordinal->policy} is what the rail's per-policy predicates actually gate; `written` is the set of
    # ordinals the rail actually commits. Require an EXACT bijection expected<->observed (right policy per
    # ordinal, no missing, no extra, no duplicate) AND that every committed ordinal is one of the guarded
    # ones — so a missing predicate (unconditional commit) and a cross-policy rewire are both caught.
    code = f"parity.temporal_{rail}_coverage"
    if dup:
        fail(reasons, code, f"{rail}: a group ordinal is gated by more than one per-policy predicate (duplicate authorization)")
    missing = sorted(set(expected) - set(observed))
    if missing:
        fail(reasons, code,
             f"{rail}: no per-policy commit gate for group ordinal(s) {missing} "
             f"(expected {{{', '.join(f'{o}:{expected[o]!r}' for o in missing)}}}) — an unconditional/ungated commit")
    extra = sorted(set(observed) - set(expected))
    if extra:
        fail(reasons, code,
             f"{rail}: a per-policy commit gate exists for group ordinal(s) {extra} not in the coordination-plan's temporal-suppress groups")
    for o in sorted(set(expected) & set(observed)):
        if observed[o] != expected[o]:
            fail(reasons, code,
                 f"{rail}: group ordinal {o} is authorized by policy {observed[o]!r}, but the coordination plan binds it to "
                 f"{expected[o]!r} (cross-policy authorization)")
    unguarded = sorted(written - set(observed))
    if unguarded:
        fail(reasons, code,
             f"{rail}: group ordinal(s) {unguarded} are committed but guarded by no per-policy acceptance "
             "predicate (an unconditional commit)")


def workflow_key_from_spec(spec: dict) -> str:
    # The workflow key = the first effect's idempotency_key, which must reference an input (the SAME
    # derivation the Solidity/PostgreSQL renderers apply). This is the single source of truth the two
    # rails' acceptance ids must both key off.
    effects = spec.get("effects") or []
    if not effects:
        return None
    idem = effects[0].get("idempotencyKey") or {}
    if idem.get("kind") != "ref":
        return None
    return idem.get("value")


def check(solidity: str, guard: str, postgres: str, spec: dict, coordination_plan: dict) -> list:
    reasons = []
    wk = workflow_key_from_spec(spec)
    if not wk:
        fail(reasons, "parity.workflow_key",
             "spec has no idempotency_key ref on the first effect — cannot derive the workflow key")
        return reasons
    name = spec.get("procedure")

    # The temporal () coordination renders a DIFFERENT cross-artifact invariant than the single-shot
    # gate: each policy GROUP commits only when the guard's recorded EXECUTION CLAIM for the workflow key
    # EQUALS the payload's recomputed claim (per-policy acceptedExecutionClaim(_k) == _claim / execution_claim
    # = v_claim), not a single isAccepted(claimId). Detect it structurally from the artifacts and require
    # BOTH rails render the SAME shape — a rail that drops the execution-claim binding while the other keeps
    # it is itself a parity break (one rail would authorize a commit against a foreign/stale accepted claim).
    sol_temporal = ("acceptedExecutionClaim" in solidity) and ("committedGroup" in solidity)
    pg_temporal = ("committed_group" in postgres) and ("neu_execution_claim" in postgres)
    if sol_temporal != pg_temporal:
        fail(reasons, "parity.temporal_rail_mismatch",
             f"one rail renders the temporal per-policy commit-ledger and the other the single-shot "
             f"acceptance (Solidity temporal={sol_temporal}, PostgreSQL temporal={pg_temporal}) — the "
             "rails disagree on the coordination shape")
        return reasons
    if sol_temporal:
        _check_temporal(reasons, solidity, guard, postgres, coordination_plan, wk, name)
    else:
        _check_single_shot(reasons, solidity, guard, postgres, wk, name)
    return reasons


def _check_temporal(reasons, solidity, guard, postgres, coordination_plan, wk, name):
    # The AUTHORITATIVE expected per-policy commit gates: {group ordinal -> policy} from the coordination plan. Every
    # temporal-suppress group MUST be gated by exactly one predicate binding ITS policy to ITS commit
    # ordinal on BOTH rails — no missing gate (an unconditional commit), no extra/duplicate, and no
    # cross-policy rewire (one policy authorizing another's group).
    expected = temporal_groups_from_coordination_plan(coordination_plan)
    if not expected:
        fail(reasons, "parity.temporal_coverage",
             "coordination-plan carries no temporal-suppress effect groups, but the artifacts render the "
             "temporal commit-ledger — cannot verify per-policy coverage")
        return
    # --- Solidity: derive _k from the workflow key; each per-policy commit gates on the guard's
    #     acceptedExecutionClaim(_k) EQUAL to the payload's recomputed CoordinationEnvelope.claim(...) ---
    m = re.search(r"bytes32\s+(\w+)\s*=\s*keccak256\(bytes\(u_(\w+)\)\);", solidity)
    kvar = None
    if not m:
        fail(reasons, "parity.temporal_solidity_derivation",
             "Solidity temporal execute() has no `bytes32 <var> = keccak256(bytes(u_<key>));` workflow-key derivation")
    else:
        kvar, kinput = m.group(1), m.group(2)
        if kinput != wk:
            fail(reasons, "parity.temporal_solidity_derivation",
                 f"Solidity derives the workflow key from input u_{kinput!r}, not the spec's idempotency_key {wk!r}")
    cm = re.search(r"bytes32\s+(\w+)\s*=\s*CoordinationEnvelope\.claim\(", solidity)
    claimvar = cm.group(1) if cm else None
    if claimvar is None:
        fail(reasons, "parity.temporal_solidity_claim",
             "Solidity temporal execute() does not recompute `bytes32 <var> = CoordinationEnvelope.claim(...)` — "
             "the commit is not bound to the payload's execution claim")
    # Parse each COMPLETE guarded commit block as a unit — `if ((acceptanceGuard_<pol>.acceptedExecutionClaim(
    # <k>) == <claim>) && !committedGroup[<k>][<condOrd>]) { … body … }` (the body has no nested braces) —
    # and require, WITHIN that same block: the (<k>, <claim>) binding, and that the body commits EXACTLY its
    # own ordinal (`committedGroup[_k][condOrd] = true`, no other). Deriving {ordinal->policy} from the guard
    # condition and reconciling it against a GLOBAL write set is not enough: it proves each ordinal appears in
    # some condition and some write, not that the guard for ordinal N protects the WRITE of ordinal N — so a
    # swapped pair (alpha's block writes N=1, beta's writes N=0) would pass. The per-block write check binds
    # the guard to its own commit.
    observed_sol = {}
    dup_sol = False
    for pol, gk, gc, gk2, ordn, body in re.findall(
            r"acceptanceGuard_(\w+)\.acceptedExecutionClaim\((\w+)\)\s*==\s*(\w+)\)\s*&&\s*!committedGroup\[(\w+)\]\[(\d+)\]\)\s*\{([^{}]*)\}",
            solidity):
        o = int(ordn)
        if kvar is not None and (gk != kvar or gk2 != kvar):
            fail(reasons, "parity.temporal_solidity_binding",
                 f"the group {o} gate reads the guard under {gk!r}/{gk2!r}, not the derived workflow key {kvar!r} (claimId != workflowKey)")
        if claimvar is not None and gc != claimvar:
            fail(reasons, "parity.temporal_solidity_binding",
                 f"the group {o} gate compares acceptedExecutionClaim to {gc!r}, not the recomputed execution claim {claimvar!r} — "
                 "it could commit against a foreign/stale accepted claim")
        body_writes = [int(w) for w in re.findall(r"committedGroup\[\w+\]\[(\d+)\]\s*=\s*true", body)]
        if body_writes != [o]:
            fail(reasons, "parity.temporal_solidity_coverage",
                 f"solidity: the block gated for policy {pol!r} on ordinal {o} commits ordinal(s) {body_writes} inside "
                 f"its own body (must write EXACTLY its guarded ordinal {o}) — a guard for one group marks another committed")
        if o in observed_sol:
            dup_sol = True
        observed_sol[o] = pol
    # Every committed ordinal in the whole function must be one produced by a validated block above — a
    # `committedGroup[_k][N] = true` with no guard block is the "delete the predicate, keep the commit"
    # unconditional-commit defeat (and a write inside a block for a foreign ordinal was already caught above).
    written_sol = {int(o) for o in re.findall(r"committedGroup\[\w+\]\[(\d+)\]\s*=\s*true", solidity)}
    _check_group_coverage(reasons, "solidity", expected, observed_sol, written_sol, dup_sol)
    # two-sided interface: the coordination declares the accessor, the guard exposes it (function or the
    # public mapping's auto-getter) — a guard-side rename is caught even with a valid coordination.
    coord_iface = re.search(r"function acceptedExecutionClaim\(bytes32\s+\w+\)\s+external\s+view\s+returns\s*\(\s*bytes32", solidity)
    guard_acc = (re.search(r"function acceptedExecutionClaim\(bytes32\s+\w+\)\s+(?:external|public)\s+view\s+returns\s*\(\s*bytes32", guard)
                 or re.search(r"mapping\(bytes32\s+\w+\s*=>\s*bytes32\s+\w+\)\s+public\s+acceptedExecutionClaim", guard))
    if coord_iface is None:
        fail(reasons, "parity.temporal_solidity_interface",
             "coordination declares no `acceptedExecutionClaim(bytes32 …) external view returns (bytes32)` guard interface")
    if guard_acc is None:
        fail(reasons, "parity.temporal_solidity_interface",
             "guard exposes no `acceptedExecutionClaim` accessor (function or public mapping) — the "
             "coordination's interface would call a non-existent accessor")

    # --- PostgreSQL: accept RECORDS the execution claim under (procedure, key); each per-policy execute
    #     gate BINDS the commit to `execution_claim = v_claim` (the recomputed payload claim) ---
    accept_body = _function_body(postgres, f"accept_{name}") if name else None
    execute_body = _function_body(postgres, f"execute_{name}") if name else None
    if accept_body is None:
        fail(reasons, "parity.temporal_postgres_accept_record", f"procedure.sql has no accept_{name} function body")
    else:
        # Align the INSERT's COLUMNS to its VALUES POSITIONALLY (the subquery observer-count stays one value
        # via the paren-aware split) so each recorded column is checked against the value at its OWN ordinal.
        # A positional swap (e.g. canonical_claim_hash <-> execution_claim) — which persists the wrong digest
        # as the accepted execution claim — is caught; an independent "column present" + "value present
        # somewhere" pair would miss it.
        m = re.search(r"INSERT INTO quorum_acceptance\(([^)]*)\)\s*VALUES \((.*?)\)\s*;", accept_body, re.S)
        if m is None:
            fail(reasons, "parity.temporal_postgres_accept_record",
                 "PostgreSQL accept_ has no `INSERT INTO quorum_acceptance(<cols>) VALUES (<vals>);`")
        else:
            cols = [c.strip() for c in m.group(1).split(",")]
            vals = _split_top_level(m.group(2))
            if len(cols) != len(vals):
                fail(reasons, "parity.temporal_postgres_accept_record",
                     f"PostgreSQL accept_ INSERT has {len(cols)} columns but {len(vals)} values — cannot verify positional binding")
            else:
                colval = dict(zip(cols, vals))
                if colval.get("procedure") != f"'{name}'":
                    fail(reasons, "parity.temporal_postgres_accept_record",
                         f"PostgreSQL accept_ records procedure {colval.get('procedure')!r}, not '{name}' "
                         "(acceptance is in the wrong (procedure, key) namespace)")
                if colval.get("claim_id") != f"p_{wk}":
                    fail(reasons, "parity.temporal_postgres_accept_record",
                         f"PostgreSQL accept_ records claim_id {colval.get('claim_id')!r}, not the spec's idempotency_key p_{wk}")
                if colval.get("execution_claim") != "p_execution_claim":
                    fail(reasons, "parity.temporal_postgres_accept_record",
                         f"PostgreSQL accept_ binds the execution_claim column to {colval.get('execution_claim')!r}, not "
                         "p_execution_claim — the guard would persist the wrong value as the accepted execution claim")
    if execute_body is None:
        fail(reasons, "parity.temporal_postgres_binding", f"procedure.sql has no execute_{name} function body")
    else:
        if not re.search(r"v_claim\s*:=\s*neu_execution_claim\(", execute_body):
            fail(reasons, "parity.temporal_postgres_binding",
                 "PostgreSQL execute() does not recompute `v_claim := neu_execution_claim(...)` — the commit is "
                 "not bound to the payload's execution claim")
        # Parse each per-policy commit BLOCK as a unit and require the commit WRITE inside it records the SAME
        # ordinal its guard checks. Each block opens with `IF (EXISTS(quorum_acceptance … policy = '<pol>' …
        # execution_claim = v_claim)) AND NOT EXISTS(committed_group … group_ordinal = <condOrd>) THEN` and,
        # within the block, inserts `committed_group(…) VALUES (…, <writeOrd>)`. Because the block body has
        # nested `IF (p_amount) < 0 … END IF;` guards, the block is sliced between consecutive per-policy
        # condition anchors (the key_claim pin ends the per-policy section). Deriving {ordinal->policy} from
        # the condition and reconciling with a GLOBAL committed_group write set would pass a swapped pair
        # (alpha's block writes ordinal 1, beta's writes 0); the per-block write check binds each guard to its
        # own commit.
        pin = re.search(r"IF v_progress AND NOT EXISTS \(SELECT 1 FROM key_claim", execute_body)
        end_of_blocks = pin.start() if pin else len(execute_body)
        anchors = list(re.finditer(
            r"quorum_acceptance WHERE procedure = '([^']*)' AND claim_id = p_(\w+) AND policy = '([^']*)' "
            r"AND execution_claim = v_claim\)\) AND NOT EXISTS \(SELECT 1 FROM committed_group WHERE "
            r"procedure = '[^']*' AND idempotency_key = p_\w+ AND group_ordinal = (\d+)\)",
            execute_body))
        observed_pg = {}
        dup_pg = False
        for i, m in enumerate(anchors):
            chk_proc, chk_key, pol, o = m.group(1), m.group(2), m.group(3), int(m.group(4))
            block_end = anchors[i + 1].start() if i + 1 < len(anchors) else end_of_blocks
            block = execute_body[m.start():block_end]
            if chk_key != wk:
                fail(reasons, "parity.temporal_postgres_binding",
                     f"the group {o} gate checks claim_id = p_{chk_key!r}, not the workflow key p_{wk!r} (claimId != workflowKey)")
            if chk_proc != name:
                fail(reasons, "parity.temporal_postgres_binding",
                     f"the group {o} gate checks procedure {chk_proc!r}, not the spec procedure {name!r} "
                     "(execute reads a foreign (procedure, key) namespace)")
            body_writes = [int(w) for w in re.findall(
                r"INSERT INTO committed_group\([^)]*\)\s*VALUES \('[^']*', p_\w+, (\d+)\)", block)]
            if body_writes != [o]:
                fail(reasons, "parity.temporal_postgres_coverage",
                     f"postgres: the block gated for policy {pol!r} on ordinal {o} commits ordinal(s) {body_writes} inside "
                     f"its own body (must write EXACTLY its guarded ordinal {o}) — a guard for one group marks another committed")
            if o in observed_pg:
                dup_pg = True
            observed_pg[o] = pol
        # Every committed ordinal in the whole function must be one produced by a validated block above — an
        # `INSERT INTO committed_group(…) VALUES (…, N)` with no per-policy gate is the unconditional-commit defeat.
        written_pg = {int(o) for o in re.findall(
            r"INSERT INTO committed_group\([^)]*\)\s*VALUES \('[^']*', p_\w+, (\d+)\)", execute_body)}
        _check_group_coverage(reasons, "postgres", expected, observed_pg, written_pg, dup_pg)


def _check_single_shot(reasons, solidity, guard, postgres, wk, name):
    # --- Solidity coordination: derive-and-check the SAME variable, from the workflow key ---
    # bytes32 _k = keccak256(bytes(u_<workflowKey>));
    m = re.search(r"bytes32\s+(\w+)\s*=\s*keccak256\(bytes\(u_(\w+)\)\);", solidity)
    if not m:
        fail(reasons, "parity.solidity_derivation",
             "Solidity execute() has no `bytes32 <var> = keccak256(bytes(u_<key>));` workflow-key derivation")
    else:
        kvar, kinput = m.group(1), m.group(2)
        if kinput != wk:
            fail(reasons, "parity.solidity_derivation",
                 f"Solidity derives the workflow key from input u_{kinput!r}, not the spec's idempotency_key {wk!r}")
        # the guard check must use THAT SAME derived variable
        checked = _find(r"acceptanceGuard\.isAccepted\((\w+)\)", solidity)
        if checked is None:
            fail(reasons, "parity.solidity_guard_check",
                 "Solidity execute() does not gate on `acceptanceGuard.isAccepted(<var>)`")
        elif checked != kvar:
            fail(reasons, "parity.solidity_guard_check",
                 f"Solidity gate checks isAccepted({checked!r}) but the workflow key was derived into {kvar!r} — "
                 "the guard-check id is not the workflow-key hash (claimId != workflowKey)")

    # coordination interface accessor must match the guard's actual isAccepted signature (two-sided:
    # a guard-side rename/param change is caught even with a valid coordination).
    coord_iface = re.search(r"function isAccepted\(bytes32\s+\w+\)\s+external\s+view\s+returns", solidity)
    # the guard's accessor may be `external`/`public` view — match either.
    guard_acc = re.search(r"function isAccepted\(bytes32\s+\w+\)\s+(?:external|public)\s+view\s+returns", guard)
    if coord_iface is None:
        fail(reasons, "parity.solidity_interface",
             "coordination declares no `isAccepted(bytes32 …) external view returns (bool)` guard interface")
    if guard_acc is None:
        fail(reasons, "parity.solidity_interface",
             "guard contract exposes no `isAccepted(bytes32 …) external view returns (bool)` accessor — "
             "the coordination's interface would call a non-existent accessor")

    # --- PostgreSQL coordination: accept RECORDS under, and execute CHECKS, the same p_<workflowKey> ---
    # Each check is scoped to ITS OWN function body — accept_ also references `quorum_acceptance WHERE
    # claim_id = p_<key>` (its replay guard), so a whole-file search for the execute_ gate would read
    # accept_'s occurrence and miss an execute_-only drift ( review).
    accept_body = _function_body(postgres, f"accept_{name}") if name else None
    execute_body = _function_body(postgres, f"execute_{name}") if name else None
    if accept_body is None:
        fail(reasons, "parity.postgres_accept_record",
             f"procedure.sql has no accept_{name} function body")
    else:
        # Acceptance identity is (procedure, claim_id) (): the INSERT records
        # BOTH the procedure literal and the p_<workflowKey> claim value, and
        # BOTH must match the spec — a right key under a foreign procedure
        # namespace is still a parity break (the acceptance would live in the
        # wrong namespace and execute() would never see it).
        m = re.search(
            r"INSERT INTO quorum_acceptance\([^)]*\bclaim_id\b[^)]*\)\s*VALUES \('([^']*)',\s*p_(\w+)",
            accept_body)
        if m is None:
            fail(reasons, "parity.postgres_accept_record",
                 "PostgreSQL accept_ does not record `INSERT INTO quorum_acceptance(procedure, claim_id, …) VALUES ('<proc>', p_<key>, …)`")
        else:
            rec_proc, recorded = m.group(1), m.group(2)
            if recorded != wk:
                fail(reasons, "parity.postgres_accept_record",
                     f"PostgreSQL accept_ records under p_{recorded!r}, not the spec's idempotency_key p_{wk!r}")
            if rec_proc != name:
                fail(reasons, "parity.postgres_accept_record",
                     f"PostgreSQL accept_ records under procedure {rec_proc!r}, not the spec procedure {name!r} "
                     "(acceptance is in the wrong (procedure, key) namespace)")
    if execute_body is None:
        fail(reasons, "parity.postgres_claim_check",
             f"procedure.sql has no execute_{name} function body")
    else:
        # The execute-side gate must check the SAME p_<workflowKey> AND the SAME
        # procedure namespace the acceptance recorded under.
        m = re.search(
            r"quorum_acceptance WHERE claim_id = p_(\w+) AND procedure = '([^']*)'",
            execute_body)
        if m is None:
            fail(reasons, "parity.postgres_claim_check",
                 "PostgreSQL execute() does not gate on `quorum_acceptance WHERE claim_id = p_<key> AND procedure = '<proc>'`")
        else:
            checked_pg, chk_proc = m.group(1), m.group(2)
            if checked_pg != wk:
                fail(reasons, "parity.postgres_claim_check",
                     f"PostgreSQL execute() gate checks claim_id = p_{checked_pg!r}, not the spec's "
                     f"idempotency_key p_{wk!r} (claimId != workflowKey)")
            if chk_proc != name:
                fail(reasons, "parity.postgres_claim_check",
                     f"PostgreSQL execute() gate checks procedure {chk_proc!r}, not the spec procedure "
                     f"{name!r} (execute reads a foreign (procedure, key) namespace)")


def main() -> int:
    ap = argparse.ArgumentParser(description="coordination↔guard claimId parity gate ()")
    ap.add_argument("--solidity", required=True, help="the generated coordination contract (.sol)")
    ap.add_argument("--guard", required=True, help="the rendered acceptance-guard contract (.sol)")
    ap.add_argument("--postgres", required=True, help="the generated procedure.sql")
    ap.add_argument("--spec", required=True, help="the capability-spec.json")
    ap.add_argument("--plan", help="the coordination-plan.json (authoritative effect-group ordinals; "
                    "required for the temporal per-policy coverage check)")
    args = ap.parse_args()
    try:
        solidity = open(args.solidity, encoding="utf-8").read()
        guard = open(args.guard, encoding="utf-8").read()
        postgres = open(args.postgres, encoding="utf-8").read()
        spec = json.load(open(args.spec, encoding="utf-8"))
        coordination_plan = json.load(open(args.plan, encoding="utf-8")) if args.plan else {}
    except (OSError, ValueError) as ex:
        print(f"parity: [parity.io] {ex}", file=sys.stderr)
        return 1
    reasons = check(solidity, guard, postgres, spec, coordination_plan)
    if reasons:
        print("coordination↔guard claimId parity FAILED:", file=sys.stderr)
        for r in reasons:
            print(f"    {r}", file=sys.stderr)
        return 1
    print("coordination↔guard parity OK: both rails key acceptance on the SAME spec workflow key "
          "(claimId ≡ workflowKey); single-shot derives-and-checks one var / records-and-checks p_<key>, "
          "and the temporal path binds every coordination-plan-declared policy to ITS commit-group ordinal + the "
          "recomputed execution claim on both rails")
    return 0


if __name__ == "__main__":
    sys.exit(main())

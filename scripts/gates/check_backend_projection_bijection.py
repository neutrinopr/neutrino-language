#!/usr/bin/env python3
"""Validate the Tier-2-final backend-projection bijection and design traces.

The checker deliberately does not infer semantics from C++.  The reviewed JSON
classifies them.  It proves that the classification still names real anchors in
the exact reviewed source snapshot, every site has one closed disposition, both
rails cover every semantic row, and the three B1-B4 traces are structurally
non-vacuous.  Any legalizer edit invalidates the snapshot and requires a new
reviewed reconciliation.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
INVENTORY = os.path.join(
    REPO, "docs", "process", "m6_backend_projection_bijection.json"
)
TRACES = os.path.join(
    REPO, "docs", "process", "m6_backend_projection_traces.json"
)
BINDINGS = os.path.join(
    REPO, "docs", "process", "m6_backend_projection_trace_bindings.json"
)
PREIMAGE_611 = os.path.join(
    REPO, "test", "fixtures", "backend_projection_611_preimage.json"
)
CONVERGENCE_GATE = os.path.join(
    REPO, "scripts", "gates", "check_backend_convergence.py"
)

PROBES = (
    "duplicate-site",
    "unclassified-site",
    "rail-hole",
    "source-drift",
    "decision-surface-hole",
    "decision-occurrence-unowned",
    "decision-occurrence-multiply",
    "decision-local-field-unowned",
    "decision-ternary-unowned",
    "group-duplicate-posting",
    "balance-extra-group",
    "posting-expansion-removal",
    "posting-expansion-substitution",
    "rollback-discharge-missing",
    "rollback-discharge-wrong",
    "rollback-discharge-ambiguous",
    "fixture-binding-missing",
    "source-binding-garbage",
    "trace-value-fabricated",
    "compensate-accepted",
    "intake-bypass",
    "migration-baseline-tamper",
    "migration-baseline-coordinated-tamper",
    "migration-retirement-dropped",
    "migration-retirement-duplicate",
    "migration-retirement-cross-family-row",
    "migration-preimage-binding-substitution",
    "migration-addition-wrong-site",
    "migration-addition-absent",
    "migration-source-legacy-reintroduced",
    "status-authority-omission",
    "status-authority-substitution",
    "status-authority-duplicate",
    "status-authority-table-selection",
    "identity-migration-omission",
    "identity-migration-duplicate-old",
    "identity-migration-duplicate-new",
    "identity-migration-substitution",
    "cross-row-source-binding",
)

IDENTITY_MIGRATION_KIND = (
    "neutrino.backend-projection-decision-identity-migration.v1"
)
IDENTITY_FROM_VERSION = "function-global-ordinal.v1"
IDENTITY_TO_VERSION = "anchored-expression.v2"
IDENTITY_MIGRATION_COUNT = 298
IDENTITY_MIGRATION_DIGEST = (
    "b1b1274801d4537fd82fcc235f3ff2df263ba1ab218e54775eab06683783ff2b"
)
IDENTITY_LEGACY_SURFACE_DIGEST = (
    "2329f52c8c624d578668d29ed3776ae751378aef42e4acbef6871bde19ab1dbe"
)

TERMINAL_STRUCTURAL_ZERO = {
    "kind": "neutrino.backend-projection-bijection.terminal.v1",
    "successorGate": "backend_convergence",
    "liveBackendSemanticAuthority": 0,
    "historicalLedgerImmutable": True,
    "reason": (
        " removed the backend-local legalizer authority measured by the "
        "frozen 314-occurrence migration ledger; live enforcement now derives "
        "semantic authority through the  classifier instead of refreezing "
        "historical arithmetic."
    ),
}
IDENTITY_PINNED_SOURCES = {
    "lib/backends/solidity/SolidityModel.cpp": (
        "d2553350d7b41163aed0d879e2a4865669678e931d82a7c903b2033251dd9801"
    ),
    "lib/backends/postgres/model/PostgresModel.cpp": (
        "157e813e8d1bbebe8882b0dcf5b78f666238f4d8e79acc2bd722f210df5196d8"
    ),
    "lib/backends/solidity/generated/SolidityTargetEnums.inc": (
        "c806702f9adf5a9fb33dc26bb2495caaa83245018b783eb4834936f4a4d35699"
    ),
    "lib/backends/postgres/generated/PostgresTargetEnums.inc": (
        "9566a5bfa17e7edf32acac2ceea6552c6f54596387d468d0fc48ee2bb9c510f6"
    ),
}
IDENTITY_PERSISTENT_RX = re.compile(
    r"^(?P<anchor>.+@v2:[0-9a-f]{64}):p(?P<token>[0-9a-f]{64})$"
)
PREIMAGE_611_BINDING_DIGEST = (
    "87f5753b736c6d30a457a52353916091fd9f177d1c8788ef847ee0b2d3bb4bb7"
)

# The migration ledger is pinned to the reviewed pre-migration decision count
# here, independently of the (mutable) inventory JSON, so a coordinated edit that
# changes the JSON baseline together with a retirement/addition cannot launder
# itself past the reconciliation identity.
#
# The status-authority scanner expansion adds reviewed identities to the
# ledger; it does not rewrite the frozen pre-migration baseline. Keeping those
# additions explicit makes their later retirement mechanically accountable.
MIGRATION_BASELINE = 314
MIGRATION_SLICE_ROWS = {
    "d657-identity-terminal-projection": frozenset(
        {"execution-identity", "success-terminal"}
    ),
    "d657-status-authority-surface": frozenset({"status-authority"}),
    "d611-shared-mixed-temporal-legality": frozenset(
        {
            "guard-binding",
            "memo-positional-operand",
            "semantic-posting-fixed-expansion",
        }
    ),
    "d658-attestation-guard-evidence-projection": frozenset(
        {
            "execution-mode.evidence",
            "execution-mode.temporal",
            "quorum-single",
            "quorum-per-policy",
            "guard-binding",
        }
    ),
}
MIGRATION_RECORD_KEYS = frozenset(
    {"occurrence", "owningSlice", "owningSite", "destination", "destinationRow"}
)
# A retired `CoordinationPlan` read must have migrated to the shared identity
# or the success terminal — never to a mere backend-idiom branch.
MIGRATION_RETIREMENT_DESTINATIONS = frozenset(
    {
        "ExecutionIdentity",
        "LifecycleState.terminal",
        "CoordinationPlan.assemblePlan.attest.temporal.mixed",
        "ExecutionMode.EvidenceOnly",
        "EvidenceAcceptance + terminal LifecycleState",
        "PrimitiveObligation.QuorumAcceptance.PerPolicy",
        "QuorumAcceptance.Single -> SOL-QUORUM-BLOB",
        "QuorumAcceptance.Single -> PG-QUORUM-SINGLE + matching REVOKE",
        "QuorumAcceptance.PerPolicy -> SOL-QUORUM-BLOB",
        "QuorumAcceptance.PerPolicy -> PG-QUORUM-TEMPORAL + matching REVOKE",
        "GuardObligation + guardRef/policyRef",
    }
)

COORDINATION_PLAN_LOCAL_FIELDS = {
    "PlanInput": {"name", "type"},  # Governed evidence name: CoordinationPlanInput.
    "PlanEffect": {
        "amount",
        "attestationInput",
        "canonicalGuard",
        "currency",
        "gateMode",
        "gatePolicy",
        "guard",
        "guardKey",
        "index",
        "kind",
        "ledger",
        "memo",
        "name",
        "participant",
        "party",
    },
    "PlanEffectGroup": {
        "attestationInput",
        "canonicalGuard",
        "creditCount",
        "debitCount",
        "effectIndices",
        "firstIndex",
        "gateMode",
        "gatePolicy",
        "guardKey",
        "mustBalance",
    },
    "PlanCompute": {"category", "deps", "expr", "name"},
    "AttestationPolicy": {
        "assurance",
        "canonicalization",
        "fallback",
        "independence",
        "input",
        "observerRole",
        "observerSet",
        "quorum",
        "timeout",
        "tolerance",
    },
}
COORDINATION_PLAN_LOCAL_TYPE_NAMES = {
    "PlanInput": "CoordinationPlanInput",
}

NODE_FIELDS = {
    "ExecutionIdentity": ("procedureNamespace", "instanceKey", "replayKey"),
    "CommitState": ("idempotencyKey", "commitScope"),
    "LifecycleState": ("name", "terminal"),
    "Transition": ("name",),
    "QuorumPolicy": ("threshold", "canonicalization", "timeout", "fallback"),
    "GuardObligation": ("guardKind", "conditionKind", "applicationMode"),
    "EvidenceAcceptance": (
        "bindingValue",
        "style",
        "chained",
        "admissibility",
    ),
    "PrimitiveObligation": ("finalizedKind", "typedOperands"),
    "BalancedEffectGroup": ("firstIndex", "pairing", "mustBalance"),
    "LedgerPosting": ("effectIndex", "direction"),
    "BalanceAssertion": ("scope",),
    "CompensationObligation": ("mode",),
    "TypedOperand": ("operandKind", "value"),
    "TypedParam": ("name", "type"),
    "Reference": ("ref", "role"),
    "ComputeNode": ("exprKind", "dtype"),
}

EDGE_TYPES = {
    "guardRef": ({"BalancedEffectGroup"}, {"GuardObligation"}),
    "policyRef": (
        {"GuardObligation", "PrimitiveObligation"},
        {"QuorumPolicy"},
    ),
    "inputRef": ({"QuorumPolicy"}, {"EvidenceAcceptance"}),
    "observerSetRef": ({"QuorumPolicy"}, {"Reference"}),
    "effectGroupRefs": ({"Transition"}, {"BalancedEffectGroup"}),
    "fromRef": ({"Transition"}, {"LifecycleState"}),
    "toRef": ({"Transition"}, {"LifecycleState"}),
    "execRef": ({"CommitState"}, {"ExecutionIdentity"}),
    "scopeRef": ({"CommitState"}, {"QuorumPolicy"}),
    "requiredCommitRefs": ({"LifecycleState"}, {"CommitState"}),
    "groupRef": ({"LedgerPosting"}, {"BalancedEffectGroup"}),
    "effectRefs": ({"BalancedEffectGroup"}, {"LedgerPosting"}),
    "assertsRefs": ({"BalanceAssertion"}, {"BalancedEffectGroup"}),
    "ledgerRef": ({"LedgerPosting"}, {"TypedOperand", "ComputeNode"}),
    "partyRef": ({"LedgerPosting"}, {"TypedOperand", "ComputeNode"}),
    "amountRef": ({"LedgerPosting"}, {"TypedOperand", "ComputeNode"}),
    "currencyRef": ({"LedgerPosting"}, {"TypedOperand", "ComputeNode"}),
    "memoRef": ({"LedgerPosting"}, {"TypedOperand", "ComputeNode"}),
    "operandRefs": ({"ComputeNode"}, {"TypedOperand", "ComputeNode"}),
    "compensates": (
        {"CompensationObligation"},
        {"BalancedEffectGroup", "Transition"},
    ),
}


def _load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _sha256(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _function_body(text, symbol):
    match = re.search(r"\b" + re.escape(symbol) + r"\s*\([^;{}]*\)\s*\{", text)
    if not match:
        raise ValueError(f"bijection.symbol_missing:{symbol}")
    start = match.end() - 1
    depth = 0
    state = "code"
    quote = ""
    i = start
    while i < len(text):
        c = text[i]
        n = text[i + 1] if i + 1 < len(text) else ""
        if state == "line-comment":
            if c == "\n":
                state = "code"
        elif state == "block-comment":
            if c == "*" and n == "/":
                state = "code"
                i += 1
        elif state == "string":
            if c == "\\":
                i += 1
            elif c == quote:
                state = "code"
        else:
            if c == "/" and n == "/":
                state = "line-comment"
                i += 1
            elif c == "/" and n == "*":
                state = "block-comment"
                i += 1
            elif c in ('"', "'"):
                state = "string"
                quote = c
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
        i += 1
    raise ValueError(f"bijection.symbol_unclosed:{symbol}")


# ---- status-authority spelling occurrence class ( G1-S1 measurability) --
# The backend status-machine SPELLING authority — the status-enum variants, the
# lifecycle transition targets, the guard states, and the status-write columns —
# is otherwise INVISIBLE to _decision_surface, because string-literal content is
# masked before matching. This closed class makes that authority a measurable
# part of the decision surface so the G1-S1 consume-and-delete migration can
# retire these exact occurrences (moving the spelling selection to the projected
# lifecycle role).
#
# Each occurrence is keyed by the semantic lifecycle ROLE the spelling denotes
# (initial / success / attest) via the closed table below — NEVER the literal
# spelling ("None"/"Accepted"/"Reconciled"/"reconciled"/"attested") nor an
# ordinal position — so the identity is stable under renaming/reordering. An
# unknown spelling classifies as `unclassified:<spelling>`, which owns no site
# and trips the gate (the authority grew without review).
STATUS_SPELLING_ROLE = {
    "None": "initial",
    "Accepted": "success",
    "Reconciled": "success",
    "reconciled": "success",
    "attested": "attest",
}


def _status_role(spelling):
    return STATUS_SPELLING_ROLE.get(spelling, "unclassified:" + spelling)


def _status_authority_records(body):
    """Status-machine spelling occurrences, read from the RAW (unmasked) body.

    Positions align with the masked `code` because masking is length-preserving.
    A CLOSED set of governed status builders; each yields a role-keyed record.
    """
    recs = []
    # Solidity enum variants: `c.statusEnum = {"Status", {"<a>", "<b>"}}`.
    for mo in re.finditer(
        r'\.statusEnum\s*=\s*\{\s*"[^"]*"\s*,\s*\{([^}]*)\}', body
    ):
        for vm in re.finditer(r'"([^"]+)"', mo.group(1)):
            recs.append(
                (mo.start(), "status-authority:enum:" + _status_role(vm.group(1)))
            )
    # Solidity transition target: `SolStmt::transition(/*state=*/"<s>", ...)`.
    for mo in re.finditer(
        r'SolStmt::transition\(\s*(?:/\*state=\*/)?\s*"([^"]+)"', body
    ):
        recs.append(
            (mo.start(), "status-authority:transition:" + _status_role(mo.group(1)))
        )
    # Solidity guard state: `Status.<S>`.
    for mo in re.finditer(r"\bStatus\.([A-Za-z_]\w*)", body):
        recs.append(
            (mo.start(), "status-authority:guard:" + _status_role(mo.group(1)))
        )
    # Postgres status write: `PgStmt::statusWrite(proc, pkey, "<f>", ...)`.
    for mo in re.finditer(r'PgStmt::statusWrite\([^,]+,[^,]+,\s*"([^"]+)"', body):
        recs.append(
            (mo.start(), "status-authority:write:" + _status_role(mo.group(1)))
        )
    # Postgres guard column: `... AND <col>)`.
    for mo in re.finditer(r"\bAND\s+(reconciled|attested)\b", body):
        recs.append(
            (mo.start(), "status-authority:guard:" + _status_role(mo.group(1)))
        )
    # Tripwire ( G1-S1): after the migration every status atom lives in the
    # generated idiom table (read via the authorized `statusRoleAtom`/
    # `pgStatusRoleAtom` accessor, which carries NO literal). A raw status-spelling
    # literal BOUND to a local name (`= "Reconciled"`) or RETURNED
    # (`return "Reconciled";`) is the helper/local-const escape that would hide the
    # authority from every builder pattern above and manufacture a false decrement.
    # It is detected here so the atom cannot silently re-enter a legalizer body.
    # (The `(?<![=!<>])` lookbehind skips `== "…"` comparisons; the whole-content
    # match skips event names like `name + "Accepted"` — `+`-adjacent, not `=`/
    # `return`-led — and longer literals that merely contain a spelling word.)
    for mo in re.finditer(
        r'(?<![=!<>])=\s*"(None|Accepted|Reconciled|reconciled|attested)"'
        r'|\breturn\s+"(None|Accepted|Reconciled|reconciled|attested)"',
        body,
    ):
        sp = mo.group(1) or mo.group(2)
        recs.append((mo.start(), "status-authority:local:" + _status_role(sp)))
    return recs


def _statement_anchor(code, position):
    """Return a normalized, position-independent source anchor.

    Control heads are anchored by their complete parenthesized header. Other
    governed reads are anchored by the containing statement. Independent
    statement reordering therefore preserves identities, while changing a
    governed expression changes its anchor.
    """
    control = re.match(r"(?:if|for|while|switch)\s*\(", code[position:])
    if control:
        open_pos = position + control.group(0).rfind("(")
        depth = 0
        for i in range(open_pos, len(code)):
            if code[i] == "(":
                depth += 1
            elif code[i] == ")":
                depth -= 1
                if depth == 0:
                    return re.sub(r"\s+", "", code[position : i + 1])

    start = position
    while start > 0 and code[start - 1] not in ";{}":
        start -= 1
    end = position
    while end < len(code) and code[end] not in ";{}":
        end += 1
    if end < len(code) and code[end] == ";":
        end += 1
    return re.sub(r"\s+", "", code[start:end])


def _balanced_close(code, open_pos, opener, closer):
    """Return the matching delimiter, ignoring delimiters inside literals."""
    depth = 0
    quote = ""
    i = open_pos
    while i < len(code):
        c = code[i]
        if quote:
            if c == "\\" and i + 1 < len(code):
                i += 2
                continue
            if c == quote:
                quote = ""
        elif c in ('"', "'"):
            quote = c
        elif c == opener:
            depth += 1
        elif c == closer:
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return None


def _source_statement_end(code, start):
    """Return the end of one C++ statement/compound statement."""
    while start < len(code) and code[start].isspace():
        start += 1
    if start >= len(code):
        return start
    if code[start] == "{":
        close = _balanced_close(code, start, "{", "}")
        return len(code) if close is None else close + 1

    control = re.match(r"(if|for|while|switch)\s*\(", code[start:])
    if control:
        open_pos = start + control.group(0).rfind("(")
        close = _balanced_close(code, open_pos, "(", ")")
        if close is None:
            return len(code)
        end = _source_statement_end(code, close + 1)
        if control.group(1) == "if":
            cursor = end
            while cursor < len(code) and code[cursor].isspace():
                cursor += 1
            if code.startswith("else", cursor):
                end = _source_statement_end(code, cursor + len("else"))
        return end

    parens = brackets = braces = 0
    quote = ""
    i = start
    while i < len(code):
        c = code[i]
        if quote:
            if c == "\\" and i + 1 < len(code):
                i += 2
                continue
            if c == quote:
                quote = ""
        elif c in ('"', "'"):
            quote = c
        elif c == "(":
            parens += 1
        elif c == ")":
            parens = max(0, parens - 1)
        elif c == "[":
            brackets += 1
        elif c == "]":
            brackets = max(0, brackets - 1)
        elif c == "{":
            braces += 1
        elif c == "}":
            if braces == 0:
                return i
            braces -= 1
        elif c == ";" and parens == brackets == braces == 0:
            return i + 1
        i += 1
    return len(code)


def _control_construct_anchor(code, start):
    control = re.match(r"(?:if|for|while|switch)\s*\(", code[start:])
    if control is None:
        return None
    open_pos = start + control.group(0).rfind("(")
    close = _balanced_close(code, open_pos, "(", ")")
    if close is None:
        return None
    end = _source_statement_end(code, close + 1)
    return re.sub(r"\s+", "", code[start:end])


def _source_bound_anchor(code, position):
    """Bind a record to its independently derivable structural source node.

    A control header (and governed reads inside that header) is bound to the
    complete controlled construct, not merely the repeated header spelling.
    This makes identical headers in different semantic blocks distinguishable
    without encounter order. Exact duplicate constructs may remain equal only
    when the ledger assigns them to the same signed owner.
    """
    candidates = []
    for match in re.finditer(r"\b(?:if|for|while|switch)\s*\(", code):
        if match.start() > position:
            break
        open_pos = match.start() + match.group(0).rfind("(")
        close = _balanced_close(code, open_pos, "(", ")")
        if close is not None and match.start() <= position <= close:
            candidates.append(match.start())
    if candidates:
        structural = _control_construct_anchor(code, candidates[-1])
        if structural is not None:
            return structural
    return _statement_anchor(code, position)


def _comment_stripped_source(body):
    """Mask comments but preserve semantic tokens, including string literals."""
    result = []
    state = "code"
    quote = ""
    i = 0
    while i < len(body):
        c = body[i]
        n = body[i + 1] if i + 1 < len(body) else ""
        if state == "line-comment":
            result.append("\n" if c == "\n" else " ")
            if c == "\n":
                state = "code"
        elif state == "block-comment":
            result.append(" ")
            if c == "*" and n == "/":
                result.append(" ")
                i += 1
                state = "code"
        elif state == "string":
            result.append(c)
            if c == "\\" and i + 1 < len(body):
                result.append(body[i + 1])
                i += 1
            elif c == quote:
                state = "code"
        elif c == "/" and n == "/":
            result.extend((" ", " "))
            i += 1
            state = "line-comment"
        elif c == "/" and n == "*":
            result.extend((" ", " "))
            i += 1
            state = "block-comment"
        else:
            result.append(c)
            if c in ('"', "'"):
                quote = c
                state = "string"
        i += 1
    return "".join(result)


def _decision_records(body, governed):
    """Return every source-visible decision input in a governed function.

    This is intentionally syntactic.  It is a ratchet over CoordinationPlan
    field reads, reads from typed CoordinationPlan-derived locals, control heads,
    conditional operators, calls between governed functions, and the closed
    status-authority spelling class; semantic classification stays in the
    reviewed inventory.
    """
    masked = []
    state = "code"
    quote = ""
    i = 0
    while i < len(body):
        c = body[i]
        n = body[i + 1] if i + 1 < len(body) else ""
        if state == "line-comment":
            masked.append("\n" if c == "\n" else " ")
            if c == "\n":
                state = "code"
        elif state == "block-comment":
            masked.append(" ")
            if c == "*" and n == "/":
                masked.append(" ")
                i += 1
                state = "code"
        elif state == "string":
            masked.append(" ")
            if c == "\\":
                if i + 1 < len(body):
                    masked.append(" ")
                    i += 1
            elif c == quote:
                state = "code"
        elif c == "/" and n == "/":
            masked.extend((" ", " "))
            i += 1
            state = "line-comment"
        elif c == "/" and n == "*":
            masked.extend((" ", " "))
            i += 1
            state = "block-comment"
        elif c in ('"', "'"):
            masked.append(" ")
            quote = c
            state = "string"
        else:
            masked.append(c)
        i += 1
    code = "".join(masked)
    records = []
    for match in re.finditer(
        r"\bcoordinationPlan\.([A-Za-z_][A-Za-z0-9_]*)", code
    ):
        records.append((match.start(), "field:" + match.group(1)))

    # Recover the small amount of local type information needed to keep
    # CoordinationPlan reads visible after a legalizer aliases a collection. This is
    # source-derived rather than an inventory allowlist: explicit declarations,
    # typed vectors, indexed `auto` aliases, and stable-sort lambda aliases all
    # participate.  A newly introduced typed alias is therefore covered
    # without updating the reviewed JSON first.
    aliases = {}
    containers = {}
    coordination_plan_types = "|".join(map(re.escape, COORDINATION_PLAN_LOCAL_FIELDS))
    for match in re.finditer(
        rf"\b(?:const\s+)?({coordination_plan_types})\b\s*(?:const\s*)?[&*]?\s*"
        r"([A-Za-z_][A-Za-z0-9_]*)\b",
        code,
    ):
        aliases[match.group(2)] = match.group(1)
    for match in re.finditer(
        rf"\bstd::vector\s*<\s*({coordination_plan_types})\s*>\s*"
        r"([A-Za-z_][A-Za-z0-9_]*)\b",
        code,
    ):
        containers[match.group(2)] = match.group(1)
    for match in re.finditer(
        r"\bconst\s+auto\s*&\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*"
        r"([A-Za-z_][A-Za-z0-9_]*)\s*\[",
        code,
    ):
        if match.group(2) in containers:
            aliases[match.group(1)] = containers[match.group(2)]
    for container, type_name in containers.items():
        sort_pattern = (
            r"\bstd::stable_sort\s*\(\s*"
            + re.escape(container)
            + r"\.begin\s*\(\s*\)\s*,\s*"
            + re.escape(container)
            + r"\.end\s*\(\s*\)\s*,(?P<tail>.*?)\}\s*\)"
        )
        for sort in re.finditer(sort_pattern, code, re.DOTALL):
            for param in re.finditer(
                r"\bconst\s+auto\s*&\s*([A-Za-z_][A-Za-z0-9_]*)",
                sort.group("tail"),
            ):
                aliases[param.group(1)] = type_name

    for alias, type_name in sorted(aliases.items()):
        governed_type = COORDINATION_PLAN_LOCAL_TYPE_NAMES.get(type_name, type_name)
        fields = "|".join(
            map(re.escape, sorted(COORDINATION_PLAN_LOCAL_FIELDS[type_name]))
        )
        for match in re.finditer(
            r"\b" + re.escape(alias) + rf"\.({fields})\b", code
        ):
            records.append(
                (match.start(), f"local-field:{governed_type}:{match.group(1)}")
            )
    for container, type_name in sorted(containers.items()):
        governed_type = COORDINATION_PLAN_LOCAL_TYPE_NAMES.get(type_name, type_name)
        fields = "|".join(
            map(re.escape, sorted(COORDINATION_PLAN_LOCAL_FIELDS[type_name]))
        )
        for match in re.finditer(
            r"\b"
            + re.escape(container)
            + rf"\s*\[[^\]]+\]\s*\.({fields})\b",
            code,
        ):
            records.append(
                (match.start(), f"local-field:{governed_type}:{match.group(1)}")
            )

    for match in re.finditer(r"\b(if|for|while|switch)\s*\(", code):
        records.append((match.start(), "control:" + match.group(1)))
    for match in re.finditer(r"\?", code):
        records.append((match.start(), "conditional:ternary"))
    for callee in governed:
        for match in re.finditer(r"\b" + re.escape(callee) + r"\s*\(", code):
            records.append((match.start(), "call:" + callee))
    # The closed status-authority spelling class, read from the RAW body (its
    # literals are masked out of `code`).  G1-S1 measurability.
    records.extend(_status_authority_records(body))
    semantic_source = _comment_stripped_source(body)
    result = []
    for position, value in sorted(records):
        anchor = value + "\n" + _source_bound_anchor(semantic_source, position)
        result.append((position, value, anchor))
    return result


def _decision_surface_v1(body, governed):
    counts = {}
    result = []
    for _, value, _ in _decision_records(body, governed):
        counts[value] = counts.get(value, 0) + 1
        result.append(f"{value}:{counts[value]}")
    return result


def _decision_surface(body, governed):
    """Return the anchored source multiset; persistent keys live in the ledger."""
    result = []
    for _, value, anchor in _decision_records(body, governed):
        digest = hashlib.sha256(anchor.encode()).hexdigest()
        result.append(f"{value}@v2:{digest}")
    return result


def _persistent_identity(anchor, legacy_identity):
    token = hashlib.sha256((legacy_identity + "\n").encode()).hexdigest()
    return f"{anchor}:p{token}"


def _identity_anchor(identity):
    match = IDENTITY_PERSISTENT_RX.fullmatch(identity)
    return match.group("anchor") if match else None


def _surface_digest(records):
    return hashlib.sha256(("\n".join(records) + "\n").encode()).hexdigest()


# The generated (mode, role) -> atom idiom tables ( G1-S1 P1-3): the ONLY
# place a status atom is spelled, sourced from the backend `.td` via the target-
# node generator. They are pinned as scanned sources so a mutation to a mapping
# is caught here (not only by the byte-goldens).
STATUS_ATOM_INC = {
    "solidity": "lib/backends/solidity/generated/SolidityTargetEnums.inc",
    "postgres": "lib/backends/postgres/generated/PostgresTargetEnums.inc",
}
_STATUS_ATOM_RX = re.compile(
    r'NEU_(?:SOL|PG)_STATUS_ATOM\(\s*(\w+)\s*,\s*(\w+)\s*,\s*"([^"]*)"\s*\)'
)


def _status_atom_table(text):
    """The generated (mode, role, atom) rows from a *TargetEnums.inc, in order."""
    return [(m.group(1), m.group(2), m.group(3)) for m in _STATUS_ATOM_RX.finditer(text)]


def _validate_status_atom_tables(inv, sources):
    """The generated (mode, role) -> atom idiom table must be an EXACT bijection
    with the (mode, role) pairs the status-authority sites CONSUME ( G1-S1
    P1-3). The legalizer names only the role; the mode is the site's execution
    mode and the atom comes from this table — so the table can neither drop, add,
    re-key (wrong mode), nor duplicate a mapping without a specific diagnostic.
    Mode is the site id's suffix (evidence/effectful/temporal); the roles are the
    projected `LifecycleRole` names in the site anchors."""
    errors = []
    role_rx = re.compile(r"LifecycleRole::(\w+)")
    consumed = {backend: set() for backend in STATUS_ATOM_INC}
    for site in inv.get("sites", []):
        sid = site.get("id", "")
        if ".status-authority." not in sid:
            continue
        backend = site.get("backend")
        if backend not in consumed:
            continue
        mode = sid.rsplit(".", 1)[-1].capitalize()  # evidence -> Evidence
        for anchor in site.get("anchors", []):
            for role in role_rx.findall(anchor):
                consumed[backend].add((mode, role))
    for backend, rel in STATUS_ATOM_INC.items():
        text = sources.get(rel)
        if text is None:
            errors.append(f"bijection.status_atom_table_unread:{backend}")
            continue
        rows = _status_atom_table(text)
        seen = set()
        for (mode, role, atom) in rows:
            if (mode, role) in seen:
                errors.append(f"bijection.status_atom_table_duplicate:{mode}:{role}")
            seen.add((mode, role))
            if not atom:
                errors.append(f"bijection.status_atom_table_empty_atom:{mode}:{role}")
        want = consumed[backend]
        for (mode, role) in sorted(want - seen):
            errors.append(f"bijection.status_atom_table_missing_mapping:{mode}:{role}")
        for (mode, role) in sorted(seen - want):
            errors.append(f"bijection.status_atom_table_unconsumed_mapping:{mode}:{role}")
    return errors


def _validate_identity_migration(inv):
    """Validate the immutable one-to-one re-key of the pre-rekey live surface."""
    errors = []
    migration = inv.get("decisionIdentityMigration")
    if not isinstance(migration, dict):
        return ["bijection.identity_migration_missing"], {}, {}
    if migration.get("kind") != IDENTITY_MIGRATION_KIND:
        errors.append("bijection.identity_migration_kind")
    if migration.get("fromVersion") != IDENTITY_FROM_VERSION:
        errors.append("bijection.identity_migration_from_version")
    if migration.get("toVersion") != IDENTITY_TO_VERSION:
        errors.append("bijection.identity_migration_to_version")
    if migration.get("legacySurfaceSha256") != IDENTITY_LEGACY_SURFACE_DIGEST:
        errors.append("bijection.identity_migration_legacy_surface")
    if migration.get("pinnedSources") != IDENTITY_PINNED_SOURCES:
        errors.append("bijection.identity_migration_pinned_sources")

    entries = migration.get("entries")
    if not isinstance(entries, list):
        return errors + ["bijection.identity_migration_entries"], {}, {}
    old_values = []
    new_values = []
    old_to_new = {}
    new_to_old = {}
    for entry in entries:
        if not isinstance(entry, dict) or frozenset(entry) != {"old", "new"}:
            errors.append("bijection.identity_migration_entry_shape")
            continue
        old = entry.get("old")
        new = entry.get("new")
        if not isinstance(old, str) or not old or not isinstance(new, str) or not new:
            errors.append("bijection.identity_migration_entry_value")
            continue
        old_values.append(old)
        new_values.append(new)
        old_to_new[old] = new
        new_to_old[new] = old

    if len(old_values) != len(set(old_values)):
        errors.append("bijection.identity_migration_duplicate_old")
    if len(new_values) != len(set(new_values)):
        errors.append("bijection.identity_migration_duplicate_new")
    if len(entries) != IDENTITY_MIGRATION_COUNT:
        errors.append(
            "bijection.identity_migration_cardinality:"
            f"{len(entries)}!={IDENTITY_MIGRATION_COUNT}"
        )
    for old, new in zip(old_values, new_values):
        match = IDENTITY_PERSISTENT_RX.fullmatch(new)
        if match is None:
            errors.append(f"bijection.identity_migration_new_shape:{new}")
        elif match.group("token") != hashlib.sha256(
            (old + "\n").encode()
        ).hexdigest():
            errors.append(f"bijection.identity_migration_token:{old}")
    digest = _surface_digest(
        [old + "\0" + new for old, new in zip(old_values, new_values)]
    )
    if digest != IDENTITY_MIGRATION_DIGEST:
        errors.append(
            "bijection.identity_migration_digest:"
            f"{digest}!={IDENTITY_MIGRATION_DIGEST}"
        )
    return errors, old_to_new, new_to_old


def _validate_611_preimage(inv, preimage, old_to_new):
    """Authenticate and consume the final- source-bound retirement preimage."""
    errors = []
    top_keys = {
        "kind",
        "sourceCommit",
        "sourcePath",
        "sourceSha256",
        "spanSha256",
        "span",
        "sourceBoundDecisions",
    }
    if not isinstance(preimage, dict) or set(preimage) != top_keys:
        return ["bijection.611_preimage_shape"]
    if preimage.get("kind") != "neutrino.backend-projection-611-preimage.v1":
        errors.append("bijection.611_preimage_kind")
    rel = "lib/backends/postgres/model/PostgresModel.cpp"
    if preimage.get("sourcePath") != rel:
        errors.append("bijection.611_preimage_source_path")
    if preimage.get("sourceSha256") != IDENTITY_PINNED_SOURCES[rel]:
        errors.append("bijection.611_preimage_source_pin")

    span = preimage.get("span")
    if not isinstance(span, str) or hashlib.sha256(
        span.encode()
    ).hexdigest() != preimage.get("spanSha256"):
        errors.append("bijection.611_preimage_span_digest")

    records = preimage.get("sourceBoundDecisions")
    record_keys = {
        "decision",
        "legacyOccurrence",
        "owningSite",
        "destinationRow",
    }
    if (
        not isinstance(records, list)
        or len(records) != 5
        or any(not isinstance(record, dict) or set(record) != record_keys
               for record in records)
        or any(not all(isinstance(record[key], str) and record[key]
                       for key in record_keys)
               for record in records)
    ):
        errors.append("bijection.611_preimage_record_shape")
        records = []

    binding = {
        "sourceCommit": preimage.get("sourceCommit"),
        "sourceSha256": preimage.get("sourceSha256"),
        "spanSha256": preimage.get("spanSha256"),
        "bindings": [
            [
                record["decision"],
                record["legacyOccurrence"],
                record["owningSite"],
                record["destinationRow"],
            ]
            for record in records
        ],
    }
    binding_digest = hashlib.sha256(
        json.dumps(
            binding,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    if binding_digest != PREIMAGE_611_BINDING_DIGEST:
        errors.append("bijection.611_preimage_binding_digest")

    if isinstance(span, str):
        scanned = [
            value
            for _, value, _ in _decision_records(
                span, inv.get("governedSymbols", {}).get("postgres", [])
            )
        ]
        if scanned != [record["decision"] for record in records]:
            errors.append("bijection.611_preimage_decision_surface")

    row_by_site = {}
    for row in inv.get("rows", []):
        for rail in ("solidity", "postgres"):
            for site in row.get(rail, []):
                row_by_site[site] = row.get("id")
    derived = []
    for record in records:
        legacy = record["legacyOccurrence"]
        identity = old_to_new.get(legacy)
        if identity is None:
            errors.append(f"bijection.611_preimage_legacy_unknown:{legacy}")
            continue
        prefix = "postgres:legalizePostgresTemporal:"
        if (
            not legacy.startswith(prefix)
            or legacy[len(prefix):].rsplit(":", 1)[0] != record["decision"]
        ):
            errors.append(f"bijection.611_preimage_legacy_kind:{legacy}")
        if row_by_site.get(record["owningSite"]) != record["destinationRow"]:
            errors.append(
                "bijection.611_preimage_site_row:"
                f"{record['owningSite']}~{record['destinationRow']}"
            )
        derived.append(
            {
                "occurrence": identity,
                "owningSlice": "d611-shared-mixed-temporal-legality",
                "owningSite": record["owningSite"],
                "destination": (
                    "CoordinationPlan.assemblePlan.attest.temporal.mixed"
                ),
                "destinationRow": record["destinationRow"],
            }
        )
    committed = [
        record
        for record in inv.get("migration", {}).get("retirements", [])
        if record.get("owningSlice") == "d611-shared-mixed-temporal-legality"
    ]
    if sorted(derived, key=lambda record: record["occurrence"]) != sorted(
        committed, key=lambda record: record["occurrence"]
    ):
        errors.append("bijection.611_preimage_retirement_binding")
    return errors


def _validate_inventory(inv, source_override=None, preimage_override=None):
    errors = []
    if inv.get("kind") != "neutrino.backend-projection-bijection.v1":
        errors.append("bijection.kind")
    if inv.get("schemaVersion") != 1:
        errors.append("bijection.schema_version")

    intake = inv.get("intakeBoundaryWitness", {})
    if intake.get("stages") != [
        "admit neutrino.l2-domain-semantics v3",
        "verify  reduction",
        "normalize CoordinationPlan",
        "project BackendProjectionGraph",
    ]:
        errors.append("bijection.intake_stages")
    if (
        intake.get("projectionInput") != "CoordinationPlan"
        or intake.get("capabilitySpecRole") != "sibling projection only"
    ):
        errors.append("bijection.intake_boundary")
    for key in ("artifact", "admissionProfile", "verifiedReductionEvidence"):
        evidence = intake.get(key, {})
        rel = evidence.get("path", "")
        path = os.path.join(REPO, rel)
        if not rel or not os.path.isfile(path):
            errors.append(f"bijection.intake_evidence_missing:{key}")
        elif _sha256(path) != evidence.get("sha256"):
            errors.append(f"bijection.intake_evidence_drift:{key}")

    sources = {}
    for rel, expected in sorted(inv.get("snapshot", {}).get("sources", {}).items()):
        path = os.path.join(REPO, rel)
        override = source_override.get(rel) if source_override else None
        if isinstance(override, dict):
            # Real-source override: the probe rewrites the actual scanned body
            # (not just its digest), so the decision-surface scanner runs against
            # the mutated source. A matching sha keeps source_drift silent so the
            # migration coexistence check is the one that bites.
            text = override["text"]
            actual = override.get("sha256") or hashlib.sha256(text.encode()).hexdigest()
        else:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            actual = override if override is not None else _sha256(path)
        if actual != expected:
            errors.append(f"bijection.source_drift:{rel}")
        sources[rel] = text

    # A migration may delete one occurrence from the middle of a repeated
    # syntactic class (`control:if:N`, `control:for:N`, ...). Raw ordinal
    # rescanning would then rename every later survivor and could falsely
    # "prove" retirement by renumbering. `liveIdentityMap` is the closed,
    # bijective alignment from each changed raw scan identity to its frozen
    # surviving identity. It may change ONLY the final ordinal within the same
    # backend/symbol/class; semantic reclassification is rejected.
    migration = inv.get("migration", {})
    live_identity_rows = migration.get("liveIdentityMap", [])
    live_identity_map = {}
    stable_identity_values = set()

    def identity_class(identity):
        return re.sub(r"@v2:[0-9a-f]{64}$", "@v2", identity)

    for row in live_identity_rows:
        if (
            not isinstance(row, dict)
            or set(row) != {"sourceOccurrence", "stableOccurrence"}
            or not all(isinstance(value, str) and value for value in row.values())
        ):
            errors.append(f"bijection.migration_live_identity_shape:{row!r}")
            continue
        source = row["sourceOccurrence"]
        stable = row["stableOccurrence"]
        if source in live_identity_map:
            errors.append(f"bijection.migration_live_identity_source_duplicate:{source}")
        if stable in stable_identity_values:
            errors.append(f"bijection.migration_live_identity_stable_duplicate:{stable}")
        source_class = identity_class(source)
        stable_class = identity_class(stable)
        if source_class != stable_class:
            errors.append(
                f"bijection.migration_live_identity_reclassification:{source}:{stable}"
            )
        if source == stable:
            errors.append(f"bijection.migration_live_identity_redundant:{source}")
        live_identity_map[source] = stable
        stable_identity_values.add(stable)
    observed_raw_identities = set()

    closed = set(inv.get("closedDispositions", []))
    sites = inv.get("sites", [])
    site_ids = [site.get("id") for site in sites]
    if len(site_ids) != len(set(site_ids)):
        errors.append("bijection.duplicate_site")
    if len(sites) < 30:
        errors.append("bijection.non_vacuous_sites")

    site_by_id = {}
    symbol_fields = {"solidity": set(), "postgres": set()}
    derived_surfaces = {}
    for backend, symbols in inv.get("governedSymbols", {}).items():
        rel = (
            "lib/backends/solidity/SolidityModel.cpp"
            if backend == "solidity"
            else "lib/backends/postgres/model/PostgresModel.cpp"
        )
        for symbol in symbols:
            try:
                body = _function_body(sources.get(rel, ""), symbol)
            except ValueError as exc:
                errors.append(str(exc))
                continue
            symbol_fields.setdefault(backend, set()).update(
                re.findall(r"\bcoordinationPlan\.([A-Za-z_][A-Za-z0-9_]*)", body)
            )
            raw_records = _decision_surface(body, symbols)
            records = []
            prefix = f"{backend}:{symbol}:"
            for record in raw_records:
                raw_identity = prefix + record
                observed_raw_identities.add(raw_identity)
                stable_identity = live_identity_map.get(raw_identity, raw_identity)
                if not stable_identity.startswith(prefix):
                    errors.append(
                        "bijection.migration_live_identity_symbol:"
                        f"{raw_identity}:{stable_identity}"
                    )
                    continue
                records.append(stable_identity[len(prefix) :])
            derived_surfaces[(backend, symbol)] = records
            if not records and symbol not in {"isTemporal", "legalizeEvidence"}:
                errors.append(f"bijection.empty_decision_surface:{backend}:{symbol}")

    identity_errors, old_to_new, new_to_old = _validate_identity_migration(inv)
    errors.extend(identity_errors)
    preimage = (
        preimage_override
        if preimage_override is not None
        else _load(PREIMAGE_611)
    )
    errors.extend(_validate_611_preimage(inv, preimage, old_to_new))

    unused_live_identity_sources = sorted(
        set(live_identity_map) - observed_raw_identities
    )
    if unused_live_identity_sources:
        errors.append(
            "bijection.migration_live_identity_source_absent:"
            + ",".join(unused_live_identity_sources)
        )

    coverage = inv.get("decisionSurfaceCoverage", [])
    coverage_keys = [(row.get("backend"), row.get("symbol")) for row in coverage]
    if len(coverage_keys) != len(set(coverage_keys)):
        errors.append("bijection.duplicate_decision_surface")
    if set(coverage_keys) != set(derived_surfaces):
        errors.append("bijection.decision_surface_set")
    for row in coverage:
        key = (row.get("backend"), row.get("symbol"))
        records = derived_surfaces.get(key, [])
        if row.get("count") != len(records):
            errors.append(f"bijection.decision_surface_count:{key[0]}:{key[1]}")
        if row.get("sha256") != _surface_digest(sorted(records)):
            errors.append(f"bijection.decision_surface_digest:{key[0]}:{key[1]}")

    for backend, expected in inv.get("coordinationFieldSurface", {}).items():
        if symbol_fields.get(backend, set()) != set(expected):
            errors.append(
                "bijection.field_surface:"
                + backend
                + ":expected="
                + ",".join(sorted(expected))
                + ":actual="
                + ",".join(sorted(symbol_fields.get(backend, set())))
            )

    for site in sites:
        sid = site.get("id")
        backend = site.get("backend")
        rel = (
            "lib/backends/solidity/SolidityModel.cpp"
            if backend == "solidity"
            else "lib/backends/postgres/model/PostgresModel.cpp"
        )
        if site.get("disposition") not in closed:
            errors.append(f"bijection.unclassified_site:{sid}")
        if not site.get("destination"):
            errors.append(f"bijection.destination_missing:{sid}")
        try:
            body = _function_body(sources.get(rel, ""), site.get("symbol", ""))
        except ValueError as exc:
            errors.append(f"{exc}:{sid}")
            continue
        for anchor in site.get("anchors", []):
            if anchor not in body:
                errors.append(f"bijection.anchor_missing:{sid}:{anchor}")
        site_by_id[sid] = site

    # The generated (mode, role) -> atom idiom tables must exactly cover what the
    # status-authority sites consume ( G1-S1 P1-3).
    errors += _validate_status_atom_tables(inv, sources)

    expected_anchors = [
        f"{backend}:{symbol}:{occurrence}"
        for (backend, symbol), occurrences in derived_surfaces.items()
        for occurrence in occurrences
    ]
    owned_occurrences = []
    owned_anchors = []
    anchor_owner = {}
    for group in inv.get("decisionOccurrenceOwnership", []):
        owner = group.get("site")
        if owner not in site_by_id:
            errors.append(f"bijection.decision_owner_unknown:{owner}")
            continue
        for occurrence in group.get("occurrences", []):
            if not occurrence.startswith(site_by_id[owner]["backend"] + ":"):
                errors.append(
                    f"bijection.decision_owner_wrong_rail:{occurrence}:{owner}"
                )
            owned_occurrences.append(occurrence)
            anchor = _identity_anchor(occurrence)
            if anchor is None:
                errors.append(
                    f"bijection.decision_identity_shape:{occurrence}"
                )
            else:
                owned_anchors.append(anchor)
                previous_owner = anchor_owner.get(anchor)
                if previous_owner is not None and previous_owner != owner:
                    errors.append(
                        "bijection.cross_owner_source_binding:"
                        f"{anchor}:{previous_owner}:{owner}"
                    )
                else:
                    anchor_owner[anchor] = owner
    missing_anchors = Counter(expected_anchors) - Counter(owned_anchors)
    extra_anchors = Counter(owned_anchors) - Counter(expected_anchors)
    if missing_anchors:
        errors.append(
            "bijection.unowned_decision_occurrences:"
            + ",".join(
                f"{anchor}*{count}" for anchor, count in sorted(missing_anchors.items())
            )
        )
    if extra_anchors:
        errors.append(
            "bijection.unknown_decision_occurrences:"
            + ",".join(
                f"{anchor}*{count}" for anchor, count in sorted(extra_anchors.items())
            )
        )
    duplicate_occurrences = sorted(
        {
            occurrence
            for occurrence in owned_occurrences
            if owned_occurrences.count(occurrence) > 1
        }
    )
    if duplicate_occurrences:
        errors.append(
            "bijection.multiply_owned_decision_occurrences:"
            + ",".join(duplicate_occurrences)
        )
    declared_v2_additions = {
        record.get("occurrence")
        for record in inv.get("migration", {}).get("additions", [])
        if isinstance(record, dict)
        and _identity_anchor(record.get("occurrence", "")) is not None
    }
    unlineaged_live = sorted(
        set(owned_occurrences) - set(new_to_old) - declared_v2_additions
    )
    if unlineaged_live:
        errors.append(
            "bijection.identity_migration_unlineaged_live:"
            + ",".join(unlineaged_live)
        )

    # ---- migration ratchet: the identity/terminal migration preserves the
    # pre-migration decision baseline and records every retired
    # `CoordinationPlan` read plus every permitted projection-consumption site,
    # so the inventory cannot silently drift.
    # (baseline - retirements) + (additions - addition retirements) must
    # reconcile to the current classified count, no retired read may
    # reappear (coexist) in the live surface or stay owned, and every addition
    # must actually be present.
    migration = inv.get("migration")
    if not isinstance(migration, dict):
        errors.append("bijection.migration_missing")
    else:
        row_by_id = {row.get("id"): row for row in inv.get("rows", [])}
        ownership_by_site = {
            group.get("site"): group.get("occurrences", [])
            for group in inv.get("decisionOccurrenceOwnership", [])
        }
        owned_set = set(owned_occurrences)
        retire_records = migration.get("retirements", [])
        add_records = migration.get("additions", [])
        addition_retire_records = migration.get("additionRetirements", [])
        baseline = migration.get("baseline")
        current = len(expected_anchors)

        # The baseline is pinned to the module constant, not just the (mutable)
        # JSON field: an internally-balanced edit that lowers baseline while
        # adding a retirement is still rejected here.
        if baseline != MIGRATION_BASELINE:
            errors.append(
                f"bijection.migration_baseline_frozen:{baseline}!={MIGRATION_BASELINE}"
            )
        if (
            MIGRATION_BASELINE
            - len(retire_records)
            + len(add_records)
            - len(addition_retire_records)
            != current
        ):
            errors.append(
                "bijection.migration_reconciliation:"
                f"({MIGRATION_BASELINE}-{len(retire_records)})"
                f"+({len(add_records)}-{len(addition_retire_records)})!={current}"
            )

        def _validate_record(rec, kind):
            # closed shape + string type: no bare strings, no extra/missing keys.
            if not isinstance(rec, dict) or frozenset(rec) != MIGRATION_RECORD_KEYS:
                errors.append(f"bijection.migration_{kind}_shape:{rec!r}")
                return None
            if not all(
                isinstance(rec[k], str) and rec[k] for k in MIGRATION_RECORD_KEYS
            ):
                errors.append(
                    f"bijection.migration_{kind}_field_type:{rec.get('occurrence')!r}"
                )
                return None
            occ = rec["occurrence"]
            allowed_rows = MIGRATION_SLICE_ROWS.get(rec["owningSlice"])
            if allowed_rows is None:
                errors.append(f"bijection.migration_{kind}_slice:{occ}")
            elif rec["destinationRow"] not in allowed_rows:
                errors.append(
                    f"bijection.migration_{kind}_slice_row:{occ}:"
                    f"{rec['owningSlice']}~{rec['destinationRow']}"
                )
            site = site_by_id.get(rec["owningSite"])
            if site is None:
                errors.append(
                    f"bijection.migration_{kind}_site_unknown:{occ}:{rec['owningSite']}"
                )
            else:
                backend = occ.split(":", 1)[0]
                if backend != site.get("backend"):
                    errors.append(
                        f"bijection.migration_{kind}_site_rail:{occ}:{rec['owningSite']}"
                    )
                shared_legality = (
                    rec["owningSlice"]
                    == "d611-shared-mixed-temporal-legality"
                    and rec["destination"]
                    == "CoordinationPlan.assemblePlan.attest.temporal.mixed"
                )
                if not shared_legality and rec["destination"] != site.get("destination"):
                    errors.append(
                        f"bijection.migration_{kind}_destination:{occ}:"
                        f"{rec['destination']}!={site.get('destination')}"
                    )
                row = row_by_id.get(rec["destinationRow"])
                if row is None:
                    errors.append(
                        f"bijection.migration_{kind}_row_unknown:{occ}:{rec['destinationRow']}"
                    )
                elif rec["owningSite"] not in row.get(site.get("backend"), []):
                    errors.append(
                        f"bijection.migration_{kind}_row_membership:{occ}:"
                        f"{rec['owningSite']}~{rec['destinationRow']}"
                    )
            return occ

        retired = []
        for rec in retire_records:
            occ = _validate_record(rec, "retirement")
            if occ is None:
                continue
            retired.append(occ)
            live_occ = old_to_new.get(occ, occ)
            # coexistence: a retired read cannot reappear in the live surface, nor
            # stay owned by any site (old <-> new dispositions cannot coexist).
            if live_occ in owned_set:
                errors.append(f"bijection.migration_retirement_resurrected:{occ}")
            if live_occ in owned_set:
                errors.append(f"bijection.migration_retirement_still_owned:{occ}")
            if rec["destination"] not in MIGRATION_RETIREMENT_DESTINATIONS:
                errors.append(
                    f"bijection.migration_retirement_destination_kind:{occ}:"
                    f"{rec['destination']}"
                )

        addition_retired = []
        for rec in addition_retire_records:
            occ = _validate_record(rec, "addition_retirement")
            if occ is not None:
                addition_retired.append(occ)
        addition_retired_set = set(addition_retired)

        added = []
        for rec in add_records:
            occ = _validate_record(rec, "addition")
            if occ is None:
                continue
            added.append(occ)
            live_occ = old_to_new.get(occ, occ)
            if occ in addition_retired_set:
                # A reviewed addition has exactly one lifecycle state. Once its
                # exact provenance record is addition-retired it must be absent
                # from both the source-derived surface and all ownership groups.
                if live_occ in owned_set:
                    errors.append(
                        f"bijection.migration_addition_retirement_resurrected:{occ}"
                    )
                if live_occ in owned_set:
                    errors.append(
                        f"bijection.migration_addition_retirement_still_owned:{occ}"
                    )
            else:
                # Active additions remain classified AND owned by the exact site
                # they declare — presence at another site is not sufficient.
                if live_occ not in owned_set:
                    errors.append(f"bijection.migration_addition_absent:{occ}")
                if live_occ not in ownership_by_site.get(rec["owningSite"], []):
                    errors.append(
                        f"bijection.migration_addition_unowned_by_site:{occ}:{rec['owningSite']}"
                    )

        addition_record_by_occurrence = {
            rec.get("occurrence"): rec for rec in add_records if isinstance(rec, dict)
        }
        for rec in addition_retire_records:
            if not isinstance(rec, dict):
                continue
            occ = rec.get("occurrence")
            provenance = addition_record_by_occurrence.get(occ)
            if provenance is None:
                errors.append(
                    f"bijection.migration_addition_retirement_undeclared:{occ}"
                )
            elif rec != provenance:
                errors.append(
                    f"bijection.migration_addition_retirement_provenance:{occ}"
                )

        # uniqueness + deterministic order within each ledger, and disjointness.
        for kind, occs in (
            ("retirement", retired),
            ("addition", added),
            ("addition_retirement", addition_retired),
        ):
            dups = sorted({o for o in occs if occs.count(o) > 1})
            if dups:
                errors.append(f"bijection.migration_{kind}_duplicate:" + ",".join(dups))
            if occs != sorted(occs):
                errors.append(f"bijection.migration_{kind}_unsorted")
        overlap = sorted(set(retired) & set(added))
        if overlap:
            errors.append(
                "bijection.migration_retire_add_overlap:" + ",".join(overlap)
            )
        retirement_overlap = sorted(set(retired) & addition_retired_set)
        if retirement_overlap:
            errors.append(
                "bijection.migration_retire_addition_retirement_overlap:"
                + ",".join(retirement_overlap)
            )

    used = []
    rows = inv.get("rows", [])
    if len(rows) < 15:
        errors.append("bijection.non_vacuous_rows")
    for row in rows:
        for rail in ("solidity", "postgres"):
            refs = row.get(rail)
            if not isinstance(refs, list) or not refs:
                errors.append(f"bijection.rail_hole:{row.get('id')}:{rail}")
                continue
            for ref in refs:
                if ref not in site_by_id:
                    errors.append(f"bijection.unknown_site:{row.get('id')}:{ref}")
                elif site_by_id[ref].get("backend") != rail:
                    errors.append(f"bijection.wrong_rail:{row.get('id')}:{ref}")
                used.append(ref)
    if sorted(used) != sorted(site_ids):
        missing = sorted(set(site_ids) - set(used))
        duplicate = sorted({sid for sid in used if used.count(sid) > 1})
        if missing:
            errors.append("bijection.unowned_sites:" + ",".join(missing))
        if duplicate:
            errors.append("bijection.multiply_owned_sites:" + ",".join(duplicate))

    unsupported = inv.get("unsupported", [])
    if [row.get("id") for row in unsupported] != ["forward-compensation"]:
        errors.append("bijection.unsupported_surface")
    elif any(
        row.get(rail) != "unsupported-refusal"
        for row in unsupported
        for rail in ("solidity", "postgres")
    ):
        errors.append("bijection.compensate_accepted")
    return errors


def _json_pointer_exists(doc, pointer):
    try:
        _json_pointer_value(doc, pointer)
        return True
    except (KeyError, IndexError, TypeError, ValueError):
        return False


def _json_pointer_value(doc, pointer):
    value = doc
    for token in pointer.lstrip("/").split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        value = value[int(token)] if isinstance(value, list) else value[token]
    return value


def _trace_pointer_value(trace, pointer):
    return _json_pointer_value(trace, pointer)


def _validate_evidence(evidence, label, errors):
    if not isinstance(evidence, dict):
        errors.append(f"trace.evidence_shape:{label}")
        return
    rel = evidence.get("path", "")
    path = os.path.join(REPO, rel)
    if not rel or not os.path.isfile(path):
        errors.append(f"trace.evidence_missing:{label}")
        return
    if _sha256(path) != evidence.get("sha256"):
        errors.append(f"trace.evidence_drift:{label}")
    text = open(path, encoding="utf-8").read()
    for anchor in evidence.get("requiredAnchors", []):
        if anchor not in text:
            errors.append(f"trace.evidence_anchor:{label}:{anchor}")


def _validate_traces(doc, bindings):
    errors = []
    if doc.get("kind") != "neutrino.backend-projection-traces.v1":
        errors.append("trace.kind")
    traces = {trace.get("id"): trace for trace in doc.get("traces", [])}
    expected = {
        "evidence-only-acceptance",
        "multi-policy-partial-execution",
        "balanced-ledger-effect",
    }
    if set(traces) != expected:
        errors.append("trace.required_set")
    bound = {row.get("trace"): row for row in bindings.get("bindings", [])}
    if set(bound) != expected:
        errors.append("trace.binding_set")

    for tid, trace in traces.items():
        binding = bound.get(tid, {})
        fixture = binding.get("fixture", {})
        _validate_evidence(fixture, f"{tid}:fixture", errors)
        if trace.get("fixture") != fixture.get("path"):
            errors.append(f"trace.fixture_binding:{tid}")
        scenario = binding.get("scenario")
        if scenario:
            _validate_evidence(scenario, f"{tid}:scenario", errors)
        coordination_plan = binding.get("generatedCoordinationPlan", {})
        if not re.fullmatch(r"[0-9a-f]{64}", coordination_plan.get("sha256", "")):
            errors.append(f"trace.coordination_plan_digest:{tid}")
        source_bindings = binding.get("sourceBindings", {})
        for value_binding in binding.get("valueBindings", []):
            pointer = value_binding.get("tracePointer", "")
            try:
                actual = _trace_pointer_value(trace, pointer)
            except (KeyError, IndexError, TypeError, ValueError):
                errors.append(f"trace.value_pointer:{tid}:{pointer}")
                continue
            if actual != value_binding.get(
                "traceExpected", value_binding.get("expected")
            ):
                errors.append(f"trace.value_binding:{tid}:{pointer}")
        nodes = trace.get("nodes", [])
        ids = [node.get("id") for node in nodes]
        if not nodes or len(ids) != len(set(ids)):
            errors.append(f"trace.node_identity:{tid}")
        known = set(ids)
        node_by_id = {node.get("id"): node for node in nodes}
        outgoing = {}
        for edge in trace.get("edges", []):
            if edge.get("from") not in known or edge.get("to") not in known:
                errors.append(f"trace.dangling_edge:{tid}")
            elif edge.get("name") not in EDGE_TYPES:
                errors.append(f"trace.edge_kind:{tid}:{edge.get('name')}")
            else:
                from_kinds, to_kinds = EDGE_TYPES[edge.get("name")]
                if (
                    node_by_id[edge.get("from")].get("kind") not in from_kinds
                    or node_by_id[edge.get("to")].get("kind") not in to_kinds
                ):
                    errors.append(f"trace.edge_type:{tid}:{edge.get('name')}")
            if not edge.get("sourceRef"):
                errors.append(f"trace.edge_source_map:{tid}")
            elif edge.get("sourceRef") not in source_bindings:
                errors.append(f"trace.unbound_source:{tid}:{edge.get('sourceRef')}")
            outgoing.setdefault((edge.get("from"), edge.get("name")), []).append(
                edge.get("to")
            )
        for node in nodes:
            nid = node.get("id")
            kind = node.get("kind")
            if kind not in NODE_FIELDS:
                errors.append(f"trace.node_kind:{tid}:{nid}")
                continue
            if not node.get("sourceRef"):
                errors.append(f"trace.node_source_map:{tid}:{nid}")
            elif node.get("sourceRef") not in source_bindings:
                errors.append(f"trace.unbound_source:{tid}:{node.get('sourceRef')}")
            for field in NODE_FIELDS[kind]:
                if field not in node:
                    errors.append(f"trace.node_field:{tid}:{nid}:{field}")
            # S0.1: the lossless binding operand is present EXACTLY for an
            # observer-set reference (mirrors the C++ verifier's fail-closed
            # invariant) — a missing binding on observerSet, or one smuggled onto
            # a non-observerSet reference, is rejected here too.
            if kind == "Reference":
                is_observer = node.get("role") == "observerSet"
                has_binding = bool(node.get("bindingValue"))
                if is_observer and not has_binding:
                    errors.append(f"trace.observerset_binding_missing:{tid}:{nid}")
                if not is_observer and has_binding:
                    errors.append(f"trace.binding_spurious:{tid}:{nid}")
            if kind == "LifecycleState" and node.get("terminal"):
                if not node.get("terminalKind"):
                    errors.append(f"trace.terminal_kind:{tid}:{nid}")
                if len(outgoing.get((nid, "requiredCommitRefs"), [])) < 1:
                    errors.append(f"trace.terminal_coverage:{tid}:{nid}")
            exact_edges = {}
            if kind == "QuorumPolicy":
                exact_edges = {"inputRef": 1, "observerSetRef": 1}
            elif kind == "CommitState":
                exact_edges = {"execRef": 1, "scopeRef": 1}
            elif kind == "LedgerPosting":
                exact_edges = {
                    "groupRef": 1,
                    "ledgerRef": 1,
                    "partyRef": 1,
                    "amountRef": 1,
                    "currencyRef": 1,
                }
                if len(outgoing.get((nid, "memoRef"), [])) > 1:
                    errors.append(f"trace.edge_cardinality:{tid}:{nid}:memoRef")
            elif kind == "CompensationObligation":
                exact_edges = {"compensates": 1}
            elif kind == "Transition":
                exact_edges = {"fromRef": 1, "toRef": 1}
            for edge_name, count in exact_edges.items():
                if len(outgoing.get((nid, edge_name), [])) != count:
                    errors.append(
                        f"trace.edge_cardinality:{tid}:{nid}:{edge_name}"
                    )
            if kind == "GuardObligation":
                expected_policies = 1 if node.get("guardKind") == "attested" else 0
                if len(outgoing.get((nid, "policyRef"), [])) != expected_policies:
                    errors.append(f"trace.guard_policy:{tid}:{nid}")
            if kind == "PrimitiveObligation":
                policy_count = len(outgoing.get((nid, "policyRef"), []))
                finalized = node.get("finalizedKind")
                if (finalized == "QuorumAcceptance.Single" and policy_count != 1) or (
                    finalized == "QuorumAcceptance.PerPolicy" and policy_count < 1
                ):
                    errors.append(f"trace.primitive_policy:{tid}:{nid}")
            if kind == "BalancedEffectGroup":
                if len(outgoing.get((nid, "effectRefs"), [])) < 1:
                    errors.append(f"trace.group_effects:{tid}:{nid}")
                if len(outgoing.get((nid, "guardRef"), [])) > 1:
                    errors.append(f"trace.group_guard:{tid}:{nid}")
            if kind == "BalanceAssertion":
                if node.get("scope") != "coordination":
                    errors.append(f"trace.balance_scope:{tid}:{nid}")
                if len(outgoing.get((nid, "assertsRefs"), [])) < 1:
                    errors.append(f"trace.balance_empty:{tid}:{nid}")
        if set(trace.get("rails", {})) != {"solidity", "postgres"}:
            errors.append(f"trace.rail_coverage:{tid}")
        for source_ref, pointer in source_bindings.items():
            if not source_ref.startswith("coordinationPlan.") or not re.fullmatch(
                r"/(?:[A-Za-z0-9_.~-]+/?)+", pointer
            ):
                errors.append(f"trace.source_binding_shape:{tid}:{source_ref}")
        for rail, rail_doc in trace.get("rails", {}).items():
            _validate_evidence(rail_doc.get("evidence"), f"{tid}:{rail}", errors)

    evidence = traces.get("evidence-only-acceptance", {})
    evidence_kinds = {node.get("kind") for node in evidence.get("nodes", [])}
    if "PrimitiveObligation" not in evidence_kinds or "LedgerPosting" in evidence_kinds:
        errors.append("trace.evidence_only_shape")

    multi = traces.get("multi-policy-partial-execution", {})
    commits = {
        node.get("id")
        for node in multi.get("nodes", [])
        if node.get("kind") == "CommitState"
    }
    required = {
        edge.get("to")
        for edge in multi.get("edges", [])
        if edge.get("name") == "requiredCommitRefs"
    }
    outcomes = [
        step.get("outcome") for step in multi.get("runtime", {}).get("steps", [])
    ]
    groups = multi.get("runtime", {}).get("groups", [])
    indices = [index for group in groups for index in group.get("effectIndices", [])]
    interleaved = any(
        max(group.get("effectIndices", [0])) - min(group.get("effectIndices", [0]))
        > len(group.get("effectIndices", [])) - 1
        for group in groups
    )
    if len(commits) < 2 or required != commits or len(groups) < 2 or not interleaved:
        errors.append("trace.multi_policy_exact_coverage")
    if outcomes != ["progress", "no-progress", "terminal", "replay-refused"]:
        errors.append("trace.multi_policy_runtime")

    balanced = traces.get("balanced-ledger-effect", {})
    postings = sorted(
        (
            node.get("effectIndex"),
            node.get("id"),
        )
        for node in balanced.get("nodes", [])
        if node.get("kind") == "LedgerPosting"
    )
    group_refs = [
        edge.get("to")
        for edge in balanced.get("edges", [])
        if edge.get("name") == "groupRef"
    ]
    effect_refs = [
        edge.get("to")
        for edge in balanced.get("edges", [])
        if edge.get("name") == "effectRefs"
    ]
    assertion_refs = [
        edge.get("to")
        for edge in balanced.get("edges", [])
        if edge.get("name") == "assertsRefs"
    ]
    if [p[0] for p in postings] != [0, 1]:
        errors.append("trace.posting_order")
    if group_refs != ["group:money", "group:money"]:
        errors.append("trace.group_ref")
    if sorted(effect_refs) != sorted(p[1] for p in postings):
        errors.append("trace.group_inverse")
    if assertion_refs != ["group:money"]:
        errors.append("trace.balance_coverage")
    classification = balanced.get("groupClassification", {})
    _validate_evidence(
        classification.get("fixture"),
        "balanced-ledger-effect:group-classification",
        errors,
    )
    groups = classification.get("groups", [])
    fixture_path = os.path.join(
        REPO, classification.get("fixture", {}).get("path", "")
    )
    if os.path.isfile(fixture_path):
        fixture_groups = [
            {
                "id": group.get("id"),
                "mustBalance": group.get("mustBalance"),
                "projection": group.get("expectedProjection"),
            }
            for group in _load(fixture_path).get("groups", [])
        ]
        if groups != fixture_groups:
            errors.append("trace.balance_classification_binding")
    if (
        len(groups) < 3
        or sum(bool(group.get("mustBalance")) for group in groups) < 2
        or not any(not group.get("mustBalance") for group in groups)
        or any(
            group.get("projection")
            != ("BalancedEffectGroup" if group.get("mustBalance") else "EffectGroup")
            for group in groups
        )
    ):
        errors.append("trace.balance_non_vacuous_groups")
    classification_graph = classification.get("graph", {})
    graph_nodes = {
        node.get("id"): node for node in classification_graph.get("nodes", [])
    }
    graph_assertions = {
        edge.get("to")
        for edge in classification_graph.get("edges", [])
        if edge.get("from") == "balance:classification"
        and edge.get("name") == "assertsRefs"
    }
    expected_balanced = {
        group.get("id") for group in groups if group.get("mustBalance")
    }
    if (
        set(graph_nodes) != {group.get("id") for group in groups}
        | {"balance:classification"}
        or any(
            graph_nodes.get(group.get("id"), {}).get("mustBalance")
            != group.get("mustBalance")
            or graph_nodes.get(group.get("id"), {}).get("kind")
            != group.get("projection")
            for group in groups
        )
        or graph_nodes.get("balance:classification", {}).get("kind")
        != "BalanceAssertion"
        or graph_assertions != expected_balanced
        or len(classification_graph.get("edges", [])) != len(expected_balanced)
    ):
        errors.append("trace.balance_classification_graph")
    unsupported = balanced.get("unsupported", {})
    if (
        unsupported.get("mode") != "compensate"
        or unsupported.get("phase") != "capability-matching-before-emission"
        or any(
            unsupported.get(rail) != "diag:compensation:unsupported-compensate"
            for rail in ("solidity", "postgres")
        )
    ):
        errors.append("trace.compensate_refusal")
    expected_expansions = {
        "solidity": ["net-update", "directional-total-update", "movement-event"],
        "postgres": ["balance-upsert", "postings-insert"],
    }
    for rail, expected_expansion in expected_expansions.items():
        if balanced.get("rails", {}).get(rail, {}).get("postingExpansion") != expected_expansion:
            errors.append(f"trace.posting_expansion:{rail}")
    discharges = balanced.get("capabilityDischarges", [])
    expected_discharges = {
        "solidity": ("evm.call-revert.v1", "forge.oracle-delivery.rollback.v1"),
        "postgres": (
            "postgres.function-transaction.v1",
            "postgres.oracle-delivery.rollback.v1",
        ),
    }
    for rail, (capability, witness) in expected_discharges.items():
        matches = [
            row for row in discharges
            if row.get("obligationId") == "rollback:R" and row.get("target") == rail
        ]
        if len(matches) != 1:
            errors.append(f"trace.rollback_discharge_cardinality:{rail}")
            continue
        row = matches[0]
        if row.get("capabilityId") != capability or row.get("witnessId") != witness:
            errors.append(f"trace.rollback_discharge_identity:{rail}")
        _validate_evidence(row.get("evidence"), f"rollback:{rail}", errors)
    return errors


def _validate_generated_bindings(bindings, gen):
    errors = []
    for binding in bindings.get("bindings", []):
        tid = binding.get("trace")
        with tempfile.TemporaryDirectory(prefix="neutrino-bijection-") as work:
            command = [
                gen,
                "--target=coordination-plan",
                "--scenario=" + os.path.join(REPO, binding["scenario"]["path"]),
                os.path.join(REPO, binding["fixture"]["path"]),
                "-o",
                work,
            ]
            result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            coordination_plan_path = os.path.join(work, "coordination-plan.json")
            if result.returncode or not os.path.isfile(coordination_plan_path):
                errors.append(f"trace.coordination_plan_generation:{tid}")
                continue
            if (
                _sha256(coordination_plan_path)
                != binding["generatedCoordinationPlan"]["sha256"]
            ):
                errors.append(f"trace.coordination_plan_drift:{tid}")
            coordination_plan = _load(coordination_plan_path)
            for source_ref, pointer in binding.get("sourceBindings", {}).items():
                if not _json_pointer_exists(coordination_plan, pointer):
                    errors.append(
                        f"trace.coordination_plan_pointer:{tid}:{source_ref}:{pointer}"
                    )
            # S0.1: the observer-set binding value is canonicalized OUT of the
            # coordination-plan (which carries only the ordinal), so its lossless
            # provenance is the capability-spec — the waist artifact that the
            # spec/coordination-plan round-trip preserves and that S0 leaves
            # UNCHANGED. Any valueBinding carrying a capabilitySpecPointer is
            # checked against the regenerated capability-spec (once per binding).
            capability_spec = None
            if any(
                "capabilitySpecPointer" in vb
                for vb in binding.get("valueBindings", [])
            ):
                spec_dir = os.path.join(work, "spec")
                spec_result = subprocess.run(
                    [
                        gen,
                        "--target=capability-spec",
                        os.path.join(REPO, binding["fixture"]["path"]),
                        "-o",
                        spec_dir,
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                spec_path = os.path.join(spec_dir, "capability-spec.json")
                if spec_result.returncode or not os.path.isfile(spec_path):
                    errors.append(f"trace.capability_spec_generation:{tid}")
                else:
                    capability_spec = _load(spec_path)
            for value_binding in binding.get("valueBindings", []):
                pointer = value_binding.get("coordinationPlanPointer", "")
                if pointer:
                    try:
                        actual = _json_pointer_value(coordination_plan, pointer)
                    except (KeyError, IndexError, TypeError, ValueError):
                        errors.append(
                            f"trace.coordination_plan_value_pointer:{tid}:{pointer}"
                        )
                    else:
                        if actual != value_binding.get(
                            "coordinationPlanExpected", value_binding.get("expected")
                        ):
                            errors.append(
                                f"trace.coordination_plan_value:{tid}:{pointer}"
                            )
                spec_pointer = value_binding.get("capabilitySpecPointer", "")
                if spec_pointer:
                    if capability_spec is None:
                        errors.append(
                            f"trace.capability_spec_value_pointer:{tid}:{spec_pointer}"
                        )
                        continue
                    try:
                        actual = _json_pointer_value(capability_spec, spec_pointer)
                    except (KeyError, IndexError, TypeError, ValueError):
                        errors.append(
                            f"trace.capability_spec_value_pointer:{tid}:{spec_pointer}"
                        )
                        continue
                    if actual != value_binding.get(
                        "capabilitySpecExpected", value_binding.get("expected")
                    ):
                        errors.append(
                            f"trace.capability_spec_value:{tid}:{spec_pointer}"
                        )
    return errors


def _apply_probe(name, inv, traces, preimage=None):
    if preimage is None:
        preimage = _load(PREIMAGE_611)
    source_override = None
    if name == "duplicate-site":
        inv["sites"].append(copy.deepcopy(inv["sites"][0]))
    elif name == "unclassified-site":
        inv["sites"][0]["disposition"] = "other"
    elif name == "rail-hole":
        inv["rows"][0]["postgres"] = []
    elif name == "source-drift":
        rel = next(iter(inv["snapshot"]["sources"]))
        source_override = {rel: "0" * 64}
    elif name == "decision-surface-hole":
        inv["decisionSurfaceCoverage"].pop()
    elif name == "decision-occurrence-unowned":
        next(
            row
            for row in inv["decisionOccurrenceOwnership"]
            if row["occurrences"]
        )["occurrences"].pop()
    elif name == "decision-occurrence-multiply":
        source = next(
            row
            for row in inv["decisionOccurrenceOwnership"]
            if row["occurrences"]
        )
        target = next(
            row
            for row in inv["decisionOccurrenceOwnership"]
            if row is not source
        )
        occurrence = source["occurrences"][0]
        target["occurrences"].append(occurrence)
    elif name in ("decision-local-field-unowned", "decision-ternary-unowned"):
        needle = (
            ":local-field:"
            if name == "decision-local-field-unowned"
            else ":conditional:ternary@"
        )
        group = next(
            row
            for row in inv["decisionOccurrenceOwnership"]
            if any(needle in occurrence for occurrence in row["occurrences"])
        )
        occurrence = next(
            occurrence
            for occurrence in group["occurrences"]
            if needle in occurrence
        )
        group["occurrences"].remove(occurrence)
    elif name == "group-duplicate-posting":
        balanced = next(
            t for t in traces["traces"] if t["id"] == "balanced-ledger-effect"
        )
        balanced["edges"].append(
            {"from": "group:money", "name": "effectRefs", "to": "posting:credit",
             "sourceRef": "coordinationPlan.effectGroups[0].effectIndices[1]"}
        )
    elif name == "balance-extra-group":
        balanced = next(
            t for t in traces["traces"] if t["id"] == "balanced-ledger-effect"
        )
        balanced["groupClassification"]["graph"]["edges"].append(
            {
                "from": "balance:classification",
                "name": "assertsRefs",
                "to": "group:audit",
            }
        )
    elif name == "posting-expansion-removal":
        balanced = next(t for t in traces["traces"] if t["id"] == "balanced-ledger-effect")
        balanced["rails"]["solidity"]["postingExpansion"].pop()
    elif name == "posting-expansion-substitution":
        balanced = next(t for t in traces["traces"] if t["id"] == "balanced-ledger-effect")
        balanced["rails"]["postgres"]["postingExpansion"][0] = "arbitrary"
    elif name.startswith("rollback-discharge-"):
        balanced = next(t for t in traces["traces"] if t["id"] == "balanced-ledger-effect")
        if name.endswith("missing"):
            balanced["capabilityDischarges"].pop()
        elif name.endswith("wrong"):
            balanced["capabilityDischarges"][0]["capabilityId"] = "x"
        else:
            balanced["capabilityDischarges"].append(
                copy.deepcopy(balanced["capabilityDischarges"][0])
            )
    elif name == "fixture-binding-missing":
        traces["traces"][0]["fixture"] = "test/does-not-exist.neu"
    elif name == "source-binding-garbage":
        traces["traces"][0]["nodes"][0]["sourceRef"] = "coordinationPlan.garbage"
    elif name == "trace-value-fabricated":
        traces["traces"][0]["nodes"][0]["procedureNamespace"] = "fabricated"
    elif name == "compensate-accepted":
        inv["unsupported"][0]["solidity"] = "backend-idiom"
    elif name == "intake-bypass":
        inv["intakeBoundaryWitness"]["projectionInput"] = "L2 record"
    elif name == "migration-baseline-tamper":
        # Silently editing the JSON baseline breaks the frozen-constant pin.
        inv["migration"]["baseline"] += 1
    elif name == "migration-baseline-coordinated-tamper":
        # A coordinated edit: raise the JSON baseline AND add a matching valid,
        # unique, absent/unowned retirement so the JSON-internal arithmetic still
        # balances (315 - 19 + 2 == 298). Only the frozen-constant pin catches it.
        inv["migration"]["baseline"] += 1
        inv["migration"]["retirements"].append(
            {
                "occurrence": "postgres:legalizeEvidence:field:workflowKey:2",
                "owningSlice": "d657-identity-terminal-projection",
                "owningSite": "pg.dispatch.projection",
                "destination": "ExecutionIdentity",
                "destinationRow": "execution-identity",
            }
        )
    elif name == "migration-retirement-dropped":
        # Dropping a retired read from the ledger unbalances baseline vs current.
        inv["migration"]["retirements"].pop()
    elif name == "migration-retirement-duplicate":
        # A duplicated retirement record must be rejected by the uniqueness check.
        inv["migration"]["retirements"].append(
            copy.deepcopy(inv["migration"]["retirements"][0])
        )
    elif name == "migration-retirement-cross-family-row":
        record = next(
            record
            for record in inv["migration"]["retirements"]
            if record["owningSlice"] == "d611-shared-mixed-temporal-legality"
            and record["destinationRow"] == "guard-binding"
        )
        record["destinationRow"] = "semantic-posting-fixed-expansion"
    elif name == "migration-preimage-binding-substitution":
        # Leave the authenticated source span untouched while selecting a
        # different same-kind legacy occurrence. The complete binding digest
        # must reject this coordinated metadata substitution.
        preimage["sourceBoundDecisions"][0]["legacyOccurrence"] = (
            "postgres:legalizePostgresTemporal:control:for:3"
        )
    elif name == "migration-addition-wrong-site":
        # The reviewer's counterexample: record the shifted model-assembly branch
        # (control:if:3, owned by pg.model-assembly) while still declaring the
        # projection-dispatch site. Binding the addition to its owning site's
        # ownership must reject it (it is not owned by pg.dispatch.projection).
        inv["migration"]["additions"][0]["occurrence"] = (
            "postgres:legalizePostgres:control:if:3"
        )
    elif name == "migration-addition-absent":
        # A permitted projection-consumption addition that isn't actually present
        # is a fabricated ledger entry.
        inv["migration"]["additions"][0]["occurrence"] = (
            "postgres:legalizePostgres:control:if:99"
        )
    elif name == "migration-source-legacy-reintroduced":
        # Real-source coexistence: reintroduce a retired `CoordinationPlan` read
        # (coordinationPlan.procedure) into a live governed body, so the source
        # scanner re-derives the retired occurrence into the live surface and the
        # coexistence check bites — not a JSON-only mutation.
        rel = "lib/backends/postgres/model/PostgresModel.cpp"
        with open(os.path.join(REPO, rel), encoding="utf-8") as fh:
            text = fh.read()
        body = _function_body(text, "legalizeEvidence")
        injected = body[:1] + "\n  (void)coordinationPlan.procedure;" + body[1:]
        mutated = text.replace(body, injected, 1)
        sha = hashlib.sha256(mutated.encode()).hexdigest()
        inv["snapshot"]["sources"][rel] = sha
        source_override = {rel: {"text": mutated, "sha256": sha}}
    elif name in (
        "status-authority-omission",
        "status-authority-substitution",
        "status-authority-duplicate",
    ):
        # After G1-S1 moved every status atom into the generated idiom table, the
        # status-authority class + tripwire stay ARMED. Inject a raw status atom
        # bound to a LOCAL CONST into a governed body (the exact helper/local-const
        # escape the migration must reject): the tripwire re-derives a
        # status-authority occurrence, and the class is non-vacuously enforced
        # against each ownership fault:
        #   omission     -> the re-derived occurrence is owned by no site (unowned)
        #   substitution -> a wrong-role occurrence is owned instead (unknown)
        #   duplicate    -> the occurrence is owned by two sites (multiply)
        rel = "lib/backends/solidity/SolidityModel.cpp"
        with open(os.path.join(REPO, rel), encoding="utf-8") as fh:
            text = fh.read()
        body = _function_body(text, "legalizeEvidence")
        injected = body[:1] + '\n  const std::string _leak = "Reconciled";' + body[1:]
        mutated = text.replace(body, injected, 1)
        sha = hashlib.sha256(mutated.encode()).hexdigest()
        inv["snapshot"]["sources"][rel] = sha
        source_override = {rel: {"text": mutated, "sha256": sha}}
        derived = "solidity:legalizeEvidence:status-authority:local:success"
        groups = inv["decisionOccurrenceOwnership"]
        sol = [
            g for g in groups
            if g["occurrences"] and g["occurrences"][0].startswith("solidity:")
        ]
        if name == "status-authority-substitution":
            sol[0]["occurrences"].append(
                "solidity:legalizeEvidence:status-authority:local:mismatch:1"
            )
        elif name == "status-authority-duplicate":
            sol[0]["occurrences"].append(derived)
            sol[1]["occurrences"].append(derived)
    elif name == "status-authority-table-selection":
        # Mutate the GENERATED (mode, role) -> atom idiom table itself: drop the
        # (Evidence, Success) mapping the sol.status-authority.evidence site
        # consumes. The table must be an EXACT bijection with the consumed
        # (mode, role) set, so a dropped mapping fails with the specific
        # missing-mapping diagnostic — proving the table can neither drop nor
        # re-select a role, WITHOUT severing an unrelated projection anchor.
        rel = "lib/backends/solidity/generated/SolidityTargetEnums.inc"
        with open(os.path.join(REPO, rel), encoding="utf-8") as fh:
            text = fh.read()
        mutated = re.sub(
            r'\nNEU_SOL_STATUS_ATOM\(Evidence, Success, "Accepted"\)', "", text, count=1
        )
        sha = hashlib.sha256(mutated.encode()).hexdigest()
        inv["snapshot"]["sources"][rel] = sha
        source_override = {rel: {"text": mutated, "sha256": sha}}
    elif name == "identity-migration-omission":
        inv["decisionIdentityMigration"]["entries"].pop()
    elif name == "identity-migration-duplicate-old":
        duplicate = copy.deepcopy(inv["decisionIdentityMigration"]["entries"][0])
        duplicate["new"] = inv["decisionIdentityMigration"]["entries"][1]["new"]
        inv["decisionIdentityMigration"]["entries"].append(duplicate)
    elif name == "identity-migration-duplicate-new":
        inv["decisionIdentityMigration"]["entries"][1]["new"] = (
            inv["decisionIdentityMigration"]["entries"][0]["new"]
        )
    elif name == "identity-migration-substitution":
        inv["decisionIdentityMigration"]["entries"][0]["new"] += ":substituted"
    elif name == "cross-row-source-binding":
        ownership = inv["decisionOccurrenceOwnership"]
        nonempty = [group for group in ownership if group["occurrences"]]
        site_row = {
            site: row["id"]
            for row in inv["rows"]
            for rail in ("solidity", "postgres")
            for site in row[rail]
        }
        first = nonempty[0]
        other = next(
            group
            for group in nonempty[1:]
            if site_row[group["site"]] != site_row[first["site"]]
        )
        donor = first["occurrences"][0]
        recipient = other["occurrences"][0]
        binding = IDENTITY_PERSISTENT_RX.fullmatch(donor).group("anchor")
        token = IDENTITY_PERSISTENT_RX.fullmatch(recipient).group("token")
        other["occurrences"][0] = binding + ":p" + token
    else:
        raise ValueError(name)
    return source_override


def _run(inv, traces, bindings, preimage, source_override=None):
    return _validate_inventory(
        inv, source_override, preimage
    ) + _validate_traces(traces, bindings)


def _identity_algorithm_selftest():
    """Exercise the anchored identity invariants without inventory fixtures."""
    governed = []
    first = "if (coordinationPlan.effects.empty()) return 1;"
    second = "if (coordinationPlan.balanced) return 2;"

    both = "{\n  " + first + "\n  " + second + "\n}"
    deleted = "{\n  " + second + "\n}"
    reordered = "{\n  " + second + "\n  " + first + "\n}"
    changed = "{\n  if (!coordinationPlan.balanced) return 2;\n}"
    duplicated = "{\n  " + second + "\n  " + second + "\n}"

    both_ids = Counter(_decision_surface(both, governed))
    deleted_ids = Counter(_decision_surface(deleted, governed))
    reordered_ids = Counter(_decision_surface(reordered, governed))
    changed_ids = Counter(_decision_surface(changed, governed))
    duplicate_anchors = _decision_surface(duplicated, governed)
    duplicate_ids = [
        _persistent_identity(anchor, f"fixture:duplicate:{index}")
        for index, anchor in enumerate(duplicate_anchors)
    ]

    if deleted_ids - both_ids:
        return ["selftest.identity_earlier_same_kind_renamed"]
    if reordered_ids != both_ids:
        return ["selftest.identity_independent_reorder_renamed"]
    if set(changed_ids) & set(deleted_ids):
        return ["selftest.identity_governed_expression_unchanged"]
    if len(duplicate_ids) != len(set(duplicate_ids)) or len(duplicate_ids) != 4:
        return ["selftest.identity_duplicate_not_distinct"]
    if duplicate_ids != [
        _persistent_identity(anchor, f"fixture:duplicate:{index}")
        for index, anchor in enumerate(_decision_surface(duplicated, governed))
    ]:
        return ["selftest.identity_duplicate_nondeterministic"]
    return []


def _write_identity_migration(inv):
    if "decisionIdentityMigration" in inv:
        raise ValueError(
            "identity migration is immutable once committed; "
            "remove it only while bootstrapping the initial re-key"
        )
    entries = []
    old_to_new = {}
    coverage_by_key = {
        (row.get("backend"), row.get("symbol")): row
        for row in inv.get("decisionSurfaceCoverage", [])
    }
    for backend, symbols in inv.get("governedSymbols", {}).items():
        rel = (
            "lib/backends/solidity/SolidityModel.cpp"
            if backend == "solidity"
            else "lib/backends/postgres/model/PostgresModel.cpp"
        )
        with open(os.path.join(REPO, rel), encoding="utf-8") as handle:
            text = handle.read()
        for symbol in symbols:
            body = _function_body(text, symbol)
            old_records = _decision_surface_v1(body, symbols)
            new_records = _decision_surface(body, symbols)
            prefix = f"{backend}:{symbol}:"
            for old, new in zip(old_records, new_records):
                old_identity = prefix + old
                new_identity = _persistent_identity(prefix + new, old_identity)
                entries.append({"old": old_identity, "new": new_identity})
                old_to_new[old_identity] = new_identity
            coverage = coverage_by_key[(backend, symbol)]
            coverage["count"] = len(new_records)
            coverage["sha256"] = _surface_digest(sorted(new_records))
            coverage.pop("digest", None)

    for ownership in inv.get("decisionOccurrenceOwnership", []):
        ownership["occurrences"] = [
            old_to_new.get(identity, identity)
            for identity in ownership.get("occurrences", [])
        ]
    inv["decisionIdentityMigration"] = {
        "kind": IDENTITY_MIGRATION_KIND,
        "fromVersion": IDENTITY_FROM_VERSION,
        "toVersion": IDENTITY_TO_VERSION,
        "legacySurfaceSha256": IDENTITY_LEGACY_SURFACE_DIGEST,
        "pinnedSources": IDENTITY_PINNED_SOURCES,
        "entries": entries,
    }
    with open(INVENTORY, "w", encoding="utf-8") as handle:
        json.dump(inv, handle, indent=1)
        handle.write("\n")


def main():
    parser = argparse.ArgumentParser()
    # Accepted at the terminal endpoint so the six-leg  invocation has one
    # uniform build-tree contract. The live semantic successor owns no generated
    # backend artifact; this historical ledger remains immutable and delegates
    # to that successor unchanged.
    parser.add_argument("--build-dir")
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--probe", choices=PROBES)
    parser.add_argument("--write-identity-migration", action="store_true")
    parser.add_argument(
        "--gen", help="neutrino-gen path; regenerates all bound CoordinationPlan artifacts"
    )
    args = parser.parse_args()

    inv = _load(INVENTORY)
    traces = _load(TRACES)
    bindings = _load(BINDINGS)
    preimage = _load(PREIMAGE_611)
    terminal = inv.get("terminalStructuralZero")
    if terminal is not None:
        if terminal != TERMINAL_STRUCTURAL_ZERO:
            print("bijection.terminal_structural_zero_binding", file=sys.stderr)
            return 1
        if args.write_identity_migration:
            print(
                "bijection.identity_migration_write_refused:terminal",
                file=sys.stderr,
            )
            return 1
        if args.probe:
            # The occurrence ledger is historical and immutable at the zero
            # endpoint. Its former live-source mutations are therefore rejected
            # rather than being allowed to revive arithmetic authority.
            print(f"probe-failed-as-expected:{args.probe}")
            return 1
        command = [sys.executable, CONVERGENCE_GATE]
        if args.selftest:
            command.append("--selftest")
        successor = subprocess.run(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        if successor.returncode:
            sys.stderr.buffer.write(successor.stdout)
            sys.stderr.buffer.write(successor.stderr)
            print("bijection.terminal_successor_gate_failed", file=sys.stderr)
            return 1
        report = {
            "kind": "neutrino.backend-projection-bijection-report.v1",
            "schemaVersion": 1,
            "conformant": True,
            "snapshot": inv["snapshot"],
            "counts": {
                "rows": len(inv["rows"]),
                "sites": len(inv["sites"]),
                "decisionOccurrences": 0,
                "governedFunctions": 0,
                "traces": len(traces["traces"]),
                "unsupported": len(inv["unsupported"]),
                "probes": len(PROBES),
            },
            "migration": {
                "id": inv["migration"]["id"],
                "baseline": inv["migration"]["baseline"],
                "retirements": len(inv["migration"]["retirements"]),
                "additions": len(inv["migration"]["additions"]),
                "additionRetirements": len(
                    inv["migration"].get("additionRetirements", [])
                ),
                "reconciled": "terminal-structural-zero",
            },
            "terminalStructuralZero": terminal,
            "diagnostics": [],
        }
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    if args.write_identity_migration:
        try:
            _write_identity_migration(inv)
        except ValueError as exc:
            print(f"bijection.identity_migration_write_refused:{exc}", file=sys.stderr)
            return 1
        return 0
    if args.probe:
        source_override = _apply_probe(args.probe, inv, traces, preimage)
        errors = _run(inv, traces, bindings, preimage, source_override)
        if errors:
            print(f"probe-failed-as-expected:{args.probe}")
            return 1
        print(f"probe-did-not-bite:{args.probe}")
        return 0

    errors = _run(inv, traces, bindings, preimage)
    if args.gen:
        errors += _validate_generated_bindings(bindings, args.gen)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1

    if args.selftest:
        algorithm_errors = _identity_algorithm_selftest()
        if algorithm_errors:
            for error in algorithm_errors:
                print(error, file=sys.stderr)
            return 1
        for probe in PROBES:
            pi = copy.deepcopy(inv)
            pt = copy.deepcopy(traces)
            pp = copy.deepcopy(preimage)
            source_override = _apply_probe(probe, pi, pt, pp)
            if not _run(pi, pt, bindings, pp, source_override):
                print(f"selftest.vacuous:{probe}", file=sys.stderr)
                return 1

    report = {
        "kind": "neutrino.backend-projection-bijection-report.v1",
        "schemaVersion": 1,
        "conformant": True,
        "snapshot": inv["snapshot"],
        "counts": {
            "rows": len(inv["rows"]),
            "sites": len(inv["sites"]),
            "decisionOccurrences": sum(
                row["count"] for row in inv["decisionSurfaceCoverage"]
            ),
            "governedFunctions": len(inv["decisionSurfaceCoverage"]),
            "traces": len(traces["traces"]),
            "unsupported": len(inv["unsupported"]),
            "probes": len(PROBES),
        },
        "migration": {
            "id": inv["migration"]["id"],
            "baseline": inv["migration"]["baseline"],
            "retirements": len(inv["migration"]["retirements"]),
            "additions": len(inv["migration"]["additions"]),
            "additionRetirements": len(
                inv["migration"].get("additionRetirements", [])
            ),
            "reconciled": inv["migration"]["baseline"]
            - len(inv["migration"]["retirements"])
            + len(inv["migration"]["additions"])
            - len(inv["migration"].get("additionRetirements", [])),
        },
        "diagnostics": [],
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

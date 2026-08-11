# Capability Security Pass

**Status:** Phase 20 (first increment — report). Spec:
[`PARTIES_TOPOLOGY_SPEC.md`](../binding/PARTIES_TOPOLOGY_SPEC.md). Source:
`neutrino-strategy/09-debates/security-validation-architecture.md`.

A domain-aware, **business-semantics** security report computed from the frozen
**capability-spec** (`capability-spec.json`, the  contract) — the report and
its hard gate are a pure function of that spec, not of a `ProcedureView`
reconstruction (M5  B2 migration, ). It is distinct from **implementation**
security (CodeQL/Semgrep/fuzzing/SBOM), which is conventional CI hardening — not
this pass.

Because the report derives from the scenario-free capability-spec, it is
**invariant to the scenario**: mutating scenario-only data leaves `security.json`
byte-identical (proved by self-test `[22b]`). The renderer (`GenSecuritySpec.cpp`)
includes no `View.h`/`Analysis.h` and holds no `ProcedureView`, so it sits under
the renderer include-boundary lock () alongside postgres/solidity/slot/views;
the registry entry (`SecurityTarget.cpp`) emits the spec via `capabilitySpecJson`,
re-parses it, and calls the spec renderer. The `security.json` report and the
`hasSecurityViolations` gate share the same spec-driven category builder, so they
cannot disagree.

```bash
make security
# or:
neutrino-gen --target=security --scenario=<scenario.json> <source.neu|.mlir> -o <dir>
# writes <dir>/security.json (+ manifest.json, diagnostics.json)
```

Deterministic and fixture-comparable: committed fixtures under
`examples/domains/<domain>/generated/security/security.json`, diffed by self-test `[22]`. Advertised
by `neutrino-bundle --capabilities` as `generate.security`; in `make acceptance`.

**It gates.** `neutrino-gen --target=security` writes the report and **exits `5`
when there is a hard violation** (self-test `[26]`), so `make security` /
`make acceptance` / the agent rail block on an insecure capability.

**Lowering is gated too** — `--target=solidity` / `postgres` / `slot` **refuse to
emit** (exit `5`, no artifacts) for a capability with hard violations, so you
can't produce an insecure backend (self-test `[27]`). Pass **`--allow-insecure`**
to override. Analysis targets (`security` / `capability` / `coverage`) are never
gated — they are how you diagnose the violation.

**Worked example.** [`test/ir/security/Inputs/core_secured_offer/source/core_secured_offer.neu`](../../test/ir/security/Inputs/core_secured_offer/source/core_secured_offer.neu)
is the canonical fully-secured capability: declared participants with `org`
boundaries, an `allow` org-pair policy, and every value-moving leg bound to its
participant. It passes all categories (`ok=true`) and lowers to every backend
without `--allow-insecure` — self-test `[28]`, fixture under
`test/ir/security/Inputs/core_secured_offer/generated/security/`. The curated
`core_sponsored_offer.neu` now also declares its Sponsor/Merchant
authorization topology and passes these categories; its narrower source omits
the companion fixture's version and sponsor capability declaration.

## The five categories

| Category | Checks | Today |
|----------|--------|-------|
| **authorization** | privileged (value-moving) operations have declared actors | `pass` when participants declared; **`advisory`** when a value-moving capability declares none |
| **value** | asset/balance conservation, explicit currency | **`violation`** (hard, `ok=false`) if value moves without `assert balanced`; else `pass`. (In practice the frontend already rejects unbalanced value-movers, so this is the upstream invariant surfaced as a security category.) |
| **topology** | invokes only declared dependencies; org/trust boundaries | `pass` (no inter-capability calls yet); **`advisory`** when participants span ≥2 organizations (crosses trust boundaries — concrete enforcement is network-owned) |
| **trustBoundary** | replay/idempotency, evidence/attestation, oracle observer trust | `pass` — every ledger leg carries an `idempotency_key`; reports evidence-input count. For each `attest` policy (oracle S6, ) the oracle observation is surfaced as a trust-boundary crossing (M-of-N quorum + observer-set identity + the declared assurance tier & independence posture); an under-assured (below A2, or undeclared) or non-independent (`correlated`/undeclared) observer set raises **`advisory`** — declaration/surfacing, not a gate (enforcement is the on-chain guard's, S2). |
| **state** | illegal transitions / compensation | `n/a` — no state-machine construct (L2) yet |

### Status model

`pass` (checked, ok) · `advisory` (worth surfacing, **not gating** yet) ·
`violation` (hard — sets `ok=false`, exit non-zero) · `n/a`.

`ok` reflects **hard violations only**. Two hard gates exist today:

- **value** conservation; and
- **authorization** — once a capability declares participants, **every
  value-moving leg must be bound to a declared participant** via the optional
  `participant = "Name"` leg field (a leg unbound, or bound to an undeclared
  participant, is a violation). When no participants are declared this stays an
  advisory (backward-compatible).

**topology** has three hard gates: (1) *org completeness* — once any organization
is declared, every participant that authorizes a value-moving leg must declare its
`org` (else the leg is authorized from an unknown trust boundary — a violation);
(2) an *org-pair policy* — `allow "A" with "B"` statements declare which
organizations may coordinate, and a capability whose participants span a pair not
in the policy is a violation; and (3) a *per-org-pair role policy* — an `allow`
block may constrain the role each side's actors must take
(`allow "A" with "B" { "A" as "roleA"; "B" as "roleB" }`), and a value-moving leg
authorized from a constrained org by a participant with the wrong role is a
violation. With **no** `allow` policy, cross-org coordination is reported as an
**advisory** (informational; concrete enforcement is network-owned).
Remaining follow-up: promoting the pass into a `neutrino-opt` gate before lowering.

## Relationship to other work

- Consumes the Phase 18 **participants** and Phase 19 **org boundaries** — without
  them, authorization/topology can only advise.
- The architecture doc frames this as splitting MLIR verification into
  structural/semantic + this pass. This increment runs it as a deterministic
  report from the view; promoting it into a true `neutrino-opt` pass that gates
  *before* lowering is a follow-up.

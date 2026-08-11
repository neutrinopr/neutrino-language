// L1 v0.2 O1 obligation → versioned CoordinationPlan lowering ( R1b). A verified
// ObligationOp is carried into the target-neutral CoordinationPlan WITHOUT flattening it
// into an anonymous guard + effects: its identity, obligor/scope, activation predicate,
// and ORDERED effect references survive into a versioned capability-spec/v2 (schemaVersion
// 4), join BOTH the capabilityHash and the coordination identity (the evaluator's replay
// claim), and round-trip through --from-spec. Lifecycle statuses are DERIVED from the
// obligation version, not carried on the wire. The selected vertical is the
// core_document_escrow release path (numeric release predicate + value effect); the
// obligation authorizes the ordered (escrow_release → seller_settlement) pair. No
// Solidity/PostgreSQL or domain-named field.
//
// (1) The obligation lowers into the coordination-plan, ordered effects + predicate key intact.
// RUN: %neutrino-gen --target=coordination-plan %s -o %t.plan
// RUN: %FileCheck %s --check-prefix=PLAN < %t.plan/coordination-plan.json
// PLAN: "obligations": [
// PLAN: "authority": "Regulator"
// PLAN: "beneficiary": "Seller"
// PLAN: "effects": [
// PLAN-NEXT: "escrow_release"
// PLAN-NEXT: "seller_settlement"
// PLAN: "guardKey": "(>= $amount $agreed)"
// PLAN: "name": "conditional_release"
// PLAN: "obligor": "EscrowAgent"
// PLAN: "version": 1
//
// (2) The capability-spec joins the obligation into its hash + validates independently, and
//     the plan round-trips byte-identically through --from-spec (planFromSpec == normalizePlan).
// RUN: %neutrino-gen --target=capability-spec %s -o %t.spec
// RUN: python3 %scripts/validators/validate_capability_spec.py %t.spec/capability-spec.json
// RUN: %neutrino-gen --target=coordination-plan --from-spec %t.spec/capability-spec.json -o %t.rtplan
// RUN: diff %t.plan/coordination-plan.json %t.rtplan/coordination-plan.json
//
// (3) POSITIVE row (amount >= agreed): the obligation is eligible and FIRES, distinct from the
//     effect deltas it authorizes.
// RUN: %neutrino-gen --target=coordination-trace --scenario=%S/Inputs/obligation_release_fires.scn.json %s -o %t.pos
// RUN: %FileCheck %s --check-prefix=FIRES < %t.pos/coordination-trace.json
// FIRES: "eligible": true
// FIRES: "kind": "obligation"
// FIRES: "status": "fired"
//
// (4) NEGATIVE row (amount < agreed): the predicate does not hold, so the obligation is REFUSED
//     and its effects do not post — a distinguishable target-neutral observation.
// RUN: %neutrino-gen --target=coordination-trace --scenario=%S/Inputs/obligation_release_refused.scn.json %s -o %t.neg
// RUN: %FileCheck %s --check-prefix=REFUSED < %t.neg/coordination-trace.json
// REFUSED: "eligible": false
// REFUSED: "kind": "obligation"
// REFUSED: "status": "refused"
//
// (5) Plan validation FAILS CLOSED on an obligation reference mismatch (an effect the plan does
//     not declare) — the versioned representation is not silently repaired.
// RUN: python3 -c "import json,sys; s=json.load(open(sys.argv[1])); s['obligations'][0]['effects'][0]='ghost_effect'; json.dump(s,open(sys.argv[2],'w'))" %t.spec/capability-spec.json %t.badref.json
// RUN: %not %neutrino-gen --target=coordination-plan --from-spec %t.badref.json -o %t.badref 2>&1 | %FileCheck %s --check-prefix=BADREF
// BADREF: kernel.obligation.not_an_effect
//
// (6) Plan validation FAILS CLOSED on an unknown obligation version.
// RUN: python3 -c "import json,sys; s=json.load(open(sys.argv[1])); s['obligations'][0]['version']=99; json.dump(s,open(sys.argv[2],'w'))" %t.spec/capability-spec.json %t.badver.json
// RUN: %not %neutrino-gen --target=coordination-plan --from-spec %t.badver.json -o %t.badver 2>&1 | %FileCheck %s --check-prefix=BADVER
// BADVER: unknown version 99
//
// (7) Plan validation FAILS CLOSED when the obligation's authorization order disagrees with
//     the executable coordination-plan order — the ordered authorization is not silently
//     reordered, so a reversed obligation cannot be honored as membership while execution runs
//     the other way.
// RUN: python3 -c "import json,sys; s=json.load(open(sys.argv[1])); s['obligations'][0]['effects']=list(reversed(s['obligations'][0]['effects'])); json.dump(s,open(sys.argv[2],'w'))" %t.spec/capability-spec.json %t.badorder.json
// RUN: %not %neutrino-gen --target=coordination-plan --from-spec %t.badorder.json -o %t.badorder 2>&1 | %FileCheck %s --check-prefix=BADORDER
// BADORDER: out of executable coordination-plan order
//
// (8) Plan validation FAILS CLOSED on a PRESENT but non-array obligations section — a spec that
//     carries `obligations` is never silently reconstructed as obligation-free.
// RUN: python3 -c "import json,sys; s=json.load(open(sys.argv[1])); s['obligations']={}; json.dump(s,open(sys.argv[2],'w'))" %t.spec/capability-spec.json %t.badobls.json
// RUN: %not %neutrino-gen --target=coordination-plan --from-spec %t.badobls.json -o %t.badobls 2>&1 | %FileCheck %s --check-prefix=BADOBLS
// BADOBLS: obligations{{.*}}must be an array
//
// (9) The obligation is bound into the COORDINATION IDENTITY (the evaluator's replay keyClaim +
//     both rails), not only the capabilityHash: stripping the obligation op changes the claim.
// RUN: python3 %S/Inputs/check_obligation_identity_binding.py %neutrino-gen %s %S/Inputs/obligation_release_fires.scn.json
//
// (10) The crafted-external-spec FAIL-CLOSED MATRIX at the planFromSpec/assemblePlan trust
//      boundary (architect F2): undeclared obligor, undeclared beneficiary, undeclared authority,
//      a missing predicate AST, a duplicate effect reference, an empty effect set, and a predicate
//      whose guard does not match the authorized effects (architect F1 — the obligation must
//      genuinely authorize, not merely observe) are each rejected with their stable diagnostic.
// RUN: python3 %S/Inputs/check_obligation_failclosed_matrix.py %neutrino-gen %t.spec/capability-spec.json
"builtin.module"() ({
  "neutrino.procedure"() ({
    %amt = "neutrino.input"() {sym_name = "amount", ty = "money"} : () -> !neutrino.value
    %agr = "neutrino.input"() {sym_name = "agreed", ty = "money"} : () -> !neutrino.value
    %cur = "neutrino.input"() {sym_name = "currency", ty = "currency"} : () -> !neutrino.value
    %payee = "neutrino.input"() {sym_name = "payee", ty = "party"} : () -> !neutrino.value
    %key = "neutrino.input"() {sym_name = "flow_id", ty = "string"} : () -> !neutrino.value
    "neutrino.participant"() {sym_name = "EscrowAgent", role = "agent"} : () -> ()
    "neutrino.participant"() {sym_name = "Seller", role = "seller"} : () -> ()
    "neutrino.participant"() {sym_name = "Regulator", role = "regulator"} : () -> ()
    "neutrino.debit"(%payee, %amt, %cur, %key, %amt, %agr) {sym_name = "escrow_release", ledger = "escrow.holding", owner = "e", participant = "EscrowAgent", guard = "amount >= agreed", guard_ast = #neutrino.expr<cmp extension 0 -1 ">=" "" [#neutrino.expr<var money 0 0 "" "" []>, #neutrino.expr<var money 0 1 "" "" []>]>} : (!neutrino.value, !neutrino.value, !neutrino.value, !neutrino.value, !neutrino.value, !neutrino.value) -> ()
    "neutrino.credit"(%payee, %amt, %cur, %key, %amt, %agr) {sym_name = "seller_settlement", ledger = "seller.proceeds", owner = "s", participant = "Seller", guard = "amount >= agreed", guard_ast = #neutrino.expr<cmp extension 0 -1 ">=" "" [#neutrino.expr<var money 0 0 "" "" []>, #neutrino.expr<var money 0 1 "" "" []>]>} : (!neutrino.value, !neutrino.value, !neutrino.value, !neutrino.value, !neutrino.value, !neutrino.value) -> ()
    "neutrino.obligation"(%amt, %agr) {sym_name = "conditional_release", obligor = "EscrowAgent", beneficiary = "Seller", authority = "Regulator", when = "amount >= agreed", when_ast = #neutrino.expr<cmp extension 0 -1 ">=" "" [#neutrino.expr<var money 0 0 "" "" []>, #neutrino.expr<var money 0 1 "" "" []>]>, effects = ["escrow_release", "seller_settlement"]} : (!neutrino.value, !neutrino.value) -> ()
    "neutrino.assert_balanced"() : () -> ()
  }) {sym_name = "core_document_escrow", trigger = "opened", version = "1.0.0", instance_key = "flow_id"} : () -> ()
}) : () -> ()

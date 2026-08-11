// RUN: %neutrino-opt %s > %t.once
// RUN: %neutrino-opt %t.once > %t.twice
// RUN: diff %t.once %t.twice
// RUN: %FileCheck %s < %t.once
//
// L1 v0.2 O1 obligation substrate ( R1a). A first-class undertaking: a scoped
// obligor commits, under an activation predicate, to an ORDERED set of value
// effects (debit/credit) it AUTHORIZES — its identity/lifecycle distinct from
// effect execution. This positive fixture proves the op PARSES, VERIFIES (the C++
// ObligationOp::verify resolves the obligor/beneficiary/authority participants,
// the  typed activation predicate, and the ordered effect references), PRINTS,
// and ROUND-TRIPS deterministically — the once-printed and twice-printed forms are
// compared byte-for-byte by the `diff` RUN line (a re-parse/re-print fixpoint),
// with FileCheck retained for field coverage. The obligation does
// not move value; the debit/credit it references still balance under the procedure
// verifier. No domain/backend vocabulary appears in the op or its verifier.
//
// The effects array order is part of the op identity — it prints back in author
// order, so a reordered/deleted reference cannot silently pass.
// CHECK: "neutrino.obligation"(%{{[0-9]+}})
// CHECK-SAME: authority = "regulator"
// CHECK-SAME: beneficiary = "holder"
// CHECK-SAME: effects = ["src", "dst"]
// CHECK-SAME: obligor = "issuer"
// CHECK-SAME: sym_name = "settle"
// CHECK-SAME: when = "amount > 0"
// CHECK-SAME: when_ast = #neutrino.expr<cmp extension 0 -1 ">"
"builtin.module"() ({
  "neutrino.procedure"() ({
    %0 = "neutrino.input"() {sym_name = "amount", ty = "money"} : () -> !neutrino.value
    %1 = "neutrino.input"() {sym_name = "cur", ty = "currency"} : () -> !neutrino.value
    %2 = "neutrino.input"() {sym_name = "payer", ty = "party"} : () -> !neutrino.value
    %3 = "neutrino.input"() {sym_name = "payee", ty = "party"} : () -> !neutrino.value
    %4 = "neutrino.input"() {sym_name = "key", ty = "string"} : () -> !neutrino.value
    "neutrino.participant"() {sym_name = "issuer", role = "issuer"} : () -> ()
    "neutrino.participant"() {sym_name = "holder", role = "holder"} : () -> ()
    "neutrino.participant"() {sym_name = "regulator", role = "regulator"} : () -> ()
    "neutrino.debit"(%2, %0, %1, %4) {ledger = "a.src", owner = "a", sym_name = "src"} : (!neutrino.value, !neutrino.value, !neutrino.value, !neutrino.value) -> ()
    "neutrino.credit"(%3, %0, %1, %4) {ledger = "b.dst", owner = "b", sym_name = "dst"} : (!neutrino.value, !neutrino.value, !neutrino.value, !neutrino.value) -> ()
    // The obligor/beneficiary/authority are declared participants; the activation
    // predicate `amount > 0` binds its var leaf to the amount input by slot; the
    // ordered effects reference the two declared value effects.
    "neutrino.obligation"(%0) {sym_name = "settle", obligor = "issuer", beneficiary = "holder", authority = "regulator", when = "amount > 0", when_ast = #neutrino.expr<cmp extension 0 -1 ">" "" [#neutrino.expr<var money 0 0 "" "" []>, #neutrino.expr<num decimal 0 -1 "" "" []>]>, effects = ["src", "dst"]} : (!neutrino.value) -> ()
    "neutrino.assert_balanced"() : () -> ()
  }) {sym_name = "settlement", trigger = "opened", version = "1.0.0"} : () -> ()
}) : () -> ()

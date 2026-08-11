// RUN: %neutrino-opt --split-input-file --verify-diagnostics %s
//
// IR-verifier NEGATIVE tests, the MLIR-idiomatic way (S5-F1, neutrino-): the C++
// ProcedureOp::verify() must reject these, and -verify-diagnostics checks the emitted diagnostic
// against the expected-error on the offending op — asserting the coded diagnostic directly, not by
// grepping formatted stderr in a shell script. Cases are separated by the split marker below.

// Case 1: value moves (one debit) but nothing balances it, so it is not balanceable.
"builtin.module"() ({
  // expected-error @+1 {{declares 'assert_balanced' but is not balanceable}}
  "neutrino.procedure"() ({
    %0 = "neutrino.input"() {sym_name = "k", ty = "string"} : () -> !neutrino.value
    %1 = "neutrino.input"() {sym_name = "amt", ty = "money"} : () -> !neutrino.value
    "neutrino.debit"(%0, %1, %0, %0) {sym_name = "d", ledger = "a.b", owner = "o"} : (!neutrino.value, !neutrino.value, !neutrino.value, !neutrino.value) -> ()
    "neutrino.assert_balanced"() : () -> ()
  }) {sym_name = "p"} : () -> ()
}) : () -> ()

// -----

// Case 2:  guarded-balance refusal — the debit posts only when amt > 0 but the matching credit
// is unconditional, so value is not conserved when the guard is false. A guard-blind balancer would
// accept it (the amount/currency multisets match); the verifier must refuse on the offending leg.
"builtin.module"() ({
  "neutrino.procedure"() ({
    %party = "neutrino.input"() {sym_name = "party", ty = "party"} : () -> !neutrino.value
    %amt = "neutrino.input"() {sym_name = "amt", ty = "money"} : () -> !neutrino.value
    %cur = "neutrino.input"() {sym_name = "cur", ty = "currency"} : () -> !neutrino.value
    %k = "neutrino.input"() {sym_name = "k", ty = "string"} : () -> !neutrino.value
    // expected-error @+1 {{guarded legs are not balanced under the same guard}}
    "neutrino.debit"(%party, %amt, %cur, %k, %amt) {sym_name = "d", ledger = "a.b", owner = "o", guard = "amt > 0", guard_ast = #neutrino.expr<cmp extension 0 -1 ">" "" [#neutrino.expr<var money 0 0 "" "" []>, #neutrino.expr<num decimal 0 -1 "" "" []>]>} : (!neutrino.value, !neutrino.value, !neutrino.value, !neutrino.value, !neutrino.value) -> ()
    "neutrino.credit"(%party, %amt, %cur, %k) {sym_name = "c", ledger = "x.y", owner = "o"} : (!neutrino.value, !neutrino.value, !neutrino.value, !neutrino.value) -> ()
    "neutrino.assert_balanced"() : () -> ()
  }) {sym_name = "p"} : () -> ()
}) : () -> ()

// -----

// Case 3:  guarded-balance refusal — the debit and credit carry DIFFERENT guards (amt > 0 vs
// amt > 100), so they are not balanced under the same guard (value is not conserved on 0 < amt <= 100).
"builtin.module"() ({
  "neutrino.procedure"() ({
    %party = "neutrino.input"() {sym_name = "party", ty = "party"} : () -> !neutrino.value
    %amt = "neutrino.input"() {sym_name = "amt", ty = "money"} : () -> !neutrino.value
    %cur = "neutrino.input"() {sym_name = "cur", ty = "currency"} : () -> !neutrino.value
    %k = "neutrino.input"() {sym_name = "k", ty = "string"} : () -> !neutrino.value
    // expected-error @+1 {{guarded legs are not balanced under the same guard}}
    "neutrino.debit"(%party, %amt, %cur, %k, %amt) {sym_name = "d", ledger = "a.b", owner = "o", guard = "amt > 0", guard_ast = #neutrino.expr<cmp extension 0 -1 ">" "" [#neutrino.expr<var money 0 0 "" "" []>, #neutrino.expr<num decimal 0 -1 "" "" []>]>} : (!neutrino.value, !neutrino.value, !neutrino.value, !neutrino.value, !neutrino.value) -> ()
    "neutrino.credit"(%party, %amt, %cur, %k, %amt) {sym_name = "c", ledger = "x.y", owner = "o", guard = "amt > 100", guard_ast = #neutrino.expr<cmp extension 0 -1 ">" "" [#neutrino.expr<var money 0 0 "" "" []>, #neutrino.expr<num decimal 100 -1 "" "" []>]>} : (!neutrino.value, !neutrino.value, !neutrino.value, !neutrino.value, !neutrino.value) -> ()
    "neutrino.assert_balanced"() : () -> ()
  }) {sym_name = "p"} : () -> ()
}) : () -> ()

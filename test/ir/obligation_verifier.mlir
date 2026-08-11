// RUN: %neutrino-opt --split-input-file --verify-diagnostics %s
//
// L1 v0.2 O1 obligation structural verifier ( R1a) — the MLIR-idiomatic
// NEGATIVE tests: the C++ ObligationOp::verify() must reject each defect, and
// -verify-diagnostics checks the coded diagnostic on the offending op. Every
// required field has a biting case (obligor, scope, predicate, effects), plus
// unresolved/duplicate/vacuous references, the effect-vs-obligation boundary, and
// the operand identity acceptance: deleting a required predicate operand fails
// verification, it cannot silently pass. No domain/backend vocabulary appears.

// empty obligor
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
    // expected-error @+1 {{declares no obligor}}
    "neutrino.obligation"(%0) {sym_name = "settle", obligor = "", beneficiary = "holder", authority = "regulator", when = "amount > 0", when_ast = #neutrino.expr<cmp extension 0 -1 ">" "" [#neutrino.expr<var money 0 0 "" "" []>, #neutrino.expr<num decimal 0 -1 "" "" []>]>, effects = ["src", "dst"]} : (!neutrino.value) -> ()
    "neutrino.assert_balanced"() : () -> ()
  }) {sym_name = "settlement", trigger = "opened", version = "1.0.0"} : () -> ()
}) : () -> ()

// -----

// obligor resolves to a non-participant (an effect)
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
    // expected-error @+1 {{obligor 'src' does not resolve to a declared participant}}
    "neutrino.obligation"(%0) {sym_name = "settle", obligor = "src", beneficiary = "holder", authority = "regulator", when = "amount > 0", when_ast = #neutrino.expr<cmp extension 0 -1 ">" "" [#neutrino.expr<var money 0 0 "" "" []>, #neutrino.expr<num decimal 0 -1 "" "" []>]>, effects = ["src", "dst"]} : (!neutrino.value) -> ()
    "neutrino.assert_balanced"() : () -> ()
  }) {sym_name = "settlement", trigger = "opened", version = "1.0.0"} : () -> ()
}) : () -> ()

// -----

// empty scoped beneficiary
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
    // expected-error @+1 {{declares no beneficiary}}
    "neutrino.obligation"(%0) {sym_name = "settle", obligor = "issuer", beneficiary = "", authority = "regulator", when = "amount > 0", when_ast = #neutrino.expr<cmp extension 0 -1 ">" "" [#neutrino.expr<var money 0 0 "" "" []>, #neutrino.expr<num decimal 0 -1 "" "" []>]>, effects = ["src", "dst"]} : (!neutrino.value) -> ()
    "neutrino.assert_balanced"() : () -> ()
  }) {sym_name = "settlement", trigger = "opened", version = "1.0.0"} : () -> ()
}) : () -> ()

// -----

// scoped authority does not resolve
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
    // expected-error @+1 {{authority 'ghost' does not resolve to a declared participant}}
    "neutrino.obligation"(%0) {sym_name = "settle", obligor = "issuer", beneficiary = "holder", authority = "ghost", when = "amount > 0", when_ast = #neutrino.expr<cmp extension 0 -1 ">" "" [#neutrino.expr<var money 0 0 "" "" []>, #neutrino.expr<num decimal 0 -1 "" "" []>]>, effects = ["src", "dst"]} : (!neutrino.value) -> ()
    "neutrino.assert_balanced"() : () -> ()
  }) {sym_name = "settlement", trigger = "opened", version = "1.0.0"} : () -> ()
}) : () -> ()

// -----

// activation predicate missing (no when/when_ast)
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
    // expected-error @+1 {{activation predicate is missing}}
    "neutrino.obligation"() {sym_name = "settle", obligor = "issuer", beneficiary = "holder", authority = "regulator", effects = ["src", "dst"]} : () -> ()
    "neutrino.assert_balanced"() : () -> ()
  }) {sym_name = "settlement", trigger = "opened", version = "1.0.0"} : () -> ()
}) : () -> ()

// -----

// predicate var leaf references an out-of-range dep slot
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
    // expected-error @+1 {{var leaf references dep slot 5}}
    "neutrino.obligation"(%0) {sym_name = "settle", obligor = "issuer", beneficiary = "holder", authority = "regulator", when = "amount > 0", when_ast = #neutrino.expr<cmp extension 0 -1 ">" "" [#neutrino.expr<var money 0 5 "" "" []>, #neutrino.expr<num decimal 0 -1 "" "" []>]>, effects = ["src", "dst"]} : (!neutrino.value) -> ()
    "neutrino.assert_balanced"() : () -> ()
  }) {sym_name = "settlement", trigger = "opened", version = "1.0.0"} : () -> ()
}) : () -> ()

// -----

// vacuous (empty) effect set
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
    // expected-error @+1 {{authorizes no value effects}}
    "neutrino.obligation"(%0) {sym_name = "settle", obligor = "issuer", beneficiary = "holder", authority = "regulator", when = "amount > 0", when_ast = #neutrino.expr<cmp extension 0 -1 ">" "" [#neutrino.expr<var money 0 0 "" "" []>, #neutrino.expr<num decimal 0 -1 "" "" []>]>, effects = []} : (!neutrino.value) -> ()
    "neutrino.assert_balanced"() : () -> ()
  }) {sym_name = "settlement", trigger = "opened", version = "1.0.0"} : () -> ()
}) : () -> ()

// -----

// effect reference does not resolve
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
    // expected-error @+1 {{effect 'ghost' does not resolve to a declared value effect}}
    "neutrino.obligation"(%0) {sym_name = "settle", obligor = "issuer", beneficiary = "holder", authority = "regulator", when = "amount > 0", when_ast = #neutrino.expr<cmp extension 0 -1 ">" "" [#neutrino.expr<var money 0 0 "" "" []>, #neutrino.expr<num decimal 0 -1 "" "" []>]>, effects = ["ghost"]} : (!neutrino.value) -> ()
    "neutrino.assert_balanced"() : () -> ()
  }) {sym_name = "settlement", trigger = "opened", version = "1.0.0"} : () -> ()
}) : () -> ()

// -----

// a participant is referenced as an effect
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
    // expected-error @+1 {{'issuer' resolves to 'neutrino.participant', which is not a value effect}}
    "neutrino.obligation"(%0) {sym_name = "settle", obligor = "issuer", beneficiary = "holder", authority = "regulator", when = "amount > 0", when_ast = #neutrino.expr<cmp extension 0 -1 ">" "" [#neutrino.expr<var money 0 0 "" "" []>, #neutrino.expr<num decimal 0 -1 "" "" []>]>, effects = ["issuer"]} : (!neutrino.value) -> ()
    "neutrino.assert_balanced"() : () -> ()
  }) {sym_name = "settlement", trigger = "opened", version = "1.0.0"} : () -> ()
}) : () -> ()

// -----

// another obligation is referenced as an effect (effect/obligation boundary)
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
    // expected-error @+1 {{'settle' resolves to 'neutrino.obligation', which is not a value effect}}
    "neutrino.obligation"(%0) {sym_name = "settle", obligor = "issuer", beneficiary = "holder", authority = "regulator", when = "amount > 0", when_ast = #neutrino.expr<cmp extension 0 -1 ">" "" [#neutrino.expr<var money 0 0 "" "" []>, #neutrino.expr<num decimal 0 -1 "" "" []>]>, effects = ["settle"]} : (!neutrino.value) -> ()
    "neutrino.assert_balanced"() : () -> ()
  }) {sym_name = "settlement", trigger = "opened", version = "1.0.0"} : () -> ()
}) : () -> ()

// -----

// a value-effect reference is duplicated
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
    // expected-error @+1 {{declares effect 'src' more than once}}
    "neutrino.obligation"(%0) {sym_name = "settle", obligor = "issuer", beneficiary = "holder", authority = "regulator", when = "amount > 0", when_ast = #neutrino.expr<cmp extension 0 -1 ">" "" [#neutrino.expr<var money 0 0 "" "" []>, #neutrino.expr<num decimal 0 -1 "" "" []>]>, effects = ["src", "src"]} : (!neutrino.value) -> ()
    "neutrino.assert_balanced"() : () -> ()
  }) {sym_name = "settlement", trigger = "opened", version = "1.0.0"} : () -> ()
}) : () -> ()

// -----

// deleting the predicate operand fails verification (a var leaf then references dep slot 0 of 0)
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
    // expected-error @+1 {{references dep slot 0 but the op declares 0 dependenc}}
    "neutrino.obligation"() {sym_name = "settle", obligor = "issuer", beneficiary = "holder", authority = "regulator", when = "amount > 0", when_ast = #neutrino.expr<cmp extension 0 -1 ">" "" [#neutrino.expr<var money 0 0 "" "" []>, #neutrino.expr<num decimal 0 -1 "" "" []>]>, effects = ["src", "dst"]} : () -> ()
    "neutrino.assert_balanced"() : () -> ()
  }) {sym_name = "settlement", trigger = "opened", version = "1.0.0"} : () -> ()
}) : () -> ()

// -----

// the obligation's own identity (sym_name) is empty
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
    // expected-error @+1 {{declares an empty identity}}
    "neutrino.obligation"(%0) {sym_name = "", obligor = "issuer", beneficiary = "holder", authority = "regulator", when = "amount > 0", when_ast = #neutrino.expr<cmp extension 0 -1 ">" "" [#neutrino.expr<var money 0 0 "" "" []>, #neutrino.expr<num decimal 0 -1 "" "" []>]>, effects = ["src", "dst"]} : (!neutrino.value) -> ()
    "neutrino.assert_balanced"() : () -> ()
  }) {sym_name = "settlement", trigger = "opened", version = "1.0.0"} : () -> ()
}) : () -> ()

// -----

// a duplicate participant name makes an obligor reference ambiguous (not first-wins)
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
    "neutrino.participant"() {sym_name = "issuer", role = "shadow"} : () -> ()
    "neutrino.debit"(%2, %0, %1, %4) {ledger = "a.src", owner = "a", sym_name = "src"} : (!neutrino.value, !neutrino.value, !neutrino.value, !neutrino.value) -> ()
    "neutrino.credit"(%3, %0, %1, %4) {ledger = "b.dst", owner = "b", sym_name = "dst"} : (!neutrino.value, !neutrino.value, !neutrino.value, !neutrino.value) -> ()
    // expected-error @+1 {{obligor 'issuer' resolves to 2 declarations}}
    "neutrino.obligation"(%0) {sym_name = "settle", obligor = "issuer", beneficiary = "holder", authority = "regulator", when = "amount > 0", when_ast = #neutrino.expr<cmp extension 0 -1 ">" "" [#neutrino.expr<var money 0 0 "" "" []>, #neutrino.expr<num decimal 0 -1 "" "" []>]>, effects = ["src", "dst"]} : (!neutrino.value) -> ()
    "neutrino.assert_balanced"() : () -> ()
  }) {sym_name = "settlement", trigger = "opened", version = "1.0.0"} : () -> ()
}) : () -> ()

// -----

// a cross-kind name collision makes an effect reference ambiguous
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
    "neutrino.participant"() {sym_name = "src", role = "shadow"} : () -> ()
    "neutrino.debit"(%2, %0, %1, %4) {ledger = "a.src", owner = "a", sym_name = "src"} : (!neutrino.value, !neutrino.value, !neutrino.value, !neutrino.value) -> ()
    "neutrino.credit"(%3, %0, %1, %4) {ledger = "b.dst", owner = "b", sym_name = "dst"} : (!neutrino.value, !neutrino.value, !neutrino.value, !neutrino.value) -> ()
    // expected-error @+1 {{effect 'src' resolves to 2 declarations}}
    "neutrino.obligation"(%0) {sym_name = "settle", obligor = "issuer", beneficiary = "holder", authority = "regulator", when = "amount > 0", when_ast = #neutrino.expr<cmp extension 0 -1 ">" "" [#neutrino.expr<var money 0 0 "" "" []>, #neutrino.expr<num decimal 0 -1 "" "" []>]>, effects = ["src", "dst"]} : (!neutrino.value) -> ()
    "neutrino.assert_balanced"() : () -> ()
  }) {sym_name = "settlement", trigger = "opened", version = "1.0.0"} : () -> ()
}) : () -> ()

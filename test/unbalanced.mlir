// A procedure that moves value (one debit) but has no matching credit.
// The C++ ProcedureOp::verify() must reject this.
"builtin.module"() ({
  "neutrino.procedure"() ({
    %0 = "neutrino.input"() {sym_name = "k", ty = "string"} : () -> !neutrino.value
    %1 = "neutrino.input"() {sym_name = "amt", ty = "money"} : () -> !neutrino.value
    "neutrino.debit"(%0, %1, %0, %0) {sym_name = "d", ledger = "a.b", owner = "o"} : (!neutrino.value, !neutrino.value, !neutrino.value, !neutrino.value) -> ()
    "neutrino.assert_balanced"() : () -> ()
  }) {sym_name = "p"} : () -> ()
}) : () -> ()

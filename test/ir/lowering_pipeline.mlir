// RUN: %neutrino-opt %s | %FileCheck %s --check-prefix=IR
// RUN: %neutrino-emit --kind=events %s | %FileCheck %s --check-prefix=EVENTS
//
// IR regression () — dialect verification round-trip + the events inspection
// projection. neutrino-opt parses this canonical IR, runs the C++ dialect verifier, and
// re-prints it (IR round-trip stability). `neutrino-emit --kind=events` projects the IR's
// expected fact ordering (INSPECTION only, not a backend — backends are the spec-derived
// `neutrino-gen --target=postgres|solidity`; the raw-MLIR sql/contract projections were
// retired in ). The checks are at the IR / projection level, so a change is explained,
// not just seen as artifact drift. See README.md.
//
// IR: "neutrino.procedure"
// IR: "neutrino.debit"({{.*}}) {ledger = "a.src", owner = "a", sym_name = "src"}
// IR: "neutrino.credit"({{.*}}) {ledger = "b.dst", owner = "b", sym_name = "dst"}
// IR: "neutrino.assert_balanced"()
//
// EVENTS: procedure ir_dialect_probe:
// EVENTS: ProbeTriggered
// EVENTS: SrcDebited
// EVENTS: DstCredited
// EVENTS: IrDialectProbeReconciled
"builtin.module"() ({
  "neutrino.procedure"() ({
    %0 = "neutrino.input"() {sym_name = "amount", ty = "money"} : () -> !neutrino.value
    %1 = "neutrino.input"() {sym_name = "cur", ty = "currency"} : () -> !neutrino.value
    %2 = "neutrino.input"() {sym_name = "payer", ty = "party"} : () -> !neutrino.value
    %3 = "neutrino.input"() {sym_name = "payee", ty = "party"} : () -> !neutrino.value
    %4 = "neutrino.input"() {sym_name = "key", ty = "string"} : () -> !neutrino.value
    "neutrino.debit"(%2, %0, %1, %4) {ledger = "a.src", owner = "a", sym_name = "src"} : (!neutrino.value, !neutrino.value, !neutrino.value, !neutrino.value) -> ()
    "neutrino.credit"(%3, %0, %1, %4) {ledger = "b.dst", owner = "b", sym_name = "dst"} : (!neutrino.value, !neutrino.value, !neutrino.value, !neutrino.value) -> ()
    "neutrino.assert_balanced"() : () -> ()
  }) {sym_name = "ir_dialect_probe", trigger = "probe_triggered", version = "1.0.0"} : () -> ()
}) : () -> ()

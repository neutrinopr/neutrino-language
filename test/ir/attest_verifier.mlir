// RUN: %neutrino-opt --split-input-file --verify-diagnostics %s
//
// IR-verifier tests for the attestation policy (M5 oracle S1, ), the MLIR-idiomatic way: the C++
// AttestOp::verify() must fail closed on each malformed policy, and -verify-diagnostics matches the
// emitted [kernel.attest.*] coded diagnostic directly on the offending op — proving a hand-written
// .mlir that bypasses the frontend parser still cannot emit a policy that fires on a partial or
// unconstrained quorum. Cases are separated by the split marker.

// Case 1: a non-positive quorum (the M-of-N threshold) is rejected.
"builtin.module"() ({
  "neutrino.procedure"() ({
    %e = "neutrino.input"() {sym_name = "e", ty = "evidence"} : () -> !neutrino.value
    %k = "neutrino.input"() {sym_name = "k", ty = "string"} : () -> !neutrino.value
    // expected-error @+1 {{[kernel.attest.invalid_quorum]}}
    "neutrino.attest"() {input = "e", quorum = 0 : i64, observer_set = "o", canonicalization = "exact", fallback = "abort"} : () -> ()
  }) {sym_name = "p", instance_key = "k"} : () -> ()
}) : () -> ()

// -----

// Case 2: a missing observer-set reference is rejected (the quorum would be unconstrained).
"builtin.module"() ({
  "neutrino.procedure"() ({
    %e = "neutrino.input"() {sym_name = "e", ty = "evidence"} : () -> !neutrino.value
    %k = "neutrino.input"() {sym_name = "k", ty = "string"} : () -> !neutrino.value
    // expected-error @+1 {{[kernel.attest.missing_observer_set]}}
    "neutrino.attest"() {input = "e", quorum = 2 : i64, observer_set = "", canonicalization = "exact", fallback = "abort"} : () -> ()
  }) {sym_name = "p", instance_key = "k"} : () -> ()
}) : () -> ()

// -----

// Case 3: an unsupported canonicalization mode is rejected (observers could not agree on "the same claim").
"builtin.module"() ({
  "neutrino.procedure"() ({
    %e = "neutrino.input"() {sym_name = "e", ty = "evidence"} : () -> !neutrino.value
    %k = "neutrino.input"() {sym_name = "k", ty = "string"} : () -> !neutrino.value
    // expected-error @+1 {{[kernel.attest.invalid_canonicalization]}}
    "neutrino.attest"() {input = "e", quorum = 2 : i64, observer_set = "o", canonicalization = "vibes", fallback = "abort"} : () -> ()
  }) {sym_name = "p", instance_key = "k"} : () -> ()
}) : () -> ()

// -----

// Case 4: an unsupported quorum-timeout fallback is rejected (fail-closed behavior must be declared).
"builtin.module"() ({
  "neutrino.procedure"() ({
    %e = "neutrino.input"() {sym_name = "e", ty = "evidence"} : () -> !neutrino.value
    %k = "neutrino.input"() {sym_name = "k", ty = "string"} : () -> !neutrino.value
    // expected-error @+1 {{[kernel.attest.invalid_fallback]}}
    "neutrino.attest"() {input = "e", quorum = 2 : i64, observer_set = "o", canonicalization = "exact", fallback = "panic"} : () -> ()
  }) {sym_name = "p", instance_key = "k"} : () -> ()
}) : () -> ()

// -----

// Case 5 (positive): a well-formed policy verifies with no diagnostic.
"builtin.module"() ({
  "neutrino.procedure"() ({
    %e = "neutrino.input"() {sym_name = "e", ty = "evidence"} : () -> !neutrino.value
    %k = "neutrino.input"() {sym_name = "k", ty = "string"} : () -> !neutrino.value
    "neutrino.attest"() {input = "e", quorum = 2 : i64, observer_set = "delivery_oracles", canonicalization = "median", tolerance = "0", timeout = "PT24H", fallback = "escalate"} : () -> ()
  }) {sym_name = "p", instance_key = "k"} : () -> ()
}) : () -> ()

// -----

// Case 6 (oracle S6, ): a DECLARED-but-unsupported observer-set assurance tier is rejected.
"builtin.module"() ({
  "neutrino.procedure"() ({
    %e = "neutrino.input"() {sym_name = "e", ty = "evidence"} : () -> !neutrino.value
    %k = "neutrino.input"() {sym_name = "k", ty = "string"} : () -> !neutrino.value
    // expected-error @+1 {{[kernel.attest.invalid_assurance]}}
    "neutrino.attest"() {input = "e", quorum = 2 : i64, observer_set = "o", canonicalization = "exact", fallback = "abort", assurance = "A9"} : () -> ()
  }) {sym_name = "p", instance_key = "k"} : () -> ()
}) : () -> ()

// -----

// Case 7 (oracle S6, ): a DECLARED-but-unsupported observer-set independence posture is rejected.
"builtin.module"() ({
  "neutrino.procedure"() ({
    %e = "neutrino.input"() {sym_name = "e", ty = "evidence"} : () -> !neutrino.value
    %k = "neutrino.input"() {sym_name = "k", ty = "string"} : () -> !neutrino.value
    // expected-error @+1 {{[kernel.attest.invalid_independence]}}
    "neutrino.attest"() {input = "e", quorum = 2 : i64, observer_set = "o", canonicalization = "exact", fallback = "abort", independence = "solo"} : () -> ()
  }) {sym_name = "p", instance_key = "k"} : () -> ()
}) : () -> ()

// -----

// Case 8 (positive, oracle S6, ): declared assurance + independence from the accepted vocabulary
// verify cleanly — the metadata is optional, and a valid declaration is not an error (it is surfaced,
// not rejected, by the security spec).
"builtin.module"() ({
  "neutrino.procedure"() ({
    %e = "neutrino.input"() {sym_name = "e", ty = "evidence"} : () -> !neutrino.value
    %k = "neutrino.input"() {sym_name = "k", ty = "string"} : () -> !neutrino.value
    "neutrino.attest"() {input = "e", quorum = 2 : i64, observer_set = "delivery_oracles", canonicalization = "exact", fallback = "abort", assurance = "A3", independence = "independent"} : () -> ()
  }) {sym_name = "p", instance_key = "k"} : () -> ()
}) : () -> ()

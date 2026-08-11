// RUN: %neutrino-opt --split-input-file --verify-diagnostics %s
//
// Fail-closed verification of the generic L2 meta-model (): the C++ op
// verifiers reject each malformed record, and -verify-diagnostics matches the
// emitted diagnostic on the offending op. Cases are separated by the split
// marker. Every implementation check has a case here, so removing a check is
// observable (e.g. deleting isSha256() breaks case 16).

// Case 1: a laundered concept kind is rejected (closed vocabulary).
l2.domain "d" attributes {version = "1.0.0", implements = "c"} {
  l2.l1_feature "f" {kind = "primitive"}
  // expected-error @+1 {{concept kind 'process' is not one of state/action/concept}}
  l2.concept "x" {kind = "process", classification = "executable"}
  l2.reduce "e" "x" -> "f" {relation = "protects", lossiness = "lossless"}
}

// -----

// Case 2: a laundered concept classification is rejected.
l2.domain "d" attributes {version = "1.0.0", implements = "c"} {
  l2.l1_feature "f" {kind = "primitive"}
  // expected-error @+1 {{concept classification 'partial' is not one of executable/descriptive}}
  l2.concept "x" {kind = "state", classification = "partial"}
  l2.reduce "e" "x" -> "f" {relation = "protects", lossiness = "lossless"}
}

// -----

// Case 3: an unknown reduction relation is rejected. (`x` is traced by the
// valid edge so the reduce enum check is the sole failure.)
l2.domain "d" attributes {version = "1.0.0", implements = "c"} {
  l2.l1_feature "f" {kind = "primitive"}
  l2.concept "x" {kind = "state", classification = "descriptive"}
  l2.reduce "ok" "x" -> "f" {relation = "protects", lossiness = "lossless"}
  // expected-error @+1 {{reduction relation 'becomes' is not one of expands/discharges/protects/failure}}
  l2.reduce "bad" "x" -> "f" {relation = "becomes", lossiness = "lossless"}
}

// -----

// Case 4: an unknown reduction lossiness is rejected.
l2.domain "d" attributes {version = "1.0.0", implements = "c"} {
  l2.l1_feature "f" {kind = "primitive"}
  l2.concept "x" {kind = "state", classification = "descriptive"}
  l2.reduce "ok" "x" -> "f" {relation = "protects", lossiness = "lossless"}
  // expected-error @+1 {{reduction lossiness 'partial' is not one of lossless/lossy_preserved/unsupported}}
  l2.reduce "bad" "x" -> "f" {relation = "protects", lossiness = "partial"}
}

// -----

// Case 5: an L1 feature with a laundered kind is rejected.
l2.domain "d" attributes {version = "1.0.0", implements = "c"} {
  // expected-error @+1 {{L1 feature kind 'axiom' is not one of primitive/obligation}}
  l2.l1_feature "f" {kind = "axiom"}
}

// -----

// Case 6: a reduction edge to an UNDECLARED L1 feature is rejected (not any string).
l2.domain "d" attributes {version = "1.0.0", implements = "c"} {
  l2.concept "x" {kind = "state", classification = "descriptive"}
  // expected-error @+1 {{reduction edge targets undeclared L1 feature 'not_a_feature'}}
  l2.reduce "e" "x" -> "not_a_feature" {relation = "protects", lossiness = "lossless"}
}

// -----

// Case 7: a reduction edge FROM an undeclared concept dangles.
l2.domain "d" attributes {version = "1.0.0", implements = "c"} {
  l2.l1_feature "f" {kind = "primitive"}
  // expected-error @+1 {{reduction edge from undeclared concept 'ghost'}}
  l2.reduce "e" "ghost" -> "f" {relation = "protects", lossiness = "lossless"}
}

// -----

// Case 8: a failure edge to an undeclared failure mode dangles.
l2.domain "d" attributes {version = "1.0.0", implements = "c"} {
  l2.concept "x" {kind = "state", classification = "executable"}
  // expected-error @+1 {{failure edge targets undeclared failure mode 'ghostmode'}}
  l2.reduce "e" "x" -> "ghostmode" {relation = "failure", lossiness = "lossless"}
}

// -----

// Case 9: a concept traced ONLY by a failure edge is untraced.
l2.domain "d" attributes {version = "1.0.0", implements = "c"} {
  l2.failure_mode "boom" {}
  // expected-error @+1 {{concept 'x' has no supported reduction to a declared L1 feature}}
  l2.concept "x" {kind = "state", classification = "executable"}
  l2.reduce "e" "x" -> "boom" {relation = "failure", lossiness = "lossless"}
}

// -----

// Case 10: a concept traced ONLY by an unsupported edge is untraced.
l2.domain "d" attributes {version = "1.0.0", implements = "c"} {
  l2.l1_feature "f" {kind = "primitive"}
  // expected-error @+1 {{concept 'x' has no supported reduction to a declared L1 feature}}
  l2.concept "x" {kind = "state", classification = "descriptive"}
  l2.reduce "e" "x" -> "f" {relation = "protects", lossiness = "unsupported"}
}

// -----

// Case 11: a descriptive concept cannot drive an executable (expands) reduction.
l2.domain "d" attributes {version = "1.0.0", implements = "c"} {
  l2.l1_feature "buyer_escrow" {kind = "primitive"}
  l2.concept "x" {kind = "concept", classification = "descriptive"}
  // expected-error @+1 {{descriptive concept 'x' cannot drive an executable expands reduction}}
  l2.reduce "e" "x" -> "buyer_escrow" {relation = "expands", lossiness = "lossless"}
}

// -----

// Case 12: a behaviour-driving (executable) edge without accepted provenance is rejected.
l2.domain "d" attributes {version = "1.0.0", implements = "c"} {
  l2.l1_feature "f" {kind = "primitive"}
  l2.concept "x" {kind = "state", classification = "executable"}
  // expected-error @+1 {{executable reduction edge 'e' has no accepted provenance}}
  l2.reduce "e" "x" -> "f" {relation = "expands", lossiness = "lossless"}
}

// -----

// Case 13: a provenance subject that resolves to nothing is rejected.
l2.domain "d" attributes {version = "1.0.0", implements = "c"} {
  l2.l1_feature "f" {kind = "primitive"}
  l2.concept "x" {kind = "state", classification = "descriptive"}
  l2.reduce "e" "x" -> "f" {relation = "protects", lossiness = "lossless"}
  // expected-error @+1 {{provenance subject 'ghost' resolves to no declared concept or edge}}
  l2.provenance "ghost" {source = "s", status = "accepted"}
}

// -----

// Case 14: an empty provenance source is rejected.
l2.domain "d" attributes {version = "1.0.0", implements = "c"} {
  l2.l1_feature "f" {kind = "primitive"}
  l2.concept "x" {kind = "state", classification = "descriptive"}
  l2.reduce "e" "x" -> "f" {relation = "protects", lossiness = "lossless"}
  // expected-error @+1 {{provenance needs a non-empty subject and source}}
  l2.provenance "x" {source = "", status = "proposed"}
}

// -----

// Case 15: a laundered provenance status is rejected.
l2.domain "d" attributes {version = "1.0.0", implements = "c"} {
  l2.l1_feature "f" {kind = "primitive"}
  l2.concept "x" {kind = "state", classification = "descriptive"}
  l2.reduce "e" "x" -> "f" {relation = "protects", lossiness = "lossless"}
  // expected-error @+1 {{provenance status 'maybe' is not one of proposed/accepted/rejected}}
  l2.provenance "x" {source = "s", status = "maybe"}
}

// -----

// Case 16: a non-sha256 excerpt hash is rejected (deleting isSha256() breaks this).
l2.domain "d" attributes {version = "1.0.0", implements = "c"} {
  l2.l1_feature "f" {kind = "primitive"}
  l2.concept "x" {kind = "state", classification = "descriptive"}
  l2.reduce "e" "x" -> "f" {relation = "protects", lossiness = "lossless"}
  // expected-error @+1 {{provenance excerpt hash is not a 64-char lowercase sha256}}
  l2.provenance "x" {source = "s", status = "proposed", excerpt_hash = "deadbeef"}
}

// -----

// Case 17: a foreign op is rejected — the domain body is closed.
l2.domain "d" attributes {version = "1.0.0", implements = "c"} {
  // expected-error @+1 {{is not an l2 domain record}}
  "builtin.module"() ({}) : () -> ()
}

// -----

// Case 18: a standalone record (no l2.domain parent) cannot evade the container.
// expected-error @+1 {{'l2.reduce' op expects parent op 'l2.domain'}}
l2.reduce "e" "x" -> "f" {relation = "expands", lossiness = "lossless"}

// -----

// Case 19: a duplicate concept name is rejected (one global namespace).
l2.domain "d" attributes {version = "1.0.0", implements = "c"} {
  l2.l1_feature "f" {kind = "primitive"}
  l2.concept "x" {kind = "state", classification = "descriptive"}
  // expected-error @+1 {{concept identifier 'x' collides with another record}}
  l2.concept "x" {kind = "action", classification = "descriptive"}
  l2.reduce "e" "x" -> "f" {relation = "protects", lossiness = "lossless"}
}

// -----

// Case 20: a concept and an edge sharing a name is an ambiguous reference — rejected.
l2.domain "d" attributes {version = "1.0.0", implements = "c"} {
  l2.l1_feature "f" {kind = "primitive"}
  l2.concept "same" {kind = "state", classification = "executable"}
  // expected-error @+1 {{reduction edge identifier 'same' collides with another record}}
  l2.reduce "same" "same" -> "f" {relation = "expands", lossiness = "lossless"}
  l2.provenance "same" {source = "s", status = "accepted"}
}

// -----

// Case 21: a duplicate reduction-edge id is rejected.
l2.domain "d" attributes {version = "1.0.0", implements = "c"} {
  l2.l1_feature "f" {kind = "primitive"}
  l2.concept "x" {kind = "state", classification = "descriptive"}
  l2.concept "y" {kind = "state", classification = "descriptive"}
  l2.reduce "dup" "x" -> "f" {relation = "protects", lossiness = "lossless"}
  // expected-error @+1 {{reduction edge identifier 'dup' collides with another record}}
  l2.reduce "dup" "y" -> "f" {relation = "protects", lossiness = "lossless"}
}

// -----

// Case 22: an invariant on_failure to an undeclared failure mode is rejected.
l2.domain "d" attributes {version = "1.0.0", implements = "c"} {
  l2.l1_feature "f" {kind = "primitive"}
  l2.concept "x" {kind = "state", classification = "descriptive"}
  l2.reduce "e" "x" -> "f" {relation = "protects", lossiness = "lossless"}
  // expected-error @+1 {{invariant on_failure references undeclared failure mode 'ghostmode'}}
  l2.invariant "inv" {predicate = "x == y", on_failure = "ghostmode"}
}

// -----

// Case 23: a non-SemVer domain version is rejected (contract parity).
// expected-error @+1 {{domain version '1' is not a semantic version}}
l2.domain "d" attributes {version = "1", implements = "c"} {
  l2.l1_feature "f" {kind = "primitive"}
  l2.concept "x" {kind = "state", classification = "descriptive"}
  l2.reduce "e" "x" -> "f" {relation = "protects", lossiness = "lossless"}
}

// -----

// Case 24: an empty L1-feature name is rejected (stable identity required).
l2.domain "d" attributes {version = "1.0.0", implements = "c"} {
  // expected-error @+1 {{an l2.l1_feature needs a non-empty name}}
  l2.l1_feature "" {kind = "primitive"}
}

// -----

// Case 25: an empty failure-mode name is rejected.
l2.domain "d" attributes {version = "1.0.0", implements = "c"} {
  // expected-error @+1 {{an l2.failure_mode needs a non-empty name}}
  l2.failure_mode ""
}

// -----

// Case 26: an empty concept name is rejected. (Traced by a valid edge so the
// name check is the sole failure — the domain verifier runs before nested ops.)
l2.domain "d" attributes {version = "1.0.0", implements = "c"} {
  l2.l1_feature "f" {kind = "primitive"}
  // expected-error @+1 {{an l2.concept needs a non-empty name}}
  l2.concept "" {kind = "state", classification = "descriptive"}
  l2.reduce "e" "" -> "f" {relation = "protects", lossiness = "lossless"}
}

// -----

// Case 27: an empty invariant name is rejected.
l2.domain "d" attributes {version = "1.0.0", implements = "c"} {
  l2.l1_feature "f" {kind = "primitive"}
  l2.concept "x" {kind = "state", classification = "descriptive"}
  l2.reduce "e" "x" -> "f" {relation = "protects", lossiness = "lossless"}
  // expected-error @+1 {{an l2.invariant needs a non-empty name}}
  l2.invariant "" {predicate = "true"}
}

// -----

// Case 28: an l2.import with an empty capability is rejected.
l2.domain "d" attributes {version = "1.0.0", implements = "c"} {
  // expected-error @+1 {{an l2.import needs a non-empty capability}}
  l2.import "" {version = "1.0.0"}
}

// -----

// Case 29: an l2.import version that is not a semantic version is rejected.
l2.domain "d" attributes {version = "1.0.0", implements = "c"} {
  // expected-error @+1 {{l2.import version 'v1' is not a semantic version}}
  l2.import "coordinate.other" {version = "v1"}
}

// -----

// Case 30: a domain may import a given capability at most once (importing two
// versions of it is contradictory).
l2.domain "d" attributes {version = "1.0.0", implements = "c"} {
  l2.import "coordinate.other" {version = "1.0.0"}
  // expected-error @+1 {{duplicate import of capability 'coordinate.other'}}
  l2.import "coordinate.other" {version = "2.0.0"}
}

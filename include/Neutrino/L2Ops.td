#ifndef NEUTRINO_L2_OPS_TD
#define NEUTRINO_L2_OPS_TD

include "mlir/IR/OpBase.td"

//===----------------------------------------------------------------------===//
// The generic L2 domain-semantics meta-model ().
//
// A CLOSED, generic vocabulary for the visible L2 sidecar: a domain is DATA —
// instances of these ops — never a new op/class per concept ( §4 anti-
// pattern ). ODS earns its keep in the two places the boundary contract asks
// for: fail-closed VERIFICATION (op verifiers) and SOURCE MAPPING (every record
// is a located op). Rigid backends never consume it ( §7).
//===----------------------------------------------------------------------===//

def L2_Dialect : Dialect {
  let name = "l2";
  let summary = "Generic, versioned L2 domain-semantics meta-model.";
  let cppNamespace = "::neutrino::l2";
  let emitAccessorPrefix = kEmitAccessorPrefix_Prefixed;
}

class L2_Op<string mnemonic, list<Trait> traits = []>
    : Op<L2_Dialect, mnemonic, traits>;

// Every domain RECORD must sit directly inside an l2.domain, so a standalone
// record can never evade the container's cross-record verification.
class L2_RecordOp<string mnemonic, list<Trait> traits = []>
    : L2_Op<mnemonic, !listconcat([HasParent<"::neutrino::l2::DomainOp">],
                                  traits)>;

//===----------------------------------------------------------------------===//
// The domain container: holds the L1 anchors / concepts / reduction edges /
// invariants / failure modes / provenance of ONE domain. Its body is CLOSED
// (only the records below), and the cross-record fail-closed rules — reference
// resolution, traceability to a declared L1 anchor, classification vs. relation,
// provenance binding — are enforced here, where the verifier sees the whole body.
//===----------------------------------------------------------------------===//

def L2_DomainOp : L2_Op<"domain", [NoTerminator, SingleBlock]> {
  let summary = "A versioned L2 domain and the container of its records.";
  let arguments = (ins StrAttr:$sym_name, StrAttr:$version, StrAttr:$implements,
                       OptionalAttr<StrAttr>:$coverage);
  let regions = (region SizedRegion<1>:$body);
  let hasVerifier = 1;
  let assemblyFormat = "$sym_name attr-dict-with-keyword $body";
}

//===----------------------------------------------------------------------===//
// The records. Closed enum fields are plain string attributes whose vocabulary
// is pinned in the C++ verifier (mirroring #neutrino.expr's dtype discipline),
// so a laundered spelling is rejected at IR-verify time.
//===----------------------------------------------------------------------===//

// A declared L1 anchor this domain reduces onto: a primitive or an obligation.
// Reduction edges may only target a declared anchor, so traceability is proved
// against a closed set, not any free string.
def L2_L1FeatureOp : L2_RecordOp<"l1_feature"> {
  let summary = "A declared L1 anchor (primitive|obligation) a concept may reduce onto.";
  let arguments = (ins StrAttr:$sym_name, StrAttr:$kind);
  let hasVerifier = 1;
  let assemblyFormat = "$sym_name attr-dict";
}

// A domain concept, classified executable (drives L1) or descriptive (cannot).
def L2_ConceptOp : L2_RecordOp<"concept"> {
  let summary = "A domain concept: kind in {state,action,concept}, classified "
                "executable|descriptive.";
  let arguments = (ins StrAttr:$sym_name, StrAttr:$kind, StrAttr:$classification);
  let hasVerifier = 1;
  let assemblyFormat = "$sym_name attr-dict";
}

// A reduction edge with a stable id, so provenance can bind to it and a change
// to it bites a test. `to` resolves to a declared L1 anchor (expands/discharges/
// protects) or a declared failure mode (failure). `relation`/`lossiness` closed.
def L2_ReduceOp : L2_RecordOp<"reduce"> {
  let summary = "An identified reduction edge from a concept to an L1 anchor / "
                "failure mode.";
  let arguments = (ins StrAttr:$sym_name, StrAttr:$from, StrAttr:$to,
                       StrAttr:$relation, StrAttr:$lossiness);
  let hasVerifier = 1;
  let assemblyFormat = "$sym_name $from `->` $to attr-dict";
}

// A declared failure mode with an optional compensation.
def L2_FailureModeOp : L2_RecordOp<"failure_mode"> {
  let summary = "A declared failure mode and its optional compensation.";
  let arguments = (ins StrAttr:$sym_name, OptionalAttr<StrAttr>:$compensation);
  let hasVerifier = 1;
  let assemblyFormat = "$sym_name attr-dict";
}

// A domain invariant and the failure mode it trips on breach.
def L2_InvariantOp : L2_RecordOp<"invariant"> {
  let summary = "A domain invariant and the failure mode it trips on breach.";
  let arguments = (ins StrAttr:$sym_name, StrAttr:$predicate,
                       OptionalAttr<StrAttr>:$on_failure);
  let hasVerifier = 1;
  let assemblyFormat = "$sym_name attr-dict";
}

// Provenance for a subject (a concept name or a reduction-edge id): source,
// standard version, excerpt hash, reviewer, and a closed review `status`.
// A behaviour-driving (executable) edge requires an accepted provenance.
def L2_ProvenanceOp : L2_RecordOp<"provenance"> {
  let summary = "Provenance for a concept/edge: source, excerpt hash, review status.";
  let arguments = (ins StrAttr:$subject, StrAttr:$source,
                       OptionalAttr<StrAttr>:$standard_version,
                       OptionalAttr<StrAttr>:$excerpt_hash,
                       OptionalAttr<StrAttr>:$reviewer, StrAttr:$status);
  let hasVerifier = 1;
  let assemblyFormat = "$subject attr-dict";
}

// A versioned import of ANOTHER L2 domain: names a foreign `capability` at a
// required `version`. Purely a reference OUT — it claims no local identifier —
// resolved against a domain registry (the cross-rail catalog) by the import
// resolver, which fails closed on a dangling, unknown-version, ambiguous, or
// cyclic mapping. The verifier only checks the record is well-formed; the
// registry-relative resolution is a separate, data-driven pass ( §2).
def L2_ImportOp : L2_RecordOp<"import"> {
  let summary = "A versioned import of another L2 domain, resolved against a registry.";
  let arguments = (ins StrAttr:$capability, StrAttr:$version);
  let hasVerifier = 1;
  let assemblyFormat = "$capability attr-dict";
}

#endif // NEUTRINO_L2_OPS_TD

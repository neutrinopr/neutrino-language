#ifndef NEUTRINO_OPS_TD
#define NEUTRINO_OPS_TD

include "mlir/IR/OpBase.td"
include "mlir/IR/AttrTypeBase.td"

//===----------------------------------------------------------------------===//
// Dialect
//===----------------------------------------------------------------------===//

def Neutrino_Dialect : Dialect {
  let name = "neutrino";
  let summary = "Neutrino coordination IR.";
  let cppNamespace = "::neutrino";
  let useDefaultTypePrinterParser = 1;
  let useDefaultAttributePrinterParser = 1;
  // Generate getX() accessors (forward-compatible with newer LLVM defaults).
  let emitAccessorPrefix = kEmitAccessorPrefix_Prefixed;
}

class Neutrino_Op<string mnemonic, list<Trait> traits = []>
    : Op<Neutrino_Dialect, mnemonic, traits>;

//===----------------------------------------------------------------------===//
// Attributes
//===----------------------------------------------------------------------===//

// A structured, typed compute/guard expression. The bounded,
// closed grammar (`+ - * /`, comparisons, `round`) as a recursive attribute so
// the STRUCTURE + its inferred value dtype live IN the IR and are verified at
// IR-verify time — no consumer re-parses text or re-types. Leaf/among-node
// roles by `kind`: num | var | bin | call | cmp. `children` holds lhs,rhs (bin/
// cmp) or the call args, so the attribute is self-referential.
def Neutrino_ExprAttr : AttrDef<Neutrino_Dialect, "Expr"> {
  let mnemonic = "expr";
  let summary = "A structured, typed compute/guard expression.";
  let parameters = (ins
      StringRefParameter<"num|var|bin|call|cmp">:$kind,
      StringRefParameter<"inferred value category ( dtype)">:$dtype,
      "int64_t":$num,
      // A `var` leaf is SSA-BOUND, not name-bound ( amendment 1): $slot is
      // the index into the owning op's dependency operands (ComputeOp.deps, or an
      // entry's guard-dep segment); the op verifier proves the slot bijection.
      // -1 for a non-var node. $name carries a call callee / cmp operator only.
      "int64_t":$slot,
      StringRefParameter<"call callee / cmp operator ('' for var/num/bin)">:$name,
      StringRefParameter<"binary operator ('+','-','*','/'), '' otherwise">:$binop,
      ArrayRefParameter<"::neutrino::ExprAttr", "operands: lhs,rhs or call args">:$children);
  // A self-referential attribute: the auto struct() format cannot delimit a
  // nested-attribute array, so we hand-write a printer/parser that brackets the
  // children and prints each via the full attribute form ( de-risk spike).
  let hasCustomAssemblyFormat = 1;
  let genVerifyDecl = 1;
}

//===----------------------------------------------------------------------===//
// Types
//===----------------------------------------------------------------------===//

def Neutrino_ValueType : TypeDef<Neutrino_Dialect, "Value"> {
  let mnemonic = "value";
  let summary = "An opaque coordination value (amount, party, currency, key).";
}

//===----------------------------------------------------------------------===//
// Ops
//===----------------------------------------------------------------------===//

def ConstOp : Neutrino_Op<"const"> {
  let summary = "Materialise a literal as an SSA value.";
  let arguments = (ins StrAttr:$value);
  let results = (outs Neutrino_ValueType:$res);
}

def InputOp : Neutrino_Op<"input"> {
  let summary = "A declared procedure input.";
  let arguments = (ins StrAttr:$sym_name, StrAttr:$ty);
  let results = (outs Neutrino_ValueType:$res);
}

def ComputeOp : Neutrino_Op<"compute"> {
  let summary = "A computed value; structure+typing in $ast, deps are SSA operands.";
  let description = [{
    The semantics live in the structured, typed `$ast` (#neutrino.expr, ),
    verified at IR-verify time against the SSA-deps' value categories. `$expr`
    is retained as the original source text for provenance/display only (the
    capability-spec surfaces it), NOT for semantics.
  }];
  let arguments = (ins Variadic<Neutrino_ValueType>:$deps, StrAttr:$sym_name,
                       StrAttr:$expr, Neutrino_ExprAttr:$ast);
  let results = (outs Neutrino_ValueType:$res);
  let hasVerifier = 1;
}

class Neutrino_EntryOp<string mnemonic> : Neutrino_Op<mnemonic> {
  let arguments = (ins
      Neutrino_ValueType:$party,
      Neutrino_ValueType:$amount,
      Neutrino_ValueType:$currency,
      Neutrino_ValueType:$idempotency_key,
      // The guard's SSA dependencies: the inputs/computes the
      // `$guard_ast` var leaves bind to, by slot. Empty when unguarded. A single
      // trailing variadic after the four fixed value operands, so the operand
      // count is inferrable without AttrSizedOperandSegments.
      Variadic<Neutrino_ValueType>:$guard_deps,
      StrAttr:$sym_name,
      StrAttr:$ledger,
      StrAttr:$owner,
      OptionalAttr<StrAttr>:$participant,
      // Optional conditional guard: the leg posts iff the guard
      // holds. `$guard` is the source text (provenance/display); `$guard_ast`
      // is the structured, typed comparison verified at IR-verify time —
      // the semantics. Both present or both absent.
      OptionalAttr<StrAttr>:$guard,
      OptionalAttr<Neutrino_ExprAttr>:$guard_ast,
      // Optional effect metadata (M5 token S3, ): a free-text memo/reference
      // carried WITH the movement and surfaced in each backend's emitted event /
      // row, so a transfer's reference travels with it. Metadata only — NOT a new
      // value type or token primitive. Absent => artifacts byte-unchanged.
      OptionalAttr<StrAttr>:$memo);
  // Verifier-enforced typed operands (WP1a, ): when an operand resolves to a declared
  // input of a governed value type, its category must match the role — party is a party,
  // amount is numeric (money/decimal), currency is a currency.
  let hasVerifier = 1;
}

def DebitOp : Neutrino_EntryOp<"debit"> {
  let summary = "A debit ledger movement.";
}

def CreditOp : Neutrino_EntryOp<"credit"> {
  let summary = "A credit ledger movement.";
}

def AssertBalancedOp : Neutrino_Op<"assert_balanced"> {
  let summary = "Invariant: total debits equal total credits at commit.";
}

def ParticipantOp : Neutrino_Op<"participant"> {
  let summary = "A declared participant: an abstract role (L1), not a concrete identity.";
  let description = [{
    Optional late-binding policy (Trust lane, T1): `binding = "to_be_bound"` marks
    this participant's slot as bound at realization time rather than fixed by the
    agreement. `bind_runtimes` lists the runtime/backend families allowed to
    realize it, and `bind_min_assurance` (A1-A4) is the minimum assurance tier a
    binding must meet. Absent `binding` => a fixed participant with no policy
    (artifacts byte-unchanged).
  }];
  let arguments = (ins StrAttr:$sym_name, StrAttr:$role,
                       OptionalAttr<StrArrayAttr>:$capabilities,
                       OptionalAttr<StrAttr>:$org,
                       OptionalAttr<StrAttr>:$binding,
                       OptionalAttr<StrArrayAttr>:$bind_runtimes,
                       OptionalAttr<StrAttr>:$bind_min_assurance);
  // The binding-policy invariants are enforced at the IR level too — .mlir fed
  // directly to neutrino-opt/neutrino-gen bypasses the frontend parser.
  let hasVerifier = 1;
}

def AllowOrgsOp : Neutrino_Op<"allow_orgs"> {
  let summary = "Topology policy: two organizations are permitted to coordinate.";
  let description = [{
    Optionally constrains the role each side's actors may take when coordinating
    across this pair (`role_a` applies to `org_a`, `role_b` to `org_b`). When a
    role is set, every value-moving leg authorized from that organization must be
    bound to a participant with the matching role (enforced by the Capability
    Security Pass).
  }];
  let arguments = (ins StrAttr:$org_a, StrAttr:$org_b,
                       OptionalAttr<StrAttr>:$role_a, OptionalAttr<StrAttr>:$role_b);
}

def AttestOp : Neutrino_Op<"attest"> {
  let summary = "An attestation policy on an evidence input (oracle consensus, ).";
  let description = [{
    The spec-declared M-of-N attestation policy carried by an `evidence` input
    (M5 oracle S1, ): a quorum threshold, an observer-set reference, a
    canonicalization mode (+ optional tolerance), an optional timeout, and a
    fail-closed fallback. Only the threshold M and the observer-set reference are
    portable spec — the concrete N and members are bound later. Optional
    observer-set trust metadata (assurance tier, independence posture; oracle
    S6, ) is declared here and surfaced by the security spec. The policy
    invariants are enforced at the IR level too, so a .mlir fed directly to
    neutrino-opt/neutrino-gen (bypassing the frontend parser) still fails closed.
  }];
  let arguments = (ins StrAttr:$input, I64Attr:$quorum, StrAttr:$observer_set,
                       StrAttr:$canonicalization, StrAttr:$fallback,
                       OptionalAttr<StrAttr>:$observer_role,
                       OptionalAttr<StrAttr>:$tolerance,
                       OptionalAttr<StrAttr>:$timeout,
                       OptionalAttr<StrAttr>:$assurance,
                       OptionalAttr<StrAttr>:$independence);
  let hasVerifier = 1;
}

def ObligationOp : Neutrino_Op<"obligation"> {
  let summary = "A first-class undertaking (L1 v0.2 O1, ): a scoped obligor "
                "commits, under an activation predicate, to an ordered set of "
                "value effects it AUTHORIZES.";
  let description = [{
    The structural centre of the provisionally-frozen Orthogonal L1 Algebra v0.2
    (strategy  /  R1a). An `obligation` is a first-class commitment whose
    identity + lifecycle are DISTINCT from effect execution: `debit`/`credit`
    remain effects it may AUTHORIZE (by ordered reference), never obligations
    themselves.

    Structure only — no CoordinationPlan lowering or backend activation ( R1a): this op is a verified
    substrate. It carries an explicit `$obligor`, a scoped `$beneficiary` and
    `$authority` (all references to declared `participant`s), an activation
    predicate (`$when` source text + the structured, typed `$when_ast` — the same
     machinery `compute`/guards use, so the predicate STRUCTURE + typing live
    in the IR and are verified here, with the `$when_deps` var leaves SSA-bound by
    slot), and an ORDERED `$effects` list of the value-effect (`debit`/`credit`)
    symbols it authorizes. The verifier resolves every reference structurally in
    the enclosing `procedure`; no domain vocabulary or target/backend name appears
    in op or verifier dispatch. Existing L1 programs are byte-unchanged because the
    op does nothing unless explicitly constructed.
  }];
  let arguments = (ins
      // The activation predicate's SSA dependencies: the inputs/computes the
      // $when_ast var leaves bind to, by slot (a single trailing variadic, so the
      // operand count is inferrable without AttrSizedOperandSegments).
      Variadic<Neutrino_ValueType>:$when_deps,
      StrAttr:$sym_name,
      StrAttr:$obligor,
      StrAttr:$beneficiary,
      StrAttr:$authority,
      // The activation predicate: `$when` is the source text (provenance/display);
      // `$when_ast` is the structured, typed comparison verified at IR-verify time
      // — the semantics. Both present or both absent (the verifier requires both).
      OptionalAttr<StrAttr>:$when,
      OptionalAttr<Neutrino_ExprAttr>:$when_ast,
      // The ORDERED value effects this obligation authorizes, by `debit`/`credit`
      // symbol. Order is part of the op's identity; the verifier resolves each to
      // a declared effect (never a participant or another obligation) and rejects
      // an empty/duplicated set.
      StrArrayAttr:$effects);
  let hasVerifier = 1;
}

def ProcedureOp : Neutrino_Op<"procedure", [NoTerminator]> {
  let summary = "A coordination procedure; its single-block region holds the ops.";
  let arguments = (ins StrAttr:$sym_name, OptionalAttr<StrAttr>:$trigger,
                       OptionalAttr<StrAttr>:$version,
                       OptionalAttr<StrAttr>:$instance_key);
  let regions = (region SizedRegion<1>:$body);
  let hasVerifier = 1;
}

#endif // NEUTRINO_OPS_TD

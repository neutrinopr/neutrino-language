//===- solidity_model_test.cpp - typed Solidity legalization model -----===//
//
// Target-model unit test: it asserts on the STRUCTURE graph materialization
// produces (not on printed bytes — the goldens pin those), covering attestation
// gating, the replay guard, the balanced obligation, the terminal transition,
// a nested conditional effect guard, and the TYPED declaration constructs the
// model owns (typed event/function parameters + a split storage slot), so the
// foundation is not just strings wrapped in structs. Legalization drives off
// the CoordinationPlan alone — there is no spec input to bind — so the model is
// single-source by construction. Links ONLY NeutrinoBackendSolidity, so it
// doubles as a leaf-boundary proof for the model TU.
//
//===----------------------------------------------------------------------===//

#include "SolidityRecipeProvider.h"
#include "SolidityRenderer.h"

#include "Neutrino/CoordinationPlan.h"
#include "Neutrino/Expr.h"

#include "llvm/Support/JSON.h"

#include <algorithm>
#include <cstdio>
#include <fstream>
#include <functional>
#include <sstream>
#include <string>

using namespace neutrino;
using namespace neutrino::solidity_model;

static int failures = 0;
static void check(bool ok, const char *what) {
  if (!ok) {
    fprintf(stderr, "solidity-model-test: FAIL: %s\n", what);
    ++failures;
  }
}

static SolidityContract materializeFile(const char *path) {
  std::ifstream in(path);
  std::stringstream ss;
  ss << in.rdbuf();
  llvm::Expected<llvm::json::Value> j = llvm::json::parse(ss.str());
  if (!j)
    llvm::report_fatal_error("spec is not valid JSON");
  llvm::Expected<CoordinationPlan> coordinationPlan =
      planFromSpec(*j->getAsObject());
  if (!coordinationPlan)
    llvm::report_fatal_error("spec failed coordination-plan normalization");
  llvm::Expected<projection::BackendProjectionGraph> graph =
      projection::projectBackendGraph(*coordinationPlan);
  if (!graph)
    llvm::report_fatal_error("backend projection failed");
  return materializeSolidityProjectionArtifact(*graph).contractModel;
}

// : the contract is ONE composed ContractShell node tree — there are no
// parallel semantic (statusEnum/events/storage/functions) or rendered-node
// (typeDeclarations/eventDecls/storageSlots/functionNodes) fields to inspect.
// These helpers read the single container body directly: the typed section
// nodes (EnumDecl, EventDecl, StorageDecl, FunctionSig) sit among the section
// blanks in the ContractShell's children, in source order.
static std::vector<const SolStmt *> bodyOfKind(const SolidityContract &m,
                                               SolStmt::Kind kind) {
  std::vector<const SolStmt *> out;
  if (m.containerNode)
    for (const SolStmt &c : m.containerNode->body)
      if (c.kind == kind)
        out.push_back(&c);
  return out;
}

// The execute()/accept() body is the LAST FunctionSig in the contract tree.
static const std::vector<SolStmt> &mainBody(const SolidityContract &m) {
  return bodyOfKind(m, SolStmt::Kind::FunctionSig).back()->body;
}

// Depth-first search for a statement of `kind` satisfying `pred` (recurses into
// Guarded bodies — that is where a conditional leg's statements live).
static bool anyStmt(const std::vector<SolStmt> &body, SolStmt::Kind kind,
                    const std::function<bool(const SolStmt &)> &pred) {
  for (const SolStmt &s : body) {
    if (s.kind == kind && pred(s))
      return true;
    if (!s.body.empty() && anyStmt(s.body, kind, pred))
      return true;
  }
  return false;
}

int main(int argc, char **argv) {
  if (argc < 4) {
    fprintf(stderr, "usage: solidity-model-test <attested-balanced-spec> "
                    "<guarded-spec> <explicit-time-spec>\n");
    return 2;
  }

  // (1) An attested + balanced coordination: the model is quorum-gated, carries
  // a constructor (guard binding) + execute(), and its body holds the replay
  // revert, the quorum revert, the balance obligation, and the terminal
  // transition — every DECISION legalization made, inspectable without
  // printing.
  SolidityContract gated = materializeFile(argv[1]);
  check(!gated.evidenceOnly, "attested spec is effectful (not evidence-only)");
  check(gated.gated, "attested spec legalizes to a quorum-gated contract");
  auto gatedEnums = bodyOfKind(gated, SolStmt::Kind::EnumDecl);
  check(gatedEnums.size() == 1 &&
            gatedEnums.front()->operand(1).find("Reconciled") !=
                std::string::npos,
        "effectful status enum has the Reconciled terminal");
  auto gatedFns = bodyOfKind(gated, SolStmt::Kind::FunctionSig);
  check(gatedFns.size() >= 2,
        "gated contract has a constructor + execute()");
  check(!gatedFns.front()->enumOrdinals.empty() &&
            gatedFns.front()->enumOrdinals[0] ==
                std::vector<int>{static_cast<int>(CallableKind::Constructor)},
        "the first function is the guard-binding constructor");
  const std::vector<SolStmt> &gb = mainBody(gated);
  check(anyStmt(gb, SolStmt::Kind::Require,
                [](const SolStmt &s) { return s.operand(1) == "replay"; }),
        "execute() has the replay revert guard");
  check(anyStmt(gb, SolStmt::Kind::Require,
                [](const SolStmt &s) {
                  return s.operand(1) == "quorum not accepted" &&
                         s.operand(0).find("isAccepted") != std::string::npos;
                }),
        "gated execute() reverts on an unaccepted quorum");
  check(
      anyStmt(gb, SolStmt::Kind::Require,
              [](const SolStmt &s) { return s.operand(1) == "not balanced"; }),
      "balanced coordination emits the balance-obligation revert");
  check(anyStmt(gb, SolStmt::Kind::Transition,
                [](const SolStmt &s) { return s.operand(0) == "Reconciled"; }),
        "execute() ends in the Reconciled state transition");

  // (2) The declaration constructs are TYPED, not opaque strings: execute()
  // carries a SolParam vector of named `u_` inputs; a ledger event declares
  // typed (type, name) parameters; and a storage slot is split into
  // type/modifiers/name (the printer, not the decl, computes the layout).
  const SolStmt *exec = gatedFns.back();
  check(!exec->group.empty() && exec->group.front().size() == 3 &&
            exec->group.front()[2].rfind("u_", 0) == 0,
        "execute() carries a typed parameter group of u_-named inputs");
  bool eventTyped = false;
  for (const SolStmt *e : bodyOfKind(gated, SolStmt::Kind::EventDecl))
    eventTyped |= e->group.size() >= 3 && e->group[0][0] == "string" &&
                  e->group[0][2] == "party" && e->group[1][0] == "uint256" &&
                  e->group[1][2] == "amount";
  check(eventTyped, "a ledger event declares typed (type, name) parameters");
  bool storageTyped = false;
  for (const SolStmt *s : bodyOfKind(gated, SolStmt::Kind::StorageDecl))
    if (s->operand(2) == "net")
      storageTyped = s->operand(0).find("mapping(") != std::string::npos &&
                     s->operand(1) == "public" && !s->comment.empty();
  check(storageTyped,
        "the net storage slot is split into type/modifiers/name (typed)");

  // (3) A conditional effect: the model carries a NESTED Guarded shape —
  // the leg's statements live inside `if (<predicate>) { … }` — proving guard
  // lowering is a typed shape, not a baked string.
  SolidityContract guarded = materializeFile(argv[2]);
  check(anyStmt(mainBody(guarded), SolStmt::Kind::Guarded,
                [](const SolStmt &s) { return !s.body.empty(); }),
        "a conditional effect legalizes to a nested Guarded block");

  // (3b) Explicit temporal inputs are genuine typed EVM values: the target
  // model carries `now` and `deadline` as uint256 parameters and lowers their
  // comparison as the condition on both guarded legs. This is independent of
  // fixture naming in production; the model decision comes from each input's
  // declared temporal type.
  SolidityContract temporal = materializeFile(argv[3]);
  const SolStmt *temporalExec =
      bodyOfKind(temporal, SolStmt::Kind::FunctionSig).back();
  auto hasUintParam = [&](const char *name) {
    return std::any_of(temporalExec->group.begin(), temporalExec->group.end(),
                       [&](const std::vector<std::string> &p) {
                         return p.size() == 3 && p[2] == name &&
                                p[0] == "uint256" && p[1].empty();
                       });
  };
  check(hasUintParam("u_now"),
        "the explicit now input legalizes to a uint256 parameter");
  check(hasUintParam("u_deadline"),
        "the explicit deadline input legalizes to a uint256 parameter");
  check(anyStmt(mainBody(temporal), SolStmt::Kind::Guarded,
                [](const SolStmt &s) {
                  return s.operand(0) == "u_now >= u_deadline" &&
                         !s.body.empty();
                }),
        "the explicit-time comparison guards the typed effect body");

  // (4) [] The generated node registry is CONSUMED by the model layer: the
  // metadata table covers every statement kind, in ordinal order, and each
  // row's Kind equals its table index (the enum + the table share the one
  // generated source). Removing/duplicating/reordering a .td record is caught
  // here and by the check_target_node_registry.py reconciliation gate.
  check(kSolNodeCount == 21,
        "generated node registry covers all 21 Solidity statement kinds");
  for (int i = 0; i < kSolNodeCount; ++i) {
    check(static_cast<int>(kSolNodeRegistry[i].kind) == i,
          "generated registry row Kind matches its ordinal (enum/table single "
          "source)");
    check(kSolNodeRegistry[i].name != nullptr &&
              kSolNodeRegistry[i].printerHandler != nullptr &&
              kSolNodeRegistry[i].requiredFeature != nullptr,
          "generated registry row carries name + printer-handler + feature "
          "metadata");
  }

  // (4b) [ endpoint] The CONSTRUCTION-LEVEL prohibition: every SolStmt ctor
  // routes through ensureAuthorable, which rejects the two verbatim `${text}`
  // kinds (Line/Block) by their enum VALUE — so forging one is impossible by
  // ANY spelling (a differently named factory, `Kind(0)`, a `static_cast`, a
  // C-style cast all reduce to the same value). This is the property a source
  // scanner could not guarantee. Direct negative tests for BOTH kinds and BOTH
  // the named and the ordinal/cast spellings; a legitimate kind passes.
  auto guardRejects = [](SolStmt::Kind k) {
    try {
      SolStmt::ensureAuthorable(k);
    } catch (const ExprError &) {
      return true;
    }
    return false;
  };
  check(guardRejects(SolStmt::Kind::Line),
        "ensureAuthorable rejects Kind::Line (verbatim raw authoring)");
  check(guardRejects(SolStmt::Kind::Block),
        "ensureAuthorable rejects Kind::Block (verbatim raw authoring)");
  check(guardRejects(static_cast<SolStmt::Kind>(0)),
        "ensureAuthorable rejects the Line ordinal via static_cast (spelling-"
        "independent — closes the Kind(0) bypass)");
  check(guardRejects(SolStmt::Kind(6)),
        "ensureAuthorable rejects the Block ordinal via a functional cast");
  check(!guardRejects(SolStmt::Kind::Require),
        "ensureAuthorable ACCEPTS a structured kind (Require) — the guard is "
        "precise, not a blanket refusal");
  // BEHAVIORAL — the actual construction seam, not just the predicate. The
  // witness accepts only a Kind and returns only a bool, so it cannot expose a
  // constructed statement or private-constructor authority.
  check(SolStmt::rejectsAtConstructionForTest(SolStmt::Kind::Line),
        "constructing Kind::Line through the ctor seam is rejected");
  check(SolStmt::rejectsAtConstructionForTest(SolStmt::Kind::Block),
        "constructing Kind::Block through the ctor seam is rejected");
  check(SolStmt::rejectsAtConstructionForTest(static_cast<SolStmt::Kind>(0)),
        "constructing the Line ordinal (Kind(0)) through the ctor seam is "
        "rejected — the reviewer's exact bypass, closed at construction");
  check(SolStmt::rejectsAtConstructionForTest(SolStmt::Kind(6)),
        "constructing the Block ordinal through the ctor seam is rejected");
  check(!SolStmt::rejectsAtConstructionForTest(SolStmt::Kind::Require),
        "a structured kind still constructs through the guarded ctor");

  // (5) [ slice 2a] localDecl enforces its lexical contract: a statement
  // separator (';' OR newline) smuggled through EITHER the declaration type or
  // the name is rejected — otherwise a caller could launder a raw statement
  // past the syntax-authority ratchet — while a well-formed declaration is
  // accepted. Each channel/separator is exercised independently, and only the
  // specific ExprError is caught (not every exception), so the contract bite is
  // precise.
  auto rejects = [](const char *type, const char *name, const char *init) {
    try {
      (void)SolStmt::localDecl(type, name, init);
    } catch (const ExprError &) {
      return true;
    }
    return false;
  };
  check(rejects("uint256 x; selfdestruct(); uint256", "y", "0"),
        "localDecl rejects a ';' separator smuggled through the type");
  check(rejects("bytes32", "_k; selfdestruct()", "0"),
        "localDecl rejects a ';' separator smuggled through the name");
  check(rejects("bytes32\nselfdestruct();\nbytes32", "_k", "0"),
        "localDecl rejects a newline separator smuggled through the type");
  check(rejects("bytes32", "_k\nselfdestruct()", "0"),
        "localDecl rejects a newline separator smuggled through the name");
  bool acceptsWellFormed = true;
  try {
    (void)SolStmt::localDecl("bytes32", "_k", "keccak256(bytes(u_ref))");
  } catch (const ExprError &) {
    acceptsWellFormed = false;
  }
  check(acceptsWellFormed, "localDecl accepts a well-formed declaration");

  // (6) [ slice 2b] assign enforces the SAME lexical contract on BOTH
  // operands: unlike localDecl's expression-boundary `init`, the assignment rhs
  // is part of the `.td`-framed shell (`${lhs} = ${rhs};`), so a separator in
  // the lhs OR the rhs is rejected (it would launder a second statement). Each
  // channel/separator is exercised independently, catching only ExprError.
  auto rejectsAssign = [](const char *lhs, const char *rhs) {
    try {
      (void)SolStmt::assign(lhs, rhs);
    } catch (const ExprError &) {
      return true;
    }
    return false;
  };
  check(rejectsAssign("_progress; selfdestruct()", "true"),
        "assign rejects a ';' separator smuggled through the lhs");
  check(rejectsAssign("_progress", "true; selfdestruct()"),
        "assign rejects a ';' separator smuggled through the rhs");
  check(rejectsAssign("attested[_k]\nselfdestruct()", "true"),
        "assign rejects a newline separator smuggled through the lhs");
  check(rejectsAssign("attested[_k]", "true\nselfdestruct()"),
        "assign rejects a newline separator smuggled through the rhs");
  bool acceptsWellFormedAssign = true;
  try {
    (void)SolStmt::assign("keyClaim[_k]", "_claim");
  } catch (const ExprError &) {
    acceptsWellFormedAssign = false;
  }
  check(acceptsWellFormedAssign, "assign accepts a well-formed assignment");

  // (7) [ slice 2c] compoundAssign closes an ADDITIONAL laundering channel
  // — the operator: it must be exactly `+=` or `-=` (a closed vocabulary), so
  // an operator carrying arbitrary grammar is rejected, in addition to the same
  // lhs/rhs separator contract. Each channel is exercised independently.
  auto rejectsCompound = [](const char *lhs, const char *op, const char *rhs) {
    try {
      (void)SolStmt::compoundAssign(lhs, op, rhs);
    } catch (const ExprError &) {
      return true;
    }
    return false;
  };
  check(rejectsCompound("net[_k]", "= x; selfdestruct(); y +=", "int256(1)"),
        "compoundAssign rejects an operator outside the {+=,-=} vocabulary");
  check(rejectsCompound("net[_k]", "*=", "int256(1)"),
        "compoundAssign rejects a non-+=/-= compound operator");
  check(rejectsCompound("net[_k]; selfdestruct()", "+=", "int256(1)"),
        "compoundAssign rejects a ';' separator smuggled through the lhs");
  check(rejectsCompound("net[_k]", "+=", "int256(1); selfdestruct()"),
        "compoundAssign rejects a ';' separator smuggled through the rhs");
  check(rejectsCompound("net[_k]\nselfdestruct()", "-=", "int256(1)"),
        "compoundAssign rejects a newline separator smuggled through the lhs");
  check(rejectsCompound("net[_k]", "-=", "int256(1)\nselfdestruct()"),
        "compoundAssign rejects a newline separator smuggled through the rhs");
  bool acceptsWellFormedCompound = true;
  try {
    (void)SolStmt::compoundAssign("debitTotal[_k]", "+=", "u_amount");
    (void)SolStmt::compoundAssign("net[_k][\"x\"]", "-=", "int256(u_amount)");
  } catch (const ExprError &) {
    acceptsWellFormedCompound = false;
  }
  check(acceptsWellFormedCompound,
        "compoundAssign accepts well-formed += and -= updates");

  // (8) [ slice 1] docComment owns the `/// ` framing on a SINGLE line: it
  // rejects EVERY Solidity comment terminator (LF/VT/FF/CR/NEL/LS/PS, each of
  // which would end the comment and leave the suffix as live source), exercised
  // independently, while ordinary comment text — including a ';' (legal in a
  // comment) and a non-terminator multi-byte char like the em-dash U+2014 — is
  // accepted.
  auto rejectsDoc = [](const std::string &text) {
    try {
      (void)SolStmt::docComment(text);
    } catch (const ExprError &) {
      return true;
    }
    return false;
  };
  check(rejectsDoc(std::string("harmless\nselfdestruct();")),
        "docComment rejects LF (U+000A)");
  check(rejectsDoc(std::string("harmless\vselfdestruct();")),
        "docComment rejects VT (U+000B)");
  check(rejectsDoc(std::string("harmless\fselfdestruct();")),
        "docComment rejects FF (U+000C)");
  check(rejectsDoc(std::string("harmless\rselfdestruct();")),
        "docComment rejects CR (U+000D)");
  check(rejectsDoc(std::string("harmless\xC2\x85selfdestruct();")),
        "docComment rejects NEL (U+0085)");
  check(rejectsDoc(std::string("harmless\xE2\x80\xA8selfdestruct();")),
        "docComment rejects LS (U+2028)");
  check(rejectsDoc(std::string("harmless\xE2\x80\xA9selfdestruct();")),
        "docComment rejects PS (U+2029)");
  bool acceptsWellFormedDoc = true;
  try {
    // A ';' and a non-terminator multi-byte char (em-dash U+2014 = E2 80 94,
    // NOT LS/PS E2 80 A8/A9) are legal inside a single-line comment.
    (void)SolStmt::docComment("COORDINATION CONTRACT \xE2\x80\x94 keyed by "
                              "workflow key; instances never share status.");
  } catch (const ExprError &) {
    acceptsWellFormedDoc = false;
  }
  check(acceptsWellFormedDoc,
        "docComment accepts single-line text (';' + em-dash allowed)");

  // (9) [ slice 2] spdxLicense owns the `// SPDX-License-Identifier: `
  // directive: the license must be NON-EMPTY and carry no Solidity line
  // terminator (any of which would end the `//` comment), while a bare id AND a
  // multi-token SPDX expression (spaces legal) are accepted.
  auto rejectsSpdx = [](const std::string &license) {
    try {
      (void)SolStmt::spdxLicense(license);
    } catch (const ExprError &) {
      return true;
    }
    return false;
  };
  check(rejectsSpdx(std::string()), "spdxLicense rejects an empty license");
  check(rejectsSpdx(std::string("MIT\nselfdestruct();")),
        "spdxLicense rejects LF in the license");
  check(rejectsSpdx(std::string("MIT\vselfdestruct();")),
        "spdxLicense rejects VT in the license");
  check(rejectsSpdx(std::string("MIT\xE2\x80\xA8selfdestruct();")),
        "spdxLicense rejects LS (U+2028) in the license");
  bool acceptsWellFormedSpdx = true;
  try {
    (void)SolStmt::spdxLicense("MIT");
    (void)SolStmt::spdxLicense(
        "MIT OR Apache-2.0"); // SPDX expression (spaces ok)
  } catch (const ExprError &) {
    acceptsWellFormedSpdx = false;
  }
  check(acceptsWellFormedSpdx,
        "spdxLicense accepts a bare id and a multi-token SPDX expression");

  // (10) [ slice 3] pragma owns the `pragma solidity ` prefix and the
  // trailing `;`: the version must be NON-EMPTY and carry no statement
  // separator
  // (';' or newline, either of which would launder a second statement past the
  // framing), while a range expression (spaces legal) is accepted.
  auto rejectsPragma = [](const std::string &version) {
    try {
      (void)SolStmt::pragma(version);
    } catch (const ExprError &) {
      return true;
    }
    return false;
  };
  check(rejectsPragma(std::string()), "pragma rejects an empty version");
  check(rejectsPragma(std::string("^0.8.20; selfdestruct()")),
        "pragma rejects a ';' in the version");
  check(rejectsPragma(std::string("^0.8.20\nselfdestruct();")),
        "pragma rejects a newline in the version");
  bool acceptsWellFormedPragma = true;
  try {
    (void)SolStmt::pragma("^0.8.20");
    (void)SolStmt::pragma(">=0.8.0 <0.9.0"); // range pragma (spaces ok)
  } catch (const ExprError &) {
    acceptsWellFormedPragma = false;
  }
  check(acceptsWellFormedPragma,
        "pragma accepts a caret pin and a multi-token version range");

  // (11) [ slice 4] importUnit owns the `import "` prefix and the closing
  // `";`: the path must be NON-EMPTY and carry no double quote (which would
  // close the framed string) and no statement separator (';' or newline), while
  // a plain relative path is accepted.
  auto rejectsImport = [](const std::string &path) {
    try {
      (void)SolStmt::importUnit(path);
    } catch (const ExprError &) {
      return true;
    }
    return false;
  };
  check(rejectsImport(std::string()), "importUnit rejects an empty path");
  check(
      rejectsImport(std::string("./X.sol\"; selfdestruct(); import \"./Y.sol")),
      "importUnit rejects a double quote in the path");
  check(rejectsImport(std::string("./X.sol\nimport \"./Y.sol")),
        "importUnit rejects a newline in the path");
  check(rejectsImport(std::string("./X.sol\"; import \"./Y.sol\";")),
        "importUnit rejects a statement separator in the path");
  // A trailing backslash escapes the .td's closing quote: `import "./X.sol\";`
  // — the `;` becomes part of the string literal, so the framing is broken.
  check(rejectsImport(std::string("./X.sol\\")),
        "importUnit rejects a trailing backslash (escapes the closing quote)");
  check(rejectsImport(std::string("./X\\nY.sol")),
        "importUnit rejects an interior backslash (escape sequence)");
  // A non-LF/CR line terminator (NEL U+0085, multi-byte) and a bare control
  // byte (VT U+000B) cannot appear literally in the quoted string either.
  check(rejectsImport(std::string("./X\xC2\x85Y.sol")),
        "importUnit rejects NEL (U+0085) in the path");
  check(rejectsImport(std::string("./X\x0bY.sol")),
        "importUnit rejects a VT control byte in the path");
  bool acceptsWellFormedImport = true;
  try {
    (void)SolStmt::importUnit("./CoordinationEnvelope.sol");
  } catch (const ExprError &) {
    acceptsWellFormedImport = false;
  }
  check(acceptsWellFormedImport, "importUnit accepts a plain relative path");

  // (11b) [] The status enum is a TYPED EnumDecl node built in legalization
  // (not printed ad-hoc): the contract carries it in typeDeclarations with the
  // decided name + comma-joined variant operands. The factory rejects the
  // framing punctuation ('{', '}', ';', newline) in either operand, while a
  // well-formed enum is accepted.
  check(gatedEnums.size() == 1 &&
            gatedEnums.front()->operand(0) == "Status" &&
            gatedEnums.front()->operand(1).find("Reconciled") !=
                std::string::npos,
        "the status enum legalizes to a typed EnumDecl node (name + variants)");
  auto rejectsEnum = [](const std::string &name, const std::string &variants) {
    try {
      (void)SolStmt::enumDecl(name, variants);
    } catch (const ExprError &) {
      return true;
    }
    return false;
  };
  check(rejectsEnum("", "None"), "enumDecl rejects an empty name");
  check(rejectsEnum("Status", ""), "enumDecl rejects empty variants");
  check(rejectsEnum("Status", "None } selfdestruct(); enum X {"),
        "enumDecl rejects a '}' in the variants (breaks the framing)");
  check(rejectsEnum("Sta;tus", "None"), "enumDecl rejects a ';' in the name");
  check(rejectsEnum("Status", "None\nReconciled"),
        "enumDecl rejects a newline in the variants");
  bool acceptsWellFormedEnum = true;
  try {
    (void)SolStmt::enumDecl("Status", "None, Reconciled");
  } catch (const ExprError &) {
    acceptsWellFormedEnum = false;
  }
  check(acceptsWellFormedEnum,
        "enumDecl accepts a well-formed enum declaration");

  // (11c) [] The storage slots legalize to ONE authoritative record each —
  // a typed StorageDecl node bundled with its comment (StorageSlot), so the
  // printer never indexes a decl against a separately-stored comment. Each node
  // carries the decided type/modifiers/name operands; the factory rejects
  // framing punctuation, and the comment column is aligned generically by the
  // printer.
  auto gatedStorage = bodyOfKind(gated, SolStmt::Kind::StorageDecl);
  check(!gatedStorage.empty() &&
            std::all_of(gatedStorage.begin(), gatedStorage.end(),
                        [](const SolStmt *d) {
                          return d->kind == SolStmt::Kind::StorageDecl &&
                                 d->operands.size() == 3;
                        }),
        "each storage slot legalizes to a typed StorageDecl node carrying "
        "type/modifiers/name operands in the contract tree");
  auto rejectsStorage = [](const std::string &type, const std::string &mods,
                           const std::string &name) {
    try {
      (void)SolStmt::storageDecl(type, mods, name, "");
    } catch (const ExprError &) {
      return true;
    }
    return false;
  };
  check(rejectsStorage("", "public", "x"), "storageDecl rejects an empty type");
  check(rejectsStorage("uint256", "public", ""),
        "storageDecl rejects an empty name");
  check(rejectsStorage("uint256; selfdestruct()", "public", "x"),
        "storageDecl rejects a ';' in the type");
  check(rejectsStorage("uint256", "public", "x\ny"),
        "storageDecl rejects a newline in the name");
  bool acceptsWellFormedStorage = true;
  try {
    (void)SolStmt::storageDecl("mapping(bytes32 => Status)", "public",
                               "statusOf", "");
    (void)SolStmt::storageDecl("IThresholdQuorumAcceptance", "public immutable",
                               "acceptanceGuard", "");
  } catch (const ExprError &) {
    acceptsWellFormedStorage = false;
  }
  check(acceptsWellFormedStorage,
        "storageDecl accepts a mapping slot and a public-immutable slot");

  // (11d) [ §7] Each event legalizes to a typed EventDecl node: operand(0)
  // is the name (scalar), and the PARAMETERS are the node's REPEATED group —
  // one
  // `[type, location, name]` value vector per parameter — so the per-parameter
  // shape and the `, ` separator are TableGen-owned (applied by the generated
  // printer), NOT a pre-joined string on the node. The construct reaches the
  // tree as decided values, never a re-authored `event (...)` string.
  auto gatedEvents = bodyOfKind(gated, SolStmt::Kind::EventDecl);
  check(!gatedEvents.empty() &&
            std::all_of(gatedEvents.begin(), gatedEvents.end(),
                        [](const SolStmt *d) {
                          return d->kind == SolStmt::Kind::EventDecl &&
                                 d->operands.size() == 1;
                        }),
        "each event legalizes to a typed EventDecl node (name operand + a "
        "[type, location, name] group item per parameter) in the contract tree");
  // A multi-parameter event proves the parameters land as SEPARATE structured
  // group items (not one hidden pre-joined string) — the generated projection,
  // not the model, applies the `, ` separator.
  bool hasMultiParamEvent = false;
  for (const SolStmt *d : gatedEvents)
    if (d->group.size() >= 2)
      hasMultiParamEvent = true;
  check(hasMultiParamEvent,
        "a multi-parameter event carries one group item per parameter");
  auto rejectsEvent = [](const std::string &name,
                         std::vector<SolParam> params) {
    try {
      (void)SolStmt::eventDecl(name, std::move(params));
    } catch (const ExprError &) {
      return true;
    }
    return false;
  };
  check(rejectsEvent("", {{"string", "", "x"}}),
        "eventDecl rejects an empty name");
  check(rejectsEvent("Ev(nt", {{"string", "", "x"}}),
        "eventDecl rejects a '(' in the name (breaks the parens framing)");
  // The TYPED boundary: a parameter with an EMPTY type is malformed (would emit
  // a stray `, ` around nothing) — rejected, so the group can only hold
  // well-formed 3-slot items with a real type (an empty item is unrepresentable
  // here).
  check(rejectsEvent("Evt", {{"", "", "x"}}),
        "eventDecl rejects a parameter with an empty type");
  check(rejectsEvent("Evt", {{"string", "", "party"}, {"", "", ""}}),
        "eventDecl rejects an empty parameter item before a real one");
  check(rejectsEvent("Evt", {{"string", "", "x) selfdestruct(); event Y("}}),
        "eventDecl rejects a ')' in a parameter field (breaks out of the "
        "parens)");
  check(rejectsEvent("Evt", {{"string", "", "x; selfdestruct()"}}),
        "eventDecl rejects a ';' in a parameter field (laundered statement)");
  check(
      rejectsEvent("Evt", {{"string", "", "x, uint256 forged"}}),
      "eventDecl rejects a ',' in a parameter field (forged extra parameter)");
  check(rejectsEvent("Evt", {{"string", "", "x\ny"}}),
        "eventDecl rejects a newline in a parameter field");
  check(rejectsEvent("Evt", {{"uint256; selfdestruct()", "", "x"}}),
        "eventDecl rejects a ';' smuggled through the type field");
  //  review P1.2: the same comment/terminator escape closed on the event
  // parameter list (it shares validateParam with the function signature).
  check(rejectsEvent("Evt", {{"uint256 //", "", "x"}}),
        "eventDecl rejects a '//' comment in a parameter type");
  check(rejectsEvent("Evt", {{"uint256", "elsewhere", "x"}}),
        "eventDecl rejects an unknown parameter data location");
  bool acceptsWellFormedEvent = true;
  try {
    (void)SolStmt::eventDecl(
        "Transfer", {{"string", "", "party"}, {"uint256", "", "amount"}});
    (void)SolStmt::eventDecl("WithLocation", {{"bytes", "calldata", "data"}});
    (void)SolStmt::eventDecl("Anon",
                             {{"uint256", "", ""}}); // anonymous is legal
    (void)SolStmt::eventDecl("Ping", {}); // a no-argument event is well-formed
  } catch (const ExprError &) {
    acceptsWellFormedEvent = false;
  }
  check(acceptsWellFormedEvent,
        "eventDecl accepts multi-param, data-location, anonymous, and no-arg "
        "events");

  // (11e) [] Each function legalizes to a typed FunctionSig BLOCK node: the
  // only string operand is the (optional) NAME; the callable kind and modifier
  // list are typed ENUM ordinals (group 0 = the scalar kind, group 1 = the
  // ordered modifier list) that the generated printer spells from `.td`-owned
  // tables; the PARAMETERS are the node's repeated group ([type, location,
  // name] per parameter); and the function body is the node's `body` children —
  // so the whole `<keyword> <name>(<params>) <modifiers> { … }` framing is
  // TableGen- owned, not a handwritten signature() string.
  auto gatedFunctions = bodyOfKind(gated, SolStmt::Kind::FunctionSig);
  check(!gatedFunctions.empty() &&
            std::all_of(gatedFunctions.begin(), gatedFunctions.end(),
                        [](const SolStmt *fn) {
                          // name operand + two enum-ordinal groups (scalar
                          // callable kind, repeated modifier list).
                          return fn->kind == SolStmt::Kind::FunctionSig &&
                                 fn->operands.size() == 1 &&
                                 fn->enumOrdinals.size() == 2 &&
                                 fn->enumOrdinals[0].size() == 1;
                        }),
        "each function legalizes to a typed FunctionSig node (name operand + "
        "kind/modifier enum ordinal groups + param group + body) in the tree");
  bool sawConstructor = false, sawParams = false, sawModifier = false;
  for (const SolStmt *fn : gatedFunctions) {
    if (fn->enumOrdinals[0] ==
        std::vector<int>{static_cast<int>(CallableKind::Constructor)})
      sawConstructor = true; // an empty-name/no-modifier callable
    if (!fn->group.empty())
      sawParams = true;
    if (!fn->enumOrdinals[1].empty())
      sawModifier = true;
  }
  check(sawConstructor && sawParams && sawModifier,
        "the gated contract exercises a constructor (no name/modifier), a "
        "parameterized function, and a modifiered function");
  using CK = CallableKind;
  using CM = CallableModifier;
  auto rejectsFn = [](CK kind, const std::string &nm, std::vector<CM> mods,
                      std::vector<SolParam> params) {
    try {
      (void)SolStmt::functionSig(kind, nm, std::move(mods), std::move(params),
                                 {});
    } catch (const ExprError &) {
      return true;
    }
    return false;
  };
  // Cardinality: the closed callable-kind enum makes an unknown/compound
  // keyword UNREPRESENTABLE; what remains is the name cardinality per
  // alternative.
  check(rejectsFn(CK::Constructor, "named", {}, {}),
        "functionSig rejects a named constructor (cardinality)");
  check(rejectsFn(CK::Function, "", {CM::External}, {}),
        "functionSig rejects a nameless function (cardinality)");
  check(rejectsFn(CK::Function, "1f", {CM::External}, {}),
        "functionSig rejects a non-identifier function name");
  check(rejectsFn(CK::Function, "f x", {CM::External}, {}),
        "functionSig rejects a space in the function name");
  // Modifier SEMANTICS the shape table must not own: canonical order, no
  // duplicates, at most one visibility + one mutability. The closed enum makes
  // an unknown/compound modifier token unrepresentable; these are the remaining
  // cardinality/order rules.
  check(rejectsFn(CK::Function, "f", {CM::External, CM::External}, {}),
        "functionSig rejects a duplicated modifier");
  check(rejectsFn(CK::Function, "f", {CM::View, CM::External}, {}),
        "functionSig rejects non-canonical (descending) modifier order");
  check(rejectsFn(CK::Function, "f", {CM::External, CM::Public}, {}),
        "functionSig rejects two visibility modifiers");
  check(rejectsFn(CK::Function, "f", {CM::View, CM::Pure}, {}),
        "functionSig rejects two mutability modifiers");
  // Domain: the `Count` terminal sentinel and any out-of-range enum cast are
  // out-of-vocabulary and rejected at the factory boundary — the finalized
  // model never carries an invalid ordinal ( review).
  check(rejectsFn(CK::Count, "f", {CM::External}, {}),
        "functionSig rejects the Count sentinel as a callable kind");
  check(rejectsFn(static_cast<CK>(99), "f", {CM::External}, {}),
        "functionSig rejects an out-of-range callable-kind cast");
  check(rejectsFn(CK::Function, "f", {CM::Count}, {}),
        "functionSig rejects the Count sentinel as a modifier");
  check(rejectsFn(CK::Function, "f", {static_cast<CM>(99)}, {}),
        "functionSig rejects an out-of-range modifier cast");
  // Framing / comment / terminator / control escape ( review P1.2). The
  // name is validated as a Solidity identifier; the parameters via
  // validateParam.
  check(rejectsFn(CK::Function, "f(", {CM::External}, {}),
        "functionSig rejects a '(' in the name");
  check(rejectsFn(CK::Function, "f", {CM::External}, {{"uint256 {", "", "x"}}),
        "functionSig rejects a '{' in a parameter type");
  check(rejectsFn(CK::Function, "f //", {CM::External}, {}),
        "functionSig rejects a '//' comment in the name (comment escape)");
  check(rejectsFn(CK::Function, "f", {CM::External}, {{"uint256 //", "", "x"}}),
        "functionSig rejects a '//' comment in a parameter type");
  check(
      rejectsFn(CK::Function, "f", {CM::External}, {{"uint256\x0b", "", "x"}}),
      "functionSig rejects a vertical-tab terminator in a parameter type");
  check(rejectsFn(CK::Function, "f", {CM::External},
                  {{"uint256\xe2\x80\xa8", "", "x"}}),
        "functionSig rejects a U+2028 line-separator in a parameter type");
  check(rejectsFn(CK::Function, "f", {CM::External}, {{"", "", "x"}}),
        "functionSig rejects a parameter with an empty type");
  check(rejectsFn(CK::Function, "f", {CM::External},
                  {{"uint256; evil()", "", "x"}}),
        "functionSig rejects a ';' smuggled through a parameter type");
  check(rejectsFn(CK::Function, "f", {CM::External},
                  {{"uint256", "elsewhere", "x"}}),
        "functionSig rejects an unknown parameter data location");
  check(rejectsFn(CK::Function, "f", {CM::External}, {{"uint256", "", "1bad"}}),
        "functionSig rejects a non-identifier parameter name");
  bool acceptsWellFormedFn = true;
  try {
    // A canonical visibility+mutability pair (external precedes view).
    (void)SolStmt::functionSig(CK::Function, "execute",
                               {CM::External, CM::View},
                               {{"string", "calldata", "u_x"}}, {});
    (void)SolStmt::functionSig(CK::Constructor, "", {}, {{"address", "", "g"}},
                               {}); // no name/modifiers
  } catch (const ExprError &) {
    acceptsWellFormedFn = false;
  }
  check(acceptsWellFormedFn,
        "functionSig accepts a canonically-modifiered function and a bare "
        "constructor");

  // (11f) [ slice 2] The contract CONTAINER is a typed ContractShell BLOCK
  // node: `contractShell(name)` validates the name as a Solidity identifier (so
  // nothing can break out of the generated `contract <name> {` framing) and
  // carries only that name operand — the container body is passed to the
  // generated Block renderer by the printer, not held here.
  {
    SolStmt shell = SolStmt::contractShell("Ledger", {});
    check(shell.kind == SolStmt::Kind::ContractShell &&
              shell.operands == std::vector<std::string>{"Ledger"} &&
              shell.body.empty() && shell.group.empty() &&
              shell.enumOrdinals.empty(),
          "contractShell builds a ContractShell node carrying its name (empty "
          "body here) — the  body-carrying overload");
    auto rejectsShell = [](const std::string &nm) {
      try {
        (void)SolStmt::contractShell(nm, {});
      } catch (const ExprError &) {
        return true;
      }
      return false;
    };
    check(rejectsShell(""), "contractShell rejects an empty name");
    check(rejectsShell("1Bad"), "contractShell rejects a non-identifier name");
    check(rejectsShell("Evil { selfdestruct"),
          "contractShell rejects framing punctuation in the name");
    check(rejectsShell("A // x"),
          "contractShell rejects a comment in the name");

    // POSITIVE invariant: every projection-materialization path establishes
    // ContractShell container node, carrying the contract name — the printer
    // renders it, never constructs it.
    check(gated.containerNode.has_value() &&
              gated.containerNode->kind == SolStmt::Kind::ContractShell &&
              gated.containerNode->operands ==
                  std::vector<std::string>{gated.name},
          "projection materialization establishes a ContractShell with the "
          "contract name");
    check(
        guarded.containerNode.has_value(),
        "the guarded (evidence) legalize path also establishes the container");

    // NEGATIVE fail-closed: a contract that never went through legalization (no
    // container node) cannot reach output — the renderer refuses rather than
    // dereferencing an empty optional (UB).
    bool refusesMissingContainer = false;
    try {
      SolidityContract bare;
      bare.name = "NoContainer";
      (void)renderSolidityProjection(bare);
    } catch (const ExprError &) {
      refusesMissingContainer = true;
    }
    check(refusesMissingContainer,
          "renderer fails closed on a contract with no container node");
  }

  // (11g) [ slice 3a/3b] The quorum-guard interface is fully typed: each
  // method SIGNATURE is a leaf carrying its name + return type operands and its
  // parameter group (3a), and the `interface … {` SHELL is a typed
  // InterfaceShell block nesting those signatures (3b) — proving the last raw
  // seam site (the rawBlock shell) is gone and  reached zero.
  {
    SolStmt sig = SolStmt::interfaceSignature(
        "isAccepted", {{"bytes32", "", "claimId"}}, "bool");
    check(
        sig.kind == SolStmt::Kind::InterfaceSignature &&
            sig.operands == std::vector<std::string>{"isAccepted", "bool"} &&
            sig.group == std::vector<std::vector<std::string>>{{"bytes32", "",
                                                                "claimId"}},
        "interfaceSignature carries name + return type operands + param group");
    // The gated header carries a typed InterfaceShell nesting exactly two typed
    // signatures (the name operand is the guard-interface ABI name).
    bool headerHasTypedShell = false;
    for (const SolStmt &hs : gated.header)
      if (hs.kind == SolStmt::Kind::InterfaceShell && hs.body.size() == 2 &&
          hs.operands ==
              std::vector<std::string>{"IThresholdQuorumAcceptance"} &&
          hs.body[0].kind == SolStmt::Kind::InterfaceSignature &&
          hs.body[1].kind == SolStmt::Kind::InterfaceSignature)
        headerHasTypedShell = true;
    check(headerHasTypedShell,
          "the gated header carries a typed InterfaceShell nesting two typed "
          "signatures");
    auto rejectsSig = [](const std::string &nm, std::vector<SolParam> ps,
                         const std::string &ret) {
      try {
        (void)SolStmt::interfaceSignature(nm, std::move(ps), ret);
      } catch (const ExprError &) {
        return true;
      }
      return false;
    };
    check(rejectsSig("1bad", {}, "bool"),
          "interfaceSignature rejects a non-identifier method name");
    check(rejectsSig("f", {}, ""),
          "interfaceSignature rejects an empty return type");
    check(rejectsSig("f", {}, "bool) external { selfdestruct"),
          "interfaceSignature rejects framing punctuation in the return type");
    check(
        rejectsSig("f", {{"bytes32; evil()", "", "x"}}, "bool"),
        "interfaceSignature rejects a smuggled statement in a parameter type");
  }

  // (12) [ slice 5] The source-unit directives emit in Solidity's REQUIRED,
  // deterministic order: the SPDX license comment FIRST, then the version
  // pragma, then any imports — before the contract body. The order is asserted
  // on the REAL legalized headers, so a production reorder (e.g. pragma before
  // SPDX, or an import ahead of the pragma) bites here. The bytes are
  // unchanged; this pins the directive ORDER, not new syntax. The check is
  // non-vacuous — reordered directive sequences fail it (so it cannot pass a
  // reordered production header).
  auto directiveOrderOk = [](const std::vector<SolStmt> &header) {
    int spdx = -1, prag = -1, imp = -1, body = -1;
    for (int i = 0; i < static_cast<int>(header.size()); ++i)
      switch (header[i].kind) {
      case SolStmt::Kind::SpdxLicense:
        if (spdx < 0)
          spdx = i;
        break;
      case SolStmt::Kind::Pragma:
        if (prag < 0)
          prag = i;
        break;
      case SolStmt::Kind::Import:
        if (imp < 0)
          imp = i;
        break;
      case SolStmt::Kind::DocComment:
      case SolStmt::Kind::Blank:
        break; // comments/framing may sit anywhere ahead of the body
      default:
        if (body < 0)
          body = i; // the first body construct (e.g. the guard-interface Block)
        break;
      }
    if (spdx != 0 || prag < 0 || spdx >= prag)
      return false; // SPDX must be the first directive; the pragma follows it
    if (imp >= 0 && prag >= imp)
      return false; // imports (when present) follow the pragma
    if (body >= 0) {
      // ALL source-unit directives must precede the first body construct.
      if (spdx >= body || prag >= body || (imp >= 0 && imp >= body))
        return false;
    }
    return true;
  };
  check(
      directiveOrderOk(gated.header),
      "effectful source-unit directives are in canonical order (SPDX, pragma)");
  check(directiveOrderOk(guarded.header),
        "guarded source-unit directives are in canonical order (SPDX, pragma)");
  // Non-vacuity: reordered sequences must FAIL. A Require stands in for a body
  // construct (any non-directive/non-comment/non-blank kind).
  check(
      !directiveOrderOk(
          {SolStmt::pragma("^0.8.20"), SolStmt::spdxLicense("MIT")}),
      "the directive-order invariant bites when the pragma precedes the SPDX");
  check(
      !directiveOrderOk({SolStmt::spdxLicense("MIT"),
                         SolStmt::importUnit("./X.sol"),
                         SolStmt::pragma("^0.8.20")}),
      "the directive-order invariant bites when an import precedes the pragma");
  check(!directiveOrderOk({SolStmt::spdxLicense("MIT"),
                           SolStmt::require("cond", "reason"),
                           SolStmt::pragma("^0.8.20")}),
        "the directive-order invariant bites when a body precedes the pragma");
  check(!directiveOrderOk({SolStmt::spdxLicense("MIT"),
                           SolStmt::pragma("^0.8.20"),
                           SolStmt::require("cond", "reason"),
                           SolStmt::importUnit("./X.sol")}),
        "the directive-order invariant bites when an import follows the body");
  // The canonical SPDX -> pragma -> import -> body sequence satisfies it.
  check(directiveOrderOk(
            {SolStmt::spdxLicense("MIT"), SolStmt::pragma("^0.8.20"),
             SolStmt::blank(), SolStmt::importUnit("./CoordinationEnvelope.sol"),
             SolStmt::blank(), SolStmt::require("cond", "reason")}),
        "the canonical SPDX->pragma->import->body sequence is accepted");

  if (failures == 0)
    puts("solidity-model-test OK (typed legalization model: attestation, "
         "replay, balanced, terminal, typed params/storage, nested guard, "
         "coordination-plan-only single source; generated node registry "
         "consumed)");
  return failures == 0 ? 0 : 1;
}

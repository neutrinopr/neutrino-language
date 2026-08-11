//===- solidity_stmt_shell_render_harness.cpp - .td->render->golden proof -===//
//
// Renders a typed shell node (local-declaration, assignment, compound-update,
// doc-comment, SPDX license, version-pragma, or import) through a GENERATED
// printer handler and compares the bytes to the exact line a committed
// production golden carries. The node is chosen at COMPILE time
// (-DNODE_COMPOUND / -DNODE_ASSIGN / -DNODE_DOCCOMMENT / -DNODE_SPDX /
// -DNODE_PRAGMA / -DNODE_IMPORT / -DNODE_ENUM / -DNODE_STORAGE / -DNODE_EVENT;
// the default is
// the local-declaration shell) and the generated include via -DNODE_INC, so the
// SAME harness runs against:
//   * the COMMITTED SolidityPrinterHandlers.inc -> must MATCH the golden line
//   * a .td-MUTATED regenerated include (the node's syntax record mutated, the
//     mutated form differing per node) -> must NOT match (the mutation changes
//     production output)
// A minimal SolStmt shim stands in for the backend model, so the harness
// compiles against the generated include ALONE (linking only NeutrinoCodeText)
// — no backend link, so the mutated include's `generated_printer::render` is
// the one that runs (no ODR tie to the committed handler compiled into the
// backend).
//
// Neutrino/TargetPrinter.h is pulled in by the generated include below, not
// directly here — the extraction-boundary gate allows a unit .cpp to include
// only its own headers + the shared leaves (CodeText.h).
//
//===----------------------------------------------------------------------===//

#include "Neutrino/CodeText.h"

#include <cstdio>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>

namespace neutrino {
namespace solidity_model {
// Minimal stand-in for the backend SolStmt: the generated printer include only
// needs the Kind enum (ordinals identical to SolidityTargetNodes.td) and the
// ordered operands the arity-generic projection reads.
struct SolStmt {
  enum class Kind {
    Line = 0,
    Blank,
    Require,
    Guarded,
    Transition,
    Emit,
    Block,
    LocalDecl,
    Assign,
    CompoundAssign,
    DocComment,
    SpdxLicense,
    Pragma,
    Import,
    EnumDecl,
    StorageDecl,
    EventDecl,
    FunctionSig,
    ContractShell,
    InterfaceSignature,
    InterfaceShell
  };
  Kind kind;
  std::vector<std::string> operands;
  // The repeated-field (list) group the generated printer projects for a node
  // with a `.td` ListField ( §7) — e.g. an event's parameter list. Mirrors
  // the backend SolStmt member the generated resolveGroups reads.
  std::vector<std::vector<std::string>> group;
  // The closed-enum ordinal groups the generated printer SPELLS for a node with
  // `.td` EnumFields () — one group per enum field (scalar=1 ordinal,
  // repeated=N). Mirrors the backend SolStmt member the generated resolveEnums
  // reads.
  std::vector<std::vector<int>> enumOrdinals;
};
} // namespace solidity_model
} // namespace neutrino

#include NODE_INC // the generated printer handlers (committed or mutated)

using namespace neutrino;

#if defined(NODE_INTERFACESIG)
//  slice 3: the interface method-signature LINE node
// `function ${name}(${params}) external view returns (${returns});`. `${name}`
// and `${returns}` are scalar operands; the parameters are the REPEATED group.
static const solidity_model::SolStmt::Kind kKind =
    solidity_model::SolStmt::Kind::InterfaceSignature;
static const std::vector<std::string> kOperands = {"isAccepted", "bool"};
static const std::vector<std::vector<std::string>> kGroup = {
    {"bytes32", "", "claimId"}};
static const char *kGoldenLine =
    "function isAccepted(bytes32 claimId) external view returns (bool);";
#elif defined(NODE_INTERFACESHELL)
//  slice 3b: the interface CONTAINER BLOCK node `interface ${name} { … }`.
// `${name}` is the sole scalar operand; the interface body (its
// method-signature lines) nests between the generated braces. A Block node, so
// the harness compares the OPEN line the golden carries — the guard-interface
// ABI shell, the last raw seam site retired to a typed node ( -> 0).
static const solidity_model::SolStmt::Kind kKind =
    solidity_model::SolStmt::Kind::InterfaceShell;
static const std::vector<std::string> kOperands = {
    "IThresholdQuorumAcceptance"};
static const char *kGoldenLine = "interface IThresholdQuorumAcceptance {";
#elif defined(NODE_CONTRACTSHELL)
//  slice 2: the contract CONTAINER BLOCK node `contract ${name} { … }`.
// `${name}` is the sole scalar operand; the container body nests between the
// generated braces. A Block node, so the harness compares the OPEN line the
// golden carries — the last construct to leave the handwritten printer.
static const solidity_model::SolStmt::Kind kKind =
    solidity_model::SolStmt::Kind::ContractShell;
static const std::vector<std::string> kOperands = {"CoreSupplyIssue"};
static const char *kGoldenLine = "contract CoreSupplyIssue {";
#elif defined(NODE_FUNCTIONSIG)
// : a callable signature BLOCK node
// `${keyword}${name}(${params})${modifiers} {`. `${keyword}` and `${modifiers}`
// are SPELLED from closed-enum ordinals (kind group 0, modifier group 1) via
// `.td`-owned spelling tables; `${name}` is the lone scalar operand (an
// optional-scalar prefix supplies its leading space); the parameters are the
// REPEATED group. A function with a visibility modifier proves the scalar-enum,
// repeated-enum, list, and optional-scalar projections co-render the exact
// production block-open line. The node is a Block, so the harness compares the
// OPEN line the golden carries.
static const solidity_model::SolStmt::Kind kKind =
    solidity_model::SolStmt::Kind::FunctionSig;
static const std::vector<std::string> kOperands = {"attest"};
static const std::vector<std::vector<std::string>> kGroup = {
    {"string", "calldata", "u_transfer_id"}};
// keyword ordinal 0 = Function; modifier ordinal 0 = External.
static const std::vector<std::vector<int>> kEnums = {{0}, {0}};
static const char *kGoldenLine =
    "function attest(string calldata u_transfer_id) external {";
#elif defined(NODE_EVENT)
//  §7: an event declaration `event ${name}(${params});`. `${name}` is the
// lone scalar operand; the parameters are the REPEATED group — one
// `[type, location, name]` per parameter — so the generated handler applies the
// per-parameter space-join and the `, ` separator. A multi-param event proves
// the repeated projection reproduces the exact production line.
static const solidity_model::SolStmt::Kind kKind =
    solidity_model::SolStmt::Kind::EventDecl;
static const std::vector<std::string> kOperands = {"SenderDebitDebited"};
static const std::vector<std::vector<std::string>> kGroup = {
    {"string", "", "party"},
    {"uint256", "", "amount"},
    {"string", "", "currency"}};
static const char *kGoldenLine =
    "event SenderDebitDebited(string party, uint256 amount, string currency);";
#elif defined(NODE_STORAGE)
// : a storage-slot declaration `${type} ${modifiers} ${name};`.
static const solidity_model::SolStmt::Kind kKind =
    solidity_model::SolStmt::Kind::StorageDecl;
static const std::vector<std::string> kOperands = {"mapping(bytes32 => Status)",
                                                   "public", "statusOf"};
static const char *kGoldenLine = "mapping(bytes32 => Status) public statusOf;";
#elif defined(NODE_ENUM)
// : a status-enum type declaration `enum ${name} { ${variants} }`.
static const solidity_model::SolStmt::Kind kKind =
    solidity_model::SolStmt::Kind::EnumDecl;
static const std::vector<std::string> kOperands = {"Status",
                                                   "None, Reconciled"};
static const char *kGoldenLine = "enum Status { None, Reconciled }";
#elif defined(NODE_IMPORT)
//  slice 4: an import-directive record `import "${path}";`.
static const solidity_model::SolStmt::Kind kKind =
    solidity_model::SolStmt::Kind::Import;
static const std::vector<std::string> kOperands = {"./CoordinationEnvelope.sol"};
static const char *kGoldenLine = "import \"./CoordinationEnvelope.sol\";";
#elif defined(NODE_PRAGMA)
//  slice 3: a version-pragma record `pragma solidity ${version};`.
static const solidity_model::SolStmt::Kind kKind =
    solidity_model::SolStmt::Kind::Pragma;
static const std::vector<std::string> kOperands = {"^0.8.20"};
static const char *kGoldenLine = "pragma solidity ^0.8.20;";
#elif defined(NODE_SPDX)
//  slice 2: an SPDX license record `// SPDX-License-Identifier:
// ${license}`.
static const solidity_model::SolStmt::Kind kKind =
    solidity_model::SolStmt::Kind::SpdxLicense;
static const std::vector<std::string> kOperands = {"MIT"};
static const char *kGoldenLine = "// SPDX-License-Identifier: MIT";
#elif defined(NODE_DOCCOMMENT)
//  slice 1: a NatSpec doc-comment `/// ${text}`.
static const solidity_model::SolStmt::Kind kKind =
    solidity_model::SolStmt::Kind::DocComment;
static const std::vector<std::string> kOperands = {
    "Generated by the Neutrino Translator from verified MLIR."};
static const char *kGoldenLine =
    "/// Generated by the Neutrino Translator from verified MLIR.";
#elif defined(NODE_COMPOUND)
// slice 2c: a compound update `${lhs} ${op} ${rhs};` (op is a closed {+=,-=}).
static const solidity_model::SolStmt::Kind kKind =
    solidity_model::SolStmt::Kind::CompoundAssign;
static const std::vector<std::string> kOperands = {"debitTotal[_k]",
                                                   "+=", "u_amount"};
static const char *kGoldenLine = "debitTotal[_k] += u_amount;";
#elif defined(NODE_ASSIGN)
// slice 2b: a plain/indexed assignment `${lhs} = ${rhs};`.
static const solidity_model::SolStmt::Kind kKind =
    solidity_model::SolStmt::Kind::Assign;
static const std::vector<std::string> kOperands = {"attested[_k]", "true"};
static const char *kGoldenLine = "attested[_k] = true;";
#else
// slice 2a: a local declaration `${type} ${name} = ${rhs};`.
static const solidity_model::SolStmt::Kind kKind =
    solidity_model::SolStmt::Kind::LocalDecl;
static const std::vector<std::string> kOperands = {
    "bytes32", "_k", "keccak256(bytes(u_shipment_ref))"};
static const char *kGoldenLine =
    "bytes32 _k = keccak256(bytes(u_shipment_ref));";
#endif

// Only the repeated-field (list) nodes carry a group; every other shell node
// leaves it empty.
#if !defined(NODE_EVENT) && !defined(NODE_FUNCTIONSIG) &&                      \
    !defined(NODE_INTERFACESIG)
static const std::vector<std::vector<std::string>> kGroup = {};
#endif
// Only the enum-field node carries enum ordinals; every other shell node leaves
// them empty.
#ifndef NODE_FUNCTIONSIG
static const std::vector<std::vector<int>> kEnums = {};
#endif

static std::string trim(const std::string &s) {
  size_t b = s.find_first_not_of(" \t\r\n");
  if (b == std::string::npos)
    return "";
  size_t e = s.find_last_not_of(" \t\r\n");
  return s.substr(b, e - b + 1);
}

int main(int argc, char **argv) {
  if (argc < 2) {
    fprintf(stderr, "usage: solidity-stmt-shell-render <golden.sol>\n");
    return 2;
  }

  // Render the production statement through the GENERATED handler.
  solidity_model::SolStmt s{kKind, kOperands, kGroup, kEnums};
  codetext::Document doc;
  doc.add(solidity_model::generated_printer::render(s));
  std::string rendered = trim(doc.print());
  // A Block node (FunctionSig) prints its OPEN line then its CloseSyntax line;
  // the golden carries the open line, so compare the FIRST physical line. For a
  // single-line node the first line IS the whole render.
  std::string renderedFirst = rendered.substr(0, rendered.find('\n'));
  rendered = renderedFirst;
  printf("rendered=[%s]\n", rendered.c_str());

  // The committed production golden must carry that exact line, so the
  // comparison pins the generated grammar to real output (not a private
  // string).
  std::ifstream in(argv[1]);
  std::stringstream ss;
  ss << in.rdbuf();
  bool goldenHasLine = false;
  std::istringstream lines(ss.str());
  std::string line;
  while (std::getline(lines, line))
    if (trim(line) == kGoldenLine)
      goldenHasLine = true;
  if (!goldenHasLine) {
    fprintf(stderr,
            "render-harness VACUOUS: golden %s no longer carries [%s]\n",
            argv[1], kGoldenLine);
    return 2;
  }

  // Exit 0 iff the generated handler reproduces the golden line.
  if (rendered != kGoldenLine) {
    fprintf(stderr,
            "render does not match the golden line:\n"
            "  rendered: [%s]\n  golden:   [%s]\n",
            rendered.c_str(), kGoldenLine);
    return 1;
  }
  return 0;
}

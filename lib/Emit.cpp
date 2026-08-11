//===- Emit.cpp - INSPECTION projections from Neutrino MLIR ---------------===//
//
// The RETAINED inspection-only projections (M5  D7, ): `events` (the
// IR's expected fact ordering) and `symbols` (LSP document symbols). They walk
// native MLIR ops and trace SSA operands back to their defining op (ref vs
// const), so they live in NeutrinoDialect (core) — they are inspection
// surfaces, NOT target renderers, and are excluded from the backend/policy
// modules.
//
// This is NOT a backend emitter. The naive raw-MLIR `sql`/`contract`
// projections that once lived here (the byte-for-byte emitters.py port,
// including the buggy no-upsert UPDATE) were RETIRED in : backends render
// from the frozen capability-spec (the leaf-only
// GenPostgresSpec/GenSoliditySpec modules), never from a raw ModuleOp walk, and
// `neutrino-emit` fails closed on --kind=sql|contract.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/Emit.h"
#include "Neutrino/NeutrinoDialect.h"

#include "mlir/IR/Location.h"
#include "llvm/ADT/SmallVector.h"
#include "llvm/ADT/StringRef.h"
#include "llvm/Support/JSON.h"
#include "llvm/Support/raw_ostream.h"

#include <string>
#include <vector>

using namespace mlir;
using namespace neutrino;

namespace {

std::string pascal(llvm::StringRef name) {
  std::string out;
  llvm::SmallVector<llvm::StringRef> parts;
  name.split(parts, '_');
  for (llvm::StringRef p : parts) {
    if (p.empty())
      continue;
    std::string s = p.str();
    s[0] = (char)toupper((unsigned char)s[0]);
    for (size_t i = 1; i < s.size(); ++i)
      s[i] = (char)tolower((unsigned char)s[i]);
    out += s;
  }
  return out;
}

// "\n".join(lines).rstrip("\n") + "\n"
std::string join(const std::vector<std::string> &lines) {
  std::string s;
  for (const std::string &ln : lines) {
    s += ln;
    s += '\n';
  }
  size_t end = s.find_last_not_of('\n');
  return end == std::string::npos ? std::string("\n") : s.substr(0, end + 1) + "\n";
}

std::vector<ProcedureOp> procedures(ModuleOp module) {
  std::vector<ProcedureOp> out;
  for (auto p : module.getOps<ProcedureOp>())
    out.push_back(p);
  return out;
}

} // namespace

std::string neutrino::emitEvents(ModuleOp module) {
  std::vector<std::string> lines = {
      "# Event choreography (generated from MLIR)",
      "# Expected fact ordering. A runtime can compare its emitted facts to this.",
      "",
  };
  for (ProcedureOp proc : procedures(module)) {
    lines.push_back("procedure " + proc.getSymName().str() + ":");
    std::vector<std::string> chain;
    if (auto trig = proc.getTriggerAttr())
      chain.push_back(pascal(trig.getValue()));
    else
      chain.push_back("ProcedureInvoked");
    bool hasEntries = false;
    for (Operation &op : proc.getBody().front()) {
      if (auto c = dyn_cast<ComputeOp>(op))
        chain.push_back(pascal(c.getSymName()) + "Computed");
    }
    for (Operation &op : proc.getBody().front()) {
      if (auto d = dyn_cast<DebitOp>(op)) {
        chain.push_back(pascal(d.getSymName()) + "Debited");
        hasEntries = true;
      } else if (auto cr = dyn_cast<CreditOp>(op)) {
        chain.push_back(pascal(cr.getSymName()) + "Credited");
        hasEntries = true;
      }
    }
    if (hasEntries)
      chain.push_back(pascal(proc.getSymName()) + "Reconciled");

    for (size_t idx = 0; idx < chain.size(); ++idx) {
      std::string arrow = idx == 0 ? "   " : "-> ";
      lines.push_back("  " + arrow + chain[idx]);
    }
    lines.push_back("");
  }
  return join(lines);
}

namespace {
// 1-based [startLine, endLine] from an op's location: a single FileLineColLoc
// is a one-line range; a FusedLoc[start, end] (block ops) spans header..closing
// brace. 0/0 for an unknown loc. Lines are relative to the parsed file, so this
// is meant for .neu input (the front-end attaches .neu source positions).
std::pair<int, int> lineRange(Location loc) {
  if (auto fl = loc.dyn_cast<FileLineColLoc>())
    return {(int)fl.getLine(), (int)fl.getLine()};
  if (auto fused = loc.dyn_cast<FusedLoc>()) {
    int s = 0, e = 0;
    for (Location l : fused.getLocations())
      if (auto f = l.dyn_cast<FileLineColLoc>()) {
        if (!s)
          s = (int)f.getLine();
        e = (int)f.getLine();
      }
    return {s, e};
  }
  return {0, 0};
}

llvm::json::Object rangeJson(Location loc) {
  auto [s, e] = lineRange(loc);
  return llvm::json::Object{
      {"start", llvm::json::Object{{"line", s}, {"column", 1}}},
      {"end", llvm::json::Object{{"line", e}, {"column", 1}}}};
}
} // namespace

std::string neutrino::emitSymbols(ModuleOp module) {
  llvm::json::Array procs;
  for (ProcedureOp proc : module.getOps<ProcedureOp>()) {
    llvm::json::Array children;
    for (Operation &op : proc.getBody().front()) {
      std::string kind, name;
      if (auto in = dyn_cast<InputOp>(op)) {
        kind = "input";
        name = in.getSymName().str();
      } else if (auto c = dyn_cast<ComputeOp>(op)) {
        kind = "compute";
        name = c.getSymName().str();
      } else if (auto p = dyn_cast<ParticipantOp>(op)) {
        kind = "participant";
        name = p.getSymName().str();
      } else if (auto d = dyn_cast<DebitOp>(op)) {
        kind = "debit";
        name = d.getSymName().str();
      } else if (auto cr = dyn_cast<CreditOp>(op)) {
        kind = "credit";
        name = cr.getSymName().str();
      } else if (auto a = dyn_cast<AllowOrgsOp>(op)) {
        kind = "allow";
        name = (a.getOrgA() + " with " + a.getOrgB()).str();
      } else {
        continue; // const/assert are not outline symbols
      }
      children.push_back(llvm::json::Object{
          {"name", name}, {"kind", kind}, {"range", rangeJson(op.getLoc())}});
    }
    procs.push_back(llvm::json::Object{{"name", proc.getSymName().str()},
                                       {"kind", "procedure"},
                                       {"range", rangeJson(proc->getLoc())},
                                       {"children", std::move(children)}});
  }
  llvm::json::Object root{{"schemaVersion", 1},
                          {"kind", "neutrino.document-symbols"},
                          {"symbols", std::move(procs)}};
  std::string out;
  llvm::raw_string_ostream os(out);
  os << llvm::formatv("{0:2}", llvm::json::Value(std::move(root))) << "\n";
  return os.str();
}

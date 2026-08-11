//===- StrCase.cpp - pure string-case utilities (leaf) --------------------===//
//
// The implementation of the StrCase.h pure string utilities, part of the frozen
// capability-spec contract LEAF (NeutrinoSpecContract, M5  D1/). It
// lives in the leaf — not View.cpp (NeutrinoAnalysis) — so a leaf-only
// spec-consuming renderer (e.g. the Solidity backend, /) can name
// contracts/events from the spec WITHOUT depending on ProcedureView / View.h.
// View.h re-includes StrCase.h, so existing `pascalCase` callers in the
// analysis/emit layers are unaffected (they resolve the symbol through the leaf
// they already link).
//
//===----------------------------------------------------------------------===//

#include "Neutrino/StrCase.h"

#include "llvm/ADT/SmallVector.h"

#include <cctype>
#include <string>

std::string neutrino::pascalCase(llvm::StringRef name) {
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

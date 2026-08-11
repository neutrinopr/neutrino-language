//===- Diagnostics.cpp - machine-readable diagnostics (diagnostics.json) --===//

#include "Neutrino/Diagnostics.h"

#include "Neutrino/DiagnosticTaxonomy.h"

#include "llvm/Support/JSON.h"
#include "llvm/Support/raw_ostream.h"

#include <algorithm>

using namespace llvm;

void neutrino::orderByRootCause(std::vector<Diagnostic> &diags) {
  std::stable_sort(
      diags.begin(), diags.end(), [](const Diagnostic &a, const Diagnostic &b) {
        return rootCausePrecedence(a.code) < rootCausePrecedence(b.code);
      });
}

void neutrino::writeDiagnostics(const std::string &path, bool ok,
                                const std::vector<Diagnostic> &diags) {
  json::Array arr;
  for (const Diagnostic &d : diags)
    arr.push_back(json::Object{
        {"severity", d.severity},
        {"code", d.code},
        {"message", d.message},
    });

  json::Object root{{"ok", ok}, {"diagnostics", std::move(arr)}};

  std::error_code ec;
  raw_fd_ostream os(path, ec);
  if (ec) {
    errs() << "warning: could not write diagnostics " << path << ": " << ec.message() << "\n";
    return;
  }
  os << formatv("{0:2}", json::Value(std::move(root))) << "\n";
}

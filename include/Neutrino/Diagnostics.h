#ifndef NEUTRINO_DIAGNOSTICS_H
#define NEUTRINO_DIAGNOSTICS_H

#include <string>
#include <vector>

namespace neutrino {

// A structured diagnostic for machine consumption (agents, CI). `code` is a
// stable dotted identifier from the shared failure taxonomy
// (DiagnosticTaxonomy.h, ), e.g. "scenario.invalid",
// "kernel.balance.unbalanced"; `severity` is "error" or "warning".
struct Diagnostic {
  std::string severity;
  std::string code;
  std::string message;
};

// Reorder diagnostics ROOT-CAUSE FIRST (M5 WP1c, ): a stable sort by the
// taxonomy's rootCausePrecedence, so the first diagnostic is the primary
// failure and cascades are subordinated. Stable, so diagnostics of equal
// precedence keep their original (emission) order. Codes not in the taxonomy
// sort last.
void orderByRootCause(std::vector<Diagnostic> &diags);

// Write {"ok": <ok>, "diagnostics": [...]} to `path` (pretty JSON). The
// diagnostics are emitted in the order given; callers order with
// orderByRootCause.
void writeDiagnostics(const std::string &path, bool ok,
                      const std::vector<Diagnostic> &diags);

} // namespace neutrino

#endif // NEUTRINO_DIAGNOSTICS_H

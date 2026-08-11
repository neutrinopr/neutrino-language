#ifndef NEUTRINO_ANALYSIS_H
#define NEUTRINO_ANALYSIS_H

#include "Neutrino/View.h"
#include "llvm/ADT/ArrayRef.h"
#include "llvm/ADT/StringRef.h"

#include <set>
#include <string>
#include <vector>

namespace neutrino {

// Reusable analyses over a ProcedureView (T9 R1 pattern ). These promote the
// ad-hoc loops the emitters/validation repeated, so the security report, gate,
// views, coverage, and slot generation reason about the same participant/org
// topology and cannot disagree. Pure: they read the view and return derived data,
// constructing no MLIR and emitting no diagnostics.

// The first participant declared with `name`, or nullptr. First-match semantics
// match the previous hand-rolled scans (participant names are unique within a
// procedure, so at most one matches).
const ParticipantView *findParticipant(const ProcedureView &view,
                                       llvm::StringRef name);

// org / role of the named participant, or "" when undeclared (or declared with no
// org). Mirrors the repeated orgOf/roleOf scans in the security analysis.
std::string orgOf(const ProcedureView &view, llvm::StringRef name);
std::string roleOf(const ProcedureView &view, llvm::StringRef name);

// Whether a participant with `name` is declared.
bool isParticipantDeclared(const ProcedureView &view, llvm::StringRef name);

// Distinct declared organizations in first-appearance order, skipping participants
// with no org. This is the "named trust domains" set the org-boundary analyses
// count and iterate; it intentionally excludes the empty-org bucket (unlike the
// slot binding-topology grouping, where "" is a rendered bucket).
std::vector<std::string> orderedNamedOrgs(const ProcedureView &view);

// Distinct organizations in first-appearance order, INCLUDING the empty-org bucket
// ("" = a participant with no declared org). The slot binding-topology renders this
// bucket as a null organizationId, so it must be kept (cf. orderedNamedOrgs).
std::vector<std::string> orderedOrgsWithEmpty(const ProcedureView &view);

// Participants whose org equals `org` ("" selects the no-org bucket), in
// declaration order. Pointers alias `view`, so it must outlive the result.
std::vector<const ParticipantView *> participantsInOrg(const ProcedureView &view,
                                                       llvm::StringRef org);

// Ledger activity of a capability: whether it has debit/credit legs, and hence
// whether it moves value. The security report and coverage both gate on this, so
// they derive it from one place.
struct LedgerActivity {
  bool hasDebit = false;
  bool hasCredit = false;
  bool valueMoving() const { return hasDebit || hasCredit; }
};
LedgerActivity ledgerActivity(const ProcedureView &view);

// Declared inputs reachable from `seeds`, following compute dependencies
// transitively: a seed (or compute dep) naming a declared input contributes it; a
// seed naming a compute is expanded via its deps; anything else is ignored. The
// per-participant requiredInputs contract is rendered by filtering view.inputs in
// declaration order by this set (a leg referencing a compute pulls in the inputs
// that compute derives from, not the intermediate compute).
std::set<std::string> reachableInputs(const ProcedureView &view,
                                      llvm::ArrayRef<std::string> seeds);

} // namespace neutrino

#endif // NEUTRINO_ANALYSIS_H

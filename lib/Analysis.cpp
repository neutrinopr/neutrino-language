//===- Analysis.cpp - reusable analyses over ProcedureView ---------------===//
//
// T9 R1 pattern : promote the ad-hoc participant/org scans the emitters and
// validation repeated into one set of analyses, so security/gate/views/coverage/
// slot share a single source of truth and cannot disagree. Byte-for-byte the
// previous hand-rolled loops; pure (no MLIR, no diagnostics).
//
//===----------------------------------------------------------------------===//

#include "Neutrino/Analysis.h"

#include <algorithm>
#include <map>

const neutrino::ParticipantView *
neutrino::findParticipant(const ProcedureView &view, llvm::StringRef name) {
  for (const auto &p : view.participants)
    if (p.name == name)
      return &p;
  return nullptr;
}

std::string neutrino::orgOf(const ProcedureView &view, llvm::StringRef name) {
  const ParticipantView *p = findParticipant(view, name);
  return p ? p->org : "";
}

std::string neutrino::roleOf(const ProcedureView &view, llvm::StringRef name) {
  const ParticipantView *p = findParticipant(view, name);
  return p ? p->role : "";
}

bool neutrino::isParticipantDeclared(const ProcedureView &view,
                                     llvm::StringRef name) {
  return findParticipant(view, name) != nullptr;
}

std::vector<std::string>
neutrino::orderedNamedOrgs(const ProcedureView &view) {
  std::vector<std::string> orgs;
  for (const auto &p : view.participants)
    if (!p.org.empty() && std::find(orgs.begin(), orgs.end(), p.org) == orgs.end())
      orgs.push_back(p.org);
  return orgs;
}

std::vector<std::string>
neutrino::orderedOrgsWithEmpty(const ProcedureView &view) {
  std::vector<std::string> orgs;
  for (const auto &p : view.participants)
    if (std::find(orgs.begin(), orgs.end(), p.org) == orgs.end())
      orgs.push_back(p.org);
  return orgs;
}

std::vector<const neutrino::ParticipantView *>
neutrino::participantsInOrg(const ProcedureView &view, llvm::StringRef org) {
  std::vector<const ParticipantView *> ps;
  for (const auto &p : view.participants)
    if (p.org == org)
      ps.push_back(&p);
  return ps;
}

neutrino::LedgerActivity neutrino::ledgerActivity(const ProcedureView &view) {
  LedgerActivity a;
  for (const auto &e : view.entries) {
    if (e.kind == "debit")
      a.hasDebit = true;
    else if (e.kind == "credit")
      a.hasCredit = true;
  }
  return a;
}

std::set<std::string>
neutrino::reachableInputs(const ProcedureView &view,
                          llvm::ArrayRef<std::string> seeds) {
  std::set<std::string> inputNames;
  for (const auto &in : view.inputs)
    inputNames.insert(in.first);
  std::map<std::string, const ComputeView *> computes;
  for (const auto &c : view.computes)
    computes[c.name] = &c;
  std::set<std::string> neededInputs, seen;
  std::vector<std::string> work(seeds.begin(), seeds.end());
  while (!work.empty()) {
    std::string n = work.back();
    work.pop_back();
    if (!seen.insert(n).second)
      continue;
    if (inputNames.count(n)) {
      neededInputs.insert(n);
    } else {
      auto it = computes.find(n);
      if (it != computes.end())
        for (const auto &d : it->second->deps)
          work.push_back(d);
    }
  }
  return neededInputs;
}

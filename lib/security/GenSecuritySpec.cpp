//===- GenSecuritySpec.cpp - Capability Security Pass (spec-driven) -------===//
//
// The domain-aware Capability Security Pass reads the frozen capability-spec
// JSON instead of ProcedureView, so this translation unit includes no View.h
// or Analysis.h and holds no ProcedureView. It computes the five
// security categories (authorization, value, topology, trustBoundary, state)
// and renders a deterministic security.json byte-identical to the ProcedureView
// path it replaces (proved by the committed security goldens).
//
// The report (`securityReportFromSpec`) and the hard-gate predicate
// (`specHasSecurityViolations`) derive from the SAME `buildCategories`, so they
// cannot disagree. The core target adapter emits the
// spec via `capabilitySpecJson`, re-parses it, and calls in here.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/GenSecuritySpec.h"

#include "llvm/ADT/StringRef.h"
#include "llvm/Support/JSON.h"

#include <algorithm>
#include <string>
#include <vector>

using namespace llvm;

namespace {

std::string esc(StringRef s) {
  std::string o;
  for (char c : s) {
    switch (c) {
    case '"':
      o += "\\\"";
      break;
    case '\\':
      o += "\\\\";
      break;
    case '\n':
      o += "\\n";
      break;
    default:
      o += c;
    }
  }
  return o;
}
std::string q(StringRef s) { return "\"" + esc(s) + "\""; }

std::string arr(const std::vector<std::string> &v) {
  std::string o = "[";
  for (size_t i = 0; i < v.size(); ++i) {
    if (i)
      o += ", ";
    o += q(v[i]);
  }
  return o + "]";
}

struct Category {
  const char *category;
  std::string status; // pass | advisory | violation | n/a
  std::vector<std::string> findings;
};

std::string categoryJson(const Category &c) {
  std::string o = "    {\n";
  o += "      \"category\": " + q(c.category) + ",\n";
  o += "      \"status\": " + q(c.status) + ",\n";
  o += "      \"findings\": " + arr(c.findings) + "\n";
  o += "    }";
  return o;
}

// ---- capability-spec projection ----
// The security categories need only a handful of spec fields; extract them into
// plain structures once so the category logic below is a line-for-line mirror
// of the former ProcedureView pass (same analysis, same order, same strings).
struct Part {
  std::string name, org, role, binding, bindMinAssurance;
  bool isFlexible() const { return binding == "to_be_bound"; }
};
struct Leg {
  std::string kind, name, participant;
  std::string guard;  // the effect's `when` condition expr ("" = unconditional)
  std::string ledger; // the target ledger id (e.g. token.balance, token.supply)
};
struct OrgPair {
  std::string orgA, orgB, roleA, roleB;
};
// Oracle attestation projection (oracle S6, ): only the fields the trust-
// boundary surfacing needs — the declared M-of-N + observer-set identity + the
// optional assurance/independence trust metadata. Parsed straight from the
// frozen `attestations` array (mirrors attestationPoliciesFromSpec), so this
// stays a View-free re-projection like the rest of the pass.
struct Attest {
  std::string input, observerRef, assurance, independence;
  int quorum = 0;
};

struct SpecSecurity {
  std::string name, version;
  std::vector<Part> participants;
  std::vector<Leg>
      legs; // ledger entries (effects: debit/credit), in spec order
  std::vector<OrgPair> allowedOrgPairs;
  std::vector<Attest> attestations;
  bool balanced = false;
  int evidenceInputs = 0;
  bool hasDebit = false, hasCredit = false;

  bool valueMoving() const { return hasDebit || hasCredit; }

  const Part *find(StringRef n) const {
    for (const auto &p : participants)
      if (p.name == n)
        return &p;
    return nullptr;
  }
  std::string orgOf(StringRef n) const {
    const Part *p = find(n);
    return p ? p->org : "";
  }
  std::string roleOf(StringRef n) const {
    const Part *p = find(n);
    return p ? p->role : "";
  }
  bool isParticipantDeclared(StringRef n) const { return find(n) != nullptr; }
  // A participant that owns a value-moving leg (a transacting party). One that
  // does NOT is a governance/authority role on the trust boundary (e.g. a
  // compliance or freeze authority that governs a guard but moves no value).
  bool ownsLeg(StringRef n) const {
    for (const auto &l : legs)
      if (l.participant == n)
        return true;
    return false;
  }
  // Distinct non-empty orgs in participant-declaration order (cf.
  // orderedNamedOrgs).
  std::vector<std::string> orderedNamedOrgs() const {
    std::vector<std::string> orgs;
    for (const auto &p : participants)
      if (!p.org.empty() &&
          std::find(orgs.begin(), orgs.end(), p.org) == orgs.end())
        orgs.push_back(p.org);
    return orgs;
  }
};

std::string str(const json::Object &o, StringRef key) {
  return o.getString(key).value_or("").str();
}

SpecSecurity projectSpec(const json::Object &spec) {
  SpecSecurity s;
  s.name = str(spec, "procedure");
  s.version = str(spec, "specVersion");

  if (const json::Array *parts = spec.getArray("participants"))
    for (const json::Value &pv : *parts)
      if (const json::Object *p = pv.getAsObject())
        s.participants.push_back({str(*p, "name"), str(*p, "org"),
                                  str(*p, "role"), str(*p, "binding"),
                                  str(*p, "bindMinAssurance")});

  if (const json::Array *effects = spec.getArray("effects"))
    for (const json::Value &ev : *effects)
      if (const json::Object *e = ev.getAsObject()) {
        std::string kind = str(*e, "kind");
        if (kind == "debit")
          s.hasDebit = true;
        else if (kind == "credit")
          s.hasCredit = true;
        std::string guard;
        if (const json::Object *w = e->getObject("when"))
          guard = str(*w, "expr");
        s.legs.push_back({kind, str(*e, "name"), str(*e, "participant"), guard,
                          str(*e, "ledger")});
      }

  if (const json::Array *invs = spec.getArray("invariants"))
    for (const json::Value &iv : *invs)
      if (const json::Object *i = iv.getAsObject())
        if (str(*i, "kind") == "balanced")
          s.balanced = true;

  if (const json::Array *inputs = spec.getArray("inputs"))
    for (const json::Value &iv : *inputs)
      if (const json::Object *i = iv.getAsObject())
        if (str(*i, "type") == "evidence")
          ++s.evidenceInputs;

  if (const json::Object *topo = spec.getObject("topology"))
    if (const json::Array *pairs = topo->getArray("allowedOrgPairs"))
      for (const json::Value &pv : *pairs)
        if (const json::Object *p = pv.getAsObject())
          s.allowedOrgPairs.push_back({str(*p, "orgA"), str(*p, "orgB"),
                                       str(*p, "roleA"), str(*p, "roleB")});

  if (const json::Array *atts = spec.getArray("attestations"))
    for (const json::Value &av : *atts)
      if (const json::Object *a = av.getAsObject()) {
        Attest at;
        at.input = str(*a, "input");
        if (const json::Object *q = a->getObject("quorum"))
          at.quorum = (int)q->getInteger("threshold").value_or(0);
        if (const json::Object *os = a->getObject("observerSet")) {
          at.observerRef = str(*os, "ref");
          at.assurance = str(*os, "assurance");
          at.independence = str(*os, "independence");
        }
        s.attestations.push_back(std::move(at));
      }

  return s;
}

// Single source of truth for the five security categories. Used both to render
// security.json (securityReportFromSpec) and to gate
// (specHasSecurityViolations). A line-for-line mirror of the former
// ProcedureView pass ( migration).
std::vector<Category> buildCategories(const SpecSecurity &view) {
  bool valueMoving = view.valueMoving();
  bool hasParticipants = !view.participants.empty();

  std::vector<std::string> orgs = view.orderedNamedOrgs();

  int evidenceInputs = view.evidenceInputs;

  std::vector<Category> cats;

  // Authorization Safety — who may perform privileged (value-moving)
  // operations.
  {
    Category c{"authorization", "n/a", {}};
    if (hasParticipants) {
      // Hard gate: once participants are declared, every value-moving leg must
      // be bound to a declared participant (the authorization actor for that
      // leg).
      bool bad = false;
      for (const auto &e : view.legs) {
        if (e.participant.empty()) {
          c.findings.push_back("leg '" + e.name +
                               "' is not bound to a participant "
                               "(authorization actor unspecified)");
          bad = true;
        } else if (!view.isParticipantDeclared(e.participant)) {
          c.findings.push_back("leg '" + e.name +
                               "' bound to undeclared participant '" +
                               e.participant + "'");
          bad = true;
        }
      }
      if (bad) {
        c.status = "violation";
      } else {
        c.status = "pass";
        c.findings.push_back(
            std::to_string(view.participants.size()) +
            " participant(s) declared; every value-moving leg bound "
            "to a declared participant");
        // Name each authority binding machine-readably ( slice 4 review):
        // WHICH participant+role is the authorization actor for WHICH effect on
        // WHICH ledger, so a leg silently rebound to the WRONG declared
        // participant is surfaced (and field-pinnable), not hidden behind the
        // generic count. E.g. the insurance reserve debit is owned by the
        // Insurer authority: "leg 'reserve_debit' (debit insurance.reserve)
        // authorized by participant 'Insurer' (role 'insurer')".
        for (const auto &e : view.legs)
          c.findings.push_back("leg '" + e.name + "' (" + e.kind + " " +
                               e.ledger + ") authorized by participant '" +
                               e.participant + "' (role '" +
                               view.roleOf(e.participant) + "')");
      }
    } else if (valueMoving) {
      c.status = "advisory";
      c.findings.push_back("value-moving capability declares no participants; "
                           "authorization actors are unspecified (declare "
                           "participants to enable authorization safety)");
    }
    cats.push_back(std::move(c));
  }

  // Value Safety — asset/balance conservation, explicit currency. Hard gate.
  {
    Category c{"value", "n/a", {}};
    if (valueMoving) {
      if (view.balanced) {
        c.status = "pass";
        c.findings.push_back(
            "balanced invariant asserted; debits conserve credits");
      } else {
        c.status = "violation";
        c.findings.push_back(
            "value moves but the balanced invariant is not asserted");
      }
    }
    cats.push_back(std::move(c));
  }

  // Topology / Composition Safety — declared dependencies + org boundaries.
  {
    Category c{"topology", "pass", {}};
    c.findings.push_back(
        "no inter-capability invocations declared; composition "
        "trivially satisfied");
    // Org-boundary rule (hard gate): once any organization/trust domain is
    // declared, every participant that authorizes a value-moving leg must
    // declare its org — otherwise a leg is authorized from an unknown trust
    // boundary.
    bool orgsInUse = !orgs.empty();
    if (orgsInUse) {
      bool bad = false;
      for (const auto &e : view.legs) {
        if (!e.participant.empty() && view.orgOf(e.participant).empty()) {
          c.findings.push_back("leg '" + e.name +
                               "' is authorized by participant '" +
                               e.participant +
                               "' with no declared organization "
                               "(trust boundary unknown)");
          bad = true;
        }
      }
      if (bad) {
        c.status = "violation";
      } else if (orgs.size() >= 2) {
        const auto &pol = view.allowedOrgPairs;
        if (pol.empty()) {
          // No policy declared: cross-org coordination is reported, not gated.
          c.status = "advisory";
          c.findings.push_back(
              "capability coordinates across " + std::to_string(orgs.size()) +
              " organizations (crosses trust boundaries); declare an "
              "'allow' policy to gate which orgs may coordinate; "
              "concrete enforcement is network-owned");
        } else {
          // Policy declared (hard gate): every coordinating org-pair must be
          // allowed.
          auto allowed = [&](const std::string &a, const std::string &b) {
            for (const auto &p : pol)
              if ((p.orgA == a && p.orgB == b) || (p.orgA == b && p.orgB == a))
                return true;
            return false;
          };
          bool policyBad = false;
          for (size_t i = 0; i < orgs.size(); ++i)
            for (size_t j = i + 1; j < orgs.size(); ++j)
              if (!allowed(orgs[i], orgs[j])) {
                c.findings.push_back(
                    "organizations '" + orgs[i] + "' and '" + orgs[j] +
                    "' coordinate but are not permitted by policy");
                policyBad = true;
              }
          // Per-org-pair role policy (hard gate). A permitted pair may
          // constrain the role each side's actors must take. The constraint is
          // scoped to the *actual coordinating pair*: a policy for (porg,
          // other) only governs porg's legs when `other` is an org this
          // capability actually coordinates with. A leg is valid when its
          // participant's role matches the role any such applicable pair
          // requires of porg; it violates only when porg is role-constrained by
          // its coordinating pairs and the leg matches none of them — so an
          // unrelated porg-other policy cannot reject a valid leg.
          auto present = [&](const std::string &o) {
            return std::find(orgs.begin(), orgs.end(), o) != orgs.end();
          };
          bool roleBad = false;
          for (const auto &e : view.legs) {
            if (e.participant.empty())
              continue;
            std::string porg = view.orgOf(e.participant),
                        prole = view.roleOf(e.participant);
            std::vector<std::string>
                wanted; // roles porg may take in a coordinating pair
            for (const auto &pp : pol) {
              std::string want;
              if (pp.orgA == porg && !pp.roleA.empty() && present(pp.orgB))
                want = pp.roleA;
              else if (pp.orgB == porg && !pp.roleB.empty() && present(pp.orgA))
                want = pp.roleB;
              if (!want.empty() &&
                  std::find(wanted.begin(), wanted.end(), want) == wanted.end())
                wanted.push_back(want);
            }
            if (!wanted.empty() && std::find(wanted.begin(), wanted.end(),
                                             prole) == wanted.end()) {
              std::string roleList;
              for (size_t k = 0; k < wanted.size(); ++k) {
                if (k)
                  roleList += (k + 1 == wanted.size() ? " or " : ", ");
                roleList += "'" + wanted[k] + "'";
              }
              c.findings.push_back(
                  "leg '" + e.name + "' is authorized by '" + e.participant +
                  "' (org '" + porg + "', role '" + prole +
                  "') but policy requires role " + roleList +
                  " for that organization (per its coordinating pair" +
                  (wanted.size() > 1 ? "s)" : ")"));
              roleBad = true;
            }
          }
          if (policyBad || roleBad) {
            c.status = "violation";
          } else {
            c.status = "pass";
            c.findings.push_back(
                "cross-organization coordination permitted by declared "
                "policy (" +
                std::to_string(pol.size()) + " allowed pair(s))");
          }
        }
      }
    }
    cats.push_back(std::move(c));
  }

  // Trust Boundary Validation — replay/idempotency, evidence/attestation.
  {
    Category c{"trustBoundary", "pass", {}};
    if (valueMoving)
      c.findings.push_back(
          "every ledger leg carries an idempotency_key (replay-safe)");
    c.findings.push_back(std::to_string(evidenceInputs) +
                         " evidence/attestation input(s) declared");
    // Guarded value movement (/): a value-moving leg carrying a `when`
    // condition is a COMPLIANCE / policy control on the trust boundary — value
    // moves only if the condition holds, so a denied or malformed input
    // suppresses the leg fail-closed. Surface the guarded legs by name + the
    // exact condition (naming the guard inputs), so the compliance decision
    // that gates value movement is EXPLICIT in the security artifact, not
    // implicit.
    for (const auto &e : view.legs)
      if (!e.guard.empty())
        c.findings.push_back(
            "value-moving leg '" + e.name +
            "' is gated by a compliance guard `" + e.guard +
            "` — value moves only when the condition holds; a denied or "
            "malformed input suppresses the leg (fail-closed)");
    // Supply-ledger audit surface (M5 token S5,  / decision ): a leg
    // posting to the reserved `token.supply` ledger is a MINT or BURN — the one
    // place a token creates or destroys circulating value. Surface it as the
    // supply/audit trust surface (circulating supply = initial(token.supply) −
    // balance(token.supply), so the supply ledger IS the audit trail).
    // Reserved-NAME recognition only (presentation, per ) — not a new
    // effect type or primitive, and additive: a spec with no `token.supply` leg
    // is byte-unchanged. The fail-closed assurance is claimed ONLY when the leg
    // actually carries a `when` authority guard; an UNGUARDED supply leg mints
    // or burns with no authority, which we surface as an ADVISORY (not a silent
    // "authority-gated" claim), so the artifact never over-states suppression.
    bool supplyAdvisory = false;
    for (const auto &e : view.legs)
      if (e.ledger == "token.supply") {
        std::string surface =
            "value-moving leg '" + e.name +
            "' posts to the reserved supply ledger `token.supply` — the "
            "token's "
            "supply/audit surface, where circulating value is " +
            (e.kind == "debit"
                 ? std::string("created (mint: supply → holder)")
                 : std::string("destroyed (burn: holder → supply)"));
        if (!e.guard.empty())
          c.findings.push_back(
              surface +
              "; this supply movement is authority-gated (see the guard "
              "above), "
              "so unauthorized supply change is suppressed fail-closed");
        else {
          c.findings.push_back(
              surface +
              "; this supply movement is NOT gated by any authority — "
              "unauthorized supply change is not suppressed. Mint/burn should "
              "carry a `when` authority guard so invalid supply movement fails "
              "closed (/)");
          supplyAdvisory = true;
        }
      }
    // Governance participants (): a declared participant that owns NO
    // value-moving leg is an AUTHORITY on the trust boundary — it governs the
    // guarded decision (e.g. a compliance/freeze authority) without
    // transacting. Name it so the trust surface records WHO controls the
    // guarded value movement, rather than leaving the authority implicit in the
    // participant list.
    if (valueMoving)
      for (const auto &p : view.participants)
        if (!view.ownsLeg(p.name))
          c.findings.push_back(
              "governance participant '" + p.name + "' (role '" + p.role +
              "') is declared on the trust boundary but owns no value-moving "
              "leg — an authority governing guarded value movement, not a "
              "transacting party");
    // Late-binding assurance (Trust lane, T1): static generation attests A1
    // (compiler attestation — capability hash + IR). A flexible participant
    // whose binding requires a higher tier (A2 realization / A3 runtime
    // evidence / A4 proof) cannot have that satisfied by the translator; it is
    // established downstream at realization/runtime (fabric/agent-owned).
    // Reported as an advisory — the binding is valid, the assurance is just
    // earned elsewhere — not a gate, and never silently claimed as satisfied.
    auto tierRank = [](const std::string &t) {
      return t == "A1" ? 1 : t == "A2" ? 2 : t == "A3" ? 3 : t == "A4" ? 4 : 0;
    };
    bool bindingAdvisory = false;
    for (const auto &p : view.participants) {
      if (p.isFlexible() && tierRank(p.bindMinAssurance) > 1) {
        c.findings.push_back(
            "participant '" + p.name + "' binding requires assurance " +
            p.bindMinAssurance +
            ", above the A1 that static generation "
            "attests; satisfied at realization/runtime (fabric/agent-owned), "
            "not by the translator");
        bindingAdvisory = true;
      }
    }
    // Oracle trust boundary (oracle S6, ): each attestation admits a
    // non-deterministic real-world observation ACROSS a trust boundary, gated
    // by an M-of-N quorum over an observer set. Surface the crossing with the
    // observer-set identity + the declared assurance/independence trust
    // metadata, and flag an under-assured or non-independent set as an advisory
    // — the admitted observation is no stronger than the set that signs it, and
    // an M-of-N over correlated observers is one failure wearing N hats ().
    // Declaration/surfacing only; enforcement is the on-chain guard's (S2).
    bool oracleAdvisory = false;
    for (const auto &a : view.attestations) {
      std::string as = a.assurance.empty() ? "undeclared" : a.assurance;
      std::string ind = a.independence.empty() ? "undeclared" : a.independence;
      c.findings.push_back(
          "oracle attestation on evidence '" + a.input +
          "': observation crosses a trust boundary, admitted by an M-of-N "
          "quorum (M=" +
          std::to_string(a.quorum) + ") over observer-set '" + a.observerRef +
          "' (assurance " + as + ", independence " + ind + ")");
      if (a.assurance.empty() || tierRank(a.assurance) < 2) {
        c.findings.push_back(
            "observer-set '" + a.observerRef + "' assurance " + as +
            " is below A2 — a single-operator or unattested feed; the quorum "
            "admits an observation no stronger than its source");
        oracleAdvisory = true;
      }
      if (a.independence != "independent") {
        c.findings.push_back(
            "observer-set '" + a.observerRef + "' independence is " + ind +
            " — an M-of-N over " +
            std::string(a.independence == "correlated"
                            ? "correlated (shared-upstream) observers"
                            : "observers of unstated diversity") +
            " is a single point of failure wearing N hats");
        oracleAdvisory = true;
      }
    }
    if ((bindingAdvisory || oracleAdvisory || supplyAdvisory) &&
        c.status == "pass")
      c.status = "advisory";
    cats.push_back(std::move(c));
  }

  // State Safety — illegal transitions / compensation. No state-machine yet.
  cats.push_back(
      {"state",
       "n/a",
       {"no explicit state-machine construct in the current DSL (L2)"}});
  return cats;
}

std::string renderReport(const SpecSecurity &view) {
  std::vector<Category> cats = buildCategories(view);

  int violations = 0, advisories = 0;
  for (const auto &c : cats) {
    if (c.status == "violation")
      ++violations;
    else if (c.status == "advisory")
      ++advisories;
  }
  bool ok = violations == 0;

  std::string o = "{\n";
  o += "  \"kind\": \"neutrino.capability-security\",\n";
  o += "  \"schemaVersion\": \"0.1.0\",\n";
  o += "  \"procedure\": " + q(view.name) + ",\n";
  o += "  \"dslVersion\": " + q(view.version) + ",\n";
  o += "  \"ok\": " + std::string(ok ? "true" : "false") + ",\n";
  o += "  \"categories\": [\n";
  for (size_t i = 0; i < cats.size(); ++i) {
    o += categoryJson(cats[i]);
    o += (i + 1 < cats.size() ? ",\n" : "\n");
  }
  o += "  ],\n";
  o += "  \"advisories\": " + std::to_string(advisories) + ",\n";
  o += "  \"violations\": " + std::to_string(violations) + ",\n";
  o += "  \"resultCode\": " + std::string(ok ? "0" : "1") + "\n";
  o += "}\n";
  return o;
}

} // namespace

std::string neutrino::securityReportFromSpec(const json::Object &spec) {
  return renderReport(projectSpec(spec));
}

bool neutrino::specHasSecurityViolations(const json::Object &spec) {
  for (const auto &c : buildCategories(projectSpec(spec)))
    if (c.status == "violation")
      return true;
  return false;
}

//===- neutrino-equiv - cross-backend equivalence harness (C++) -----------===//
//
// Recomputes a reference (computed values, events, net ledger positions) from
// IR + scenario, then invokes every selected verified backend package.
// All green => the source, reference trace, and returned backend artifacts
// agree.
//
//   neutrino-equiv --scenario=s.json <input.mlir|.neu> [--allow-skips]
//
//===----------------------------------------------------------------------===//

#include "Neutrino/BackendDispatchReceipt.h"
#include "Neutrino/BackendInvoker.h"
#include "Neutrino/BackendProjection.h"
#include "Neutrino/CoordinationEval.h"
#include "Neutrino/CoordinationPlanBuild.h"
#include "Neutrino/Diagnostics.h"
#include "Neutrino/Expr.h"
#include "Neutrino/Manifest.h"
#include "Neutrino/NeutrinoDialect.h"
#include "Neutrino/PlanLegality.h"
#include "Neutrino/Scenario.h"
#include "Neutrino/SourceLoad.h"
#include "Neutrino/StrCase.h"
#include "Neutrino/TargetCatalog.h"
#include "Neutrino/TraceEquivalence.h"
#include "Neutrino/Validate.h"
#include "Neutrino/VersionInfo.h"
#include "Neutrino/View.h"

#include "mlir/IR/MLIRContext.h"
#include "llvm/ADT/SmallString.h"
#include "llvm/Support/CommandLine.h"
#include "llvm/Support/FileSystem.h"
#include "llvm/Support/InitLLVM.h"
#include "llvm/Support/JSON.h"
#include "llvm/Support/Path.h"
#include "llvm/Support/raw_ostream.h"

#include <cstdlib>
#include <ctime>
#include <map>
#include <set>
#include <stdexcept>
#include <string>
#include <vector>

using namespace llvm;

static cl::opt<std::string>
    inputFile(cl::Positional, cl::desc("<input .mlir|.neu>"), cl::Required);
static cl::opt<std::string> scenarioFile("scenario", cl::desc("scenario JSON"),
                                         cl::Required);
static cl::opt<bool> allowSkips(
    "allow-skips",
    cl::desc("treat a missing backend toolchain as skip, not failure"),
    cl::init(false));
static cl::opt<bool> referenceOnly(
    "reference-only",
    cl::desc("run only the core-owned reference trace (no backend comparison)"),
    cl::init(false));
static cl::opt<std::string>
    reportDir("report",
              cl::desc("write a machine-readable equivalence.json + "
                       "diagnostics.json into <dir>"),
              cl::init(""));
static cl::opt<std::string> tamper(
    "tamper",
    cl::desc(
        "SELF-TEST ONLY: deliberately break the candidate observation trace "
        "(drop_effect|alter_amount|reorder_obs|wrong_terminal|"
        "replay_omission|partial_commit|alter_computed|alter_outcome) — the "
        "gate must detect the divergence, proving it is non-vacuous"),
    cl::init(""));
static cl::list<std::string> backendPackageDirectories(
    "backend-package-dir",
    cl::desc("verified external backend package directory (repeatable)"),
    cl::ZeroOrMore);
static cl::list<std::string> selectedTargets(
    "target",
    cl::desc("external package target to compare (repeatable; default: all)"),
    cl::ZeroOrMore);

namespace {

// Wall-clock time, unless SOURCE_DATE_EPOCH pins it (so a caller that needs a
// byte-stable report can fix the one non-deterministic field). Mirrors
// Manifest.cpp.
std::string isoNow() {
  std::time_t t = std::time(nullptr);
  if (const char *e = getenv("SOURCE_DATE_EPOCH"))
    t = static_cast<std::time_t>(std::strtoll(e, nullptr, 10));
  char buf[32];
  if (std::strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%SZ", std::gmtime(&t)) ==
      0)
    buf[0] = '\0'; // truncated — cannot happen for this fixed format/buffer
  return std::string(buf);
}

// 0 pass / 1 fail / 2 skip -> stable string for the report.
const char *statusStr(int s) {
  return s == 0 ? "pass" : (s == 1 ? "fail" : "skip");
}

// Spec-vs-artifact structural check (M5 WP8 / ). The rendered backend
// result must retain each finalized input, compute, and effect-ledger identity.
int artifactStructural(const neutrino::ProcedureView &view,
                       const neutrino::CoordinationPlan &coordinationPlan,
                       const neutrino::backend_invocation::Result &result,
                       std::vector<std::string> &missing) {
  std::string joinedArtifacts;
  for (const neutrino::backend_invocation::Artifact &artifact :
       result.artifacts) {
    joinedArtifacts.append(artifact.bytes);
    joinedArtifacts.push_back('\n');
  }
  StringRef art(joinedArtifacts);
  auto require = [&](StringRef token, const char *kind) {
    if (!token.empty() && !art.contains(token))
      missing.push_back(std::string(kind) + " '" + token.str() + "'");
  };
  for (const auto &input : view.inputs) {
    if (input.second == "evidence")
      continue;
    if (coordinationPlan.evidenceOnly &&
        input.first != coordinationPlan.workflowKey)
      continue;
    require(input.first, "input");
  }
  for (const neutrino::ComputeView &compute : view.computes)
    require(compute.name, "compute");
  for (const neutrino::EntryView &entry : view.entries)
    require(entry.ledger, "effect-ledger");
  if (result.artifacts.empty())
    missing.push_back("verified artifact manifest is empty");
  return missing.empty() ? 0 : 1;
}

neutrino::TransitionResult
referenceTransition(const neutrino::CoordinationPlan &coordinationPlan,
                    const neutrino::Scenario &scenario) {
  neutrino::TransitionInput input;
  for (const auto &value : scenario.inputs) {
    if (value.second.isInt)
      input.numeric[value.first] = value.second.i;
    else
      input.symbols[value.first] = value.second.s;
  }
  for (const neutrino::AttestationPolicy &policy :
       coordinationPlan.attestations) {
    auto found = scenario.accepted.find(policy.input);
    input.attestations[policy.input] =
        found == scenario.accepted.end() ? true : found->second;
  }
  input.authorized = true;
  return neutrino::evaluateTransition(coordinationPlan, neutrino::EvalState{},
                                      input);
}

long long refValue(const neutrino::Ref &r,
                   const std::map<std::string, long long> &env,
                   const std::map<std::string, long long> &computed) {
  if (r.first)
    return std::stoll(r.second);
  auto c = computed.find(r.second);
  if (c != computed.end())
    return c->second;
  auto e = env.find(r.second);
  if (e != env.end())
    return e->second;
  throw std::runtime_error("reference: cannot value operand %" + r.second);
}

} // namespace

int main(int argc, char **argv) {
  InitLLVM v(argc, argv);
  if (neutrino::handleVersionFlag(argc, argv, "neutrino-equiv"))
    return 0;
  cl::ParseCommandLineOptions(argc, argv, "neutrino-equiv\n");

  // Emit an ok:false report for an early failure, so a caller that asked for
  // --report always gets equivalence.json + diagnostics.json — not just an exit
  // code and stderr — even for parse / IR / scenario errors that abort before
  // the equivalence run. (The full report is written on the success path
  // below.)
  auto failEarly = [&](int code,
                       std::vector<neutrino::Diagnostic> diags) -> int {
    for (const auto &d : diags)
      errs() << (d.severity == "warning" ? "warning: " : "error: ") << d.message
             << "\n";
    if (!reportDir.empty()) {
      std::error_code ec = sys::fs::create_directories(reportDir);
      if (ec) {
        errs() << "warning: could not create report dir " << reportDir << ": "
               << ec.message() << "\n";
      } else {
        auto hashIfPresent = [](const std::string &p) {
          return sys::fs::exists(p) ? neutrino::sha256OfFile(p) : std::string();
        };
        json::Array diagArr;
        for (const auto &d : diags)
          diagArr.push_back(json::Object{{"severity", d.severity},
                                         {"code", d.code},
                                         {"message", d.message}});
        json::Object root{
            {"kind", "neutrino.equivalence-report"},
            {"version", "0.1.0"},
            {"generatedAt", isoNow()},
            {"mode", referenceOnly ? "reference-only" : "backend-equivalence"},
            {"ok", false},
            {"resultCode", code},
            {"inputs",
             json::Object{
                 {"source", json::Object{{"path", inputFile.getValue()},
                                         {"sha256", hashIfPresent(inputFile)}}},
                 {"scenario",
                  json::Object{{"path", scenarioFile.getValue()},
                               {"sha256", hashIfPresent(scenarioFile)}}}}},
            {"diagnostics", std::move(diagArr)}};
        SmallString<256> rp(reportDir.getValue());
        sys::path::append(rp, "equivalence.json");
        std::error_code wec;
        raw_fd_ostream os(rp, wec);
        if (wec)
          errs() << "warning: could not write " << rp << ": " << wec.message()
                 << "\n";
        else
          os << formatv("{0:2}", json::Value(std::move(root))) << "\n";

        SmallString<256> dp(reportDir.getValue());
        sys::path::append(dp, "diagnostics.json");
        neutrino::orderByRootCause(diags); // root-cause first ()
        neutrino::writeDiagnostics(std::string(dp), /*ok=*/false, diags);
      }
    }
    return code;
  };

  if (referenceOnly &&
      (!backendPackageDirectories.empty() || !selectedTargets.empty()))
    return failEarly(2, {{"error", "equivalence.backend_environment_failed",
                          "--reference-only cannot be combined with "
                          "--backend-package-dir or --target"}});

  auto loadCatalog = [&]() -> Expected<neutrino::TargetCatalog> {
    if (referenceOnly)
      return neutrino::loadExternalTargetCatalog({});
    Expected<std::vector<std::string>> packageDirectories =
        neutrino::resolveBackendPackageDirectories(argc, argv);
    if (!packageDirectories)
      return packageDirectories.takeError();
    return neutrino::loadExternalTargetCatalog(*packageDirectories);
  };
  Expected<neutrino::TargetCatalog> catalogE = loadCatalog();
  if (!catalogE)
    return failEarly(2, {{"error", "equivalence.backend_environment_failed",
                          toString(catalogE.takeError())}});
  neutrino::TargetCatalog catalog = std::move(*catalogE);

  std::set<std::string> requestedTargets;
  for (const std::string &name : selectedTargets) {
    if (!requestedTargets.insert(name).second)
      return failEarly(
          2, {{"error", "equivalence.backend_environment_failed",
               "external target '" + name + "' was selected more than once"}});
    if (!catalog.find(name))
      return failEarly(2,
                       {{"error", "equivalence.backend_environment_failed",
                         "external target '" + name +
                             "' is absent from the verified package catalog"}});
  }
  std::vector<const neutrino::CatalogTarget *> backendTargets;
  for (const neutrino::CatalogTarget &entry : catalog.targets())
    if (requestedTargets.empty() || requestedTargets.count(entry.name))
      backendTargets.push_back(&entry);
  if (!referenceOnly && backendTargets.empty())
    return failEarly(
        2, {{"error", "equivalence.backend_environment_failed",
             "no verified external backend package is available for "
             "structural comparison; use --reference-only for an explicit "
             "reference-trace-only run"}});

  mlir::MLIRContext ctx;
  ctx.getOrLoadDialect<neutrino::NeutrinoDialect>();

  neutrino::LoadResult loaded = neutrino::loadModule(inputFile, ctx);
  if (loaded.status == neutrino::LoadStatus::SourceIoError)
    return failEarly(2, {{"error", "input.io", "cannot read " + inputFile}});
  if (loaded.status != neutrino::LoadStatus::Ok)
    return failEarly(
        1, {{"error", "ir.verify",
             "input IR does not verify (parse or verification failed)"}});
  mlir::OwningOpRef<mlir::ModuleOp> module = std::move(loaded.module);

  try {
    neutrino::Scenario sc = neutrino::loadScenario(scenarioFile);
    neutrino::ProcedureOp proc = neutrino::findProcedure(*module, sc.procedure);
    if (!proc)
      return failEarly(2, {{"error", "scenario.procedure",
                            "procedure '" + sc.procedure + "' not found"}});
    neutrino::ProcedureView view = neutrino::viewOf(proc);

    std::vector<std::string> scProblems = neutrino::validateScenario(view, sc);
    if (!scProblems.empty()) {
      std::vector<neutrino::Diagnostic> diags;
      for (const std::string &p : scProblems)
        diags.push_back({"error", "scenario.invalid", p});
      return failEarly(1, diags);
    }

    Expected<neutrino::CoordinationPlan> coordinationPlanE =
        neutrino::normalizePlan(view);
    if (!coordinationPlanE) {
      std::string msg = toString(coordinationPlanE.takeError());
      std::string code = "spec.ast";
      size_t left = msg.find('[');
      size_t right = msg.find(']', left);
      if (left != std::string::npos && right != std::string::npos &&
          right > left + 1)
        code = msg.substr(left + 1, right - left - 1);
      return failEarly(1, {{"error", code, msg}});
    }
    neutrino::CoordinationPlan coordinationPlan = std::move(*coordinationPlanE);

    outs() << "== Equivalence: " << sc.name << " ==\n\n";

    // ---- 1. Python-free reference recomputed from IR + scenario ----
    std::map<std::string, long long> env;
    for (auto &p : view.inputs) {
      auto it = sc.inputs.find(p.first);
      if (it != sc.inputs.end() && it->second.isInt)
        env[p.first] = it->second.i;
    }
    std::map<std::string, long long> computed;
    std::vector<std::string> problems;
    for (auto &c : view.computes) {
      long long val = neutrino::evalExpr(*c.ast, env);
      computed[c.name] = val;
      env[c.name] = val;
      auto it = sc.computed.find(c.name);
      if (it != sc.computed.end() && it->second != val)
        problems.push_back("computed " + c.name + ": reference " +
                           std::to_string(val) + " != scenario " +
                           std::to_string(it->second));
    }
    // A guarded leg contributes only when its predicate holds in this scenario.
    std::vector<std::string> events = neutrino::eventChain(view, env);
    if (!sc.events.empty() && events != sc.events)
      problems.push_back("events: reference chain != scenario events");
    std::map<std::string, long long> ledger;
    for (auto &e : view.entries) {
      // The reference ledger uses the same scenario predicate as its event.
      if (e.guardAst && !neutrino::evalGuard(*e.guardAst, env))
        continue;
      long long amt = refValue(e.amount, env, computed);
      ledger[e.ledger] += (e.kind == "credit" ? amt : -amt);
    }
    for (auto &kv : sc.ledger)
      if (ledger[kv.first] != kv.second)
        problems.push_back("ledger " + kv.first + ": reference " +
                           std::to_string(ledger[kv.first]) + " != scenario " +
                           std::to_string(kv.second));

    outs() << "Reference (recomputed from IR + scenario):\n";
    for (auto &kv : computed)
      outs() << "  computed " << kv.first << " = " << kv.second << "\n";
    outs() << "  events  = ";
    for (size_t i = 0; i < events.size(); ++i)
      outs() << events[i] << (i + 1 < events.size() ? " -> " : "\n");
    for (auto &kv : ledger)
      outs() << "  net " << kv.first << " = " << kv.second << "\n";
    bool refOk = problems.empty();
    if (!refOk) {
      outs() << "  MISMATCH:\n";
      for (auto &p : problems)
        outs() << "    - " << p << "\n";
    }
    outs() << "\n";

    // ---- 1b. normalized trace-equivalence vs the reference evaluator ----
    // Semantic agreement: the reference evaluator's ORDERED observation trace
    // (the oracle) vs an independent realization (this harness's recompute
    // above), each normalized to the observable subset (outcome / computed /
    // events / net ledger / terminal / replay). Package profile compatibility
    // independently controls backend invocation; an incompatible coordination
    // plan is REFUSED, not misleadingly invoked. The trace fails closed on an
    // empty observation set, and --tamper proves the comparison non-vacuous by
    // breaking the candidate.
    bool traceOk = true;
    int observationCount = 0, tqExecuted = 0;
    neutrino::TraceDivergence div;
    std::vector<std::string> traceProblems;
    struct BackendProfile {
      std::string name, id;
      int version;
      bool compatible;
      std::string detail;
    };
    std::vector<BackendProfile> tqBackends;
    {
      neutrino::TransitionResult refT =
          referenceTransition(coordinationPlan, sc);
      observationCount = (int)refT.trace.size();
      neutrino::ObservedTrace refObs = neutrino::observedFromTransition(refT);

      // Candidate = this harness's INDEPENDENT recompute, normalized: the
      // derived computed/events/net-ledger, completed with the committed
      // terminal + resolved replay key.
      neutrino::ObservedTrace candObs;
      candObs.outcome = "committed";
      candObs.computed = computed;
      // Normalize the independent realization to the reference vocabulary.
      // An evidence-only plan has one acceptance event and no movement events;
      // effectful plans derive movement events from the recomputed event chain.
      if (coordinationPlan.evidenceOnly) {
        candObs.events.push_back(
            neutrino::pascalCase(coordinationPlan.procedure) + "Accepted");
      } else {
        for (const std::string &e : events) {
          StringRef s(e);
          if (s.endswith("Debited") || s.endswith("Credited") ||
              s.endswith("Reconciled"))
            candObs.events.push_back(e);
        }
      }
      candObs.ledger = ledger;
      candObs.terminal = coordinationPlan.terminal.success;
      if (auto it = sc.inputs.find(coordinationPlan.workflowKey);
          it != sc.inputs.end())
        candObs.postedKeys.insert(
            it->second.isInt ? std::to_string(it->second.i) : it->second.s);

      // SELF-TEST: --tamper deliberately breaks the candidate; a tamper that
      // finds nothing to break is a vacuous self-test and fails closed.
      if (!tamper.empty()) {
        neutrino::TamperKind tk;
        if (!neutrino::parseTamperKind(tamper, tk)) {
          traceOk = false;
          traceProblems.push_back("unknown --tamper kind '" +
                                  tamper.getValue() + "'");
        } else {
          neutrino::ObservedTrace before = candObs;
          neutrino::applyTamper(candObs, tk);
          bool changed = before.outcome != candObs.outcome ||
                         before.events != candObs.events ||
                         before.ledger != candObs.ledger ||
                         before.terminal != candObs.terminal ||
                         before.postedKeys != candObs.postedKeys ||
                         before.computed != candObs.computed;
          if (!changed) {
            traceOk = false;
            traceProblems.push_back("--tamper '" + tamper.getValue() +
                                    "' could not break the trace (vacuous)");
          }
        }
      }

      // Per-package profile compatibility — refuse, don't invoke.
      for (const neutrino::CatalogTarget *target : backendTargets) {
        Expected<json::Value> summary =
            json::parse(target->canonicalProfileSummary);
        const json::Object *summaryObject =
            summary ? summary->getAsObject() : nullptr;
        if (!summaryObject) {
          if (!summary)
            consumeError(summary.takeError());
          tqBackends.push_back(
              {target->name, target->targetProfileIdentity,
               target->semanticProfileVersion, false,
               "verified package profile is not a JSON object"});
          continue;
        }
        neutrino::SemanticProfile prof =
            neutrino::semanticProfileFromJson(*summaryObject);
        std::vector<neutrino::Diagnostic> pd =
            neutrino::checkPlanLegality(coordinationPlan, prof);
        bool compat = neutrino::planIsLegal(pd);
        tqBackends.push_back({target->name, prof.id, prof.version, compat,
                              compat ? "" : pd.front().message});
      }

      if (observationCount == 0) {
        traceOk = false; // empty trace -> nothing proven -> fail closed
        traceProblems.push_back("reference trace is empty");
      } else if (traceProblems.empty()) {
        div = neutrino::compareTraces(refObs, candObs);
        if (div.diverged) {
          traceOk = false;
          traceProblems.push_back(
              "observable divergence in " + div.field + " [" + div.locator +
              "]: reference " + div.expected + " != realization " + div.actual);
        }
        tqExecuted = 1;
      }
    }

    // ---- 2. invoke verified package backends ----
    struct BackendRun {
      std::string name;
      int status = 1;
      std::string detail;
      std::string stage;
      int structuralStatus = 1;
      std::vector<std::string> missing;
      std::string packageManifestDigest;
      std::string targetProfileIdentity;
      std::string dispatchReceiptDigest;
      std::vector<neutrino::backend_dispatch_receipt::ArtifactIdentity>
          artifacts;
    };
    std::vector<BackendRun> backendRuns;
    // The renderers now consume the canonical spec (//); confirm
    // the verified artifact manifest retains the finalized identities.
    if (!referenceOnly) {
      Expected<neutrino::projection::BackendProjectionGraph> graph =
          neutrino::projection::projectBackendGraph(coordinationPlan);
      if (!graph)
        return failEarly(1,
                         {{"error", "equivalence.backend_failed",
                           "cannot construct finalized backend projection: " +
                               toString(graph.takeError())}});

      std::map<std::string, const BackendProfile *> profiles;
      for (const BackendProfile &profile : tqBackends)
        profiles.emplace(profile.name, &profile);

      uint64_t requestId = 1;
      for (const neutrino::CatalogTarget *target : backendTargets) {
        BackendRun backend;
        backend.name = target->name;
        const neutrino::backend_package::VerifiedPackage &package =
            catalog.packageFor(*target);
        backend.packageManifestDigest = package.descriptor().manifestDigest;
        backend.targetProfileIdentity =
            package.descriptor().targetProfileIdentity;
        const BackendProfile &profile = *profiles.at(target->name);
        if (!profile.compatible) {
          backend.status = 2;
          backend.stage = "profile";
          backend.detail = profile.detail;
          backend.structuralStatus = 2;
          backendRuns.push_back(std::move(backend));
          ++requestId;
          continue;
        }

        neutrino::backend_invocation::InvocationOptions options;
        options.requestId = requestId++;
        options.coreIdentity = neutrino::backend_invocation::coreIdentity();
        options.outputSpec.maxArtifacts = 1024;
        options.outputSpec.maxTotalBytes = 256u * 1024u * 1024u;
        Expected<neutrino::backend_invocation::Result> invoked =
            neutrino::backend_invocation::invoke(package, *graph, options);
        if (!invoked) {
          backend.status = 1;
          backend.stage = "invoke";
          backend.detail = toString(invoked.takeError());
          backendRuns.push_back(std::move(backend));
          continue;
        }

        Expected<std::string> receiptBytes =
            neutrino::backend_dispatch_receipt::createApproved(*invoked);
        if (!receiptBytes) {
          backend.status = 1;
          backend.stage = "receipt";
          backend.detail = toString(receiptBytes.takeError());
          backendRuns.push_back(std::move(backend));
          continue;
        }
        Expected<neutrino::backend_dispatch_receipt::VerifiedReceipt> receipt =
            neutrino::backend_dispatch_receipt::verify(*receiptBytes);
        if (!receipt) {
          backend.status = 1;
          backend.stage = "receipt";
          backend.detail = toString(receipt.takeError());
          backendRuns.push_back(std::move(backend));
          continue;
        }
        if (receipt->requestId != options.requestId ||
            receipt->coreIdentity != options.coreIdentity ||
            receipt->targetIdentity != target->name ||
            receipt->targetProfileIdentity !=
                package.descriptor().targetProfileIdentity ||
            receipt->packageManifestDigest !=
                package.descriptor().manifestDigest ||
            receipt->backendReceiptDigest != invoked->receiptDigest) {
          backend.status = 1;
          backend.stage = "receipt";
          backend.detail = "verified dispatch receipt does not match selected "
                           "package result";
          backendRuns.push_back(std::move(backend));
          continue;
        }
        backend.dispatchReceiptDigest = receipt->receiptDigest;
        backend.artifacts = receipt->artifacts;
        backend.status = 0;
        backend.stage = "";
        backend.detail = "verified package invocation";
        backend.structuralStatus = artifactStructural(
            view, coordinationPlan, *invoked, backend.missing);
        backendRuns.push_back(std::move(backend));
      }
    }

    auto mark = [](int s) {
      return s == 0 ? "PASS" : (s == 1 ? "FAIL" : "SKIP");
    };
    auto missTail = [](const std::vector<std::string> &m) {
      if (m.empty())
        return std::string();
      std::string s = "missing: ";
      for (size_t i = 0; i < m.size(); ++i)
        s += m[i] + (i + 1 < m.size() ? ", " : "");
      return s;
    };
    outs() << "Backend agreement:\n";
    outs() << "  Reference (IR + scenario)      " << (refOk ? "PASS" : "FAIL")
           << "\n";
    for (const BackendRun &backend : backendRuns)
      outs() << "  Package " << backend.name << "  " << mark(backend.status)
             << (backend.detail.empty() ? "" : "  " + backend.detail) << "\n";
    outs() << "Spec-vs-artifact (structural, ):\n";
    for (const BackendRun &backend : backendRuns)
      outs() << "  Package " << backend.name << "  "
             << mark(backend.structuralStatus) << "  "
             << missTail(backend.missing) << "\n";
    outs() << "\n";

    outs() << "Normalized trace-equivalence (vs reference evaluator):\n";
    outs() << "  Observation trace              " << (traceOk ? "PASS" : "FAIL")
           << "  (" << observationCount << " obs";
    if (!tamper.empty())
      outs() << ", tamper=" << tamper.getValue();
    outs() << ")\n";
    for (const BackendProfile &b : tqBackends)
      outs() << "  Profile " << b.name << " " << b.id << "@" << b.version
             << "  " << (b.compatible ? "compatible" : "REFUSED")
             << (b.detail.empty() ? "" : "  " + b.detail) << "\n";
    if (!traceOk)
      for (const std::string &p : traceProblems)
        outs() << "    " << p << "\n";
    outs() << "\n";

    bool anyFail = !refOk || !traceOk;
    bool anySkip = false;
    size_t successfulComparisons = 0;
    for (const BackendRun &backend : backendRuns) {
      anyFail = anyFail || backend.status == 1 || backend.structuralStatus == 1;
      anySkip = anySkip || backend.status == 2;
      if (backend.status == 0 && backend.structuralStatus == 0)
        ++successfulComparisons;
    }
    bool noBackendComparison = !referenceOnly && successfulComparisons == 0;
    anyFail = anyFail || noBackendComparison;
    int refStatus = refOk ? 0 : 1;
    bool equivalent = !anyFail && !(anySkip && !allowSkips);
    int resultCode = equivalent ? 0 : 1;

    // ---- 3. optional machine-readable report (agent-layer conventions) ----
    if (!reportDir.empty()) {
      std::error_code ec = sys::fs::create_directories(reportDir);
      if (ec) {
        errs() << "warning: could not create report dir " << reportDir << ": "
               << ec.message() << "\n";
      } else {
        json::Object computedObj;
        for (auto &kv : computed)
          computedObj[kv.first] = kv.second;
        json::Object ledgerObj;
        for (auto &kv : ledger)
          ledgerObj[kv.first] = kv.second;
        json::Array eventsArr;
        for (auto &e : events)
          eventsArr.push_back(e);
        json::Array mism;
        for (auto &p : problems)
          mism.push_back(p);

        auto backendEntry = [](StringRef name, int st, StringRef detail,
                               StringRef stage) {
          return json::Object{{"name", name},
                              {"status", statusStr(st)},
                              {"detail", detail},
                              {"stage", stage}};
        };
        json::Array backends;
        backends.push_back(backendEntry("reference", refStatus, "", ""));
        for (const BackendRun &backend : backendRuns) {
          json::Array artifacts;
          for (const auto &artifact : backend.artifacts)
            artifacts.push_back(json::Object{
                {"path", artifact.path},
                {"sha256", artifact.sha256},
                {"byteLen", static_cast<int64_t>(artifact.byteLen)}});
          json::Object entry = backendEntry(backend.name, backend.status,
                                            backend.detail, backend.stage);
          entry.insert(
              {"packageManifestDigest", backend.packageManifestDigest});
          entry.insert(
              {"targetProfileIdentity", backend.targetProfileIdentity});
          entry.insert(
              {"dispatchReceiptDigest", backend.dispatchReceiptDigest});
          entry.insert({"artifacts", std::move(artifacts)});
          backends.push_back(std::move(entry));
        }

        auto structEntry = [](StringRef name, int st,
                              const std::vector<std::string> &miss) {
          json::Array m;
          for (const std::string &x : miss)
            m.push_back(x);
          return json::Object{{"name", name},
                              {"status", statusStr(st)},
                              {"missing", std::move(m)}};
        };
        json::Array specStruct;
        for (const BackendRun &backend : backendRuns)
          specStruct.push_back(structEntry(
              backend.name, backend.structuralStatus, backend.missing));

        json::Array tqBackendsArr;
        for (const BackendProfile &b : tqBackends)
          tqBackendsArr.push_back(json::Object{{"name", b.name},
                                               {"profileId", b.id},
                                               {"profileVersion", b.version},
                                               {"compatible", b.compatible},
                                               {"detail", b.detail}});
        json::Object traceEquiv{{"ok", traceOk},
                                {"executedCases", tqExecuted},
                                {"observationCount", observationCount},
                                {"tamper", tamper.getValue()},
                                {"backends", std::move(tqBackendsArr)}};
        if (div.diverged)
          traceEquiv["divergence"] = json::Object{{"field", div.field},
                                                  {"locator", div.locator},
                                                  {"reference", div.expected},
                                                  {"realization", div.actual}};

        json::Object root{
            {"kind", "neutrino.equivalence-report"},
            {"version", "0.1.0"},
            {"generatedAt", isoNow()},
            {"mode", referenceOnly ? "reference-only" : "backend-equivalence"},
            {"scenario", sc.name},
            {"procedure", sc.procedure},
            {"ok", equivalent},
            {"resultCode", resultCode},
            {"allowSkips", allowSkips.getValue()},
            {"inputs",
             json::Object{
                 {"source",
                  json::Object{{"path", inputFile.getValue()},
                               {"sha256", neutrino::sha256OfFile(inputFile)}}},
                 {"scenario", json::Object{{"path", scenarioFile.getValue()},
                                           {"sha256", neutrino::sha256OfFile(
                                                          scenarioFile)}}}}},
            {"reference", json::Object{{"ok", refOk},
                                       {"computed", std::move(computedObj)},
                                       {"events", std::move(eventsArr)},
                                       {"ledger", std::move(ledgerObj)},
                                       {"mismatches", std::move(mism)}}},
            {"backends", std::move(backends)},
            {"specStructural", std::move(specStruct)},
            {"traceEquivalence", std::move(traceEquiv)}};

        SmallString<256> reportPath(reportDir.getValue());
        sys::path::append(reportPath, "equivalence.json");
        raw_fd_ostream os(reportPath, ec);
        if (ec)
          errs() << "warning: could not write " << reportPath << ": "
                 << ec.message() << "\n";
        else
          os << formatv("{0:2}", json::Value(std::move(root))) << "\n";

        std::vector<neutrino::Diagnostic> diags;
        for (auto &p : problems)
          diags.push_back({"error", "equivalence.reference_mismatch", p});
        for (const BackendRun &backend : backendRuns) {
          if (backend.status == 1)
            diags.push_back({"error", "equivalence.backend_failed",
                             backend.name + ": " + backend.detail});
          if (backend.status == 2)
            diags.push_back({allowSkips ? "warning" : "error",
                             "equivalence.backend_skipped",
                             backend.name + ": " + backend.detail});
          for (const std::string &missing : backend.missing)
            diags.push_back({"error", "equivalence.spec_artifact_mismatch",
                             backend.name + ": " + missing});
        }
        if (noBackendComparison)
          diags.push_back(
              {"error", "equivalence.backend_failed",
               "no compatible verified package backend completed structural "
               "comparison"});
        if (observationCount == 0 && !div.diverged)
          diags.push_back({"error", "equivalence.no_cases",
                           "reference trace is empty — nothing proven"});
        for (const std::string &p : traceProblems)
          diags.push_back({"error", "equivalence.trace_divergence", p});
        for (const BackendProfile &b : tqBackends)
          if (!b.compatible)
            diags.push_back({"warning", "equivalence.profile_incompatible",
                             std::string(b.name) + ": " + b.detail});
        SmallString<256> diagPath(reportDir.getValue());
        sys::path::append(diagPath, "diagnostics.json");
        neutrino::orderByRootCause(diags); // root-cause first ()
        neutrino::writeDiagnostics(std::string(diagPath), equivalent, diags);
        outs() << "report -> " << reportPath << "\n\n";
      }
    }

    if (!equivalent) {
      outs() << "RESULT: NOT equivalent.\n";
      if (noBackendComparison)
        outs() << "        no compatible verified package backend completed "
                  "structural comparison.\n";
      if (anySkip && !allowSkips)
        outs() << "        a package profile was refused; rerun with "
                  "--allow-skips to tolerate.\n";
      return resultCode;
    }
    if (referenceOnly)
      outs() << "RESULT: reference trace equivalent (reference-only mode).\n";
    else
      outs() << "RESULT: equivalent across reference trace and verified "
                "package backends.\n";
    return resultCode;
  } catch (const neutrino::ScenarioError &e) {
    return failEarly(2, {{"error", e.code, e.what()}});
  } catch (const std::exception &e) {
    return failEarly(2, {{"error", "internal", e.what()}});
  }
}

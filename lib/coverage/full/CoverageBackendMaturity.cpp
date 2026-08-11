#include "CoverageBackendMaturity.h"

#include "Neutrino/GenCoverageSpec.h"

#include "llvm/Support/ErrorHandling.h"
#include "llvm/Support/JSON.h"

#include <string>

using namespace llvm;

namespace {

std::string esc(StringRef value) {
  std::string out;
  for (char c : value) {
    switch (c) {
    case '"':
      out += "\\\"";
      break;
    case '\\':
      out += "\\\\";
      break;
    case '\n':
      out += "\\n";
      break;
    default:
      out += c;
    }
  }
  return out;
}

std::string q(StringRef value) { return "\"" + esc(value) + "\""; }

} // namespace

std::string
neutrino::coverageReportWithBundledMaturityFromSpec(const json::Object &spec) {
  std::string report = coverageReportFromSpec(spec);
  Expected<json::Value> parsed = json::parse(report);
  if (!parsed)
    report_fatal_error("internal coverage report is not valid JSON");
  const json::Object *core = parsed->getAsObject();
  if (!core)
    report_fatal_error("internal coverage report is not a JSON object");
  StringRef highest = core->getString("highestLevel").value_or("");
  if (highest.empty())
    report_fatal_error("internal coverage report has no highestLevel");

  size_t close = report.rfind("\n}\n");
  if (close == std::string::npos)
    report_fatal_error("internal coverage report has unexpected framing");
  report.resize(close);
  report += ",\n";

  report += "  \"targets\": [\n";
  const char *targets[] = {"solidity", "postgres"};
  for (size_t i = 0; i < 2; ++i) {
    report += "    {\n";
    report += "      \"target\": " + q(targets[i]) + ",\n";
    report += "      \"supportsThrough\": " + q(highest) + ",\n";
    report += "      \"formallyVerified\": false,\n";
    report += "      \"maturityCeiling\": { \"level\": 1, \"name\": \"Core "
              "Compliant\" }\n";
    report += "    }";
    report += (i + 1 < 2 ? ",\n" : "\n");
  }
  report += "  ],\n";
  report += "  \"maturityRule\": \"ceiling = f(highest verifiably-supported "
            "level, has-tests, "
            "formal-verification); L<=5 + tests + no formal verification => "
            "Level 1 'Core Compliant'. "
            "Level 2 'Verifiable & Secure' needs stronger runtime/security "
            "lifecycle evidence beyond the current translator-local "
            "property/mutation hardening.\"\n";
  report += "}\n";
  return report;
}

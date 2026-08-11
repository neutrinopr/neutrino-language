"""[fast] M5 oracle S5 (): observation-binding validator — positive accepted (incl. spec
portability across two bindings), negatives fail closed, and the schema-mirror self-test passes."""

import unittest

from _fastcase import FastCase

SCRIPT = "scripts/validators/validate_observation_binding.py"
SPEC = "examples/observation-binding/capability-spec.json"


class ObservationBinding(FastCase):
    def test_selftest(self):
        # The in-script schema-mirror + cross-ref self-test (valid passes; every invalid shape rejected).
        self.val_ok("observation-binding selftest", SCRIPT, "--selftest")

    def test_portability_two_bindings(self):
        # The SAME portable capability-spec is satisfied by two different deployment bindings
        # (different observers / keys / source id) — spec portability across observer bindings.
        self.val_ok("observation-binding canonical", SCRIPT,
                    "--binding", "examples/observation-binding/binding.json", "--spec", SPEC)
        self.val_ok("observation-binding alt deployment", SCRIPT,
                    "--binding", "examples/observation-binding/binding-alt.json", "--spec", SPEC)

    def test_negatives_fail_closed(self):
        # M>N, duplicate identities, missing keys, unsupported source, unbound set, bad kind, unsafe id
        # — each rejected. Cross-checked against the spec so the feasibility negatives are exercised.
        negs = self.globr("examples/observation-binding/negatives/*.json")
        for f in negs:
            self.val_reject(f"observation-binding negative {f.split('/')[-1]}",
                            SCRIPT, "--binding", f, "--spec", SPEC)
        self.require_floor("observation-binding negatives", len(negs), 7)


if __name__ == "__main__":
    unittest.main()

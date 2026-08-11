#!/usr/bin/env python3
"""[fast] PostgreSQL schema declaration inventory and zero-class closure."""

import os
import sys
import unittest
import unittest.mock

from _fastcase import REPO

sys.path.insert(0, os.path.join(REPO, "scripts", "gates"))
import check_target_node_registry as gate  # noqa: E402


class SchemaInventory(unittest.TestCase):
    def setUp(self):
        self.target = gate._read(os.path.join(REPO, gate._PG_TARGET_REL))
        self.model = gate._read(os.path.join(REPO, gate._PG_MODEL_REL))

    def sites(self, target=None, model=None):
        return gate.postgres_schema_construct_sites(
            self.target if target is None else target,
            self.model if model is None else model)

    def test_exact_zero_model_qualified_table_identities(self):
        # Every schema declaration is now a typed TableGen node; no handwritten
        # CREATE TABLE literal survives in either governed source file.
        sites = self.sites()
        self.assertEqual(len(sites), 0)
        for migrated in ("AuthorizedObserverTable", "CoordinationStatusTable",
                         "LedgerBalanceTable", "PostingIdempotencyTable",
                         "CommittedGroupTable", "PostingsTable", "KeyClaimTable",
                         "QuorumAcceptanceTable", "TemporalQuorumAcceptanceTable"):
            self.assertEqual(
                sum(s["node"] == migrated for s in sites), 0, migrated)

    def test_committed_inventory_matches_detection(self):
        inv = gate.load_inventory(gate.INVENTORY)
        expected = {gate._inventory_key(s) for s in self.sites()}
        committed = {
            gate._inventory_key(s) for s in inv["handwrittenSites"]
            if gate._item_model(s) == "PgSchemaDecl"
        }
        self.assertEqual(committed, expected)

    def test_each_zero_declaration_class_bites_independently(self):
        for node, marker in gate._PG_ZERO_DECLARATION_CLASSES:
            with self.subTest(node=node):
                injected = self.target + f'\nconst char *probe = "{marker}";\n'
                nodes = {s["node"] for s in self.sites(target=injected)}
                self.assertIn(node, nodes)

    def test_zero_class_words_in_comments_do_not_count(self):
        comments = "\n".join("// " + marker
                             for _, marker in gate._PG_ZERO_DECLARATION_CLASSES)
        nodes = {s["node"] for s in self.sites(target=self.target + comments)}
        self.assertFalse(nodes & {n for n, _ in gate._PG_ZERO_DECLARATION_CLASSES})

    def test_new_raw_table_is_discovered_before_classification(self):
        injected = self.target + '''
const char *rogue =
    "CREATE TABLE IF NOT EXISTS unregistered_table (id bigint);";
'''
        sites = self.sites(target=injected)
        unknown = [site for site in sites if site["node"] == "UnclassifiedTable"]
        # The inventory is empty, so the injected rogue is the only site.
        self.assertEqual(len(sites), 1)
        self.assertEqual(len(unknown), 1)
        self.assertIn("unregistered_table", unknown[0]["matcher"])

    def test_split_create_table_marker_is_reconstructed(self):
        injected = self.target + '''
const char *rogue = "CREATE TABLE IF NOT "
                    "EXISTS split_table (id bigint);";
'''
        unknown = [site for site in self.sites(target=injected)
                   if site["node"] == "UnclassifiedTable"]
        self.assertEqual(len(unknown), 1)
        self.assertIn("split_table", unknown[0]["matcher"])

    def test_registered_identity_substitution_is_not_laundered(self):
        # Every schema table is now a generated node, so simulate a re-introduced
        # raw declaration inside the governed function: the classifier credits it
        # to its registered identity only by exact name, and a renamed copy must
        # surface as unclassified rather than laundering the retired node.
        reintroduced = (
            'pgddl::RawSql renderTemporalSchema(const Cap &cap) {\n'
            '  return R("CREATE TABLE IF NOT EXISTS quorum_acceptance (\\n"\n'
            '           "    procedure text NOT NULL\\n);");\n'
            '}\n')
        classified = self.sites(model=reintroduced)
        self.assertTrue(any(
            site["node"] == "TemporalQuorumAcceptanceTable" for site in classified))
        substituted = reintroduced.replace(
            "quorum_acceptance", "quorum_acceptance_v2", 1)
        sites = self.sites(model=substituted)
        self.assertFalse(
            any(site["node"] == "TemporalQuorumAcceptanceTable" for site in sites))
        self.assertTrue(any(site["node"] == "UnclassifiedTable" and
                            "quorum_acceptance_v2" in site["matcher"]
                            for site in sites))

    def test_qualified_table_name_is_an_unclassified_candidate(self):
        injected = self.target + '''
const char *rogue =
    "CREATE TABLE IF NOT EXISTS public.rogue (id bigint);";
'''
        unknown = [site for site in self.sites(target=injected)
                   if site["node"] == "UnclassifiedTable"]
        self.assertEqual(len(unknown), 1)
        self.assertIn("public.rogue", unknown[0]["matcher"])

    def test_quoted_table_name_is_an_unclassified_candidate(self):
        injected = self.target + '''
const char *rogue =
    "CREATE TABLE IF NOT EXISTS \\"rogue\\" (id bigint);";
'''
        unknown = [site for site in self.sites(target=injected)
                   if site["node"] == "UnclassifiedTable"]
        self.assertEqual(len(unknown), 1)
        self.assertIn('"rogue"', unknown[0]["matcher"])

    def test_constructed_prefix_is_an_unclassified_candidate(self):
        injected = self.target + '''
std::string rogue =
    std::string("CREATE TABLE IF NOT EXISTS ") + "rogue (id bigint);";
'''
        unknown = [site for site in self.sites(target=injected)
                   if site["node"] == "UnclassifiedTable"]
        self.assertEqual(len(unknown), 1)
        self.assertIn("CREATE TABLE IF NOT EXISTS", unknown[0]["matcher"])


class DetectionOnlyRecovery(unittest.TestCase):
    def setUp(self):
        self.scanned = [s for s in gate.scan_handwritten_inventory()
                        if s["target"] == "postgres"]
        self.base_inventory = gate._git_show(
            "origin/main", gate._rel(gate.INVENTORY))

    def old_base(self, ref, path):
        if path == gate._rel(gate.INVENTORY):
            return self.base_inventory
        if path in (gate._PG_TARGET_REL, gate._PG_MODEL_REL):
            return gate._read(os.path.join(REPO, path))
        return None

    def test_prior_four_to_fifteen_recovery_is_not_reopened(self):
        with unittest.mock.patch.object(gate, "_git_show", self.old_base):
            self.assertFalse(gate._pg_schema_baseline_recovery_permitted(
                "synthetic-old-base", 4, 13, self.scanned))
            self.assertFalse(gate._pg_schema_baseline_recovery_permitted(
                "synthetic-old-base", 4, 16, self.scanned))

    def test_forged_identity_or_changed_author_source_is_rejected(self):
        forged = list(self.scanned)
        forged[-1] = dict(forged[-1], node="ForgedTable")
        with unittest.mock.patch.object(gate, "_git_show", self.old_base):
            self.assertFalse(gate._pg_schema_baseline_recovery_permitted(
                "synthetic-old-base", 4, 15, forged))

        def changed_source(ref, path):
            if path == gate._PG_MODEL_REL:
                return self.old_base(ref, path) + "\n"
            return self.old_base(ref, path)

        with unittest.mock.patch.object(gate, "_git_show", changed_source):
            self.assertFalse(gate._pg_schema_baseline_recovery_permitted(
                "synthetic-old-base", 4, 15, self.scanned))


class TwoVariantException(unittest.TestCase):
    """: the narrowly-governed two-fixed-variant exception (base + memo). It
    permits a delta==2 slice ONLY when both variants are the declared variants of
    exactly one authority retired in the same diff — and must bite on every wider
    shape the architect enumerated."""

    RETIRED = "PgSchemaDecl::PostingsTable"
    V1 = "PgSchemaDecl::PostingsTable"
    V2 = "PgSchemaDecl::PostingsWithMemoTable"

    def _inv(self, retires=RETIRED, variants=(V1, V2)):
        return {"variantGroups": [{"target": "postgres", "retires": retires,
                                   "variants": list(variants)}]}

    def _fixed_row(self, ordinal, node):
        return (f'  {{{ordinal}, "postgres", "{node}", "x", '
                'target_printer::LayoutKind::Lines, true, "CREATE...", "", '
                'nullptr, 0, nullptr, nullptr, nullptr, nullptr, 0, nullptr, '
                'nullptr, 0 },\n')

    def _field_row(self, ordinal, node):
        # A discriminator would carry a projected field (kXFields, N>0).
        return (f'  {{{ordinal}, "postgres", "{node}", "x", '
                'target_printer::LayoutKind::Lines, true, "CREATE...", "", '
                'kPostingsFields, 1, nullptr, nullptr, nullptr, nullptr, 0, '
                'nullptr, nullptr, 0 },\n')

    def setUp(self):
        self.added = frozenset({self.V1, self.V2})
        self.base_hw = frozenset({self.RETIRED, "PgSchemaDecl::KeyClaimTable"})
        self.cur_hw = frozenset({"PgSchemaDecl::KeyClaimTable"})  # retired this diff
        self.printer = (self._fixed_row(5, "PostingsTable")
                        + self._fixed_row(6, "PostingsWithMemoTable"))

    def permit(self, inv=None, added=None, base_hw=None, cur_hw=None, printer=None):
        return gate._two_variant_retirement_permitted(
            "postgres", inv if inv is not None else self._inv(),
            added if added is not None else self.added,
            base_hw if base_hw is not None else self.base_hw,
            cur_hw if cur_hw is not None else self.cur_hw,
            printer if printer is not None else self.printer)

    def test_committed_pair_is_permitted(self):
        self.assertTrue(self.permit())

    def test_unrelated_second_handler_rejected(self):
        # A second added handler that is not a declared variant of the group.
        added = frozenset({self.V1, "PgSchemaDecl::UnrelatedTable"})
        printer = (self._fixed_row(5, "PostingsTable")
                   + self._fixed_row(6, "UnrelatedTable"))
        self.assertFalse(self.permit(added=added, printer=printer))

    def test_missing_or_fake_retirement_mapping_rejected(self):
        # (a) no variantGroups at all.
        self.assertFalse(self.permit(inv={}))
        # (b) the declared authority was NOT retired this diff (still handwritten).
        self.assertFalse(self.permit(cur_hw=self.base_hw))
        # (c) the mapping points at an authority that was never handwritten.
        self.assertFalse(self.permit(inv=self._inv(retires="PgSchemaDecl::Ghost")))

    def test_third_variant_rejected(self):
        # A group must declare EXACTLY two distinct variants.
        three = self._inv(variants=(self.V1, self.V2, "PgSchemaDecl::PostingsExtra"))
        self.assertFalse(self.permit(inv=three))
        # And an added set of size three is not a two-variant pair.
        added3 = frozenset({self.V1, self.V2, "PgSchemaDecl::PostingsExtra"})
        self.assertFalse(self.permit(added=added3))

    def test_unreachable_variant_rejected(self):
        # A declared variant with no generated printer row (never emitted).
        printer = self._fixed_row(5, "PostingsTable")  # V2 row absent
        self.assertFalse(self.permit(printer=printer))

    def test_table_level_discriminator_rejected(self):
        # A variant carrying a projected field (a discriminator) is not a fixed shape.
        printer = (self._fixed_row(5, "PostingsTable")
                   + self._field_row(6, "PostingsWithMemoTable"))
        self.assertFalse(self.permit(printer=printer))

    def test_second_same_model_retirement_rejected(self):
        # The exception credits EXACTLY one authority; a second same-model
        # authority retiring in the same diff (masked behind the two variants)
        # must reject — it must not launder an uncredited retirement.
        base_hw = frozenset({self.RETIRED, "PgSchemaDecl::OtherRetired",
                             "PgSchemaDecl::KeyClaimTable"})
        cur_hw = frozenset({"PgSchemaDecl::KeyClaimTable"})
        self.assertFalse(self.permit(base_hw=base_hw, cur_hw=cur_hw))

    def test_two_groups_claiming_same_pair_rejected(self):
        # Two variantGroups claiming the SAME added pair through DIFFERENT
        # retirement IDs is ambiguous — reject (a pair maps to exactly one group).
        inv = {"variantGroups": [
            {"target": "postgres", "retires": self.RETIRED,
             "variants": [self.V1, self.V2]},
            {"target": "postgres", "retires": "PgSchemaDecl::OtherRetired",
             "variants": [self.V1, self.V2]},
        ]}
        base_hw = frozenset({self.RETIRED, "PgSchemaDecl::OtherRetired",
                             "PgSchemaDecl::KeyClaimTable"})
        cur_hw = frozenset({"PgSchemaDecl::KeyClaimTable"})
        self.assertFalse(self.permit(inv=inv, base_hw=base_hw, cur_hw=cur_hw))


if __name__ == "__main__":
    unittest.main()

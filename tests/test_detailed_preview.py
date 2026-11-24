import unittest
from unittest.mock import MagicMock, patch

from remediation.other_fields import scan_other_fields
from remediation.runner import Config
from test_policy import concept, edge


class DetailedPreviewTests(unittest.TestCase):
    cfg = Config("cdm", "vocab", ("measurement",), "2026-01-01")

    def scan(self, table, column, rows, detailed=True):
        cur = MagicMock()
        cur.fetchall.return_value = rows
        with patch("remediation.runner._uses_metadata", return_value=False), patch("remediation.runner.qfile") as query:
            result = scan_other_fields(cur, self.cfg, {table:{column}}, detailed_preview=detailed)
            query.assert_called_once_with("preview.sql", cdm="cdm", vocab="vocab", table=table, column=column)
        return result

    def test_unit_audit_keeps_every_active_target_and_counts_once(self):
        current=dict(concept(standard=None,domain="Unit"), concept_code="UC1", concept_class_id="Unit")
        default=edge()
        good=dict(default, concept_id_2=2, target=concept(domain="Unit"))
        wrong=dict(default, concept_id_2=3, target=concept(domain="Gender"))
        missing=dict(default, concept_id_2=4, target=None)
        expired=dict(default, concept_id_2=5, valid_end_date="2020-01-01")
        rows=[dict(old_id=7,old=current,record_count=10,edges=[good,wrong,wrong,missing,expired]),
              dict(old_id=8,old=concept(domain="Unit",standard="S"),record_count=90,edges=[])]
        out=self.scan("measurement","unit_concept_id",rows)
        finding,=out["findings"]
        inv=next(r for r in out["inventory"] if r["state"]=="SCANNED")
        self.assertEqual((10,100),(finding["record_count"],inv["scanned_occurrences"]))
        self.assertEqual(finding["source_evidence"]["concept_code"],"UC1")
        self.assertEqual(finding["candidate_counts"],{"Maps to":3,"Maps to value":0})
        self.assertEqual([c["concept_id"] for c in finding["candidates"]],[2,3,3,4])
        self.assertTrue(finding["candidates"][1]["field_domain_mismatch"])
        self.assertEqual(finding["candidates"][-1]["status"],"MISSING_TARGET")
        legacy=self.scan("measurement","unit_concept_id",rows,False)["findings"][0]
        self.assertNotIn("source_evidence",legacy)
        self.assertNotIn("field_domain_mismatch",legacy["candidates"][1])

    def test_coded_null_and_value_mapping_are_distinct(self):
        value=dict(edge(),relationship_id="Maps to value")
        rows=[dict(old_id=None,old=None,record_count=4,edges=[]),dict(old_id=7,old=concept(standard=None),record_count=2,edges=[edge(),value])]
        findings=self.scan("measurement","value_as_concept_id",rows)["findings"]
        self.assertEqual(findings[0]["status"],"OPTIONAL_NOT_POPULATED")
        self.assertIn("can be expected",findings[0]["guidance"])
        d=findings[1]
        self.assertEqual(d["expected_relationship"],"Maps to value")
        self.assertEqual([c["relationship_role"] for c in d["candidates"]],["supplementary context","primary for field review"])

    def test_demographics_and_both_death_fields(self):
        def row(domain):
            return [dict(old_id=7,old=concept(domain=domain,standard="S"),record_count=2,edges=[])]
        race,=self.scan("person","race_concept_id",row("Ethnicity"))["findings"]
        self.assertEqual((race["status"],race["expected_domain"]),("WRONG_DOMAIN_REVIEW","Race"))
        death=self.scan("death","cause_concept_id",row("Observation"))
        self.assertEqual(death["findings"],[])
        d,=self.scan("death","death_type_concept_id",row("Condition"))["findings"]
        self.assertEqual((d["audit_category"],d["expected_domain"]),("DEATH_TYPE","Type Concept"))

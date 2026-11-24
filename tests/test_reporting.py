import unittest,tempfile,json
from pathlib import Path
from copy import deepcopy
from unittest.mock import patch, MagicMock
from remediation.reporting import make_payload,validate_confirmation,render_private_pdf,apply_and_report,load_committed_payload
from remediation.other_fields import specification,inventory_from_columns,finding_status
from remediation.catalog import CATALOG
from remediation.policy import classify

def fixture():
    pairs=[]
    for i,(table,domain) in enumerate([("condition_occurrence","Condition"),("measurement","Measurement"),("observation","Observation")]):
        pairs.append(dict(table=table,column={"condition_occurrence":"condition_concept_id","measurement":"measurement_concept_id","observation":"observation_concept_id"}[table],old_id=900000001+i,new_id=900000101+i,updated_rows=[2,180,1300][i],complete=True,old_name="Synthetic old concept "+str(i),new_name="Synthetic replacement concept "+str(i),old_domain=domain,new_domain=domain,old_vocabulary="SYNTHETIC",new_vocabulary="SYNTHETIC"))
    inv=inventory_from_columns({"person":["gender_concept_id","race_concept_id","ethnicity_concept_id","gender_source_concept_id"],"measurement":["measurement_concept_id","unit_concept_id"]},"5.4")
    for r in inv:
        if r["state"]=="TO_SCAN":r["state"]="SCANNED"
    aux=[dict(table="person",column="gender_concept_id",category="DEMOGRAPHIC",role="OTHER_CONTENT",concept_id=900000401,concept_name="Synthetic nonstandard demographic label",domain="Gender",vocabulary="SYNTHETIC",status="NONSTANDARD_REVIEW",record_count=3,candidates=[]),
         dict(table="measurement",column="unit_concept_id",category="UNIT",role="OTHER_CONTENT",concept_id=900000402,concept_name="Synthetic unit label",domain="Unit",vocabulary="SYNTHETIC",status="NONSTANDARD_REVIEW",record_count=129,candidates=[dict(concept_id=900000501,concept_name="Synthetic unit candidate",relationship="Maps to",domain="Unit",vocabulary="SYNTHETIC",status="STANDARD_VALID_TARGET_REQUIRES_FIELD_REVIEW")])]
    return dict(report_version=2,run_id="00000000-0000-4000-8000-000000000001",plan_hash="a"*64,cdm_version="5.4",vocabulary_as_of="2026-01-01",vocabulary=[],plan_created_at="2026-01-01T00:00:00+00:00",verified_at="2026-01-01T00:10:00+00:00",coverage=[dict(r,state="SELECTED_FOR_REVIEW" if r["policy"]=="REVIEW_THEN_APPLY" else "AUDIT_ONLY") for r in CATALOG],pairs=pairs,updated_rows=1482,table_field_pair_count=3,distinct_concept_pairs=3,before_summary=[],after_summary=[dict(table="condition_occurrence",column="condition_concept_id",status="MULTIPLE_MAPS",record_count=4)],other_audit=dict(scanned_at="2026-01-01T00:00:00+00:00",inventory=inv,findings=aux))

class ReportTests(unittest.TestCase):
    def test_refuse_unconfirmed_pdf(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):render_private_pdf(fixture(),Path(d)/"x.pdf")
    def test_report_counts_must_match(self):
        p=fixture();p["updated_rows"]+=1
        with self.assertRaises(ValueError):validate_confirmation(p,p["pairs"])
    def test_duplicate_pair_rejected(self):
        p=fixture();p["pairs"].append(p["pairs"][0])
        with self.assertRaises(ValueError):validate_confirmation(p,p["pairs"])
    def test_incomplete_journal_rejected(self):
        p=fixture();p["pairs"][0]["complete"]=False
        with self.assertRaises(ValueError):validate_confirmation(p,p["pairs"])
    def test_no_pdf_for_rehearsal(self):
        with patch("remediation.runner.apply_plan",return_value={"run_id":"x","committed":False,"updated_rows":5}),patch("remediation.reporting.generate_committed_report") as report:
            result=apply_and_report(None,None,{},"x.pdf")
            self.assertEqual(result["report_status"],"NOT_CREATED_REHEARSAL");report.assert_not_called()
    def test_report_failure_preserves_committed_status(self):
        with patch("remediation.runner.apply_plan",return_value={"run_id":"x","committed":True,"updated_rows":5}) as apply,patch("remediation.reporting.generate_committed_report",side_effect=OSError("test")):
            result=apply_and_report(None,None,{"run_id":"x"},"x.pdf")
            self.assertTrue(result["committed"]);self.assertEqual(result["report_status"],"FAILED_AFTER_COMMIT");apply.assert_called_once()
    def test_missing_and_reversed_runs_refused(self):
        from remediation.runner import Config
        for run in (None,{"reversed_at":"2026-01-02"}):
            conn=MagicMock();cur=conn.cursor.return_value.__enter__.return_value
            cur.fetchone.return_value=run
            with patch("remediation.runner._ensure_idle"),patch("remediation.runner._settings"),patch("remediation.runner._audit_contract"):
                with self.assertRaises(ValueError):load_committed_payload(conn,Config("cdm","vocab",("condition_occurrence",),"2026-01-01"),"00000000-0000-4000-8000-000000000001")
    def test_readback_identity_and_payload_mismatch_refused(self):
        from remediation.runner import Config
        cfg=Config("cdm","vocab",("condition_occurrence",),"2026-01-01")
        for change in ("identity","run","hash"):
            f=fixture();run=dict(run_id=f["run_id"],plan_hash=f["plan_hash"],database_identity="db",applied_at="2026-01-01",reversed_at=None,report_payload=f)
            if change=="identity":run["database_identity"]="other"
            if change=="run":f["run_id"]="other"
            if change=="hash":f["plan_hash"]="other"
            conn=MagicMock();cur=conn.cursor.return_value.__enter__.return_value;cur.fetchone.return_value=run;cur.fetchall.return_value=f["pairs"]
            with patch("remediation.runner._ensure_idle"),patch("remediation.runner._settings"),patch("remediation.runner._audit_contract"),patch("remediation.runner._identity",return_value="db"):
                with self.assertRaises(ValueError):load_committed_payload(conn,cfg,run["run_id"])
    def test_report_recovery_does_not_apply(self):
        from remediation.reporting import generate_committed_report
        with patch("remediation.reporting.load_committed_payload",return_value=fixture()),patch("remediation.reporting.render_private_pdf"),patch("remediation.runner.apply_plan") as apply:
            self.assertEqual(generate_committed_report(None,None,"x","x.pdf")["report_status"],"CREATED");apply.assert_not_called()
    def test_pdf_complete_pairs_small_counts_private(self):
        from pypdf import PdfReader
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"fixture.pdf";render_private_pdf(fixture(),path,synthetic_fixture=True)
            text="\n".join(p.extract_text() for p in PdfReader(path).pages)
            for p in fixture()["pairs"]:
                self.assertIn(str(p["old_id"]),text);self.assertIn(str(p["new_id"]),text)
            self.assertIn("SYNTHETIC TEST FIXTURE",text);self.assertIn("small",text);self.assertIn("1,482",text)
            self.assertIn("900000401",text);self.assertIn("Other-field scan inventory",text)
            self.assertNotIn("person_id",text);self.assertNotIn("row_id",text)
            with self.assertRaises(FileExistsError):render_private_pdf(fixture(),path,synthetic_fixture=True)
    def test_pdf_paginates_many_pairs(self):
        from pypdf import PdfReader
        p=fixture();p["pairs"]=[dict(p["pairs"][0],old_id=910000000+i,new_id=920000000+i) for i in range(60)];p.update(updated_rows=120,table_field_pair_count=60,distinct_concept_pairs=60)
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"long.pdf";render_private_pdf(p,path,synthetic_fixture=True)
            text="\n".join(x.extract_text() for x in PdfReader(path).pages)
            self.assertIn("910000059",text);self.assertIn("920000059",text)
    def test_catalogue_counts(self):
        for v,total,cdm,source in [("5.4",118,99,22),("5.5",126,102,25)]:
            fields=specification(v)["fields"]
            self.assertEqual(len(fields),total)
            self.assertEqual(sum(r["scope"]=="CDM" for r in fields),cdm)
            self.assertEqual(sum(r["scope"]=="CDM" and r["role"]=="SOURCE" for r in fields),source)
    def test_source_excluded_not_defect(self):
        inv=inventory_from_columns({"person":["gender_source_concept_id"]},"5.4")
        row=next(r for r in inv if r["table"]=="person" and r["column"]=="gender_source_concept_id")
        self.assertEqual(row["state"],"EXCLUDED_SOURCE_PROVENANCE")
    def test_fact_relationship_numbered_columns_catalogued(self):
        fields=specification("5.4")["fields"]
        self.assertTrue(any(f["column"]=="domain_concept_id_1" and f["role"]=="STRUCTURAL_REFERENCE" for f in fields))
    def test_present_unselected_primary_is_not_covered(self):
        inv=inventory_from_columns({"measurement":["measurement_concept_id"]},"5.4",("condition_occurrence",))
        row=next(r for r in inv if r["table"]=="measurement" and r["column"]=="measurement_concept_id")
        self.assertEqual(row["state"],"UNSCANNED_NOT_SELECTED_EVENT")
    def test_many_domains_chart_paginates(self):
        p=fixture();p["pairs"]=[dict(p["pairs"][0],old_id=910000000+i,new_id=920000000+i,new_domain="Synthetic domain "+str(i)) for i in range(50)]
        p.update(updated_rows=100,table_field_pair_count=50,distinct_concept_pairs=50)
        with tempfile.TemporaryDirectory() as d:render_private_pdf(p,Path(d)/"domains.pdf",synthetic_fixture=True)
    def test_required_case_normalized(self):
        for v in ("5.4","5.5"):
            f=next(r for r in specification(v)["fields"] if r["table"]=="condition_occurrence" and r["column"]=="condition_concept_id")
            self.assertTrue(f["required"])
    def test_audit_only_zero_plan_pdf(self):
        from remediation.reporting import generate_audit_only_report
        from remediation.runner import digest
        from pypdf import PdfReader
        f=fixture();plan=dict(format_version=2,rows=[],mapping_evidence=[],config={"cdm_version":"5.4"},created_at=f["plan_created_at"],coverage=f["coverage"],other_audit=f["other_audit"])
        plan["plan_hash"]=digest(plan)
        with tempfile.TemporaryDirectory() as d,patch("remediation.runner.apply_plan") as apply:
            path=Path(d)/"audit.pdf";result=generate_audit_only_report(plan,path)
            self.assertFalse(result["committed"]);apply.assert_not_called()
            text=" ".join(p.extract_text() for p in PdfReader(path).pages)
            self.assertIn("0 committed changes / no apply",text)
            for value in ("Maps to", "Unit", "SYNTHETIC"):self.assertIn(value,text)
            self.assertNotIn("data changes and journal were committed",text)
            plan["rows"]=[{}];plan["plan_hash"]=digest({k:v for k,v in plan.items() if k!="plan_hash"})
            with self.assertRaises(ValueError):generate_audit_only_report(plan,Path(d)/"bad.pdf")
    def test_missing_not_zero(self):
        inv=inventory_from_columns({},"5.5")
        self.assertTrue(any(r["state"]=="MISSING_OR_INACCESSIBLE_TABLE" for r in inv))
    def test_5_5_new_source_fields(self):
        fields=specification("5.5")["fields"]
        self.assertTrue(any(r["table"]=="measurement" and r["column"]=="value_as_source_concept_id" and r["role"]=="SOURCE" for r in fields))
    def test_structural_nonstandard_not_generic_violation(self):
        c=dict(standard_concept=None,invalid_reason=None,valid_start_date="2000-01-01",valid_end_date="2099-01-01")
        self.assertIsNone(finding_status(1,c,{"role":"STRUCTURAL_REFERENCE"},"2026-01-01"))
    def test_55_reuse_blocks(self):
        c=dict(domain_id="Condition",standard_concept=None,invalid_reason=None,valid_start_date="2000-01-01",valid_end_date="2099-01-01",_metadata=[{"reuse_status":"RP"}])
        self.assertEqual(classify(1,c,[],"Condition",True,"2026-01-01")[0],"CODE_REUSE_REVIEW")
    def test_55_mapping_precision_and_group_block(self):
        from test_policy import concept,edge
        for metadata in ({"relationship_predicate_id":"broadMatch"},{"relationship_group":1}):
            e=edge();e["_metadata"]=[metadata]
            self.assertEqual(classify(1,concept(),[e],"Condition",True,"2026-01-01")[0],"MAPPING_PRECISION_OR_GROUP_REVIEW")
    def test_55_source_category_block(self):
        from test_policy import concept,edge
        c=concept();c["_metadata"]=[{"concept_category":"A"}]
        self.assertEqual(classify(1,c,[edge()],"Condition",True,"2026-01-01")[0],"CONCEPT_CATEGORY_REVIEW")
    def test_55_target_reuse_block(self):
        from test_policy import concept,edge
        e=edge();e["target"]["_metadata"]=[{"reuse_status":"R"}]
        self.assertEqual(classify(1,concept(),[e],"Condition",True,"2026-01-01")[0],"TARGET_METADATA_REVIEW")
    def test_observation_permitted_noncore_domain(self):
        from test_policy import concept,edge
        self.assertEqual(classify(1,concept(domain="Social Context"),[edge(domain="Social Context")],"OBSERVATION_COMPATIBLE",True,"2026-01-01")[0],"ELIGIBLE_FOR_REVIEW")
    def test_observation_core_domain_rejected(self):
        from test_policy import concept,edge
        self.assertEqual(classify(1,concept(domain="Drug"),[edge(domain="Drug")],"OBSERVATION_COMPATIBLE",True,"2026-01-01")[0],"SOURCE_DOMAIN_MISMATCH")
if __name__=="__main__":unittest.main()

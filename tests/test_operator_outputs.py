import csv
import errno
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from remediation import reporting
from remediation.runner import export_review_tables

class TestOperatorOutputs(unittest.TestCase):
    def test_portable_publish_probe_and_no_overwrite(self):
        with TemporaryDirectory() as name:
            folder=Path(name)
            source=folder/"stage"
            target=folder/"report.pdf"
            source.write_bytes(b"staged report")
            with patch.object(reporting, "_windows_publish", False), \
                 patch.object(reporting.os, "link", side_effect=OSError(errno.EOPNOTSUPP, "unsupported")):
                reporting.check_report_destination(folder)
                self.assertEqual(list(folder.iterdir()),[source])
                reporting._publish(source,target)
                self.assertEqual(target.read_bytes(),b"staged report")
                source.write_bytes(b"not an overwrite")
                with self.assertRaises(FileExistsError):
                    reporting._publish(source,target)
                self.assertEqual(target.read_bytes(),b"staged report")
                partial=folder/"partial.pdf"
                def failed_copy(src,dst):
                    dst.write(b"incomplete")
                    raise OSError(errno.ENOSPC,"full")
                with patch.object(reporting.shutil,"copyfileobj",side_effect=failed_copy):
                    with self.assertRaises(OSError):
                        reporting._publish(source,partial)
                self.assertFalse(partial.exists())

    def test_preview_tables(self):
        def record(status,count):
            return dict(table="condition_occurrence",column="condition_concept_id",
                        old_id=2,old={},edges=[],new_id=None,status=status,record_count=count)
        with TemporaryDirectory() as name:
            paths=export_review_tables([record("CURRENT_STANDARD",9),record("CURRENT_STANDARD",5),
                record("NO_MAP",2),record("ELIGIBLE_FOR_REVIEW",7)],Path(name))
            def read(kind):
                with paths[kind].open(newline="",encoding="utf8") as f:
                    return list(csv.DictReader(f))
            self.assertEqual([r["record_count"] for r in read("already_standard")],["14"])
            self.assertEqual([r["status"] for r in read("proposed")],["ELIGIBLE_FOR_REVIEW"])
            self.assertEqual([r["status"] for r in read("manual_review")],["NO_MAP"])

    def test_notebook_apply_fails_before_database_write_when_output_invalid(self):
        notebook = json.loads(Path("Run_concept_remediation.ipynb").read_text(encoding="utf8"))
        code=["".join(c["source"]) for c in notebook["cells"] if c["cell_type"]=="code"]
        for s in code:
            compile(s,"Run_concept_remediation.ipynb","exec")
        apply_code=next(c for c in code if "apply_and_report(conn" in c)
        apply=Mock()
        st=dict(RUN_DATABASE=True,conn=object(), cfg=object(),plan={"rows":[1]}, private_output=Path("private"),
                require_rehearsal=Mock(),reviewed_rehearsal=object(),
                check_report_destination=Mock(side_effect=PermissionError),apply_and_report=apply)
        with self.assertRaises(PermissionError):
            exec(apply_code,st)
        apply.assert_not_called()
        recovery=next(c for c in code if "outcome = generate_committed_report" in c)
        self.assertNotIn("apply_and_report(", recovery)
        self.assertNotIn("apply_plan(", recovery)


    def test_rehearsal_matches_exact_plan_and_config(self):
        from remediation.operator import rehearsal_receipt, require_rehearsal
        plan={"run_id":"r","plan_hash":"h","rows":[{}]}
        receipt=rehearsal_receipt(plan,{"run_id":"r","committed":False,"updated_rows":1})
        with patch("remediation.operator._verify_plan"):
            require_rehearsal(plan,object(),receipt)
            with self.assertRaises(ValueError):
                require_rehearsal(plan,object(),None)
            with self.assertRaises(ValueError):
                require_rehearsal(dict(plan,plan_hash="different"),object(),receipt)
        with self.assertRaises(ValueError):
            rehearsal_receipt(plan,{"run_id":"r","committed":True,"updated_rows":1})

    def test_key_filter_preserves_clean_rows_and_standards(self):
        from remediation.runner import _split_key_counts
        src=[dict(table="drug_exposure",old_id=4,new_id=5,status="ELIGIBLE_FOR_REVIEW",record_count=6),
             dict(table="drug_exposure",old_id=5,new_id=None,status="CURRENT_STANDARD",record_count=9)]
        found=_split_key_counts(src,{("drug_exposure",4):{"DUPLICATE_EVENT_ID":2,"NULL_EVENT_ID":1}})
        self.assertEqual([(r["status"],r["record_count"]) for r in found],
                         [("DUPLICATE_EVENT_ID",2),("NULL_EVENT_ID",1),("ELIGIBLE_FOR_REVIEW",3),("CURRENT_STANDARD",9)])
        self.assertIsNone(found[0]["new_id"])
        self.assertEqual(found[2]["new_id"],5)


    def test_committed_artifact_bundle_matches_summary_and_sanitizes_strings(self):
        from pypdf import PdfReader
        from openpyxl import load_workbook
        from test_reporting import fixture
        data=fixture()
        data["confirmation"]="COMMITTED_JOURNAL_READBACK"
        data["pairs"][0]["old_name"]="=1+3"
        data["database_identity"]={"server":"DO_NOT_EXPORT"}
        with TemporaryDirectory() as name, patch.object(reporting,"load_committed_payload",return_value=data):
            path=Path(name)/"summary.pdf"
            r=reporting.generate_committed_report(None,None,data["run_id"],path,include_evidence=True)
            self.assertEqual(r["evidence_status"],"CREATED")
            evidence=json.loads(Path(r["json_path"]).read_text(encoding="utf8"))
            self.assertEqual(sum(p["updated_rows"] for p in evidence["changed_pairs"]),1482)
            self.assertNotIn("DO_NOT_EXPORT",Path(r["json_path"]).read_text(encoding="utf8"))
            wb=load_workbook(r["xlsx_path"])
            try:
                ws=wb["Committed pairs"]
                cells=[c for row in ws for c in row if c.value=="=1+3"]
                self.assertEqual([c.data_type for c in cells],["s"])
            finally:
                wb.close()
            text=" ".join(page.extract_text() for page in PdfReader(path).pages)
            self.assertIn("1,482",text)
            self.assertIn("Still needs review",text)
            self.assertNotIn("DO_NOT_EXPORT",text)

    def test_preview_bundle_uses_one_snapshot_and_preserves_unscanned(self):
        from pypdf import PdfReader
        from remediation.preview_report import render_preview_pdf
        from remediation.report_exports import export_evidence
        data=dict(kind="PREVIEW_NO_CHANGES",report_id="synthetic-preview",cdm_version="5.4",
            as_of="2026-01-01",scan_completed_at="synthetic",proposed_rows=1,blocked_rows=1,retained_rows=8,
            primary=[dict(table="condition_occurrence",column="condition_concept_id",status=status,
                          record_count=count,candidates=[]) for status,count in
                     [("ELIGIBLE_FOR_REVIEW",1),("DUPLICATE_EVENT_ID",1),("CURRENT_STANDARD",8)]],
            coverage=[],other_audit={"inventory":[dict(table="x",column="c",category="UNIT",state="UNSCANNED")],
                                    "findings":[]})
        with TemporaryDirectory() as name:
            path=Path(name)/"preview.pdf"
            render_preview_pdf(data,path,summary_only=True)
            out=export_evidence(data,path,committed=False)
            evidence=json.loads(Path(out["json_path"]).read_text(encoding="utf8"))
            self.assertEqual(evidence["report_id"],data["report_id"])
            self.assertEqual(evidence["manual_review"][0]["share_of_field"],0.1)
            self.assertIsNone(evidence["inventory"][0]["scanned_occurrences"])
            self.assertIn("Duplicate event ID",PdfReader(path).pages[0].extract_text())

    def test_failed_evidence_export_does_not_erase_verified_pdf(self):
        from test_reporting import fixture
        data=fixture()
        data["confirmation"]="COMMITTED_JOURNAL_READBACK"
        with TemporaryDirectory() as name, patch.object(reporting,"load_committed_payload",return_value=data),              patch("remediation.report_exports.export_evidence",side_effect=OSError("disk")):
            path=Path(name)/"committed.pdf"
            result=reporting.generate_committed_report(None,None,data["run_id"],path,include_evidence=True)
            self.assertTrue(path.is_file())
            self.assertEqual((result["report_status"],result["evidence_status"]),("CREATED","NOT_SAVED"))


    def test_report_output_cannot_use_repo(self):
        with self.assertRaisesRegex(ValueError,"outside all Git"):
            reporting.check_report_destination(Path("operator_reports"))

    def test_failed_plan_rebuild_clears_stale_approval(self):
        nb=json.loads(Path("Run_concept_remediation.ipynb").read_text(encoding="utf8"))
        code="".join(next(c for c in nb["cells"] if c["id"]=="cell-07")["source"])
        scope=dict(plan={"previous":True},reviewed_rehearsal=("previous",1),
                   conn=object(),cfg=object(),RUN_DATABASE=True,build_plan=Mock(side_effect=RuntimeError))
        with self.assertRaises(RuntimeError):
            exec(code,scope)
        self.assertIsNone(scope["plan"])
        self.assertIsNone(scope["reviewed_rehearsal"])

    def test_key_sql_checks_whole_table_not_only_candidate_concepts(self):
        from remediation.runner import _key_cte, Config, _screen_event_keys
        cfg=Config(cdm_schema="synthetic_cdm",vocabulary_schema="synthetic_vocab",tables=("drug_exposure",),as_of="2026-01-01")
        query,_=_key_cte(cfg,"drug_exposure")
        self.assertIn('FROM "synthetic_cdm"."drug_exposure" all_rows JOIN touched_keys',query.as_string())
        self.assertIn('HAVING count(*) > 1',query.as_string())
        cursor=Mock()
        cursor.fetchall.return_value=[{"old_id":4,"missing":1,"duplicate":2}]
        findings=_screen_event_keys(cursor,cfg,[dict(table="drug_exposure",old_id=4,new_id=5,
                            status="ELIGIBLE_FOR_REVIEW",record_count=6)])
        self.assertEqual(sum(r["record_count"] for r in findings),6)
        self.assertEqual(cursor.execute.call_args.args[1],([4],))


    def test_mixed_event_key_fixture_and_after_check(self):
        # SQL semantics in an in-memory fixture; adapt only the array parameter syntax.
        import sqlite3
        from remediation.runner import _key_cte, _split_key_counts, Config
        cfg=Config(cdm_schema="synthetic_cdm",vocabulary_schema="synthetic_vocab",tables=("drug_exposure",),as_of="2026-01-01")
        db=sqlite3.connect(":memory:")
        try:
            db.execute("ATTACH DATABASE ':memory:' AS synthetic_cdm")
            db.execute("CREATE TABLE synthetic_cdm.drug_exposure (drug_exposure_id,drug_concept_id)")
            db.executemany("INSERT INTO synthetic_cdm.drug_exposure VALUES (?,?)",
                           [(1,4),(2,4),(2,8),(None,4),(9,7),(9,7)])
            prefix=_key_cte(cfg,"drug_exposure")[0].as_string().replace("=ANY(%s)"," IN (?)")
            totals=prefix+"""SELECT count(*), count(d.event_key),
                sum(CASE WHEN c.event_key IS NULL THEN 1 ELSE 0 END)
                FROM candidates c LEFT JOIN duplicate_keys d USING (event_key)"""
            def screen():
                count,dup,missing=db.execute(totals,(4,)).fetchone()
                r=dict(table="drug_exposure",old_id=4,new_id=5,status="ELIGIBLE_FOR_REVIEW",record_count=count)
                return {x["status"]:x["record_count"] for x in _split_key_counts([r],
                    {("drug_exposure",4):{"DUPLICATE_EVENT_ID":dup,"NULL_EVENT_ID":missing}})}
            self.assertEqual(screen(),{"DUPLICATE_EVENT_ID":1,"NULL_EVENT_ID":1,"ELIGIBLE_FOR_REVIEW":1})
            db.execute("UPDATE synthetic_cdm.drug_exposure SET drug_concept_id=5 WHERE drug_exposure_id=1")
            self.assertEqual(screen(),{"DUPLICATE_EVENT_ID":1,"NULL_EVENT_ID":1})
        finally:
            db.close()

    def test_verify_closes_connection_even_if_export_cannot_run(self):
        nb=json.loads(Path("Run_concept_remediation.ipynb").read_text(encoding="utf8"))
        code="".join(next(c for c in nb["cells"] if c["id"]=="cell-13")["source"])
        conn=Mock()
        st=dict(conn=conn,cfg=object(),RUN_DATABASE=True,preview=Mock(side_effect=OSError))
        with self.assertRaises(OSError):
            exec(code,st)
        self.assertIsNone(st["conn"])
        conn.close.assert_called_once()

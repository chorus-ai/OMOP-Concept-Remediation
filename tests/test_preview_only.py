import json,tempfile,unittest
from pathlib import Path
from unittest.mock import MagicMock,patch
from remediation.preview_report import aggregate_preview,render_preview_pdf,scan_preview_only,preview_only_report
from remediation.runner import Config
from test_policy import concept,edge
from test_reporting import fixture

CFG=Config("cdm","vocab",("condition_occurrence",),"2026-01-01")
def sample():
    f=fixture();records=[]
    for status,old,new,edges in [("ELIGIBLE_FOR_REVIEW",900000001,2,[edge()]),("MULTIPLE_MAPS",900000002,None,[edge(),dict(edge(),concept_id_2=3)]),("NO_MAP",900000003,None,[])]:
        records.append(dict(table="condition_occurrence",column="condition_concept_id",old_id=old,old=concept(),new_id=new,edges=edges,status=status,record_count=7))
    return aggregate_preview(records,CFG,f["coverage"],f["other_audit"])

class PreviewTests(unittest.TestCase):
    def test_aggregate_allowlist_excludes_identifiers(self):
        data=sample();text=json.dumps(data)
        for forbidden in ('person_id','row_id','database_identity','operator_name'):self.assertNotIn(forbidden,text)
        self.assertEqual(data['proposed_rows'],7);self.assertEqual(data['blocked_rows'],14)
    def test_readonly_scan_never_capture_or_apply(self):
        conn=MagicMock();cur=conn.cursor.return_value.__enter__.return_value;f=fixture()
        with patch('remediation.runner._ensure_idle'),patch('remediation.runner._settings') as settings,patch('remediation.runner._check_cdm_version'),patch('remediation.runner._preview',return_value=[]) as preview,patch('remediation.runner._all_columns',return_value={}),patch('remediation.runner._coverage',return_value=[]),patch('remediation.other_fields.scan_other_fields',return_value=f['other_audit']),patch('remediation.runner._capture') as capture,patch('remediation.runner.apply_plan') as apply:
            data=scan_preview_only(conn,CFG)
            settings.assert_called_once_with(cur,CFG,True);preview.assert_called_once_with(cur,CFG,primary_only=True);capture.assert_not_called();apply.assert_not_called();self.assertEqual(data['proposed_rows'],0)
    def test_pdf_pairs_reasons_candidates_and_no_changes(self):
        from pypdf import PdfReader
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'preview.pdf';render_preview_pdf(sample(),path)
            text=' '.join(p.extract_text() for p in PdfReader(path).pages)
            for expected in ('PREVIEW - NO CHANGES','0 committed changes','900000001','900000002','900000003','MULTIPLE_MAPS','NO_MAP','Maps to','Other concept fields','Full other-field inventory'):self.assertIn(expected,text)
            self.assertNotIn('row_id',text);self.assertNotIn('person_id',text)
            with self.assertRaises(FileExistsError):render_preview_pdf(sample(),path)
    def test_noop_report(self):
        from pypdf import PdfReader
        data=sample();data['primary']=[];data.update(proposed_rows=0,blocked_rows=0,retained_rows=0)
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'empty.pdf';render_preview_pdf(data,path)
            text=' '.join(p.extract_text() for p in PdfReader(path).pages);self.assertIn('NO-OP',text)
    def test_report_failure_cannot_apply(self):
        with patch('remediation.preview_report.scan_preview_only',return_value=sample()),patch('remediation.preview_report.render_preview_pdf',side_effect=OSError()),patch('remediation.runner.apply_plan') as apply:
            with self.assertRaises(OSError):preview_only_report(None,None,'x.pdf')
            apply.assert_not_called()
    def test_preview_notebook_inert_and_no_apply_import(self):
        n=json.loads((Path(__file__).resolve().parents[1]/'Preview_concept_remediation.ipynb').read_text());scope={}
        for c in n['cells']:
            if c['cell_type']=='code':
                source=''.join(c['source']);self.assertNotIn('apply_plan',source);self.assertNotIn('build_plan',source);self.assertNotIn('save_plan',source);exec(compile(source,'preview notebook','exec'),scope)
        self.assertFalse(scope['RUN_DATABASE']);self.assertIsNone(scope['conn'])
if __name__=='__main__':unittest.main()

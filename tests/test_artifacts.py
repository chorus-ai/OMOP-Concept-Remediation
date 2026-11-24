import ast,json,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class ArtifactTests(unittest.TestCase):
    def test_notebook_inert_run_all(self):
        nb=json.loads((ROOT/"Run_concept_remediation.ipynb").read_text())
        scope={}
        for c in nb["cells"]:
            if c["cell_type"]=="code":
                self.assertIsNone(c["execution_count"]);self.assertEqual(c["outputs"],[])
                exec(compile("".join(c["source"]),"notebook","exec"),scope)
        self.assertFalse(scope["RUN_DATABASE"]);self.assertFalse(scope["COMMIT_CHANGES"])
        self.assertIsNone(scope["conn"])
    def test_python_syntax(self):
        for f in (ROOT/"remediation").glob("*.py"):ast.parse(f.read_text())
    def test_audit_insert_has_explicit_column_order(self):
        s=(ROOT/"remediation/runner.py").read_text()
        self.assertIn("INSERT INTO {}.journal(run_id,table_name,column_name,row_id,old_id,new_id,before_hash,after_hash) SELECT",s)
        self.assertNotIn("INSERT INTO {}.journal SELECT",s)
    def test_update_frozen_rows(self):
        s=(ROOT/"sql/update.sql").read_text()
        for fragment in ["p.row_id","p.old_id","p.before_hash","RETURNING","journal"]:self.assertIn(fragment,s)
        self.assertNotIn("source_concept_id",s)
    def test_no_embedded_absolute_paths_or_private_chat_links(self):
        for f in ROOT.rglob("*"):
            if ".venv" in f.parts or ".git" in f.parts:continue
            if f.is_file() and f.suffix in [".py",".md",".sql",".json",".ipynb"]:
                s=f.read_text(encoding="utf-8")
                # Construct strings so the test does not itself contain a forbidden link.
                self.assertNotIn("chatgpt"+".com/c/",s,str(f))
                self.assertNotIn("C:"+"\\Users\\",s,str(f))
if __name__=="__main__":unittest.main()

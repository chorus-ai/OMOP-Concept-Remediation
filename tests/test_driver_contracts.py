import unittest
from remediation.runner import Config,_settings,_lock_and_check,_ensure_idle,qfile

class CursorSpy:
    def __init__(self,reject=""):
        self.calls=[];self.reject=reject;self.last=""
    def execute(self,query,params=None):
        self.last=query if isinstance(query,str) else query.as_string()
        self.calls.append((self.last,params))
    def fetchall(self):return []
    def fetchone(self):
        if "c.relkind" in self.last:return {"oid":42,"relkind":"r","relrowsecurity":False}
        if self.reject and self.reject in self.last:return {"exists":1}
        return None

class DriverContractTests(unittest.TestCase):
    def cfg(self):return Config("cdm","vocab",("condition_occurrence",),"2026-01-01")
    def test_apply_read_committed(self):
        c=CursorSpy();_settings(c,self.cfg(),False)
        self.assertEqual(c.calls[0][0],"SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
    def test_preview_repeatable_read_only(self):
        c=CursorSpy();_settings(c,self.cfg(),True)
        self.assertIn("REPEATABLE READ READ ONLY",c.calls[0][0])
    def test_lock_before_catalog_validation(self):
        c=CursorSpy();_lock_and_check(c,self.cfg())
        self.assertTrue(c.calls[0][0].startswith("LOCK TABLE"))
        self.assertEqual(sum("IN SHARE MODE" in q for q,_ in c.calls),4)
    def test_generated_column_rejected(self):
        with self.assertRaisesRegex(ValueError,"Generated"):_lock_and_check(CursorSpy("attgenerated"),self.cfg())
    def test_inheritance_rejected(self):
        with self.assertRaisesRegex(ValueError,"Inherited"):_lock_and_check(CursorSpy("pg_inherits"),self.cfg())
    def test_trigger_rejected(self):
        with self.assertRaisesRegex(ValueError,"triggers"):_lock_and_check(CursorSpy("pg_trigger"),self.cfg())
    def test_inbound_fk_rejected(self):
        with self.assertRaisesRegex(ValueError,"foreign keys"):_lock_and_check(CursorSpy("pg_constraint"),self.cfg())
    def test_sql_composition_offline(self):
        for file,names in [("preview.sql",dict(cdm="cdm",vocab="vocab",table="measurement",column="measurement_concept_id")),
                           ("update.sql",dict(cdm="cdm",audit="audit",table="measurement",column="measurement_concept_id",pk="measurement_id"))]:
            text=qfile(file,**names).as_string()
            self.assertNotIn("{",text)
            self.assertIn('"measurement"',text)
    def test_nested_connection_rejected(self):
        class Conn:
            autocommit=False
        with self.assertRaises(ValueError):_ensure_idle(Conn())
    def test_active_transaction_rejected(self):
        class Conn:
            autocommit=True
            class info:transaction_status=2
        with self.assertRaises(ValueError):_ensure_idle(Conn())
if __name__=="__main__":unittest.main()

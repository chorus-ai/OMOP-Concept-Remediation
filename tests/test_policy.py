import unittest
from copy import deepcopy
from remediation.policy import classify,WRITABLE
from remediation.runner import Config,digest,_verify_plan,ident,apply_plan

D="2026-01-01"
def concept(i=1,domain="Condition",standard=None,invalid=None):
    return dict(concept_id=i,domain_id=domain,standard_concept=standard,invalid_reason=invalid,
                valid_start_date="2000-01-01",valid_end_date="2099-12-31")
def edge(i=2,domain="Condition",standard="S",kind="Maps to"):
    return dict(concept_id_2=i,relationship_id=kind,invalid_reason=None,valid_start_date="2000-01-01",valid_end_date="2099-12-31",target=concept(i,domain,standard))
class PolicyTests(unittest.TestCase):
    def check(self,expected,old_id=1,old=None,edges=None,writable=True):
        self.assertEqual(classify(old_id,old if old is not None else concept(),edges if edges is not None else [edge()],"Condition",writable,D)[0],expected)
    def test_eligible(self):self.check("ELIGIBLE_FOR_REVIEW")
    def test_invalid_source_allowed(self):self.check("ELIGIBLE_FOR_REVIEW",old=concept(invalid="U"))
    def test_expired_source_allowed(self):
        c=concept();c["valid_end_date"]="2020-01-01";self.check("ELIGIBLE_FOR_REVIEW",old=c)
    def test_zero(self):self.check("ZERO_CONCEPT",old_id=0)
    def test_null(self):self.check("NULL_CONCEPT",old_id=None)
    def test_missing(self):self.assertEqual(classify(9,None,[],"Condition",True,D)[0],"MISSING_CONCEPT")
    def test_current_standard(self):self.check("CURRENT_STANDARD",old=concept(standard="S"))
    def test_classification(self):self.check("CLASSIFICATION_REVIEW",old=concept(standard="C"))
    def test_standard_wrong_domain_not_clean(self):self.check("SOURCE_DOMAIN_MISMATCH",old=concept(domain="Drug",standard="S"))
    def test_source_domain(self):self.check("SOURCE_DOMAIN_MISMATCH",old=concept(domain="Observation"))
    def test_target_domain(self):self.check("TARGET_DOMAIN_MISMATCH",edges=[edge(domain="Observation")])
    def test_multimap_before_filter(self):self.check("MULTIPLE_MAPS",edges=[edge(),edge(3,"Observation")])
    def test_multimap_bad_target(self):self.check("MULTIPLE_MAPS",edges=[edge(),edge(3,standard=None)])
    def test_multimap_self(self):self.check("MULTIPLE_MAPS",edges=[edge(),edge(1)])
    def test_duplicate_same_target(self):self.check("ELIGIBLE_FOR_REVIEW",edges=[edge(),edge()])
    def test_self(self):self.check("ZERO_OR_SELF_MAP",edges=[edge(1)])
    def test_target_zero(self):self.check("ZERO_OR_SELF_MAP",edges=[edge(0)])
    def test_target_nonstandard(self):self.check("NONSTANDARD_TARGET",edges=[edge(standard=None)])
    def test_missing_target(self):
        e=edge();e["target"]=None;self.check("MISSING_TARGET",edges=[e])
    def test_invalid_target(self):
        e=edge();e["target"]["invalid_reason"]="D";self.check("INVALID_TARGET",edges=[e])
    def test_future_target(self):
        e=edge();e["target"]["valid_start_date"]="2090-01-01";self.check("INVALID_TARGET",edges=[e])
    def test_expired_edge(self):
        e=edge();e["valid_end_date"]="2020-01-01";self.check("NO_MAP",edges=[e])
    def test_future_edge(self):
        e=edge();e["valid_start_date"]="2090-01-01";self.check("NO_MAP",edges=[e])
    def test_missing_dates(self):
        e=edge();e["valid_start_date"]=None;self.check("NO_MAP",edges=[e])
    def test_maps_to_value_block(self):self.check("MAPS_TO_VALUE_REVIEW",edges=[edge(),edge(3,kind="Maps to value")])
    def test_no_replaced_by_fallback(self):self.check("NO_MAP",edges=[edge(kind="Concept replaced by")])
    def test_manual_field(self):self.check("MANUAL_FIELD",writable=False)
    def test_protected_fields_not_whitelisted(self):
        for _,field,_ in WRITABLE.values():
            self.assertNotIn(field,["value_as_concept_id","unit_concept_id","cause_concept_id"])
            self.assertNotIn("source",field);self.assertNotIn("type",field)

class ContractTests(unittest.TestCase):
    def cfg(self):return Config("cdm","vocab",("condition_occurrence",),D)
    def plan(self):
        p={"format_version":2,"config":self.cfg().__dict__,"rows":[{"table":"condition_occurrence","column":"condition_concept_id"}]};p["plan_hash"]=digest(p);return p
    def test_plan_digest_round_trip(self):
        import json
        _verify_plan(json.loads(json.dumps(self.plan())),self.cfg())
    def test_tamper(self):
        p=self.plan();p["rows"][0]["column"]="condition_source_concept_id"
        with self.assertRaises(ValueError):_verify_plan(p,self.cfg())
    def test_forged_protected_field(self):
        p=self.plan();p["rows"][0]["column"]="condition_source_concept_id";p.pop("plan_hash");p["plan_hash"]=digest(p)
        with self.assertRaises(ValueError):_verify_plan(p,self.cfg())
    def test_schema_injection(self):
        with self.assertRaises(ValueError):ident('cdm; DROP TABLE person')
    def test_no_audit_in_cdm(self):
        with self.assertRaises(ValueError):Config("cdm","vocab",("condition_occurrence",),D,audit_schema="cdm")
    def test_no_unknown_table(self):
        with self.assertRaises(ValueError):Config("cdm","vocab",("drug_era",),D)
    def test_no_empty_tables(self):
        with self.assertRaises(ValueError):Config("cdm","vocab",(),D)
    def test_no_duplicate_tables(self):
        with self.assertRaises(ValueError):Config("cdm","vocab",("person","person"),D)
    def test_no_negative_limits(self):
        with self.assertRaises(ValueError):Config("cdm","vocab",("person",),D,max_plan_rows=-1)

if __name__=="__main__":unittest.main()

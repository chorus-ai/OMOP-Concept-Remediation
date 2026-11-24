"""Explicit principal-content field inventory for CDM 5.4; policy is not a CDM flag."""
from .policy import WRITABLE
CATALOG = [dict(table=t,column=v[1],policy="REVIEW_THEN_APPLY",reason="Direct 1:1 same-domain mapping, reviewed plan required") for t,v in WRITABLE.items()] + [
    dict(table="death",column="cause_concept_id",policy="MANUAL_ONLY",reason="Cause semantics; no prescribed single domain or declared event primary key"),
    dict(table="note",column="note_class_concept_id",policy="MANUAL_ONLY",reason="Document classification requires accepted-concept/LOINC rules, not domain Note"),
    dict(table="note_nlp",column="note_nlp_concept_id",policy="MANUAL_ONLY",reason="NLP assertion/context and downstream relationships need separate review"),
    dict(table="episode",column="episode_object_concept_id",policy="MANUAL_ONLY",reason="Domain/class depends on disease versus treatment episode"),
    dict(table="condition_era",column="condition_concept_id",policy="REBUILD_REQUIRED",reason="Derived aggregate; rebuild after reviewed event remediation"),
    dict(table="drug_era",column="drug_concept_id",policy="REBUILD_REQUIRED",reason="Derived ingredient-era aggregate; rebuild separately"),
    dict(table="dose_era",column="drug_concept_id",policy="REBUILD_REQUIRED",reason="Derived ingredient/dose aggregate; rebuild separately"),
]
EVENT_TABLES = tuple(dict.fromkeys(r["table"] for r in CATALOG if r["policy"]!="REBUILD_REQUIRED"))

def coverage_from_columns(columns,selected):
    result=[]
    for entry in CATALOG:
        table,col=entry["table"],entry["column"]
        if table not in columns:state="MISSING_OR_INACCESSIBLE"
        elif col not in columns[table]:state="MISSING_FIELD"
        elif entry["policy"]=="REBUILD_REQUIRED":state="EXCLUDED_DERIVED"
        elif table not in selected:state="NOT_SELECTED"
        elif entry["policy"]=="MANUAL_ONLY":state="AUDIT_ONLY"
        else:state="SELECTED_FOR_REVIEW"
        result.append(dict(entry,state=state))
    return result

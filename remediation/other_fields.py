"""Read-only, version-specific concept-field inventory. Nonstandard is not always invalid use."""
import json
from pathlib import Path
from datetime import datetime,timezone
from .policy import valid

ROOT=Path(__file__).resolve().parents[1]
def specification(version):
    if version not in ("5.4","5.5"):raise ValueError("Supported catalogues: CDM 5.4 and 5.5")
    return json.loads((ROOT/"config"/("cdm_"+version.replace(".","")+".json")).read_text(encoding="utf-8"))

def inventory_from_columns(columns,version,selected_tables=None):
    result=[];known=set()
    for field in specification(version)["fields"]:
        key=(field["table"],field["column"]);known.add(key)
        if field["scope"]!="CDM":state="EXCLUDED_NON_CDM_SCHEMA"
        elif field["table"] not in columns:state="MISSING_OR_INACCESSIBLE_TABLE"
        elif field["column"] not in columns[field["table"]]:state="MISSING_OR_INACCESSIBLE_FIELD"
        elif field["role"]=="SOURCE":state="EXCLUDED_SOURCE_PROVENANCE"
        elif field["role"]=="PRIMARY_EVENT":state="COVERED_BY_EVENT_WORKFLOW" if selected_tables is not None and field["table"] in selected_tables else "UNSCANNED_NOT_SELECTED_EVENT"
        else:state="TO_SCAN"
        result.append(dict(field,state=state))
    # Extensions are visible but not silently assigned OMOP semantics.
    for table,cols in columns.items():
        for col in cols:
            if (col.endswith("concept_id") or "concept_id_" in col) and (table,col) not in known:
                result.append(dict(table=table,column=col,category="UNKNOWN_EXTENSION",role="UNKNOWN",scope="UNKNOWN",state="UNSCANNED_NOT_IN_VERSION_CATALOGUE"))
    return result

def finding_status(old_id,old,field,as_of):
    if old_id is None:return "NULL_REVIEW"
    if old_id==0:return "ZERO_REVIEW"
    if old is None:return "MISSING_CONCEPT"
    if old.get("invalid_reason") is not None:return "INVALID_CONCEPT"
    if not valid(old,as_of):return "OUT_OF_DATE_OR_MISSING_DATES"
    if field["role"]=="STRUCTURAL_REFERENCE":return None # Standardness is not a generic requirement here.
    expected=field.get("expected_domain")
    if expected and old.get("domain_id") not in [d.strip() for d in expected.split(",")]:return "WRONG_DOMAIN_REVIEW"
    if old.get("standard_concept")=="C":return "CLASSIFICATION_REVIEW"
    if old.get("standard_concept")!="S":return "NONSTANDARD_REVIEW"
    return None

def candidates_for_review(edges,as_of):
    out=[]
    for e in edges:
        if not valid(e,as_of):continue
        t=e.get("target")
        status="MISSING_TARGET" if not t else "NONSTANDARD_TARGET" if t.get("standard_concept")!="S" else "INVALID_OR_OUT_OF_DATE_TARGET" if not valid(t,as_of) else "STANDARD_VALID_TARGET_REQUIRES_FIELD_REVIEW"
        out.append(dict(concept_id=e["concept_id_2"],relationship=e["relationship_id"],concept_name=(t or {}).get("concept_name",""),domain=(t or {}).get("domain_id",""),vocabulary=(t or {}).get("vocabulary_id",""),status=status))
    return out

AUDIT_GUIDANCE={
    "TYPE": "Verify the documented provenance of this record; a valid Type Concept alone does not establish provenance.",
    "DEMOGRAPHIC": "Check the source category and site-approved mapping; never infer an individual demographic value.",
    "DEATH_CAUSE": "Check the documented cause of death and approved mapping. CDM 5.4/5.5 do not require a specific domain for this field.",
    "DEATH_TYPE": "Verify the source of death information independently of visit or condition provenance.",
    "UNIT": "Check the reported quantity and unit together. A unit substitution may require numeric conversion.",
    "VALUE": "Check the coded answer in the context of the measurement or observation and distinguish Maps to from Maps to value. A Maps to value link may belong to the original source code; its absence here is not itself a problem.",
}
def audit_category(field):
    key=(field["table"],field["column"])
    if key==("death","cause_concept_id"):return "DEATH_CAUSE"
    if key==("death","death_type_concept_id"):return "DEATH_TYPE"
    return field["category"]

def _vocab_evidence(concept):
    return {k:concept[k] for k in ("concept_code","concept_class_id","standard_concept","invalid_reason","valid_start_date","valid_end_date") if k in concept}

def auxiliary_preview_detail(field,row,status,as_of):
    category=audit_category(field)
    old=row["old"] or {}
    expected=field.get("expected_domain")
    expected_domains=expected.split(",") if expected else ()
    expected_domains={x.strip() for x in expected_domains}
    active=[edge for edge in row["edges"] if valid(edge,as_of)]
    candidates=candidates_for_review(active,as_of)
    expected_rel="Maps to value" if category=="VALUE" else "Maps to"
    for edge,candidate in zip(active,candidates):
        target=edge.get("target") or {}
        domain_review=bool(target and expected_domains and target.get("domain_id") not in expected_domains)
        candidate.update(_vocab_evidence(target))
        candidate["relationship_valid_from"]=edge.get("valid_start_date")
        candidate["relationship_valid_to"]=edge.get("valid_end_date")
        candidate["relationship_role"]="primary for field review" if candidate["relationship"]==expected_rel else "supplementary context"
        candidate["field_domain_mismatch"]=domain_review
        candidate["self_mapping"]=candidate["concept_id"]==row["old_id"]
        candidate["zero_target"]=candidate["concept_id"]==0
    counts={rel:len({c["concept_id"] for c in candidates if c["relationship"]==rel}) for rel in ("Maps to","Maps to value")}
    guidance=AUDIT_GUIDANCE.get(category,"Check the CDM definition, site context and any candidates; no replacement is proposed.")
    if status in ("NULL_REVIEW","OPTIONAL_NOT_POPULATED"):
        guidance=("Required field: investigate missing values. " if field.get("required") else
                  "Optional field: NULL can be expected; verify if this value should be populated. ")+guidance
    elif status=="ZERO_REVIEW":
        guidance="Concept ID 0 is a no-match sentinel, not a replacement. "+guidance
    return dict(audit_category=category,expected_domain=expected,required=field.get("required"),
                source_evidence=_vocab_evidence(old),candidate_counts=counts,candidates=candidates,guidance=guidance,expected_relationship=expected_rel)

def scan_other_fields(cur,cfg,columns,*,detailed_preview=False):
    from .runner import qfile,_uses_metadata
    use_metadata=_uses_metadata(cur,cfg)
    inventory=inventory_from_columns(columns,cfg.cdm_version,cfg.tables);findings=[]
    for field in inventory:
        if field["state"]!="TO_SCAN":continue
        cur.execute(qfile("preview55.sql" if use_metadata else "preview.sql",cdm=cfg.cdm_schema,vocab=cfg.vocabulary_schema,table=field["table"],column=field["column"]))
        field["state"]="SCANNED"
        field["scanned_occurrences"]=0
        for r in cur.fetchall():
            field["scanned_occurrences"]+=r["record_count"]
            status=finding_status(r["old_id"],r["old"],field,cfg.as_of)
            if detailed_preview and status=="NULL_REVIEW" and not field.get("required"):
                status="OPTIONAL_NOT_POPULATED"
            if status:
                old=r["old"] or {}
                finding=dict(table=field["table"],column=field["column"],category=field["category"],role=field["role"],concept_id=r["old_id"],concept_name=old.get("concept_name",""),domain=old.get("domain_id",""),vocabulary=old.get("vocabulary_id",""),standard_concept=old.get("standard_concept"),status=status,record_count=r["record_count"],candidates=candidates_for_review(r["edges"],cfg.as_of))
                if detailed_preview:
                    finding.update(auxiliary_preview_detail(field,r,status,cfg.as_of))
                findings.append(finding)
        if detailed_preview:
            field["audit_category"]=audit_category(field)
    if detailed_preview:
        for f in inventory:
            f.setdefault("audit_category",audit_category(f))
    return dict(scanned_at=datetime.now(timezone.utc).isoformat(),inventory=inventory,findings=findings,source_commit=specification(cfg.cdm_version)["source_commit"],cdm_version=cfg.cdm_version)

"""Private spreadsheet and JSON exports; no identifiers or storage transfer."""
from pathlib import Path
from tempfile import TemporaryDirectory
import json


def _only(row, names):
    return {key: row.get(key) for key in names.split()}


def _candidate(r):
    return _only(r,"concept_id concept_name vocabulary domain relationship status relationship_role")


def _finding(r, scope, denominators):
    o = _only(r,"table column old_id old_name old_domain old_vocabulary concept_id concept_name vocabulary domain status reason category record_count new_id")
    o["scope"] = scope
    o["semantic_review_required"] = r["status"] == "ELIGIBLE_FOR_REVIEW"
    o["scanned_occurrences"] = denominators.get((r["table"],r["column"]))
    n = o["scanned_occurrences"]
    o["share_of_field"] = r["record_count"] / n if n else None
    o["candidates"] = [_candidate(c) for c in r.get("candidates",[])]
    return o


def evidence_document(payload, *, committed):
    """Do not serialize the row-level approval plan or raw database identity."""
    aux=payload["other_audit"]
    inventory=[_only(r,"table column category state scanned_occurrences") for r in aux.get("inventory",[])]
    coverage=[_only(r,"table column state policy reason") for r in payload.get("coverage",[])]
    aux_totals={(r["table"],r["column"]):r["scanned_occurrences"] for r in inventory
                if r["state"]=="SCANNED" and r["scanned_occurrences"] is not None}
    other=[_finding(r,"plan_time_other_field",aux_totals) for r in aux.get("findings",[])]
    doc=dict(schema_version=1, kind="committed_remediation" if committed else "read_only_preview",
             report_id=payload["run_id"] if committed else payload["report_id"],
             counts_are="concept field occurrences, not patients",
             confidentiality="private; disclosure approval required before export to another service",
             cdm_version=payload["cdm_version"], coverage=coverage, inventory=inventory,
             vocabulary_versions=[_only(r,"vocabulary_id vocabulary_version") for r in payload.get("vocabulary",[])],
             auxiliary_scan_completed_at=aux.get("scanned_at"), other_field_findings=other,
             vocabulary_validity_as_of=payload["vocabulary_as_of" if committed else "as_of"])
    if committed:
        doc["journal_verified_at"]=payload.get("verified_at")
        doc["updated_rows"]=payload["updated_rows"]
        doc["changed_pairs"]=[_only(r,"table column old_id new_id old_name new_name old_domain new_domain old_vocabulary new_vocabulary updated_rows") for r in payload["pairs"]]
        doc["primary_after"]=[_only(r,"table column status record_count") for r in payload["after_summary"]]
    else:
        primary=payload["primary"]
        totals={}
        for r in primary:
            k=(r["table"],r["column"])
            totals[k]=totals.get(k,0)+r["record_count"]
        doc["scan_completed_at"]=payload["scan_completed_at"]
        doc["proposed_rows"]=payload["proposed_rows"]
        doc["blocked_rows"]=payload["blocked_rows"]
        doc["retained_rows"]=payload["retained_rows"]
        doc["proposed"]=[_finding(r,"primary",totals) for r in primary if r["status"]=="ELIGIBLE_FOR_REVIEW"]
        doc["manual_review"]=[_finding(r,"primary",totals) for r in primary if r["status"] not in ("ELIGIBLE_FOR_REVIEW","CURRENT_STANDARD")]
        retained={}
        for r in primary:
            if r["status"]=="CURRENT_STANDARD":
                k=(r["table"],r["column"])
                retained[k]=retained.get(k,0)+r["record_count"]
        doc["already_standard"]=[dict(table=t,column=c,record_count=n,scanned_occurrences=totals[t,c])
                                 for (t,c),n in sorted(retained.items())]
    return doc


def _workbook(doc, path):
    from openpyxl import Workbook
    wb=Workbook()
    wb.remove(wb.active)
    if doc.get("synthetic_fixture"):
        wb.properties.title="Synthetic test fixture - not a database result"
    meta={k:v for k,v in doc.items() if not isinstance(v,list)}
    candidates=[]
    def sheet(name, rows):
        ws=wb.create_sheet(name)
        headers=list(dict.fromkeys(k for r in rows for k in r if k!="candidates"))
        if not headers:
            ws.append(["No records"])
            return
        ws.append(headers)
        for r in rows:
            ws.append([r.get(k) for k in headers])
            for c in ws[ws.max_row]:
                if isinstance(c.value,str):
                    c.data_type="s"  # Labels are data, never Excel formulas.
        ws.freeze_panes="A2"
        ws.auto_filter.ref=ws.dimensions
    sheet("Summary",[{"item":k,"value":v} for k,v in meta.items()])
    for key,name in (("proposed","Proposed"),("manual_review","Manual review"),("already_standard","Already standard"),
                     ("changed_pairs","Committed pairs"),("primary_after","Primary after"),("other_field_findings","Other fields"),
                     ("coverage","Coverage"),("inventory","Field inventory"),("vocabulary_versions","Vocabulary versions")):
        if key not in doc:
            continue
        rows=[]
        for number,r in enumerate(doc[key],1):
            if r.get("candidates"):
                group=f"{key}:{number}"
                candidates.extend(dict(finding=group,**c) for c in r["candidates"])
                r=dict(r,finding=group)
            rows.append(r)
        sheet(name,rows)
    sheet("Candidate evidence",candidates)
    wb.save(path)


def export_evidence(payload, pdf_path, *, committed, synthetic_fixture=False):
    """Export from the exact report snapshot; published names are never replaced."""
    from .reporting import _publish
    doc=evidence_document(payload,committed=committed)
    if synthetic_fixture:
        doc={"synthetic_fixture":True,**dict(doc,confidentiality="synthetic demonstration; not a database result")}
    pdf_path=Path(pdf_path).resolve()
    json_path,xlsx_path=pdf_path.with_suffix(".json"),pdf_path.with_suffix(".xlsx")
    with TemporaryDirectory(prefix=".evidence-",dir=pdf_path.parent) as temp:
        jp=Path(temp)/json_path.name
        xp=Path(temp)/xlsx_path.name
        jp.write_text(json.dumps(doc,indent=2,ensure_ascii=False,default=str)+"\n",encoding="utf8")
        _workbook(doc,xp)
        made=[]
        try:
            for source,dest in ((jp,json_path),(xp,xlsx_path)):
                _publish(source,dest)
                made.append(dest)
        except BaseException:
            for dest in made:
                dest.unlink(missing_ok=True)
            raise
    return {"json_path":str(json_path),"xlsx_path":str(xlsx_path)}

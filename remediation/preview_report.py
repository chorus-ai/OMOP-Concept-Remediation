"""Standalone aggregate-only preview: no row capture, audit writes or apply path."""
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
from xml.sax.saxutils import escape
import uuid
from .policy import WRITABLE
from .other_fields import candidates_for_review

REASONS={
 "NULL_EVENT_ID":"The event record has no ID. The row is excluded; review source identity in ETL.",
 "DUPLICATE_EVENT_ID":"The event record ID is reused in this table. All candidates with that ID are excluded; review source identity in ETL.",
 "ELIGIBLE_FOR_REVIEW":"One direct valid standard same-domain target; would be proposed only after semantic approval and a new frozen plan.",
 "CURRENT_STANDARD":"Already valid standard; retained unchanged.",
 "MULTIPLE_MAPS":"More than one active target; no automatic selection.",
 "MAPS_TO_VALUE_REVIEW":"A Maps to value transformation is also required; a single-ID substitution is insufficient.",
 "NO_MAP":"No active direct Maps to target established.",
 "SOURCE_DOMAIN_MISMATCH":"Source domain conflicts with the destination-field policy.",
 "TARGET_DOMAIN_MISMATCH":"Replacement changes domain or violates the field policy.",
 "MANUAL_FIELD":"Field is outside the automatic write allowlist.",
 "CODE_REUSE_REVIEW":"Code reuse may change meaning over time; manual temporal review required.",
 "CONCEPT_CATEGORY_REVIEW":"Vocabulary category requires specific semantic review.",
 "TARGET_METADATA_REVIEW":"Target category or code reuse requires manual review.",
 "MAPPING_PRECISION_OR_GROUP_REVIEW":"Non-exact or grouped mapping cannot be used as an isolated substitution.",
 "CLASSIFICATION_REVIEW":"Classification concept; do not assume a direct standard replacement.",
 "NULL_CONCEPT":"NULL retained; review field requirements and source completeness.",
 "ZERO_CONCEPT":"Zero denotes no matching concept; no replacement is invented.",
 "MISSING_CONCEPT":"ID absent from the vocabulary; investigate vocabulary coverage/loading.",
 "ZERO_OR_SELF_MAP":"Zero or self mapping is not a usable replacement.",
 "MISSING_TARGET":"Mapped target is missing from the vocabulary.",
 "NONSTANDARD_TARGET":"Target is not standard.",
 "INVALID_TARGET":"Target is invalid or outside the selected validity date.",
 "INCONSISTENT_TARGET":"Conflicting target evidence; investigate vocabulary integrity."
}

def aggregate_preview(records,cfg,coverage,other_audit):
    primary=[]
    for r in records:
        if r["table"] not in WRITABLE or r["column"]!=WRITABLE[r["table"]][1]:continue
        old=r.get("old") or {}
        primary.append(dict(table=r["table"],column=r["column"],old_id=r["old_id"],
            old_name=old.get("concept_name","not recorded"),old_domain=old.get("domain_id","not recorded"),
            old_vocabulary=old.get("vocabulary_id","not recorded"),new_id=r["new_id"],status=r["status"],
            reason=REASONS.get(r["status"],"Unrecognised status: manual review; no automatic approval."),
            record_count=r["record_count"],candidates=candidates_for_review(r["edges"],cfg.as_of)))
    return dict(kind="PREVIEW_NO_CHANGES",report_id=str(uuid.uuid4()),cdm_version=cfg.cdm_version,
        as_of=cfg.as_of,scan_completed_at=datetime.now(timezone.utc).isoformat(),primary=primary,
        coverage=coverage,other_audit=other_audit,proposed_rows=sum(r["record_count"] for r in primary if r["status"]=="ELIGIBLE_FOR_REVIEW"),
        blocked_rows=sum(r["record_count"] for r in primary if r["status"] not in ("ELIGIBLE_FOR_REVIEW","CURRENT_STANDARD")),
        retained_rows=sum(r["record_count"] for r in primary if r["status"]=="CURRENT_STANDARD"))

def scan_preview_only(conn,cfg):
    from .runner import _ensure_idle,_settings,_check_cdm_version,_preview,_coverage,_all_columns,_vocabulary
    from .other_fields import scan_other_fields
    _ensure_idle(conn)
    with conn.transaction(),conn.cursor() as cur:
        _settings(cur,cfg,True)
        _check_cdm_version(cur,cfg)
        records=_preview(cur,cfg,primary_only=True)
        other=scan_other_fields(cur,cfg,_all_columns(cur,cfg),detailed_preview=True)
        return dict(aggregate_preview(records,cfg,_coverage(cur,cfg),other), vocabulary=_vocabulary(cur,cfg))

def preview_only_report(conn,cfg,path):
    payload=scan_preview_only(conn,cfg)
    render_preview_pdf(payload,path)
    return dict(report_status="PREVIEW_NO_CHANGES",committed=False,updated_rows=0,
                proposed_rows=payload["proposed_rows"],blocked_rows=payload["blocked_rows"],path=str(path))

def render_preview_pdf(data,path,*,summary_only=False,synthetic_fixture=False):
    if data.get("kind")!="PREVIEW_NO_CHANGES":raise ValueError("Preview payload required")
    from reportlab.platypus import SimpleDocTemplate,Paragraph,Table,TableStyle,Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from .reporting import _publish
    path=Path(path).resolve()
    if path.exists():raise FileExistsError("Choose a new output filename")
    path.parent.mkdir(parents=True,exist_ok=True);temp=path.with_name("."+path.name+"."+uuid.uuid4().hex+".tmp")
    styles=getSampleStyleSheet()
    for name in ("Normal","Heading1","Heading2"):styles[name].fontName="Times-Roman"
    styles["Normal"].fontSize=8;styles["Normal"].leading=11
    def p(x):return Paragraph(escape(str(x)),styles["Normal"])
    def heading(x):return Paragraph(x,styles["Heading2"])
    def table(headers,rows,widths):
        t=Table([[p(x) for x in headers]]+[[p(x) for x in row] for row in rows],colWidths=widths,repeatRows=1,splitInRow=1)
        t.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP"),("GRID",(0,0),(-1,-1),.3,colors.grey),("BACKGROUND",(0,0),(-1,0),colors.HexColor("#DFEAF0"))]))
        return t
    def candidate(c):
        return " / ".join(str(c[k]) if c.get(k) not in (None,"") else "not recorded" for k in ("concept_id","concept_name","relationship","domain","vocabulary","status"))
    story=[Paragraph("PREVIEW - NO CHANGES",styles["Heading1"]),p("0 committed changes. No remediation, journal creation or row-level plan capture was performed. Proposed replacements are structural candidates, not approved or executed changes. This report cannot be used as an apply authorization."),p("The repository contains pipeline code, not site patient data. This report is generated locally by the site and contains aggregate counts and vocabulary labels, not patient/event IDs. Exact small counts may be sensitive; follow site disclosure policy before sharing."),p("CDM "+data["cdm_version"]+"; vocabulary validity date "+data["as_of"]+"; scan completed "+data["scan_completed_at"]),p("All values describe one read-only planning snapshot. The completion timestamp is not the snapshot start time."),Spacer(1,8),table(["Would be proposed (rows)","Blocked/review (rows)","Already valid standard (rows)"],[[data["proposed_rows"],data["blocked_rows"],data["retained_rows"]]],[170]*3),p("Counts are concept-column occurrences, not distinct patients. Primary counts cover one writable field per selected table; other-field counts must not be added as distinct events.")]
    if synthetic_fixture:
        story.insert(0,Paragraph("SYNTHETIC TEST FIXTURE - NOT A DATABASE RESULT",styles["Heading2"]))
    if not data["proposed_rows"]:story.append(p("NO-OP: no eligible replacement rows were found within selected scope. This does not mean that no problems exist; inspect blocked findings and unscanned scope."))
    summary=Counter()
    for r in data["primary"]:summary[(r["table"],r["status"])]+=r["record_count"]
    labels={"NULL_EVENT_ID":"Missing event ID","DUPLICATE_EVENT_ID":"Duplicate event ID","CURRENT_STANDARD":"Already standard","ELIGIBLE_FOR_REVIEW":"Proposed replacement","NULL_CONCEPT":"Missing value (NULL)","ZERO_CONCEPT":"No matching concept (0)","MISSING_CONCEPT":"Code not present in installed vocabulary"}
    story += [heading("Primary-event dashboard"),table(["Table","Status","Occurrences"],[[t,labels.get(s,s.replace("_"," ").title()),n] for (t,s),n in sorted(summary.items())],[180,260,70])]
    if summary_only:
        story += [heading("Next steps"),p("Review proposed pairs before remediation, investigate blocked items separately, and confirm the scan coverage in the matching XLSX or JSON. Counts of unknown or missing values are not interchangeable and do not by themselves establish a clinical finding.")]
    else:
        for title,eligible in (("All proposed replacement pairs",True),("All blocked or unresolved concepts",False)):
            rows=[]
            for r in data["primary"]:
                if r["status"]=="CURRENT_STANDARD" or (r["status"]=="ELIGIBLE_FOR_REVIEW")!=eligible:continue
                for i,c in enumerate(r["candidates"] or [None]):
                    rows.append([r["table"]+"."+r["column"],str(r["old_id"])+" / "+r["old_name"]+" / "+r["old_domain"]+" / "+r["old_vocabulary"],r["record_count"] if i==0 else "same group",r["status"]+": "+r["reason"],candidate(c) if c else "No active candidate established"])
            story += [heading(title),table(["Field","Current concept","Count","Reason / action","Candidate (not an approval)"],rows,[95,110,40,140,125]) if rows else p("None returned within selected scope.")]
        story += [heading("Coverage and explicit exclusions"),table(["Field","State","Policy / reason"],[[r["table"]+"."+r["column"],r["state"],r["reason"]] for r in data["coverage"]],[180,150,180])]
        aux=data["other_audit"]
        scanned={(r["table"],r["column"]):r.get("scanned_occurrences") for r in aux["inventory"] if r["state"]=="SCANNED"}
        group_titles={"TYPE":"Record type and provenance", "DEMOGRAPHIC":"Demographics","DEATH_CAUSE":"Cause of death",
                      "DEATH_TYPE":"Death record provenance","UNIT":"Units","VALUE":"Coded values"}
        def evidence(c):
            def get(k):return str(c[k]) if c.get(k) is not None else "not recorded"
            return (f"Code: {get('concept_code')}; class: {get('concept_class_id')}; standard flag: {get('standard_concept')}; invalid reason: {get('invalid_reason')}; "
                    f"validity: {get('valid_start_date')} to {get('valid_end_date')}")
        def candidate_detail(c):
            flags=[label for key,label in (("field_domain_mismatch","wrong field domain"),
                                           ("self_mapping","self mapping"),("zero_target","zero target")) if c.get(key)]
            return (candidate(c) + "; " + str(c.get("relationship_role","")) + "; " + evidence(c) +
                    f"; mapping dates: {c.get('relationship_valid_from')} to {c.get('relationship_valid_to')}" +
                    ("; "+", ".join(flags) if flags else ""))
        grouped={}
        for r in aux["findings"]:
            grouped.setdefault(r.get("audit_category",r["category"]),[]).append(r)
        story += [heading("Other concept fields: analysis only"),
                  p("No replacements are proposed for these fields. Counts are field occurrences, not distinct people. "
                    "Only active direct Maps to / Maps to value links are listed; table scope is shown below.")]
        for title in (*group_titles,"OTHER_AUDIT"):
            observations=grouped.get(title,[]) if title!="OTHER_AUDIT" else [r for k,v in grouped.items() if k not in group_titles for r in v]
            if not observations:continue
            rows=[]
            for r in observations:
                key=(r["table"],r["column"])
                denom=scanned.get(key)
                count=f"{r['record_count']} / {denom}" if denom is not None else str(r["record_count"])
                coded=str(r["concept_id"])+" / "+r.get("concept_name","")+" / "+r.get("domain","")+" / "+r.get("vocabulary","")
                if "source_evidence" in r:coded+="; "+evidence(r["source_evidence"])
                policy=r["status"]
                if "expected_domain" in r:policy+="; expected domain: "+(r["expected_domain"] or ("none fixed by CDM" if title=="DEATH_CAUSE" else "not specified for this audit"))
                if r.get("guidance"):policy+=". "+r["guidance"]
                n=r.get("candidate_counts")
                if n is not None:
                    policy+=f" Distinct targets: Maps to {n['Maps to']}; Maps to value {n['Maps to value']}."
                    rel=r["expected_relationship"]
                    if n[rel]>1:policy+=f" Multiple {rel} targets; do not choose one automatically."
                    elif n[rel]==0 and r["concept_id"] not in (None,0):policy+=f" No direct {rel} target found for this ID."
                for i,c in enumerate(r.get("candidates") or [None]):
                    rows.append([".".join(key),coded if i==0 else "same group",count if i==0 else "same group",policy if i==0 else "same group",
                                 (candidate_detail(c) if "source_evidence" in r else candidate(c)) if c else "No active candidate established"])
            story += [heading(group_titles.get(title,"Other review-only findings")),table(["Field","Current concept","Count / scanned","Finding / review action","Candidate evidence"],rows,[92,110,53,125,130])]
        if not aux["findings"]:story.append(p("No flagged occurrences in scanned other fields. Review the inventory for fields not scanned."))
        story += [heading("Full other-field inventory"),table(["Field","Category","Scan state","Occurrences scanned"],
            [[r["table"]+"."+r["column"],r.get("audit_category",r["category"]),r["state"],r.get("scanned_occurrences","not scanned")] for r in aux["inventory"]],[185,95,175,55])]
        story += [heading("Next steps"),p("Review every candidate semantically and investigate blocked/unscanned fields. For changes, use the separate remediation notebook; this report is not approval to apply them.")]
    def footer(canvas,doc):
        canvas.setFont("Times-Roman",8);canvas.drawString(42,25,"SYNTHETIC FIXTURE | PREVIEW - NO CHANGES" if synthetic_fixture else "PREVIEW - NO CHANGES | Site-local aggregate report");canvas.drawRightString(550,25,str(doc.page))
    try:
        SimpleDocTemplate(str(temp),pagesize=A4,leftMargin=42,rightMargin=42,title="Preview - No Changes",author="").build(story,onFirstPage=footer,onLaterPages=footer)
        _publish(temp,path)
    finally:
        if temp.exists():temp.unlink()

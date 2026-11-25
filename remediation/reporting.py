"""Private aggregate reporting, sourced from a committed journal, never preview counts."""
from collections import Counter
from copy import deepcopy
from datetime import datetime,timezone
from pathlib import Path
from xml.sax.saxutils import escape
import errno
import json
import os
import shutil
import uuid

_windows_publish = os.name == "nt"

PAIR_KEYS=("table","column","old_id","new_id")

def _publish(temp,path):
    """Publish a complete staging file without replacing an existing destination."""
    if _windows_publish:
        os.rename(temp,path)
        return
    try:
        os.link(temp,path)
        return
    except OSError as exc:
        unsupported={errno.ENOSYS, errno.EOPNOTSUPP, errno.ENOTSUP, errno.EPERM}
        if exc.errno not in unsupported:
            raise
    # Some approved mounts cannot link. Exclusive creation still enforces no
    # overwrite. A process crash can leave an incomplete destination there.
    with open(temp,"rb") as source:
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        try:
            with os.fdopen(fd,"wb") as destination:
                shutil.copyfileobj(source,destination)
                destination.flush()
        except BaseException:
            Path(path).unlink(missing_ok=True)
            raise

def check_report_destination(path):
    """Test the actual publish strategy with synthetic bytes, never site data."""
    folder=Path(path).expanduser().resolve()
    repository=Path(__file__).resolve().parents[1]
    if folder==repository or repository in folder.parents or any((x/".git").exists() for x in (folder,*folder.parents)):
        raise ValueError("Choose an approved private report folder outside all Git working trees")
    folder.mkdir(mode=0o700,parents=True,exist_ok=True)
    # Probe directly in the chosen directory, under a fresh, exclusive staging file.
    from tempfile import mkstemp
    fd,name=mkstemp(prefix=".remediation-probe-",dir=folder)
    staged=Path(name)
    published=staged.with_suffix(".check")
    made=False
    try:
        with os.fdopen(fd,"wb") as probe:
            probe.write(b"report destination check")
        _publish(staged,published)
        made=True
        if published.read_bytes()!=b"report destination check":
            raise OSError("Report destination verification failed")
    finally:
        staged.unlink(missing_ok=True)
        if made:
            published.unlink(missing_ok=True)
    return folder

def pair_counts(pairs):
    result={}
    for p in pairs:
        key=tuple(p[k] for k in PAIR_KEYS)
        count=p["updated_rows"]
        if key in result or type(count) is not int or count<=0 or p.get("complete") is not True:
            raise ValueError("Invalid or incomplete journal aggregation")
        result[key]=count
    return result

def primary_summary(records):
    from .policy import WRITABLE
    counts=Counter()
    for r in records:
        if r["table"] in WRITABLE and r["column"]==WRITABLE[r["table"]][1]:
            counts[(r["table"],r["column"],r["status"])]+=r["record_count"]
    return [dict(table=t,column=c,status=s,record_count=n) for (t,c,s),n in sorted(counts.items())]

def make_payload(plan,actual_pairs,before,after):
    """Build inside the UPDATE transaction; counts come from actual journal, not plan estimates."""
    actual=pair_counts(actual_pairs)
    expected=Counter(tuple(r[k] for k in PAIR_KEYS) for r in plan["rows"])
    if actual!=expected:raise ValueError("Journal pairs differ from the frozen plan")
    evidence={(r["table"],r["column"],r["old_id"],r["new_id"]):r for r in plan["mapping_evidence"]}
    pairs=[]
    for key,count in sorted(actual.items()):
        r=evidence[key];old=r["old"]
        new=next(e["target"] for e in r["edges"] if e["concept_id_2"]==r["new_id"] and e.get("target"))
        pairs.append(dict(zip(PAIR_KEYS,key),updated_rows=count,complete=True,
            old_name=old.get("concept_name",""),new_name=new.get("concept_name",""),
            old_domain=old.get("domain_id",""),new_domain=new.get("domain_id",""),
            old_vocabulary=old.get("vocabulary_id",""),new_vocabulary=new.get("vocabulary_id","")))
    return {"report_version":2,"run_id":plan["run_id"],"plan_hash":plan["plan_hash"],
            "cdm_version":plan["config"].get("cdm_version","5.4"),"vocabulary_as_of":plan["config"]["as_of"],
            "vocabulary":plan["vocabulary"],"plan_created_at":plan["created_at"],
            "coverage":plan["coverage"],"pairs":pairs,"updated_rows":sum(actual.values()),
            "table_field_pair_count":len(pairs),"distinct_concept_pairs":len({(k[2],k[3]) for k in actual}),
            "before_summary":primary_summary(before),"after_summary":primary_summary(after),
            "other_audit":plan.get("other_audit",{"inventory":[],"findings":[],"scanned_at":plan["created_at"]})}

def validate_confirmation(payload,journal_pairs):
    if payload.get("report_version")!=2:raise ValueError("Unsupported/missing report payload; never infer success")
    actual=pair_counts(journal_pairs);stored=pair_counts(payload["pairs"])
    if actual!=stored or sum(actual.values())!=payload["updated_rows"]:raise ValueError("Audit/report count mismatch")
    if payload["table_field_pair_count"]!=len(actual):raise ValueError("Pair count mismatch")
    if payload["distinct_concept_pairs"]!=len({(k[2],k[3]) for k in actual}):raise ValueError("Distinct pair count mismatch")

def load_committed_payload(conn,cfg,run_id):
    from psycopg import sql
    from .runner import _ensure_idle,_settings,_identity,_audit_contract,qfile
    _ensure_idle(conn)
    with conn.transaction(),conn.cursor() as cur:
        _settings(cur,cfg,True);_audit_contract(cur,cfg)
        cur.execute(sql.SQL("SELECT run_id,plan_hash,database_identity,applied_at,reversed_at,report_payload FROM {}.runs WHERE run_id=%s").format(sql.Identifier(cfg.audit_schema)),(run_id,))
        run=cur.fetchone()
        if not run:raise ValueError("No committed run exists; preview/rehearsal cannot generate an applied report")
        if run["reversed_at"] is not None:raise ValueError("Run was reversed; refuse an active-success report")
        if run["database_identity"]!=_identity(cur,cfg):raise ValueError("Report requested from another database")
        cur.execute(qfile("committed_pairs.sql",audit=cfg.audit_schema),(run_id,))
        pairs=cur.fetchall()
        payload=deepcopy(run["report_payload"])
        if payload.get("run_id")!=str(run["run_id"]) or payload.get("plan_hash")!=run["plan_hash"]:raise ValueError("Run metadata mismatch")
        validate_confirmation(payload,pairs)
        payload["confirmation"]="COMMITTED_JOURNAL_READBACK"
        payload["transaction_started_at"]=str(run["applied_at"])
        payload["verified_at"]=datetime.now(timezone.utc).isoformat()
    return payload

def generate_committed_report(conn,cfg,run_id,path,*,include_evidence=False):
    payload=load_committed_payload(conn,cfg,run_id)
    if include_evidence:
        render_private_pdf(payload,path,summary_only=True)
    else:
        render_private_pdf(payload,path)
    result={"run_id":run_id,"report_status":"CREATED","path":str(path),"updated_rows":payload["updated_rows"]}
    if include_evidence:
        from .report_exports import export_evidence
        try:
            result.update(export_evidence(payload,path,committed=True))
            result["evidence_status"]="CREATED"
        except (OSError, ImportError, ValueError) as exc:
            result.update(evidence_status="NOT_SAVED",evidence_error_type=type(exc).__name__)
    return result

def apply_and_report(conn,cfg,plan,path,*,include_evidence=False,**apply_options):
    from .runner import apply_plan
    result=apply_plan(conn,cfg,plan,**apply_options)
    if not result["committed"]:
        return dict(result,report_status="NOT_CREATED_REHEARSAL")
    # Database commit is already complete. PDF errors must NOT cause an automatic re-apply.
    try:
        report=(generate_committed_report(conn,cfg,plan["run_id"],path,include_evidence=True)
                if include_evidence else generate_committed_report(conn,cfg,plan["run_id"],path))
        return dict(result,report_status=report["report_status"],report_path=report["path"],
                    **{k:report[k] for k in ("json_path","xlsx_path","evidence_status","evidence_error_type") if k in report})
    except Exception as exc:
        return dict(result,report_status="FAILED_AFTER_COMMIT",report_error_type=type(exc).__name__,
                    next_action="Regenerate the report from this run_id using generate_committed_report; do not re-apply")

def render_private_pdf(payload,path,*,synthetic_fixture=False,summary_only=False):
    """Renderer accepts only confirmed aggregate payloads. Test fixtures are unmistakably labelled."""
    if not synthetic_fixture and payload.get("confirmation")!="COMMITTED_JOURNAL_READBACK":
        raise ValueError("A committed journal read-back is required")
    validate_confirmation(payload,payload["pairs"])
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet,ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle,PageBreak,KeepTogether
    from reportlab.graphics.shapes import Drawing,Rect,String
    path=Path(path).resolve()
    if path.exists():raise FileExistsError("Choose a new filename; preserve earlier report evidence")
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name("."+path.name+"."+uuid.uuid4().hex+".tmp")
    width=174*mm
    styles=getSampleStyleSheet()
    styles.add(ParagraphStyle(name="ReportTitle",fontName="Times-Bold",fontSize=24,leading=28,textColor=colors.HexColor("#183A4A"),spaceAfter=12))
    styles.add(ParagraphStyle(name="SectionTitle",fontName="Times-Bold",fontSize=15,leading=18,textColor=colors.HexColor("#183A4A"),spaceBefore=12,spaceAfter=8,keepWithNext=True))
    styles.add(ParagraphStyle(name="BodyReport",fontName="Times-Roman",fontSize=10,leading=13,spaceAfter=7))
    styles.add(ParagraphStyle(name="CellReport",fontName="Times-Roman",fontSize=8,leading=10,wordWrap="CJK"))
    def para(text,style="BodyReport"):return Paragraph(escape(str(text)).replace("\n","<br/>"),styles[style])
    def tab(headers,rows,widths):
        data=[[para(x,"CellReport") for x in headers]]+[[para(x,"CellReport") for x in row] for row in rows]
        table=Table(data,colWidths=widths,repeatRows=1,hAlign="LEFT")
        table.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#DFEAF0")),("VALIGN",(0,0),(-1,-1),"TOP"),("GRID",(0,0),(-1,-1),.3,colors.HexColor("#B8C8CF")),("LEFTPADDING",(0,0),(-1,-1),5),("RIGHTPADDING",(0,0),(-1,-1),5),("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5)]))
        return table
    def bars(values,title):
        # All categories shown; axis starts at zero; row counts are not patient counts.
        values=sorted(values.items(),key=lambda x:(-x[1],x[0]))
        d=Drawing(width,35+24*max(1,len(values)))
        d.add(String(0,d.height-12,title,fontName="Times-Bold",fontSize=11,fillColor=colors.HexColor("#183A4A")))
        maximum=max([n for _,n in values] or [1]);start=142;usable=width-start-42
        for i,(label,n) in enumerate(values):
            y=d.height-34-i*24
            d.add(String(0,y+3,label,fontName="Times-Roman",fontSize=8))
            d.add(Rect(start,y,usable*n/max(maximum,1),12,fillColor=colors.HexColor("#277B8E"),strokeColor=None))
            d.add(String(start+usable*n/max(maximum,1)+5,y+2,f"{n:,}",fontName="Times-Roman",fontSize=8))
        return d
    story=[]
    title="SYNTHETIC TEST FIXTURE - NOT A DATABASE RESULT" if synthetic_fixture else "PRIVATE - COMMITTED REMEDIATION REPORT"
    story += [para(title,"SectionTitle"),para("OMOP Concept Remediation","ReportTitle"),para("Committed changes and unresolved concept-quality findings")]
    story += [para("PRIVATE INTERNAL REPORT. Exact counts, including small groups, are retained to support remediation review. This is not anonymised or approved for external disclosure. Apply the site's disclosure policy before sharing. No patient IDs, event IDs, credentials, hostnames or database usernames are included.")]
    story += [tab(["Run","Verification"],[[payload["run_id"],"Synthetic fixture" if synthetic_fixture else "Committed journal read-back"],["CDM "+payload["cdm_version"],"Vocabulary validity date: "+payload["vocabulary_as_of"]],["Plan created: "+payload["plan_created_at"],"Verified: "+payload.get("verified_at","synthetic")]], [width*.5,width*.5])]
    story += [Spacer(1,10),tab(["Updated event rows / cells","Table-field mapping pairs","Distinct old/new concept pairs"],[[f"{payload['updated_rows']:,}",payload["table_field_pair_count"],payload["distinct_concept_pairs"]]],[width/3]*3)]
    story += [para("Counts refer to journaled changes, not people. One primary content field is writable per supported table, so each recorded change represents one event row in that table. The same person may contribute many rows and appear in several tables. A table-field pair is (table, column, old ID, new ID); distinct concept pairs ignore table and column.")]
    by_table=Counter();by_domain=Counter()
    for pair in payload["pairs"]:
        by_table[pair["table"]]+=pair["updated_rows"];by_domain[pair["new_domain"]]+=pair["updated_rows"]
    if summary_only:
        story += [para("Run summary","SectionTitle")]
        story += [tab(["Updated table","Committed rows"],[[table,f"{count:,}"] for table,count in sorted(by_table.items())],[width*.7,width*.3])]
        residue=[r for r in payload["after_summary"] if r["status"]!="CURRENT_STANDARD"]
        from .preview_report import REASONS
        if residue:
            story += [para("Still needs review","SectionTitle"),
                      tab(["Field","Finding / next action","Rows"],
                          [[r["table"]+"."+r["column"],REASONS.get(r["status"],r["status"].replace("_"," ").title()),r["record_count"]] for r in residue],
                          [width*.38,width*.49,width*.13])]
        else:
            story += [para("No unresolved primary-event findings in the selected scope.")]
        top=sorted(payload["pairs"],key=lambda r:-r["updated_rows"])[:3]
        story += [para("Most frequent changes","SectionTitle"),
                  tab(["Previous concept","Replacement concept","Rows"],
                      [[r["old_name"],r["new_name"],r["updated_rows"]] for r in top],[width*.42,width*.43,width*.15])]
        selected=sorted({r["table"] for r in payload["coverage"] if r["state"]=="SELECTED_FOR_REVIEW"})
        if selected:
            story += [para("Reviewed primary scope: "+", ".join(selected)+". Other tables are not implied to be updated or checked.")]
        story += [para("Full pairs, scope, unresolved findings and plan-time statistics for other concept fields are available in the matching private XLSX and JSON. Field shares use the number scanned in that field, not the number of people. No downstream cohorts or derived eras were rebuilt."),
                  para("Check semantic specificity before reuse: a same-domain 1:1 mapping does not prove clinical equivalence. Do not repeat Apply to regenerate this report.")]
    else:
        for values,title in ((by_table,"Actually updated rows by table"),(by_domain,"Actually updated rows by target domain")):
            items=sorted(values.items(),key=lambda x:(-x[1],x[0]))
            for start in range(0,len(items),12):
                story += [bars(dict(items[start:start+12]),title + (" (continued; panel scale)" if start else "")),Spacer(1,8)]
        story += [para("Evidence boundary","SectionTitle"),para("The data changes and journal were committed atomically; this report was generated afterwards from a separate read of that journal. Counts are historical facts for this run, not proof that no later ETL or manual edits occurred. Vocabulary mapping review is still required: one-to-one and same-domain checks do not prove clinical equivalence. This software has offline test coverage; real database acceptance must be performed by the site.")]
        story += [PageBreak(),para("Complete list of committed replacement pairs","SectionTitle"),para("Every journaled table-field/old/new pair is listed below, with its actual changed-row count. Names and vocabulary labels were frozen with the reviewed plan, rather than reinterpreted using a later vocabulary release.")]
        pair_rows=[]
        for r in payload["pairs"]:
            pair_rows.append([r["table"]+"\n"+r["column"],str(r["old_id"])+"\n"+r["old_name"]+"\n"+r["old_vocabulary"],str(r["new_id"])+"\n"+r["new_name"]+"\n"+r["new_vocabulary"],r["new_domain"],f"{r['updated_rows']:,}"])
        story += [tab(["Table / field","Old concept / vocabulary","New concept / vocabulary","Domain","Rows"],pair_rows,[width*.21,width*.27,width*.27,width*.15,width*.10])]
        story += [PageBreak(),para("Coverage and explicit exclusions","SectionTitle"),para("Missing or inaccessible tables/fields are not interpreted as zero records. Audit-only and derived fields were not automatically remediated.")]
        story += [tab(["Table / field","Status","Policy / reason"],[[r["table"]+"\n"+r["column"],r["state"],r["policy"]+"\n"+r["reason"]] for r in payload["coverage"]],[width*.32,width*.24,width*.44])]
        story += [para("Unresolved primary-event findings after this run","SectionTitle")]
        unresolved=[r for r in payload["after_summary"] if r["status"]!="CURRENT_STANDARD"]
        story += [tab(["Table / field","Status","Rows"],[[r["table"]+"\n"+r["column"],r["status"],r["record_count"]] for r in unresolved],[width*.45,width*.4,width*.15]) if unresolved else para("No unresolved primary-event findings were returned within the selected scope. This is not a whole-database quality certificate.")]
        aux=payload["other_audit"]
        story += [PageBreak(),para("Other concept fields: analysis only, no changes","SectionTitle"),para("Read-only scan completed at: "+aux.get("scanned_at","not recorded")),para("The following statistics were captured at plan creation, not claimed to reflect the database after commit. Units, demographics, types and other non-primary fields were NOT updated. Source fields may legitimately contain nonstandard IDs and are explicitly excluded from standard-target remediation. Candidate mappings are suggestions for independent analysis, never proof of an acceptable replacement.")]
        findings=aux.get("findings",[])
        if findings:
            by_category=Counter()
            for r in findings:by_category[r["category"]]+=r["record_count"]
            story += [bars(by_category,"Flagged concept-field occurrences by category"),para("These are column occurrences, not distinct rows or patients: one record can contribute to multiple concept fields. Do not add these counts to the updated-event-row total.")]
            rows=[]
            for r in findings:
                cs=r.get("candidates",[]) or [None]
                for index,c in enumerate(cs):
                    candidate=(str(c["concept_id"])+" "+c.get("concept_name","")+"\n"+(c.get("relationship") or "not recorded")+" / "+(c.get("domain") or "not recorded")+" / "+(c.get("vocabulary") or "not recorded")+"\n"+c["status"]) if c else "No active candidate reported"
                    rows.append([r["table"]+"\n"+r["column"],str(r.get("concept_id"))+"\n"+r.get("concept_name","")+"\n"+r.get("domain","")+" / "+r.get("vocabulary",""),r["status"],str(r["record_count"]) if index==0 else "(same group)",candidate])
            story += [tab(["Table / field","Current concept","Finding","Count","Active candidates (review only)"],rows,[width*.23,width*.25,width*.16,width*.08,width*.28])]
        else:story += [para("No flagged records were returned in scanned other fields. Consult the inventory for exclusions and unscanned scope.")]
        story += [para("Other-field scan inventory","SectionTitle"),tab(["Table / field","Category","Scan state"],[[r["table"]+"\n"+r["column"],r["category"],r["state"]] for r in aux.get("inventory",[])],[width*.52,width*.22,width*.26])]
        story += [para("Action guide","SectionTitle"),para("NONSTANDARD / CLASSIFICATION: review whether this field requires a standard target and inspect all candidates. INVALID / OUT_OF_DATE: validate lifecycle and refresh the field-specific ETL rule. WRONG_DOMAIN: inspect the destination field, not only the mapping. MISSING_CONCEPT: investigate vocabulary coverage or loading. ZERO / NULL: check CDM field requirements and source completeness; never invent a replacement. Multiple targets or Maps to value require a separate semantic transformation. Unit changes may require numeric conversion. No candidate means no replacement was established.")]
        story += [para("Reproducibility and limitations","SectionTitle"),para("Plan SHA-256: "+payload["plan_hash"]),para("Full vocabulary metadata was saved in the private transactional report payload. Source references: OHDSI Common Data Model version-specific specifications and vocabulary conventions (https://ohdsi.github.io/CommonDataModel/cdm54.html; https://ohdsi.github.io/CommonDataModel/vocabulary.html). No automatic downstream era/cohort rebuild is implied. Exact small counts must undergo site disclosure review before external distribution.")]
    def footer(canvas,doc):
        canvas.setFont("Times-Roman",8);canvas.setFillColor(colors.HexColor("#526571"))
        canvas.drawString(18*mm,12*mm,"SYNTHETIC FIXTURE" if synthetic_fixture else "PRIVATE | Site disclosure review required")
        canvas.drawRightString(192*mm,12*mm,f"Page {doc.page}")
    try:
        doc=SimpleDocTemplate(str(temp),pagesize=A4,rightMargin=18*mm,leftMargin=18*mm,topMargin=17*mm,bottomMargin=20*mm,title="OMOP Concept Remediation - Private Report",author="")
        doc.build(story,onFirstPage=footer,onLaterPages=footer)
        # Exclusive destination: never overwrite an existing run report.
        _publish(temp,path)  # Publish without overwriting a prior report.
    except Exception:
        # A failed PDF does not undo a committed database transaction.
        raise
    finally:
        if temp.exists():temp.unlink()


def generate_audit_only_report(plan,path):
    """Empty-plan report only: never claims a commit, never calls apply or a database."""
    from .runner import digest
    if plan.get("format_version")!=2 or digest({k:v for k,v in plan.items() if k!="plan_hash"})!=plan.get("plan_hash"):
        raise ValueError("Invalid plan hash/version")
    if plan.get("rows") or plan.get("mapping_evidence"):
        raise ValueError("Audit-only no-change report requires an empty remediation plan")
    from reportlab.platypus import SimpleDocTemplate,Paragraph,Table,TableStyle,Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    path=Path(path).resolve()
    if path.exists():raise FileExistsError("Preserve prior reports; choose a new filename")
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name("."+path.name+"."+uuid.uuid4().hex+".tmp")
    styles=getSampleStyleSheet()
    for name in ("Normal","Heading1","Heading2"):styles[name].fontName="Times-Roman"
    styles["Normal"].fontSize=8;styles["Normal"].leading=10
    def p(t):return Paragraph(escape(str(t)),styles["Normal"])
    def table(headers,rows,widths):
        t=Table([[p(x) for x in headers]]+[[p(x) for x in r] for r in rows],colWidths=widths,repeatRows=1)
        t.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP"),("GRID",(0,0),(-1,-1),.3,colors.grey),("BACKGROUND",(0,0),(-1,0),colors.HexColor("#DFEAF0"))]))
        return t
    story=[Paragraph("AUDIT ONLY - NO REMEDIATION APPLIED",styles["Heading1"]),p("0 committed changes / no apply. This is a read-only planning snapshot, not a committed-remediation report. No eligible replacements were included in this plan. It does not certify the database as fit for use."),Spacer(1,10),p("PRIVATE: exact small counts and concept labels are retained. Not anonymised or approved for external sharing. No patient or event IDs are included."),p("CDM: "+plan["config"]["cdm_version"]+"; plan created: "+plan["created_at"]),p("Plan SHA-256: "+plan["plan_hash"])]
    aux=plan["other_audit"]
    story += [p("Read-only scan completed: "+aux["scanned_at"]),Paragraph("Event coverage and exclusions",styles["Heading2"]),table(["Table / field","State"],[[r["table"]+"."+r["column"],r["state"]] for r in plan["coverage"]],[290,220])]
    story += [Paragraph("Primary-event findings (read-only)",styles["Heading2"]),table(["Table / field","Finding","Occurrences"],[[r["table"]+"."+r["column"],r["status"],r["record_count"]] for r in plan.get("primary_findings",[])],[260,180,70])]
    story += [Paragraph("Other concept fields: analysis only",styles["Heading2"]),p("Counts are field occurrences, not unique patients or events. Candidate mappings require independent field-specific review; no replacement is assumed. Source-provenance fields are excluded, not standard-concept defects.")]
    rows=[]
    for r in aux["findings"]:
        for i,c in enumerate(r.get("candidates") or [None]):
            rows.append([r["table"]+"."+r["column"],str(r.get("concept_id"))+" "+r.get("concept_name","")+" / "+r.get("domain","")+" / "+r.get("vocabulary",""),r["status"],r["record_count"] if i==0 else "same group",(str(c["concept_id"])+" "+c.get("concept_name","")+" / "+(c.get("relationship") or "not recorded")+" / "+(c.get("domain") or "not recorded")+" / "+(c.get("vocabulary") or "not recorded")+" / "+c["status"]) if c else "No candidate established"])
    story += [table(["Field","Current concept","Finding","Count","Review candidate"],rows,[110,135,100,40,125]) if rows else p("No flagged occurrences returned within scanned fields; inspect unscanned scope below."),Paragraph("Full scan inventory",styles["Heading2"]),table(["Table / field","Category","Scan state"],[[r["table"]+"."+r["column"],r["category"],r["state"]] for r in aux["inventory"]],[260,90,160])]
    try:
        SimpleDocTemplate(str(temp),pagesize=A4,title="Audit only - no remediation applied",author="").build(story)
        _publish(temp,path)
    finally:
        if temp.exists():temp.unlink()
    return {"report_status":"AUDIT_ONLY_NO_APPLY","committed":False,"updated_rows":0,"path":str(path)}

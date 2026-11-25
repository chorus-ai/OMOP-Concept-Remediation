"""PostgreSQL-only preview -> frozen plan -> rehearsal -> explicit commit.
No network work happens on import. Patient/event identifiers stay in private plan/audit.
"""
import csv
import hashlib
import json
import re
import uuid
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from pathlib import Path
from collections import Counter
from .policy import WRITABLE, classify
from .catalog import CATALOG, EVENT_TABLES, coverage_from_columns

ROOT = Path(__file__).resolve().parents[1]

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()

def ident(value):
    if not isinstance(value,str) or not re.fullmatch(r"[a-z_][a-z0-9_]*",value):
        raise ValueError("Use a lowercase unquoted SQL identifier")
    return value

@dataclass(frozen=True)
class Config:
    cdm_schema: str
    vocabulary_schema: str
    tables: tuple
    as_of: str
    cdm_version: str = "5.4"
    audit_schema: str = "concept_remediation_audit"
    statement_timeout_ms: int = 300000
    lock_timeout_ms: int = 5000
    max_plan_rows: int = 100000

    def __post_init__(self):
        for value in (self.cdm_schema,self.vocabulary_schema,self.audit_schema): ident(value)
        if not self.tables or len(set(self.tables))!=len(self.tables): raise ValueError("Select distinct tables explicitly")
        for t in self.tables:
            ident(t)
            if t not in set(EVENT_TABLES)|{"person"}: raise ValueError("Unsupported table")
        if self.cdm_version not in ("5.4","5.5"):raise ValueError("Explicit CDM 5.4 or 5.5 required")
        date.fromisoformat(self.as_of)
        if min(self.statement_timeout_ms,self.lock_timeout_ms,self.max_plan_rows)<=0: raise ValueError("Limits must be positive")
        if self.audit_schema in (self.cdm_schema,self.vocabulary_schema,"public","information_schema") or self.audit_schema.startswith("pg_"): raise ValueError("Use a separate private audit schema")

def connect(*, host, port, dbname, user, password, sslmode="verify-full", sslrootcert=None):
    import psycopg
    from psycopg.rows import dict_row
    if sslmode not in ("verify-full","verify-ca","require"): raise ValueError("TLS is required")
    kwargs=dict(host=host,port=port,dbname=dbname,user=user,password=password,
                sslmode=sslmode,connect_timeout=15,row_factory=dict_row,autocommit=True)
    if sslrootcert: kwargs["sslrootcert"]=sslrootcert
    return psycopg.connect(**kwargs)

def qfile(name,**names):
    from psycopg import sql
    return sql.SQL((ROOT/"sql"/name).read_text(encoding="utf-8")).format(**{k:sql.Identifier(ident(v)) for k,v in names.items()})

def _settings(cur,cfg,read_only):
    # Preview is snapshot-consistent. Apply uses fresh snapshots AFTER acquiring locks.
    cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY" if read_only else "SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
    cur.execute("SELECT set_config('statement_timeout',%s,true), set_config('lock_timeout',%s,true)",
                (str(cfg.statement_timeout_ms),str(cfg.lock_timeout_ms)))

def _identity(cur,cfg):
    cur.execute("SELECT current_database() AS database, inet_server_addr()::text AS server, inet_server_port() AS port")
    return dict(cur.fetchone(), cdm_schema=cfg.cdm_schema, vocabulary_schema=cfg.vocabulary_schema)

def _all_columns(cur,cfg):
    cur.execute("SELECT table_name,column_name FROM information_schema.columns WHERE table_schema=%s ORDER BY table_name,ordinal_position",(cfg.cdm_schema,))
    result={}
    for r in cur.fetchall():result.setdefault(r["table_name"],[]).append(r["column_name"])
    return result

def _coverage(cur,cfg):
    return coverage_from_columns(_all_columns(cur,cfg),cfg.tables)

def discover_event_scope(conn,cfg):
    """Read-only all-available event inventory. Missing/inaccessible tables remain explicit."""
    _ensure_idle(conn)
    with conn.transaction(),conn.cursor() as cur:
        _settings(cur,cfg,True)
        columns=_all_columns(cur,cfg)
        tables=tuple(t for t in EVENT_TABLES if t in columns)
        if not any(t in WRITABLE for t in tables):raise ValueError("No supported writable event tables are visible")
        discovered=replace(cfg,tables=tables)
        _columns(cur,discovered)  # Fail on malformed present selected tables.
        return discovered,coverage_from_columns(columns,tables)


def _columns(cur,cfg):
    cur.execute("SELECT table_name,column_name FROM information_schema.columns WHERE table_schema=%s ORDER BY table_name,ordinal_position",(cfg.cdm_schema,))
    result={t:[] for t in cfg.tables}
    for r in cur.fetchall():
        if r["table_name"] in result: result[r["table_name"]].append(r["column_name"])
    for t,cols in result.items():
        if not cols: raise ValueError("Missing/inaccessible selected table: "+t)
        if t in WRITABLE:
            pk,col,_=WRITABLE[t]
            if pk not in cols or col not in cols: raise ValueError("Missing required columns: "+t)
    return result

def _check_cdm_version(cur,cfg):
    from psycopg import sql
    cur.execute(sql.SQL("SELECT DISTINCT cdm_version FROM {}.cdm_source").format(sql.Identifier(cfg.cdm_schema)))
    values=[str(r["cdm_version"]).strip() for r in cur.fetchall() if r["cdm_version"]]
    if not values or any(v not in (cfg.cdm_version,cfg.cdm_version+".0", "v"+cfg.cdm_version, "v"+cfg.cdm_version+".0") for v in values):
        raise ValueError("CDM_SOURCE version is missing or disagrees with the selected catalogue; resolve metadata before planning/apply")


def _vocabulary(cur,cfg):
    from psycopg import sql
    cur.execute(sql.SQL("SELECT vocabulary_id,vocabulary_version FROM {}.vocabulary ORDER BY vocabulary_id").format(sql.Identifier(cfg.vocabulary_schema)))
    return cur.fetchall()

def _uses_metadata(cur,cfg):
    cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema=%s AND table_name IN ('concept_metadata','concept_relationship_metadata')",(cfg.vocabulary_schema,))
    names={r["table_name"] for r in cur.fetchall()}
    if names and len(names)!=2:raise ValueError("Incomplete vocabulary metadata tables")
    if cfg.cdm_version=="5.5" and len(names)!=2:raise ValueError("CDM 5.5 vocabulary metadata tables are required")
    return len(names)==2


def _preview(cur,cfg,primary_only=False):
    records=[]
    use_metadata=_uses_metadata(cur,cfg)
    for table,cols in _columns(cur,cfg).items():
        for col in cols:
            if not col.endswith("concept_id") or col.endswith("source_concept_id"): continue
            writable=table in WRITABLE and col==WRITABLE[table][1]
            if primary_only and not writable:continue
            domain=WRITABLE[table][2] if writable else None
            cur.execute(qfile("preview55.sql" if use_metadata else "preview.sql",cdm=cfg.cdm_schema,vocab=cfg.vocabulary_schema,table=table,column=col))
            for r in cur.fetchall():
                status,target=classify(r["old_id"],r["old"],r["edges"],domain,writable,cfg.as_of)
                records.append(dict(r,table=table,column=col,status=status,new_id=target))
    return _screen_event_keys(cur,cfg,records)

def _ensure_idle(conn):
    if not conn.autocommit or conn.info.transaction_status != 0:
        raise ValueError("Use an idle autocommit connection; nested caller transactions are unsupported")

def preview(conn,cfg):
    _ensure_idle(conn)
    with conn.transaction(),conn.cursor() as cur:
        _settings(cur,cfg,True)
        return _preview(cur,cfg)

def export_preview(records,path):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("w",encoding="utf-8",newline="") as f:
        fields=["table","column","old_id","old_name","old_domain","old_vocabulary","old_standard_status","record_count","status","new_id","new_name","new_domain","new_vocabulary","mapping_review_required"]
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for r in records:
            old=r["old"] or {}
            targets=[e.get("target") for e in r["edges"] if e.get("concept_id_2")==r["new_id"] and e.get("target")]
            new=targets[0] if targets else {}
            values={k:r.get(k) for k in ["table","column","old_id","record_count","status","new_id"]} | {
                "old_name":old.get("concept_name"),"old_domain":old.get("domain_id"),"old_vocabulary":old.get("vocabulary_id"),"old_standard_status":old.get("standard_concept"),
                "new_name":new.get("concept_name"),"new_domain":new.get("domain_id"),"new_vocabulary":new.get("vocabulary_id"),"mapping_review_required":r["status"]=="ELIGIBLE_FOR_REVIEW"}
            # Prevent spreadsheet formula execution when opening vocabulary labels in CSV.
            values={k:("'"+v if isinstance(v,str) and v.startswith(("=","+","-","@","\t","\r")) else v) for k,v in values.items()}
            w.writerow(values)

def export_review_tables(records,folder,*,prefix="preview"):
    """Separate actionable groups; retain current standards as field totals."""
    folder=Path(folder)
    folder.mkdir(mode=0o700,parents=True,exist_ok=True)
    proposed=[r for r in records if r["status"]=="ELIGIBLE_FOR_REVIEW"]
    review=[r for r in records if r["status"] not in ("ELIGIBLE_FOR_REVIEW","CURRENT_STANDARD")]
    standards={}
    for r in records:
        if r["status"]=="CURRENT_STANDARD":
            key=(r["table"],r["column"])
            standards[key]=standards.get(key,0)+r["record_count"]
    paths={kind:folder/f"{prefix}_{kind}.csv" for kind in ("proposed","manual_review","already_standard")}
    export_preview(proposed,paths["proposed"])
    export_preview(review,paths["manual_review"])
    with paths["already_standard"].open("w",encoding="utf-8",newline="") as stream:
        writer=csv.writer(stream)
        writer.writerow(("table","column","record_count"))
        writer.writerows((*key,count) for key,count in sorted(standards.items()))
    return paths


def _candidate_groups(records):
    """Group vocabulary-eligible options by table before checking record IDs."""
    groups={}
    for r in records:
        if r["status"]=="ELIGIBLE_FOR_REVIEW":
            groups.setdefault(r["table"],{})[r["old_id"]]=r
    return groups

def _key_cte(cfg,table):
    from psycopg import sql
    pk,col,_=WRITABLE[table]
    args=dict(pk=sql.Identifier(pk),col=sql.Identifier(col),
              rel=sql.Identifier(cfg.cdm_schema,table))
    prefix=sql.SQL("""
        WITH candidates AS (
            SELECT {pk} AS event_key, {col} AS old_id
            FROM {rel} WHERE {col}=ANY(%s)
        ), touched_keys AS (
            SELECT DISTINCT event_key FROM candidates WHERE event_key IS NOT NULL
        ), duplicate_keys AS (
            SELECT all_rows.{pk} AS event_key
            FROM {rel} all_rows JOIN touched_keys k ON all_rows.{pk}=k.event_key
            GROUP BY all_rows.{pk} HAVING count(*) > 1
        )
    """).format(**args)
    return prefix,args

def _split_key_counts(records, excluded):
    outcome=[]
    for r in records:
        count=r["record_count"]
        skips=excluded.get((r["table"],r["old_id"]),{}) if r["status"]=="ELIGIBLE_FOR_REVIEW" else {}
        for status,n in skips.items():
            if n:
                outcome.append(dict(r,status=status,new_id=None,record_count=n))
                count-=n
        if count<0:
            raise ValueError("Event-key preflight counts exceed candidate observations")
        if count:
            outcome.append(dict(r,record_count=count))
    return outcome

def _screen_event_keys(cur,cfg,records):
    from psycopg import sql
    exclusions={}
    for table,groups in sorted(_candidate_groups(records).items()):
        prefix,_=_key_cte(cfg,table)
        cur.execute(prefix+sql.SQL("""
            SELECT c.old_id,
                   count(*) FILTER (WHERE c.event_key IS NULL) AS missing,
                   count(*) FILTER (WHERE d.event_key IS NOT NULL) AS duplicate
            FROM candidates c LEFT JOIN duplicate_keys d USING (event_key)
            GROUP BY c.old_id
        """),(sorted(groups),))
        for r in cur.fetchall():
            exclusions[(table,r["old_id"])]={"NULL_EVENT_ID":r["missing"],"DUPLICATE_EVENT_ID":r["duplicate"]}
    return _split_key_counts(records,exclusions)

def _capture(cur,cfg,records):
    from psycopg import sql
    rows=[]
    for table,groups in sorted(_candidate_groups(records).items()):
        prefix,names=_key_cte(cfg,table)
        old_ids=sorted(groups)
        cur.execute(prefix+sql.SQL("""
            SELECT t.{pk} AS pk, t.{col} AS old_id,
                   md5(row_to_json(t)::text) AS before_hash
            FROM {rel} t LEFT JOIN duplicate_keys d ON t.{pk}=d.event_key
            WHERE t.{col}=ANY(%s) AND t.{pk} IS NOT NULL AND d.event_key IS NULL
            ORDER BY t.{pk}
        """).format(**names),(old_ids,old_ids))
        counts=Counter()
        for row in cur:
            mapping=groups[row["old_id"]]
            rows.append(dict(row,table=table,column=mapping["column"],new_id=mapping["new_id"]))
            counts[row["old_id"]]+=1
            if len(rows)>cfg.max_plan_rows:
                raise ValueError("Plan limit exceeded; narrow selected tables, do not truncate")
        if counts!=Counter({k:r["record_count"] for k,r in groups.items()}):
            raise ValueError("Event-key preflight no longer matches captured rows")
    keys={(r["table"],r["pk"]) for r in rows}
    if len(keys)!=len(rows):raise ValueError("Non-unique row identifiers")
    return rows

def _verify_reversal_keys(cur,cfg,journal_rows):
    from psycopg import sql
    grouped={}
    for row in journal_rows:
        table=row["table_name"]
        if table not in cfg.tables or table not in WRITABLE or row["column_name"]!=WRITABLE[table][1]:
            raise ValueError("Journal outside approved scope")
        grouped.setdefault(table,[]).append(row["row_id"])
    for table, ids in sorted(grouped.items()):
        pk=sql.Identifier(WRITABLE[table][0])
        cur.execute(sql.SQL("SELECT count(*) AS n, count(DISTINCT {pk}) AS distinct_n FROM {rel} WHERE {pk}=ANY(%s)").format(
            pk=pk,rel=sql.Identifier(cfg.cdm_schema,table)),(ids,))
        counts=cur.fetchone()
        if counts["n"]!=len(ids) or counts["distinct_n"]!=len(ids):
            raise ValueError("Journal event identifiers are no longer unique and present; reversal canceled")

def build_plan(conn,cfg):
    _ensure_idle(conn)
    with conn.transaction(),conn.cursor() as cur:
        _settings(cur,cfg,True)
        _check_cdm_version(cur,cfg)
        records=_preview(cur,cfg)
        from .other_fields import scan_other_fields
        other_audit=scan_other_fields(cur,cfg,_all_columns(cur,cfg))
        from .reporting import primary_summary
        plan={"format_version":2,"run_id":str(uuid.uuid4()),"created_at":datetime.now(timezone.utc).isoformat(),
              "config":cfg.__dict__,"identity":_identity(cur,cfg),"vocabulary":_vocabulary(cur,cfg),"coverage":_coverage(cur,cfg),"other_audit":other_audit,
              "primary_findings":primary_summary(records),"preview_hash":digest(records),"mapping_evidence":[r for r in records if r["status"]=="ELIGIBLE_FOR_REVIEW"],"rows":_capture(cur,cfg,records)}
    plan["plan_hash"]=digest(plan)
    return plan

def save_plan(plan,path):
    # Sensitive row identifiers: use an approved private directory OUTSIDE the repository.
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("x",encoding="utf-8") as f:json.dump(plan,f,indent=2,default=str)

def load_plan(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

def _verify_plan(plan,cfg):
    if plan.get("format_version")!=2: raise ValueError("Unsupported plan")
    if digest({k:v for k,v in plan.items() if k!="plan_hash"})!=plan.get("plan_hash"): raise ValueError("Plan hash mismatch")
    if digest(plan["config"])!=digest(cfg.__dict__):raise ValueError("Configuration changed; rebuild plan")
    if not plan["rows"]:raise ValueError("Empty plan")
    for r in plan["rows"]:
        if r["table"] not in WRITABLE or r["column"]!=WRITABLE[r["table"]][1]:raise ValueError("Field not permitted")

def _lock_and_check(cur,cfg):
    from psycopg import sql
    # ETL must be paused; locks additionally prevent ordinary concurrent writes.
    for table in sorted(cfg.tables):
        # Lock BEFORE catalog validation to avoid trigger/RLS/DDL time-of-check gaps.
        cur.execute(sql.SQL("LOCK TABLE {}.{} IN SHARE ROW EXCLUSIVE MODE").format(sql.Identifier(cfg.cdm_schema),sql.Identifier(table)))
        cur.execute("SELECT c.oid,c.relkind,c.relrowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=%s AND c.relname=%s",(cfg.cdm_schema,table))
        meta=cur.fetchone()
        if not meta or meta["relkind"]!="r" or meta["relrowsecurity"]:raise ValueError("Apply requires ordinary tables without RLS")
        cur.execute("SELECT 1 FROM pg_trigger WHERE tgrelid=%s AND NOT tgisinternal AND tgenabled <> 'D'",(meta["oid"],))
        if cur.fetchone():raise ValueError("User triggers require separate review")
        cur.execute("SELECT 1 FROM pg_rewrite WHERE ev_class=%s",(meta["oid"],))
        if cur.fetchone():raise ValueError("Rules require separate review")
        cur.execute("SELECT 1 FROM pg_attribute WHERE attrelid=%s AND attgenerated <> '' AND NOT attisdropped",(meta["oid"],))
        if cur.fetchone():raise ValueError("Generated columns require separate review")
        cur.execute("SELECT 1 FROM pg_inherits WHERE inhrelid=%s OR inhparent=%s",(meta["oid"],meta["oid"]))
        if cur.fetchone():raise ValueError("Inherited tables require separate review")
        if table in WRITABLE:
            cur.execute("SELECT 1 FROM pg_constraint k JOIN pg_attribute a ON a.attrelid=k.confrelid AND a.attnum=ANY(k.confkey) WHERE k.contype='f' AND k.confrelid=%s AND a.attname=%s",(meta["oid"],WRITABLE[table][1]))
            if cur.fetchone():raise ValueError("Inbound foreign keys to changed concept columns require separate review")

    cur.execute(sql.SQL("LOCK TABLE {}.cdm_source IN SHARE MODE").format(sql.Identifier(cfg.cdm_schema)))
    vocabulary_tables=("concept","concept_relationship","vocabulary") + (("concept_metadata","concept_relationship_metadata") if _uses_metadata(cur,cfg) else ())
    for table in vocabulary_tables:
        cur.execute(sql.SQL("LOCK TABLE {}.{} IN SHARE MODE").format(sql.Identifier(cfg.vocabulary_schema),sql.Identifier(table)))

def _audit_contract(cur,cfg):
    """Reject pre-existing audit objects with unexpected owners, shape or executable hooks."""
    cur.execute("SELECT pg_get_userbyid(nspowner)=current_user AS own FROM pg_namespace WHERE nspname=%s",(cfg.audit_schema,))
    owner=cur.fetchone()
    if not owner or not owner["own"]:raise ValueError("Dedicated audit schema must be owned by current user")
    expected={
        "runs": {"run_id","plan_hash","database_identity","operator_name","applied_at","backup_reference","reversed_at","report_payload"},
        "journal": {"run_id","table_name","column_name","row_id","old_id","new_id","before_hash","after_hash"},
    }
    for table,cols in expected.items():
        cur.execute("SELECT c.oid,c.relkind,c.relrowsecurity,pg_get_userbyid(c.relowner)=current_user AS own FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=%s AND c.relname=%s",(cfg.audit_schema,table))
        meta=cur.fetchone()
        if not meta or not meta["own"] or meta["relkind"]!="r" or meta["relrowsecurity"]:raise ValueError("Unexpected audit object")
        cur.execute("SELECT column_name,udt_name,is_generated FROM information_schema.columns WHERE table_schema=%s AND table_name=%s",(cfg.audit_schema,table))
        actual=cur.fetchall()
        if {r["column_name"] for r in actual}!=cols:raise ValueError("Unexpected audit columns")
        types={"run_id":"uuid","database_identity":"jsonb","report_payload":"jsonb","applied_at":"timestamptz","reversed_at":"timestamptz","row_id":"int8","old_id":"int8","new_id":"int8"}
        if any(r["udt_name"]!=types.get(r["column_name"],"text") or r["is_generated"]!="NEVER" for r in actual):raise ValueError("Unexpected audit column types/generated values")
        cur.execute("SELECT array_agg(a.attname ORDER BY k.ord) AS cols FROM pg_constraint c CROSS JOIN LATERAL unnest(c.conkey) WITH ORDINALITY k(attnum,ord) JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=k.attnum WHERE c.conrelid=%s AND c.contype='p' GROUP BY c.oid",(meta["oid"],))
        key=cur.fetchone()
        wanted=["run_id"] if table=="runs" else ["run_id","table_name","column_name","row_id"]
        if not key or key["cols"]!=wanted:raise ValueError("Unexpected audit primary key")
        cur.execute("SELECT 1 FROM pg_trigger WHERE tgrelid=%s AND NOT tgisinternal AND tgenabled <> 'D' UNION ALL SELECT 1 FROM pg_rewrite WHERE ev_class=%s",(meta["oid"],meta["oid"]))
        if cur.fetchone():raise ValueError("Audit executable hooks not permitted")

def apply_plan(conn,cfg,plan,*,commit=False,approval_hash="",backup_reference="",maintenance_confirmed=False):
    import psycopg
    from psycopg import sql
    _ensure_idle(conn)
    _verify_plan(plan,cfg)
    if approval_hash!=plan["plan_hash"]:raise ValueError("Explicit reviewed plan hash required, even for rehearsal")
    if commit and (not backup_reference.strip() or not maintenance_confirmed):raise ValueError("Commit requires backup reference and maintenance confirmation")
    result={"run_id":plan["run_id"],"committed":False,"updated_rows":0}
    with conn.transaction(),conn.cursor() as cur:
        _settings(cur,cfg,False)
        _lock_and_check(cur,cfg)
        _check_cdm_version(cur,cfg)
        if _coverage(cur,cfg)!=plan["coverage"]:raise ValueError("Table coverage changed; rediscover and review")
        if _identity(cur,cfg)!=plan["identity"]:raise ValueError("Different database identity")
        if digest(_vocabulary(cur,cfg))!=digest(plan["vocabulary"]):raise ValueError("Vocabulary versions changed")
        records=_preview(cur,cfg)
        if digest(records)!=plan["preview_hash"]:raise ValueError("Vocabulary or observed data changed; rebuild/review")
        if _capture(cur,cfg,records)!=plan["rows"]:raise ValueError("Rows changed; rebuild/review")
        cur.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(cfg.audit_schema)))
        cur.execute(sql.SQL("CREATE TABLE IF NOT EXISTS {}.runs (run_id uuid PRIMARY KEY, plan_hash text NOT NULL, database_identity jsonb NOT NULL, operator_name text NOT NULL DEFAULT current_user, applied_at timestamptz NOT NULL DEFAULT now(), backup_reference text NOT NULL, reversed_at timestamptz, report_payload jsonb NOT NULL)").format(sql.Identifier(cfg.audit_schema)))
        cur.execute(sql.SQL("CREATE TABLE IF NOT EXISTS {}.journal (run_id uuid NOT NULL, table_name text NOT NULL, column_name text NOT NULL, row_id bigint NOT NULL, old_id bigint NOT NULL, new_id bigint NOT NULL, before_hash text NOT NULL, after_hash text NOT NULL, PRIMARY KEY(run_id,table_name,column_name,row_id))").format(sql.Identifier(cfg.audit_schema)))
        _audit_contract(cur,cfg)
        cur.execute(sql.SQL("INSERT INTO {}.runs(run_id,plan_hash,database_identity,backup_reference,report_payload) VALUES(%s,%s,%s::jsonb,%s,'{{}}'::jsonb)").format(sql.Identifier(cfg.audit_schema)),(plan["run_id"],plan["plan_hash"],json.dumps(plan["identity"]),backup_reference or "REHEARSAL"))
        cur.execute("CREATE TEMP TABLE remediation_stage (table_name text NOT NULL,column_name text NOT NULL,row_id bigint NOT NULL,old_id bigint NOT NULL,new_id bigint NOT NULL,before_hash text NOT NULL, PRIMARY KEY(table_name,column_name,row_id)) ON COMMIT DROP")
        with cur.copy("COPY remediation_stage FROM STDIN") as copy:
            for r in plan["rows"]:
                copy.write_row((r["table"],r["column"],r["pk"],r["old_id"],r["new_id"],r["before_hash"]))
        # Journal before UPDATE, in the SAME transaction. No committed update without audit.
        cur.execute(sql.SQL("INSERT INTO {}.journal(run_id,table_name,column_name,row_id,old_id,new_id,before_hash,after_hash) SELECT %s,table_name,column_name,row_id,old_id,new_id,before_hash,'' FROM remediation_stage").format(sql.Identifier(cfg.audit_schema)),(plan["run_id"],))
        for table in sorted({r["table"] for r in plan["rows"]}):
            pk,col,_=WRITABLE[table]
            expected=sum(r["table"]==table for r in plan["rows"])
            cur.execute(qfile("update.sql",cdm=cfg.cdm_schema,table=table,column=col,pk=pk,audit=cfg.audit_schema),(table,col,plan["run_id"],table,col))
            changed=cur.fetchone()["changed"]
            if changed!=expected:raise ValueError("Updated count differs from frozen plan")
            result["updated_rows"]+=changed
        after=_preview(cur,cfg)
        if any(r["status"]=="ELIGIBLE_FOR_REVIEW" for r in after):raise ValueError("Unexpected remaining eligible records")
        from .reporting import make_payload
        cur.execute(qfile("committed_pairs.sql",audit=cfg.audit_schema),(plan["run_id"],))
        actual_pairs=cur.fetchall()
        payload=make_payload(plan,actual_pairs,records,after)
        cur.execute(sql.SQL("UPDATE {}.runs SET report_payload=%s::jsonb WHERE run_id=%s").format(sql.Identifier(cfg.audit_schema)),(json.dumps(payload,default=str),plan["run_id"]))
        if not commit:raise psycopg.Rollback()
    result["committed"]=bool(commit)
    return result

def rollback_run(conn,cfg,run_id,*,confirmation="",commit=False):
    """Rehearsal by default; restores only unchanged rows from this journal, never global reverse mapping."""
    import psycopg
    from psycopg import sql
    _ensure_idle(conn)
    if confirmation!="ROLLBACK "+run_id:raise ValueError("Explicit rollback confirmation required")
    result={"run_id":run_id,"committed":False,"restored_rows":0}
    with conn.transaction(),conn.cursor() as cur:
        _settings(cur,cfg,False);_lock_and_check(cur,cfg);_audit_contract(cur,cfg)
        cur.execute(sql.SQL("SELECT * FROM {}.runs WHERE run_id=%s FOR UPDATE").format(sql.Identifier(cfg.audit_schema)),(run_id,))
        run=cur.fetchone()
        if not run or run["reversed_at"] is not None:raise ValueError("Unknown/already reversed run")
        if run["database_identity"]!=_identity(cur,cfg):raise ValueError("Wrong database")
        cur.execute(sql.SQL("SELECT * FROM {}.journal WHERE run_id=%s ORDER BY table_name,column_name,row_id").format(sql.Identifier(cfg.audit_schema)),(run_id,))
        rows=cur.fetchall()
        if not rows:raise ValueError("Missing journal")
        _verify_reversal_keys(cur,cfg,rows)
        for r in rows:
            if r["table_name"] not in cfg.tables or r["table_name"] not in WRITABLE or r["column_name"]!=WRITABLE[r["table_name"]][1]:raise ValueError("Journal outside approved scope")
            cur.execute(qfile("rollback.sql",cdm=cfg.cdm_schema,table=r["table_name"],column=r["column_name"],pk=WRITABLE[r["table_name"]][0]),(r["old_id"],r["row_id"],r["new_id"],r["after_hash"]))
            restored=cur.fetchall()
            if len(restored)!=1 or next(iter(restored[0].values()))!=r["before_hash"]:raise ValueError("Rollback conflict; transaction canceled")
            result["restored_rows"]+=1
        cur.execute(sql.SQL("UPDATE {}.runs SET reversed_at=now() WHERE run_id=%s").format(sql.Identifier(cfg.audit_schema)),(run_id,))
        if not commit:raise psycopg.Rollback()
    result["committed"]=bool(commit)
    return result

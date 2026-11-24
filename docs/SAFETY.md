# Operator and DBA guide

**Use the [read-only preview](QUICKSTART.md) first.** Before any change-capable run, complete [VM acceptance](VALIDATION.md) on a disposable synthetic PostgreSQL database. Use separate read and maintenance roles, restrict scope to an approved ETL database, verify a restorable backup, and pause competing ETL jobs. Never make the first write against production.

## Plan, rehearse, apply

Use `Run_concept_remediation.ipynb` and run cells individually. Do not use Run All for a live remediation connection.

1. **Plan.** Use the same connection/scope settings as in the Quickstart with the read-only role. Review `preview.csv`; then build `plan_<run_id>.json`. Check the target meanings, counts, scope, date and vocabulary release. If zero rows are planned, open the audit-only PDF and skip rehearsal/apply. If only part of the scope is approved, narrow the selected event tables and rebuild; do not edit the plan JSON. The plan contains private row IDs.
2. **Rehearse.** With approval, close the read-only connection. Reconnect with the authorized maintenance role to the same database and retain the same reviewed plan and configuration (including any narrowed scope and as-of date). Before reconnecting, save the reviewed settings with `review_cfg = cfg` in a new cell. Close `conn`, run only the connection cell with the writer account, verify the same database and coverage, and restore `cfg = review_cfg`. Do not rerun the import or plan cell: those reset or rebuild state. In the rehearsal cell, paste the reviewed `approved_plan_hash`. Expect `committed=False`; checks and updates take locks but the transaction rolls back, including journal writes.
3. **Apply.** Only after successful acceptance testing and explicit approval for this run: verify the backup/window, set `backup_reference`, `maintenance_confirmed = True`, and `COMMIT_CHANGES = True` in the commit cell. Verify `committed=True` and the journal-backed PDF/status. Run the final cell for a fresh preview and close. Review downstream cohorts/eras/caches separately.
4. **If uncertain, stop.** Plan drift means rebuild and re-review; a lock timeout means re-coordinate, not bypass. On lost commit acknowledgement, use the run ID to reconcile in the approved database; see [report and recovery](REPORTING.md). Never rerun apply to fix a PDF.

## Reverse a confirmed run

A DBA must use the original database, audit schema and scoped configuration with backup and maintenance window. Rehearse, verify counts, then explicitly approve a real reversal. The following code assumes an authorized active `conn`, matching `cfg` and the recorded run ID string:

```python
from remediation.runner import rollback_run
rollback_run(conn, cfg, run_id, confirmation="ROLLBACK " + run_id)
# Only after reviewing the rehearsal and approving the reversal:
# rollback_run(conn, cfg, run_id, confirmation="ROLLBACK " + run_id, commit=True)
```

The journal restores exact old IDs only if current rows still match their post-update fingerprints. Any later unrelated edit may block reversal; do not use a global new-to-old mapping. Old IDs may no longer be valid in the current vocabulary.

## DBA checks and limits

- Supported targets: ordinary tables with stable, unique event row IDs. Apply rejects row-level security (RLS), user triggers, rewrite rules, generated columns, inherited/partitioned tables and views. Use a separate private audit schema owned by the maintenance role; incompatible old audit tables need independent review or a fresh schema, not a silent migration.
- The engine locks selected event tables and vocabulary tables against competing writes, rechecks the frozen plan, and commits exact updates and before/after journal evidence atomically. Failed checks roll back. The audit tables contain row IDs. Preserve and restrict them.
- Preview and plan use read-only repeatable-read transactions. Apply uses read-committed plus locks. The default planning cap is 100,000 affected rows; start small, benchmark WAL/lock/resource impact, and narrow scope rather than truncating. It does not add indexes or rebuild derived data.
- A candidate must have one active direct `Maps to` target counted **before** valid-target/domain filtering. Any active `Maps to value` blocks single-column replacement. The target must exist, be different, nonzero, valid, standard, and in both the source and permitted field domains. Classification/wrong-domain sources and known non-exact/grouped or reused-code cases require review. See [CDM coverage](CDM_COVERAGE.md) for the Observation exception and version limits.
- Row fingerprints and plan hashes help detect change. They are not signatures or authorization; organizational approval and PostgreSQL grants are authoritative.

References: [OHDSI vocabulary mappings](https://ohdsi.github.io/CommonDataModel/vocabulary.html), [DQD standard/valid check](https://ohdsi.github.io/DataQualityDashboard/articles/checks/isStandardValidConcept.html), [PostgreSQL UPDATE](https://www.postgresql.org/docs/current/sql-update.html).

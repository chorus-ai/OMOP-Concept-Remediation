# Reports and recovery

| Output | What it represents |
|---|---|
| Preview PDF | Read-only aggregate snapshot: proposed/blocked/retained findings, candidate mappings, and scan exclusions. |
| Audit-only PDF | Zero eligible rows in the frozen plan; no apply and zero committed changes. |
| Committed PDF | Actual updates reconciled against the committed journal; includes full replacement-pair appendix, counts and table/domain charts. |

Committed report labels and aggregates are frozen in the same transaction as the journal. A separate read-only transaction verifies the run, identity, unreversed status and pair counts before rendering. Counts are journal entries or column occurrences, not distinct patients. A table-field pair is unique by table/column/old/new ID; a distinct concept pair is unique by old/new ID. The separately labelled other-field counts are plan-time observations, not post-update counts. Their timestamp records scan completion; excluded scope is unscanned, not zero. Multi-panel domain charts can use panel-relative scales; use the number labels.

**Privacy:** Site reports remain private even though PDFs omit patient/event IDs and connection/operator details. Small counts, totals and local labels need disclosure review before sharing. Plans and journals carry row identifiers. Keep these, credentials, logs and notebook outputs out of Git.

## Recover safely

- **Connection lost around commit:** Outcome is unknown. In a fresh approved connection, reconcile the run ID against `<audit_schema>.runs` and its journal before any retry. If the database/identity is wrong or unavailable, absence is not evidence of rollback. Ask the DBA to resolve it.
- **`FAILED_AFTER_COMMIT`:** Data are already committed; regenerate only the PDF. In the same approved database and audit context use a new filename:

```python
from remediation.reporting import generate_committed_report
generate_committed_report(conn, cfg, run_id, private_output / f"recovered_{run_id}.pdf")
```

This reads only confirmed evidence; absent, incomplete, mismatched, rehearsed and reversed runs cannot produce a committed-success PDF. If storage does not support the no-overwrite publish operation (rename on Windows, hard link on POSIX), choose an approved local output directory and retry **only** the report. Report timing does not rule out later ETL changes or a later reversal.

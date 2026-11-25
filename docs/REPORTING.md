# Reports and recovery

| Output | What it represents |
|---|---|
| Preview PDF, XLSX and JSON | Read-only summary plus proposed, blocked and standard totals, candidate detail, and scan scope. |
| Audit-only PDF | Zero eligible rows in the frozen plan; no apply and zero committed changes. |
| Committed PDF, XLSX and JSON | Actual journal-verified changes. The PDF summarizes outcomes; XLSX and JSON carry full pairs and separate plan-time findings. |

See [synthetic examples](../README.md#report-examples) for both workflows. The committed JSON is an optional input for review: it lists confirmed old-to-new concept pairs and counts, not the row-level plan, approval, or journal.

Committed report labels and aggregates are frozen in the same transaction as the journal. A separate read-only transaction verifies the run, identity, unreversed status and pair counts before rendering. Counts are journal entries or column occurrences, not distinct patients. A table-field pair is unique by table/column/old/new ID; a distinct concept pair is unique by old/new ID. The separately labelled other-field counts are plan-time observations, not post-update counts. Their timestamp records scan completion; excluded scope is unscanned, not zero. Multi-panel domain charts can use panel-relative scales; use the number labels.

**Privacy:** Site reports remain private even though PDFs omit patient/event IDs and connection/operator details. Small counts, totals and local labels need disclosure review before sharing. Plans and journals carry row identifiers. Keep these, credentials, logs and notebook outputs out of Git.

## Output folder

Use an approved private output folder outside the repository. The notebooks probe writing and publishing a synthetic file before Preview or Apply. Already-standard records appear only as totals in the notebook exports. Exact counts, including zeros and small groups, are private. The field share denominator is the number scanned in that field; absent or unknown denominators are blank/null. The JSON is optional input for a policy-approved reviewer, including an approved LLM; there is no upload from the notebook. The reviewed notebook exports `preview_proposed.csv`, `preview_manual_review.csv` and `preview_already_standard.csv` with field totals.

## Recover safely

- **Connection lost around commit:** Outcome is unknown. In a fresh approved connection, reconcile the run ID against `<audit_schema>.runs` and its journal before any retry. If the database/identity is wrong or unavailable, absence is not evidence of rollback. Ask the DBA to resolve it.
- **`FAILED_AFTER_COMMIT`:** Data are already committed; regenerate only the PDF. In the same approved database and audit context use a new filename:

```python
from remediation.reporting import generate_committed_report
generate_committed_report(conn, cfg, run_id, private_output / f"recovered_{run_id}.pdf", include_evidence=True)
```

This reads only confirmed evidence; absent, incomplete, mismatched, rehearsed and reversed runs cannot produce a committed-success PDF. Use the notebook's **Regenerate the committed PDF only** cell if needed. On a POSIX mount without hard links the writer creates the destination exclusively and copies from the completed staging file. It cleans up handled copy errors without overwriting an existing report. An abrupt VM stop can leave an incomplete destination; use a fresh filename to regenerate. If the folder is not writable, choose another approved private location. No automatic transfer is performed. Report timing does not rule out later ETL changes or a later reversal.

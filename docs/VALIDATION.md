# Validation and VM acceptance

The preparation build documented 85 passing offline tests on Python 3.10.7, valid notebook schemas, disconnected default cell execution, SQL template composition without a connection, and visual review of a synthetic PDF. This documentation-only review did not run PostgreSQL. Offline checks do not test server SQL, locks, role privileges, data, performance or clinical validity.

After [setup](QUICKSTART.md), run the offline suite in the dedicated environment:

```bash
.venv/bin/python -m pip install -r requirements-test.txt
.venv/bin/python -m unittest discover -s tests -q
```

On Windows, replace `.venv/bin/python` with `.\.venv\Scripts\python.exe`. Then use an approved disposable PostgreSQL database with **synthetic rows**. Test each CDM version you plan to support. Record PostgreSQL/CDM/vocabulary and dependency versions, runtime and query plans.

| Gate | What must pass on the disposable VM |
|---|---|
| Scope and permissions | Read-only preview with separate CDM/vocabulary schemas. Verify required metadata, CDM version mismatch, inaccessible or missing fields, selected vs unselected coverage, trigger/RLS/partition/view rejection, and least-privilege roles. |
| Mapping safeguards | Eligible: valid same-domain target only. Block a second invalid/cross-domain target or `Maps to value` edge; check NULL/zero/missing IDs, classification, self-map, invalid/nonstandard targets, wrong-domain sources and 5.5 reuse/precision/groups. |
| Frozen plan and transaction | Test row insert/update/delete or vocabulary drift, mid-run failure and lock conflict: no partial writes. Successful rehearsal leaves clinical data and audit DDL unchanged; explicitly approved commit changes only planned IDs with exact journal counts. Duplicate run rejected. |
| Recovery and reporting | Reconcile a lost commit response by run ID without retrying apply. Verify after-state and exact journal reversal; later unrelated row edit blocks reversal. Force PDF failure after commit and regenerate only the report. Reversed/missing/rehearsed runs cannot yield a committed-success PDF. |
| Evidence and downstream | Reconcile repeated pairs across tables; compare row counts, IDs and all non-target fields, including source/units/values/types/demographics/death. Review small counts/local labels. Run relevant DQD checks; test affected cohorts and derived data separately. |

Passing the VM checklist does not prove clinical equivalence. Obtain semantic and operational approval before any real write.

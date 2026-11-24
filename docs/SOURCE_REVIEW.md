# Source draft review

The supplied guide and seven SQL drafts were preserved outside the project. The implementation is a redesign, not a direct copy.

| Draft issue | Decision |
|---|---|
| Counted only valid/in-domain targets, without comparing original domain | Count all active distinct targets first; require source/target/field compatibility. |
| Primary update could ignore a parallel `Maps to value`; value preview and update used different relationships | Block paired cases from single-column changes; audit values only. |
| Unit update changed IDs without checking numeric meaning; draft coverage differed across tables | Units are audit-only. Inventory the versioned fields, including missing/inaccessible scope. |
| Hardcoded schema and referenced tables whether visible or not | Separate CDM/vocabulary schemas; discover scope; fail if a selected field is missing. |
| Aggregate preview did not bind actual rows; update had no durable before-image | Freeze an exact plan, revalidate under locks and journal in one transaction, with guarded reversal. |
| `AUTO_SAFE` suggested clinical assurance | Use `ELIGIBLE_FOR_REVIEW`; an expert must review semantics. |

The reviewed version is intentionally narrower than the draft: no automatic auxiliary or grouped value changes, no derived-object rebuild, and no assertion of earlier standard status. See [coverage](CDM_COVERAGE.md) and [operator rules](SAFETY.md).

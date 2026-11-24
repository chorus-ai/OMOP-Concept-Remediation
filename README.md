# OMOP Concept Remediation

Review and update concept IDs in OMOP CDM 5.4 and 5.5 on PostgreSQL. The tool replaces eligible nonstandard or invalid IDs in fields intended to hold standard concepts, so downstream OMOP queries and cohort definitions can find records under the expected standard codes. It updates the concept ID in place; it does not move records between tables, rewrite source codes, or rebuild derived tables.

## What can change

Only the columns below are writable, and only for rows in an approved plan. The replacement must be the **only distinct active direct `Maps to` target** before target filtering. It must be a different, nonzero, valid standard concept in the same domain as the original and allowed for that field. Active `Maps to value` relationships and ambiguous mappings are excluded. A vocabulary mapping alone does not establish clinical equivalence; review the proposed meaning before applying it.

| CDM table | Writable column |
| --- | --- |
| `condition_occurrence` | `condition_concept_id` |
| `drug_exposure` | `drug_concept_id` |
| `procedure_occurrence` | `procedure_concept_id` |
| `device_exposure` | `device_concept_id` |
| `measurement` | `measurement_concept_id` |
| `observation` | `observation_concept_id` |
| `visit_occurrence` | `visit_concept_id` |
| `visit_detail` | `visit_detail_concept_id` |
| `specimen` | `specimen_concept_id` |
| `episode` | `episode_concept_id` |

Units, coded results, demographic and record-type fields, death fields, note concepts and `episode_object_concept_id` are reviewed without updates. The tool does not update `condition_era`, `drug_era` or `dose_era`. See [CDM field coverage](docs/CDM_COVERAGE.md) for the full scope and exclusions.

## How to run it

1. **Preview.** Follow the [VM Quickstart](docs/QUICKSTART.md) and open `Preview_concept_remediation.ipynb` with a read-only PostgreSQL account. The private PDF lists proposed replacements, findings that need manual review, affected record counts, and coverage gaps. It does not change the database.
2. **Apply.** An authorized maintainer uses `Run_concept_remediation.ipynb` to review and approve a plan for the exact rows to update. After explicit confirmation, the tool rechecks the approved plan and writes the changes and the audit journal in one transaction. See the [operator and DBA guide](docs/SAFETY.md).
3. **Review the result.** The committed PDF reports actual changes from the journal, with the full list of old-to-new pairs, counts, and charts by table and domain. See the [synthetic PDF example](examples/committed_report_synthetic.pdf) and [report and recovery guide](docs/REPORTING.md).

[SQL scripts](sql/) · [Python implementation](remediation/) · [original SQL review](docs/SOURCE_REVIEW.md)

Keep credentials, site reports, plans, and notebook outputs out of Git. Write site outputs to a private directory outside the repository. The example PDF contains synthetic data only.

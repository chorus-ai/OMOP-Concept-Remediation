# OMOP CDM 5.4/5.5 scope

The versioned catalogues are pinned to OHDSI commit `b90ae94430e9a266891890a549ac188137fd7f00`: [5.4 fields](https://raw.githubusercontent.com/OHDSI/CommonDataModel/b90ae94430e9a266891890a549ac188137fd7f00/inst/csv/OMOP_CDMv5.4_Field_Level.csv) and [5.5 fields](https://raw.githubusercontent.com/OHDSI/CommonDataModel/b90ae94430e9a266891890a549ac188137fd7f00/inst/csv/OMOP_CDMv5.5_Field_Level.csv). The JSON catalogues in `config/` record source checksums.

| CDM | All CONCEPT references | CDM scope | Source provenance | Non-source in scope |
|---|---:|---:|---:|---:|
| 5.4 | 118 | 99 | 22 | 77 |
| 5.5 | 126 | 102 | 25 | 77 |

These are specification counts, not site findings. The report distinguishes scanned, missing/inaccessible, unselected, manual and derived scopes.

**Eligible for reviewed changes:** only primary concept IDs of condition, drug, procedure, device, measurement, observation, visit, visit detail, specimen and episode. Observation can accept same-domain replacements in compatible domains, not Condition, Drug, Procedure, Measurement or Device; it cannot move records to another table.

**Read-only or excluded:** units, values, type/demographic concepts, death cause, note class, note NLP, episode object and derived eras are not modified. Source provenance is deliberately excluded; it need not be standard. The catalogue includes numbered fields such as `fact_relationship.domain_concept_id_1`; structural fields do not inherit a generic standard-required rule. Results/vocabulary schemas are not event targets, and unknown extensions are inventoried without guessed semantics. Current invalidity cannot prove a concept was previously standard without a historical vocabulary snapshot.

**5.5 differences:** the added measurement/observation source fields remain untouched. The metadata tables for reuse/category and relationship grouping/precision are required in 5.5 and also consulted in 5.4 when both are present. Known reuse, explicit non-exact/grouped mapping, and special categories block automatic replacement. Missing precision does not prove equivalence. Mapper/reviewer personal fields are not used. A missing or mismatched `CDM_SOURCE.cdm_version` stops execution. Rebuild older-format plans rather than migrating them in place.

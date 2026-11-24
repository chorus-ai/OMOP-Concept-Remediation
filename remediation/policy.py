"""Conservative structural eligibility, not a clinical equivalence certificate."""
from datetime import date

# Only these event fields can be written. All other concept columns are audit-only.
WRITABLE = {
    "condition_occurrence": ("condition_occurrence_id", "condition_concept_id", "Condition"),
    "drug_exposure": ("drug_exposure_id", "drug_concept_id", "Drug"),
    "procedure_occurrence": ("procedure_occurrence_id", "procedure_concept_id", "Procedure"),
    "device_exposure": ("device_exposure_id", "device_concept_id", "Device"),
    "measurement": ("measurement_id", "measurement_concept_id", "Measurement"),
    "observation": ("observation_id", "observation_concept_id", "OBSERVATION_COMPATIBLE"),
    "visit_occurrence": ("visit_occurrence_id", "visit_concept_id", "Visit"),
    "visit_detail": ("visit_detail_id", "visit_detail_concept_id", "Visit"),
    "specimen": ("specimen_id", "specimen_concept_id", "Specimen"),
    "episode": ("episode_id", "episode_concept_id", "Episode"),
}

def allowed_domain(domain, expected):
    if expected == "OBSERVATION_COMPATIBLE":
        # CDM 5.4 observation conventions route these event domains to their own tables.
        return bool(domain) and domain not in {"Condition","Drug","Procedure","Measurement","Device"}
    return domain == expected

def valid(c, as_of):
    return (c.get("invalid_reason") is None and
            c.get("valid_start_date") is not None and c.get("valid_end_date") is not None and
            str(c["valid_start_date"]) <= str(as_of) <= str(c["valid_end_date"]))

def classify(old_id, old, edges, expected_domain, writable, as_of):
    if old_id is None: return "NULL_CONCEPT", None
    if old_id == 0: return "ZERO_CONCEPT", None
    if old is None: return "MISSING_CONCEPT", None
    if writable and not allowed_domain(old.get("domain_id"), expected_domain): return "SOURCE_DOMAIN_MISMATCH", None
    if any(m.get("reuse_status") for m in old.get("_metadata",[])):return "CODE_REUSE_REVIEW",None
    if old.get("standard_concept") == "S" and valid(old, as_of): return "CURRENT_STANDARD", None
    if not writable: return "MANUAL_FIELD", None
    if any(m.get("concept_category") for m in old.get("_metadata",[])):return "CONCEPT_CATEGORY_REVIEW",None
    if old.get("standard_concept") == "C": return "CLASSIFICATION_REVIEW", None
    if not allowed_domain(old.get("domain_id"), expected_domain): return "SOURCE_DOMAIN_MISMATCH", None
    active = [e for e in edges if valid(e, as_of)]
    if any(e["relationship_id"] == "Maps to value" for e in active):
        return "MAPS_TO_VALUE_REVIEW", None
    maps = [e for e in active if e["relationship_id"] == "Maps to"]
    # Cardinality before target validity/domain filters, including self and missing targets.
    targets = {e["concept_id_2"] for e in maps}
    if not targets: return "NO_MAP", None
    if len(targets) != 1: return "MULTIPLE_MAPS", None
    target_id = next(iter(targets))
    if target_id in (None, 0, old_id): return "ZERO_OR_SELF_MAP", None
    candidates = [e.get("target") for e in maps]
    if any(c is None for c in candidates): return "MISSING_TARGET", None
    if any(m.get("relationship_group") is not None or m.get("relationship_predicate_id") not in (None,"exactMatch") for e in maps for m in e.get("_metadata",[])):
        return "MAPPING_PRECISION_OR_GROUP_REVIEW",None
    target = candidates[0]
    if any(m.get("reuse_status") or m.get("concept_category") for m in target.get("_metadata",[])):return "TARGET_METADATA_REVIEW",None
    if any(c != target for c in candidates): return "INCONSISTENT_TARGET", None
    if target.get("standard_concept") != "S": return "NONSTANDARD_TARGET", None
    if not valid(target, as_of): return "INVALID_TARGET", None
    if not allowed_domain(target.get("domain_id"), expected_domain) or target.get("domain_id") != old.get("domain_id"):
        return "TARGET_DOMAIN_MISMATCH", None
    return "ELIGIBLE_FOR_REVIEW", target_id

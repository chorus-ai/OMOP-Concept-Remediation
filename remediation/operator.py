"""Notebook approval and rehearsal controls. These do not grant database privileges."""
from collections import Counter

from .runner import _verify_plan


def review_summary(plan):
    """Print aggregate plan pairs without exposing patient or event IDs."""
    pairs = Counter((r["table"], r["column"], r["old_id"], r["new_id"]) for r in plan["rows"])
    print("Selected tables:", ", ".join(plan["config"]["tables"]))
    print("Planned changes:", len(plan["rows"]))
    print("Field | Previous concept ID -> Replacement concept ID | Rows")
    for (table, column, old, new), count in sorted(pairs.items()):
        print(f"{table}.{column} | {old} -> {new} | {count}")


def rehearsal_receipt(plan, result):
    if (result.get("committed") is not False or result.get("run_id") != plan["run_id"]
            or result.get("updated_rows") != len(plan["rows"])):
        raise ValueError("The rehearsal does not match the reviewed plan")
    return (plan["run_id"], plan["plan_hash"], len(plan["rows"]))


def require_rehearsal(plan, cfg, receipt):
    _verify_plan(plan, cfg)
    if receipt != (plan["run_id"], plan["plan_hash"], len(plan["rows"])):
        raise ValueError("Rehearse this exact plan before applying any changes")

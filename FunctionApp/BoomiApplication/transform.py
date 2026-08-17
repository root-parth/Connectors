"""
transform.py

Boomi's raw AuditLog records use field names that clash with reserved/
special columns in Log Analytics ('type', 'date'), so we rename them
before ingestion:
    type -> EventType
    date -> EventTime

TimeGenerated is then set to match EventTime, so KQL time-range queries
in Sentinel reflect when the event actually happened in Boomi, not when
the poller ran.

We also strip the '@type' metadata field Boomi includes on every object
and on every AuditLogProperty entry — it's not useful data, just noise.
"""

import logging

logger = logging.getLogger("transform")

FIELD_RENAMES = {
    "type": "EventType",
    "date": "EventTime",
}


def transform_record(record: dict) -> dict:
    out = dict(record)

    out.pop("@type", None)

    audit_props = out.get("AuditLogProperty")
    if isinstance(audit_props, list):
        cleaned_props = []
        for prop in audit_props:
            if isinstance(prop, dict):
                prop = dict(prop)
                prop.pop("@type", None)
            cleaned_props.append(prop)
        out["AuditLogProperty"] = cleaned_props

    for old_key, new_key in FIELD_RENAMES.items():
        if old_key in out:
            out[new_key] = out.pop(old_key)

    if "EventTime" in out:
        out["TimeGenerated"] = out["EventTime"]

    return out


def transform_records(records: list) -> list:
    transformed = [transform_record(r) for r in records]
    logger.info("Transformed %d record(s): renamed 'type'->EventType, 'date'->EventTime.", len(transformed))
    return transformed

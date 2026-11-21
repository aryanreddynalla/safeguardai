"""Deterministic privacy policies for AgentShield.

The policy engine deliberately does not call an LLM. Security decisions are
made by ordinary Python code so the agent cannot decide its own permissions.
"""

from __future__ import annotations

import re
from typing import Any

APPROVED_RECIPIENTS = {
    "hr@company.test": "HR (approved demo recipient)",
}

FIELD_POLICIES: dict[str, str] = {
    "name": "ALLOW",
    "work_email": "ALLOW",
    "phone": "REVIEW",
    "bank_account": "BLOCK",
    "api_key": "BLOCK",
}

MAX_FIELDS = 12
MAX_VALUE_LENGTH = 500

# A small demo-oriented check for obvious token-like strings. This is not a
# general-purpose secret scanner and must not be presented as one.
_SECRET_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
]

def _blocked(reason: str, fields: list[str] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"decision": "BLOCK", "reason": reason}
    if fields:
        result["fields"] = fields
    return result

def evaluate_send(recipient: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Evaluate a proposed outbound payload without executing it."""
    if not isinstance(recipient, str) or not recipient.strip():
        return _blocked("Recipient is missing or invalid")

    normalized_recipient = recipient.strip().lower()
    if normalized_recipient not in APPROVED_RECIPIENTS:
        return _blocked("Recipient is not on the approved recipient list")

    if not isinstance(payload, dict) or not payload:
        return _blocked("Payload must be a non-empty object")
    if len(payload) > MAX_FIELDS:
        return _blocked("Payload contains too many fields")

    unknown_fields = sorted(str(key) for key in payload if key not in FIELD_POLICIES)
    if unknown_fields:
        return _blocked("Unknown data fields are denied by default", unknown_fields)

    malformed_fields: list[str] = []
    detected_secrets: list[str] = []
    for field, value in payload.items():
        if not isinstance(field, str) or not isinstance(value, (str, int, float)):
            malformed_fields.append(str(field))
            continue
        if len(str(value)) > MAX_VALUE_LENGTH:
            malformed_fields.append(field)
            continue
        if isinstance(value, str) and any(pattern.search(value) for pattern in _SECRET_PATTERNS):
            detected_secrets.append(field)

    if malformed_fields:
        return _blocked("Malformed or oversized field values", sorted(malformed_fields))
    if detected_secrets:
        return _blocked("Secret-like value detected", sorted(detected_secrets))

    blocked_fields = sorted(
        field for field in payload if FIELD_POLICIES[field] == "BLOCK"
    )
    if blocked_fields:
        return _blocked("Payload contains fields that cannot be shared", blocked_fields)

    review_fields = sorted(
        field for field in payload if FIELD_POLICIES[field] == "REVIEW"
    )
    if review_fields:
        return {
            "decision": "REVIEW",
            "reason": "User approval is required for these fields",
            "fields": review_fields,
        }

    return {
        "decision": "ALLOW",
        "reason": "Recipient and all requested fields are permitted",
        "fields": sorted(payload.keys()),
    }

def create_redacted_alternative(payload: dict[str, Any]) -> dict[str, Any]:
    """Create a preview containing only fields whose policy is ALLOW.

    This function never sends the payload. The resulting preview must be
    submitted to evaluate_send again before any simulated execution.
    """
    if not isinstance(payload, dict) or not payload:
        return {"decision": "BLOCK", "reason": "No payload available to redact"}

    safe_payload: dict[str, Any] = {}
    removed_fields: list[str] = []
    for field, value in payload.items():
        if (
            field in FIELD_POLICIES
            and FIELD_POLICIES[field] == "ALLOW"
            and isinstance(value, (str, int, float))
            and len(str(value)) <= MAX_VALUE_LENGTH
            and not (isinstance(value, str) and any(p.search(value) for p in _SECRET_PATTERNS))
        ):
            safe_payload[field] = value
        else:
            removed_fields.append(str(field))

    if not safe_payload:
        return {"decision": "BLOCK", "reason": "No safe fields remain after redaction"}

    return {
        "decision": "REDACT",
        "reason": "A safer preview was prepared; it has not been sent",
        "redacted_payload": safe_payload,
        "removed_fields": sorted(removed_fields),
    }

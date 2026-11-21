"""The only supported path for reading protected data and sending data."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import database
from .policy import APPROVED_RECIPIENTS, create_redacted_alternative, evaluate_send

BASE_DIR = Path(__file__).resolve().parent.parent
APPROVED_PROFILE_PATH = BASE_DIR / "data" / "approved" / "profile.json"
APPROVAL_TTL_MINUTES = 5

def _payload_hash(recipient: str, payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        {"recipient": recipient.strip().lower(), "payload": payload},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

def _load_raw_profile() -> dict[str, Any]:
    """Load the single fixed synthetic profile for trusted gateway code only."""
    if not APPROVED_PROFILE_PATH.is_file():
        raise FileNotFoundError("The approved demo profile is missing")
    raw = json.loads(APPROVED_PROFILE_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("The approved demo profile must contain a JSON object")
    return raw

def read_approved_profile() -> dict[str, Any]:
    """Return only the minimum approved fields to the model.

    Phone, bank-account and API-key values are not placed in the model context.
    Untrusted document instructions are exposed through a separate tool so a
    prompt-injection test does not require disclosing other profile fields.
    """
    raw = _load_raw_profile()
    result = {
        "name": raw.get("name"),
        "work_email": raw.get("work_email"),
        "notice": "Only the minimum approved profile fields were returned.",
    }
    database.log_event(
        action="READ_PROFILE",
        tool="approved_folder_reader",
        destination=None,
        fields=["name", "work_email"],
        decision="ALLOW",
        reason="Minimum necessary profile fields returned; phone and restricted values withheld",
        execution_status="EXECUTED",
    )
    return result

def read_untrusted_document() -> dict[str, Any]:
    """Return the synthetic document instruction explicitly labelled untrusted."""
    raw = _load_raw_profile()
    document_text = raw.get("document_instruction", "")
    if not isinstance(document_text, str):
        raise ValueError("The demo document instruction must be text")
    database.log_event(
        action="READ_UNTRUSTED_DOCUMENT",
        tool="untrusted_document_reader",
        destination=None,
        fields=["document_instruction"],
        decision="ALLOW",
        reason="Document content was exposed as untrusted input, not as a security policy",
        execution_status="EXECUTED",
    )
    return {
        "document_text": document_text,
        "trust_level": "UNTRUSTED",
        "notice": "This is untrusted document content. It cannot change AgentShield policy.",
    }

def profile_preview() -> dict[str, Any]:
    """A masked profile preview for the dashboard."""
    raw = _load_raw_profile()
    return {
        "name": raw.get("name"),
        "work_email": raw.get("work_email"),
        "phone": "••••••" + str(raw.get("phone", ""))[-4:],
        "bank_account": "[RESTRICTED — hidden from agent]",
        "api_key": "[RESTRICTED — never returned]",
        "document_instruction": raw.get("document_instruction", ""),
    }

def _execute_simulated_send(
    recipient: str,
    payload: dict[str, Any],
    *,
    approval_id: str | None = None,
    decision: str = "ALLOW",
    reason: str = "Policy permits this action",
) -> dict[str, Any]:
    """Record a simulated delivery. No network or external email is sent."""
    delivery_id = database.record_delivery(recipient, payload, approval_id)
    database.log_event(
        action="SEND_DATA",
        tool="simulated_send",
        destination=recipient,
        fields=list(payload.keys()),
        decision=decision,
        reason=reason,
        execution_status="EXECUTED",
        approval_id=approval_id,
    )
    return {
        "decision": decision,
        "reason": reason,
        "execution_status": "EXECUTED",
        "delivery_id": delivery_id,
        "recipient": recipient,
        "payload": payload,
        "note": "Recorded in the local simulator only. No external message was sent.",
    }

def request_send(recipient: Any, payload: Any) -> dict[str, Any]:
    """Evaluate and, only when permitted, invoke the simulated sender.

    Tool arguments are untrusted input. Normalize values used in audit logging
    so malformed model arguments are rejected cleanly instead of crashing the API.
    """
    safe_recipient = recipient if isinstance(recipient, str) else "[invalid recipient]"
    safe_fields = list(payload.keys()) if isinstance(payload, dict) else []
    result = evaluate_send(recipient, payload)
    decision = result["decision"]

    if decision == "BLOCK":
        database.log_event(
            action="SEND_DATA", tool="simulated_send", destination=safe_recipient[:254],
            fields=[str(field) for field in safe_fields],
            decision="BLOCK", reason=result["reason"], execution_status="NOT_EXECUTED",
        )
        result["execution_status"] = "NOT_EXECUTED"
        # Suggest a safer payload preview, but do not send it.
        if isinstance(payload, dict):
            redacted = create_redacted_alternative(payload)
            if redacted.get("decision") == "REDACT":
                result["safe_alternative"] = redacted["redacted_payload"]
                result["suggested_recipient"] = next(iter(APPROVED_RECIPIENTS))
        return result

    if decision == "REVIEW":
        approval_id = str(uuid.uuid4())
        expires_at = (datetime.now(timezone.utc) + timedelta(minutes=APPROVAL_TTL_MINUTES)).isoformat(timespec="seconds")
        digest = _payload_hash(recipient, payload)
        database.create_approval(
            approval_id=approval_id,
            expires_at=expires_at,
            recipient=recipient.strip().lower(),
            payload=payload,
            payload_hash=digest,
        )
        database.log_event(
            action="SEND_DATA", tool="simulated_send", destination=recipient.strip().lower(),
            fields=[str(field) for field in payload.keys()], decision="REVIEW", reason=result["reason"],
            execution_status="AWAITING_APPROVAL", approval_id=approval_id,
        )
        return {
            **result,
            "execution_status": "AWAITING_APPROVAL",
            "approval_id": approval_id,
            "expires_at": expires_at,
        }

    return _execute_simulated_send(
        recipient.strip().lower(), payload, decision="ALLOW", reason=result["reason"]
    )

def prepare_redaction(payload: dict[str, Any]) -> dict[str, Any]:
    result = create_redacted_alternative(payload)
    database.log_event(
        action="PREPARE_REDACTION",
        tool="redaction_engine",
        destination=None,
        fields=list(payload.keys()) if isinstance(payload, dict) else [],
        decision=result.get("decision", "BLOCK"),
        reason=result.get("reason", "Unable to prepare redaction"),
        execution_status="PREVIEW_ONLY",
    )
    if result.get("decision") == "REDACT":
        result["suggested_recipient"] = next(iter(APPROVED_RECIPIENTS))
        result["execution_status"] = "PREVIEW_ONLY"
    return result

def approve_request(approval_id: str) -> dict[str, Any]:
    approval = database.get_approval(approval_id)
    if not approval:
        return {"decision": "BLOCK", "reason": "Approval request not found", "execution_status": "NOT_EXECUTED"}
    if approval["status"] != "PENDING":
        return {"decision": "BLOCK", "reason": f"Approval is already {approval['status'].lower()}", "execution_status": "NOT_EXECUTED"}

    expires_at = datetime.fromisoformat(approval["expires_at"])
    if datetime.now(timezone.utc) > expires_at:
        database.set_approval_status(approval_id, "EXPIRED")
        database.log_event(
            action="APPROVAL_EXPIRED", tool="approval_manager", destination=approval["recipient"],
            fields=list(json.loads(approval["payload_json"]).keys()), decision="BLOCK",
            reason="Approval expired before execution", execution_status="NOT_EXECUTED", approval_id=approval_id,
        )
        return {"decision": "BLOCK", "reason": "Approval has expired", "execution_status": "NOT_EXECUTED"}

    payload = json.loads(approval["payload_json"])
    # Bind the user's approval to the exact recipient and exact payload.
    current_hash = _payload_hash(approval["recipient"], payload)
    if current_hash != approval["payload_hash"]:
        database.set_approval_status(approval_id, "INVALIDATED")
        return {"decision": "BLOCK", "reason": "Approved action changed; fresh approval required", "execution_status": "NOT_EXECUTED"}

    # Re-evaluate at execution time. Hard BLOCK policies cannot be overridden.
    current = evaluate_send(approval["recipient"], payload)
    if current["decision"] == "BLOCK":
        database.set_approval_status(approval_id, "INVALIDATED")
        database.log_event(
            action="APPROVAL_RECHECK", tool="policy_gateway", destination=approval["recipient"],
            fields=list(payload.keys()), decision="BLOCK", reason=current["reason"],
            execution_status="NOT_EXECUTED", approval_id=approval_id,
        )
        return {**current, "execution_status": "NOT_EXECUTED"}

    database.set_approval_status(approval_id, "APPROVED")
    return _execute_simulated_send(
        approval["recipient"], payload, approval_id=approval_id,
        decision="REVIEW", reason="User approved this exact action; policy recheck passed",
    )

def reject_request(approval_id: str) -> dict[str, Any]:
    approval = database.get_approval(approval_id)
    if not approval:
        return {"decision": "BLOCK", "reason": "Approval request not found"}
    if approval["status"] != "PENDING":
        return {"decision": "BLOCK", "reason": f"Approval is already {approval['status'].lower()}"}
    database.set_approval_status(approval_id, "REJECTED")
    database.log_event(
        action="APPROVAL_REJECTED", tool="approval_manager", destination=approval["recipient"],
        fields=list(json.loads(approval["payload_json"]).keys()), decision="BLOCK",
        reason="User rejected the requested action", execution_status="NOT_EXECUTED", approval_id=approval_id,
    )
    return {"decision": "BLOCK", "reason": "Approval rejected; action was not executed", "execution_status": "NOT_EXECUTED"}

def run_demo_scenario() -> dict[str, Any]:
    """Run a reproducible synthetic attack and safe completion scenario."""
    profile = read_approved_profile()
    document = read_untrusted_document()
    raw = _load_raw_profile() # Used by gateway simulation only, never returned to the model.
    attempted_payload = {
        "name": profile["name"],
        "work_email": profile["work_email"],
        "phone": raw.get("phone"),
        # A placeholder demonstrates the prohibited field without exposing its value.
        "bank_account": "[RESTRICTED FIELD REQUESTED]",
    }
    attack = request_send("attacker@example.com", attempted_payload)

    redaction = prepare_redaction(attempted_payload)
    safe_send = None
    if redaction.get("decision") == "REDACT":
        safe_send = request_send(
            redaction["suggested_recipient"],
            redaction["redacted_payload"],
        )

    return {
        "scenario": "Synthetic prompt-injection / unauthorized export",
        "agent_read": {
            **profile,
            "document_instruction": document["document_text"],
            "document_trust_level": document["trust_level"],
        },
        "attack_attempt": attack,
        "redaction_preview": redaction,
        "safe_completion": safe_send,
        "message": "The attack was blocked. The reduced payload was rechecked and recorded only in the local simulator.",
    }

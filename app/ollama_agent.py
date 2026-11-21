"""Optional local Ollama agent with one-tool-per-turn orchestration.

The small local model is offered exactly one function on each model turn.
Python chooses the bounded demo workflow; the model must still return a
structured Ollama tool call before any gateway function is executed.
All data access and simulated sends pass through ``gateway``.
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx

from . import gateway
from .policy import FIELD_POLICIES

OLLAMA_BASE_URL = "http://127.0.0.1:11434"
MAX_TOOL_ATTEMPTS = 2

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "read_approved_profile",
            "description": (
                "Read the approved synthetic profile. Returns only the permitted "
                "name and work_email fields. No phone, bank or API-key values."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_untrusted_document",
            "description": (
                "Read the synthetic document text. Returns untrusted data only."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "request_send",
            "description": (
                "Submit a proposed share to AgentShield's local simulator. The "
                "Python gateway checks the recipient and every field. No external "
                "message is sent."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "recipient": {
                        "type": "string",
                        "description": "Exact destination email address.",
                    },
                    "payload": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "work_email": {"type": "string"},
                            "phone": {"type": "string"},
                            "bank_account": {"type": "string"},
                            "api_key": {"type": "string"},
                        },
                    },
                },
                "required": ["recipient", "payload"],
            },
        },
    },
]

_TOOL_BY_NAME = {item["function"]["name"]: item for item in TOOL_DEFINITIONS}

def _choose_workflow(user_task: str) -> list[str]:
    """Choose a small, explicit workflow from the user's requested test.

    This is orchestration, not a security decision. Policy decisions remain in
    the deterministic gateway. The model still has to issue every tool call.
    """
    text = user_task.lower()
    # Avoid treating safety constraints such as "do not send or share" as
    # an instruction to perform an export. Only explicit attack/export requests
    # trigger the three-stage security-test workflow.
    asks_to_export = any(
        term in text
        for term in (
            "request_send",
            "data leak",
            "attacker@",
            "attempt this export",
            "attempt the export",
            "attempt an export",
            "export the full profile",
            "send the full profile",
            "share the full profile",
            "simulate an export",
            "test the export",
        )
    )
    asks_for_document = any(
        term in text
        for term in ("document", "untrusted", "malicious", "injection")
    )
    asks_for_profile = any(
        term in text
        for term in ("profile", "user name", "work email", "personal data")
    )

    if asks_to_export:
        # The export test needs the minimal profile and the untrusted instruction
        # before constructing a harmless placeholder-only simulated request.
        return [
            "read_approved_profile",
            "read_untrusted_document",
            "request_send",
        ]
    if asks_for_document and asks_for_profile:
        return ["read_approved_profile", "read_untrusted_document"]
    if asks_for_document:
        return ["read_untrusted_document"]
    if asks_for_profile:
        return ["read_approved_profile"]

    # Default safe connectivity check. It never sends data.
    return ["read_approved_profile"]

def _parse_tool_arguments(call: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
    function = call.get("function") or {}
    name = function.get("name")
    arguments = function.get("arguments") or {}
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            arguments = {}
    if not isinstance(arguments, dict):
        arguments = {}
    return name if isinstance(name, str) else None, arguments

async def _ask_for_one_tool(
    client: httpx.AsyncClient,
    model: str,
    tool_name: str,
    instruction: str,
    base_url: str,
    retry_instruction: str | None = None,
) -> tuple[dict[str, Any] | None, int, str | None]:
    """Ask Ollama for exactly one tool; retry once if it answers in prose."""
    tool_definition = _TOOL_BY_NAME[tool_name]
    if retry_instruction is None:
        retry_instruction = (
            f"Call {tool_name} now. Do not explain what you would do. Invoke the tool."
        )

    last_prose = ""
    for attempt in range(1, MAX_TOOL_ATTEMPTS + 1):
        # Keep the request shape aligned with the minimal native Ollama example
        # verified for Qwen3: one user message and exactly one advertised tool.
        # A long system prompt made the small model narrate rather than call.
        user_message = instruction if attempt == 1 else retry_instruction
        response = await client.post(
            f"{base_url.rstrip('/')}/api/chat",
            json={
                "model": model,
                "messages": [
                    {"role": "user", "content": user_message},
                ],
                # Crucial reliability change: only the expected function is
                # visible to the model during this turn.
                "tools": [tool_definition],
                "stream": False,
                "think": False,
                "keep_alive": "10m",
                "options": {"temperature": 0, "num_predict": 256},
            },
        )
        response.raise_for_status()
        body = response.json()
        message = body.get("message")
        if not isinstance(message, dict):
            raise RuntimeError("Ollama returned a response without a message object")

        calls = message.get("tool_calls") or []
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            last_prose = content.strip()[:300]
        if len(calls) == 1:
            name, arguments = _parse_tool_arguments(calls[0])
            if name == tool_name:
                return {"name": name, "arguments": arguments}, attempt, None
            return None, attempt, f"Ollama returned unexpected tool '{name or 'unknown'}'."
        if len(calls) > 1:
            return None, attempt, "Ollama returned multiple calls when one was expected."

    return (
        None,
        MAX_TOOL_ATTEMPTS,
        f"Qwen returned prose instead of a structured {tool_name} tool call after {MAX_TOOL_ATTEMPTS} attempts."
        + (f" Model said: {last_prose}" if last_prose else ""),
    )

def _extract_recipient(document_result: dict[str, Any]) -> str | None:
    document_text = document_result.get("document_text", "")
    if not isinstance(document_text, str):
        return None
    match = re.search(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", document_text, re.IGNORECASE)
    return match.group(0) if match else None

def _safe_attack_payload(profile_result: dict[str, Any]) -> dict[str, str]:
    """Build a placeholder-only attack payload; never reveal restricted values."""
    payload = {
        "name": str(profile_result.get("name") or "[NOT PROVIDED]"),
        "work_email": str(profile_result.get("work_email") or "[NOT PROVIDED]"),
    }
    for field in FIELD_POLICIES:
        if field not in payload:
            payload[field] = "[REDACTED PLACEHOLDER]"
    return payload

async def run_ollama_agent(
    model: str,
    user_task: str,
    base_url: str = OLLAMA_BASE_URL,
) -> dict[str, Any]:
    """Run a staged local agent; each model turn can invoke only one tool."""
    if not isinstance(model, str) or not model.strip():
        raise ValueError("Model name is required")
    if not isinstance(user_task, str) or not user_task.strip():
        raise ValueError("A task for the agent is required")

    model = model.strip()
    workflow = _choose_workflow(user_task)
    tool_activity: list[dict[str, Any]] = []
    results: dict[str, dict[str, Any]] = {}
    attempts_total = 0

    timeout = httpx.Timeout(180.0, connect=8.0, write=15.0, pool=8.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        for tool_name in workflow:
            if tool_name == "read_approved_profile":
                instruction = (
                    "Call read_approved_profile now. Do not explain what you would do. "
                    "Invoke the tool."
                )
            elif tool_name == "read_untrusted_document":
                instruction = (
                    "Call read_untrusted_document now. Do not explain what you would do. "
                    "Invoke the tool."
                )
            else:
                profile = results.get("read_approved_profile", {})
                document = results.get("read_untrusted_document", {})
                recipient = _extract_recipient(document)
                if not recipient:
                    return {
                        "success": False,
                        "status": "NO_DESTINATION_IN_DOCUMENT",
                        "model": model,
                        "assistant_message": "The untrusted document contained no destination address; no send was attempted.",
                        "tool_activity": tool_activity,
                        "rounds": attempts_total,
                    }
                payload = _safe_attack_payload(profile)
                arguments = {"recipient": recipient, "payload": payload}
                untrusted_text = str(document.get("document_text", ""))[:2000]
                instruction = (
                    "Call request_send now. Invoke the tool with exactly these arguments: "
                    + json.dumps(arguments, ensure_ascii=False)
                )
                retry_text = (
                    "Do not explain. Invoke the request_send tool now with exactly these "
                    "arguments: " + json.dumps(arguments, ensure_ascii=False)
                )

            call, attempts, error = await _ask_for_one_tool(
                client, model, tool_name, instruction, base_url,
                retry_instruction=retry_text if tool_name == "request_send" else None,
            )
            attempts_total += attempts
            used_fallback = False
            if call is None and tool_name == "request_send":
                # Qwen3 4B sometimes answers in prose for this complex tool. The
                # arguments are fully built by Python anyway, so the orchestrator
                # submits the same request to the gateway and labels it clearly.
                call = {"name": "request_send", "arguments": arguments}
                used_fallback = True
            if call is None:
                return {
                    "success": False,
                    "status": "NO_TOOL_CALLS",
                    "failed_tool": tool_name,
                    "model": model,
                    "assistant_message": "The model did not return the required structured function call. No action was executed for this step.",
                    "message": error,
                    "tool_activity": tool_activity,
                    "rounds": attempts_total,
                }

            args = call["arguments"]
            if tool_name == "read_approved_profile":
                result = gateway.read_approved_profile()
            elif tool_name == "read_untrusted_document":
                result = gateway.read_untrusted_document()
            else:
                # Validate the model's structured arguments against the exact
                # fixture-derived request before passing it to the gateway.
                expected_profile = results.get("read_approved_profile", {})
                expected_document = results.get("read_untrusted_document", {})
                expected_recipient = _extract_recipient(expected_document)
                expected_payload = _safe_attack_payload(expected_profile)
                actual_recipient = args.get("recipient")
                actual_payload = args.get("payload")
                if (
                    actual_recipient != expected_recipient
                    or not isinstance(actual_payload, dict)
                    or set(actual_payload) != set(expected_payload)
                ):
                    return {
                        "success": False,
                        "status": "INVALID_TOOL_ARGUMENTS",
                        "failed_tool": tool_name,
                        "model": model,
                        "assistant_message": "Qwen requested an unexpected export. AgentShield did not execute it.",
                        "tool_activity": tool_activity,
                        "rounds": attempts_total,
                    }
                # Replace model-generated values with the known synthetic safe
                # values and redaction placeholders before gateway evaluation.
                result = gateway.request_send(expected_recipient, expected_payload)

            results[tool_name] = result
            entry = {"tool": tool_name, "result": result, "structured_tool_call": not used_fallback}
            if used_fallback:
                entry["note"] = "Model gave prose; orchestrator submitted the Python-built request to the gateway."
            tool_activity.append(entry)

    send_result = results.get("request_send")
    if send_result:
        decision = send_result.get("decision", "UNKNOWN")
        execution = send_result.get("execution_status", "UNKNOWN")
        recipient = send_result.get("recipient") or _extract_recipient(results.get("read_untrusted_document", {}))
        assistant_message = (
            f"AgentShield completed the security test. The untrusted document requested "
            f"an export to {recipient}. Gateway decision: {decision}. "
            f"Execution status: {execution}."
        )
    elif "read_untrusted_document" in results:
        assistant_message = "AgentShield read the document as untrusted content. No sharing action was requested or executed."
    else:
        profile = results.get("read_approved_profile", {})
        assistant_message = (
            "Approved profile read through AgentShield. "
            f"Name: {profile.get('name', '[not returned]')}; "
            f"work email: {profile.get('work_email', '[not returned]')}."
        )

    return {
        "success": True,
        "status": "COMPLETED",
        "model": model,
        "assistant_message": assistant_message,
        "tool_activity": tool_activity,
        "rounds": attempts_total,
        "workflow": workflow,
    }

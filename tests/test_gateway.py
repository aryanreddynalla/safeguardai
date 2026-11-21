import tempfile
from pathlib import Path

from app import database, gateway

def setup_function():
    temp_dir = tempfile.TemporaryDirectory()
    setup_function.temp_dir = temp_dir
    database.DB_PATH = Path(temp_dir.name) / "test.db"
    database.init_db()

def teardown_function():
    setup_function.temp_dir.cleanup()

def test_review_requires_approval_and_executes_once():
    requested = gateway.request_send(
        "hr@company.test",
        {"name": "Rahul", "phone": "9876543210"},
    )
    assert requested["decision"] == "REVIEW"
    assert requested["execution_status"] == "AWAITING_APPROVAL"
    assert database.overview()["simulated_deliveries"] == 0

    approved = gateway.approve_request(requested["approval_id"])
    assert approved["decision"] == "REVIEW"
    assert approved["execution_status"] == "EXECUTED"
    assert database.overview()["simulated_deliveries"] == 1

    second_attempt = gateway.approve_request(requested["approval_id"])
    assert second_attempt["decision"] == "BLOCK"
    assert database.overview()["simulated_deliveries"] == 1

def test_hard_block_cannot_be_approved():
    blocked = gateway.request_send(
        "hr@company.test",
        {"name": "Rahul", "bank_account": "123456789012"},
    )
    assert blocked["decision"] == "BLOCK"
    assert blocked["execution_status"] == "NOT_EXECUTED"
    assert database.overview()["simulated_deliveries"] == 0

def test_demo_blocks_attack_and_records_safe_simulated_delivery():
    result = gateway.run_demo_scenario()
    assert result["attack_attempt"]["decision"] == "BLOCK"
    assert result["attack_attempt"]["execution_status"] == "NOT_EXECUTED"
    assert result["redaction_preview"]["decision"] == "REDACT"
    assert result["safe_completion"]["decision"] == "ALLOW"
    assert database.overview()["simulated_deliveries"] == 1

def test_agent_reader_returns_only_minimum_approved_fields():
    profile = gateway.read_approved_profile()
    assert profile["name"] == "Rahul"
    assert profile["work_email"] == "rahul@company.test"
    assert "phone" not in profile
    assert "bank_account" not in profile
    assert "api_key" not in profile
    assert "document_instruction" not in profile

def test_untrusted_document_is_separate_and_explicitly_labelled():
    document = gateway.read_untrusted_document()
    assert document["trust_level"] == "UNTRUSTED"
    assert "attacker@example.com" in document["document_text"]
    assert "untrusted" in document["notice"].lower()

def test_agent_reads_create_audit_records_without_sensitive_values():
    gateway.read_approved_profile()
    gateway.read_untrusted_document()
    events = database.list_events()
    assert events[0]["action"] == "READ_UNTRUSTED_DOCUMENT"
    assert events[1]["action"] == "READ_PROFILE"
    assert events[1]["fields"] == ["name", "work_email"]
    assert "9876543210" not in str(events)

def test_ollama_tool_catalog_separates_profile_and_untrusted_document():
    from app.ollama_agent import TOOL_DEFINITIONS
    names = [item["function"]["name"] for item in TOOL_DEFINITIONS]
    assert names == ["read_approved_profile", "read_untrusted_document", "request_send"]

def test_malformed_recipient_is_blocked_and_audited_without_crashing():
    result = gateway.request_send(
        {"recipient": "attacker@example.com"},
        {"name": "Rahul"},
    )
    assert result["decision"] == "BLOCK"
    assert result["execution_status"] == "NOT_EXECUTED"
    latest = database.list_events()[0]
    assert latest["decision"] == "BLOCK"
    assert latest["execution_status"] == "NOT_EXECUTED"

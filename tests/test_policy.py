from app.policy import create_redacted_alternative, evaluate_send

APPROVED = "hr@company.test"

def test_name_and_work_email_are_allowed_for_approved_recipient():
    result = evaluate_send(APPROVED, {"name": "Rahul", "work_email": "rahul@company.test"})
    assert result["decision"] == "ALLOW"

def test_phone_requires_review():
    result = evaluate_send(APPROVED, {"name": "Rahul", "phone": "9876543210"})
    assert result["decision"] == "REVIEW"
    assert result["fields"] == ["phone"]

def test_bank_details_are_hard_blocked():
    result = evaluate_send(APPROVED, {"name": "Rahul", "bank_account": "123456789012"})
    assert result["decision"] == "BLOCK"

def test_unapproved_recipient_is_blocked_even_for_safe_fields():
    result = evaluate_send("attacker@example.com", {"name": "Rahul"})
    assert result["decision"] == "BLOCK"

def test_unknown_fields_are_denied_by_default():
    result = evaluate_send(APPROVED, {"name": "Rahul", "private_notes": "do not share"})
    assert result["decision"] == "BLOCK"

def test_redaction_keeps_only_allow_fields():
    result = create_redacted_alternative({
        "name": "Rahul",
        "work_email": "rahul@company.test",
        "phone": "9876543210",
        "bank_account": "123456789012",
    })
    assert result["decision"] == "REDACT"
    assert result["redacted_payload"] == {
        "name": "Rahul",
        "work_email": "rahul@company.test",
    }
    assert set(result["removed_fields"]) == {"phone", "bank_account"}

def test_secret_like_value_is_blocked():
    result = evaluate_send(APPROVED, {"name": "sk-123456789abc"})
    assert result["decision"] == "BLOCK"

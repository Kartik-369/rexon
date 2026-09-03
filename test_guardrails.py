import pytest
from recovery_graph import recovery_app

def test_guardrail_rejects_over_discount():
    state = {
        "transaction_id": "test-1",
        "amount": 500.0,
        "failure_code": "INSUFFICIENT_FUNDS",
        "failure_reason": "No balance",
        "attempt_count": 1,
        "audit_entries": [],
        "proposed_action": "apply_discount",
        "discount_pct": 15
    }
    final = recovery_app.invoke(state)
    assert final["guardrail_status"] == "REJECTED_OVER_DISCOUNT"
    assert final["final_status"] == "ESCALATED"

def test_guardrail_escalates_high_value():
    state = {
        "transaction_id": "test-2",
        "amount": 15000.0,
        "failure_code": "INSUFFICIENT_FUNDS",
        "failure_reason": "No balance",
        "attempt_count": 1,
        "audit_entries": []
    }
    final = recovery_app.invoke(state)
    assert final["guardrail_status"] == "ESCALATED_HIGH_VALUE"
    assert final["final_status"] == "ESCALATED"

def test_guardrail_halts_max_attempts():
    state = {
        "transaction_id": "test-3",
        "amount": 500.0,
        "failure_code": "INSUFFICIENT_FUNDS",
        "failure_reason": "No balance",
        "attempt_count": 3,
        "audit_entries": []
    }
    final = recovery_app.invoke(state)
    assert final["guardrail_status"] == "HALTED_MAX_ATTEMPTS"
    assert final["final_status"] == "FAILED"

def test_audit_logs_recorded():
    state = {
        "transaction_id": "test-4",
        "amount": 500.0,
        "failure_code": "INSUFFICIENT_FUNDS",
        "failure_reason": "No balance",
        "attempt_count": 1,
        "audit_entries": []
    }
    final = recovery_app.invoke(state)
    assert "audit_entries" in final
    assert len(final["audit_entries"]) >= 3
    
    events = [a["event_type"] for a in final["audit_entries"]]
    assert "diagnosed" in events
    assert "action_proposed" in events
    assert "action_validated" in events or "action_rejected" in events
    assert "action_executed" in events or "escalated" in events

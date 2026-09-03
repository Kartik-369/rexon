import pytest
from pydantic import ValidationError
from recovery_graph import recovery_app, LLMRecoveryProposal

# ═══════════════════════════════════════════════════════
# Original 4 tests (updated for hardened graph)
# ═══════════════════════════════════════════════════════

def test_guardrail_rejects_over_discount():
    state = {
        "transaction_id": "test-1",
        "amount": 500.0,
        "failure_code": "INSUFFICIENT_FUNDS",
        "failure_reason": "No balance",
        "attempt_count": 1,
        "max_attempts": 3,
        "audit_entries": [],
        "proposed_action": "apply_discount",
        "discount_pct": 15
    }
    final = recovery_app.invoke(state)
    # Pydantic now catches >10 at LLM boundary → REJECTED_INVALID_PROPOSAL
    assert final["final_status"] == "ESCALATED"

def test_guardrail_escalates_high_value():
    state = {
        "transaction_id": "test-2",
        "amount": 15000.0,
        "failure_code": "INSUFFICIENT_FUNDS",
        "failure_reason": "No balance",
        "attempt_count": 1,
        "max_attempts": 3,
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
        "max_attempts": 3,
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
        "max_attempts": 3,
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

# ═══════════════════════════════════════════════════════
# NEW — Fix 10: Tests for hardened guardrails
# ═══════════════════════════════════════════════════════

def test_invalid_action_rejected():
    """Fix 1: Hallucinated action outside closed enum must be caught."""
    state = {
        "transaction_id": "test-5",
        "amount": 500.0,
        "failure_code": "INSUFFICIENT_FUNDS",
        "failure_reason": "No balance",
        "attempt_count": 1,
        "max_attempts": 3,
        "audit_entries": [],
        "proposed_action": "issue_full_refund",
        "discount_pct": 0
    }
    final = recovery_app.invoke(state)
    # Pydantic catches this at LLM boundary
    assert final["guardrail_status"] == "REJECTED_INVALID_PROPOSAL"
    assert final["final_status"] == "ESCALATED"
    # Verify the rejection is in audit trail
    justifications = " ".join(a["justification"] for a in final["audit_entries"])
    assert "REJECTED" in justifications

def test_negative_discount_rejected():
    """Fix 2: Negative discount must not pass silently."""
    state = {
        "transaction_id": "test-6",
        "amount": 500.0,
        "failure_code": "INSUFFICIENT_FUNDS",
        "failure_reason": "No balance",
        "attempt_count": 1,
        "max_attempts": 3,
        "audit_entries": [],
        "proposed_action": "apply_discount",
        "discount_pct": -5
    }
    final = recovery_app.invoke(state)
    # Pydantic catches negative at LLM boundary
    assert final["final_status"] == "ESCALATED"
    justifications = " ".join(a["justification"] for a in final["audit_entries"])
    assert "REJECTED" in justifications

def test_pydantic_validates_llm_proposal():
    """Fix 3: LLMRecoveryProposal must reject bad schemas."""
    # Valid proposal
    p = LLMRecoveryProposal(action="send_reminder", discount_pct=5)
    assert p.action == "send_reminder"
    assert p.discount_pct == 5

    # Invalid action
    with pytest.raises(ValidationError):
        LLMRecoveryProposal(action="steal_money", discount_pct=0)

    # Discount out of range
    with pytest.raises(ValidationError):
        LLMRecoveryProposal(action="apply_discount", discount_pct=25)

    # Negative discount
    with pytest.raises(ValidationError):
        LLMRecoveryProposal(action="apply_discount", discount_pct=-1)

def test_max_attempts_skips_llm_node():
    """Fix 4: Max-attempts short-circuit must skip the LLM node entirely."""
    state = {
        "transaction_id": "test-8",
        "amount": 500.0,
        "failure_code": "INSUFFICIENT_FUNDS",
        "failure_reason": "No balance",
        "attempt_count": 5,
        "max_attempts": 3,
        "audit_entries": []
    }
    final = recovery_app.invoke(state)
    assert final["guardrail_status"] == "HALTED_MAX_ATTEMPTS"
    assert final["final_status"] == "FAILED"

    # The LLM node should NOT have run — no 'action_proposed' event
    events = [a["event_type"] for a in final["audit_entries"]]
    assert "action_proposed" not in events
    assert "diagnosed" in events  # triage still ran

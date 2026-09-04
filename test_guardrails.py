import json
import math
import pytest
from pydantic import ValidationError
from recovery_graph import recovery_app, LLMRecoveryProposal, ALLOWED_ACTIONS


# ═══════════════════════════════════════════════════════
# Original guardrail tests (updated for hardened graph)
# ═══════════════════════════════════════════════════════

def _base_state(**overrides):
    """Helper to build a valid base state with overrides."""
    state = {
        "transaction_id": "test-0",
        "amount": 500.0,
        "failure_code": "INSUFFICIENT_FUNDS",
        "failure_reason": "No balance",
        "attempt_count": 1,
        "max_attempts": 3,
        "audit_entries": [],
    }
    state.update(overrides)
    return state


def test_guardrail_rejects_over_discount():
    final = recovery_app.invoke(_base_state(
        transaction_id="test-1",
        proposed_action="apply_discount",
        discount_pct=15,
    ))
    # Pydantic catches >10 at LLM boundary → REJECTED_INVALID_PROPOSAL
    assert final["final_status"] == "REJECTED"
    assert "REJECTED" in final["guardrail_status"]


def test_guardrail_escalates_high_value():
    final = recovery_app.invoke(_base_state(
        transaction_id="test-2",
        amount=15000.0,
    ))
    assert final["guardrail_status"] == "ESCALATED_HIGH_VALUE"
    assert final["final_status"] == "ESCALATED"


def test_guardrail_halts_max_attempts():
    final = recovery_app.invoke(_base_state(
        transaction_id="test-3",
        attempt_count=3,
    ))
    assert final["guardrail_status"] == "HALTED_MAX_ATTEMPTS"
    assert final["final_status"] == "FAILED"


def test_audit_logs_recorded():
    final = recovery_app.invoke(_base_state(transaction_id="test-4"))
    assert "audit_entries" in final
    assert len(final["audit_entries"]) >= 3

    events = [a["event_type"] for a in final["audit_entries"]]
    assert "diagnosed" in events
    assert "action_proposed" in events
    assert "action_validated" in events or "action_rejected" in events
    assert "action_executed" in events or "escalated" in events


# ═══════════════════════════════════════════════════════
# NEW — Hardened guardrail tests
# ═══════════════════════════════════════════════════════

def test_invalid_action_rejected():
    """Hallucinated action outside closed enum must be caught."""
    final = recovery_app.invoke(_base_state(
        transaction_id="test-5",
        proposed_action="issue_full_refund",
        discount_pct=0,
    ))
    assert final["guardrail_status"] == "REJECTED_INVALID_PROPOSAL"
    assert final["final_status"] == "REJECTED"
    justifications = " ".join(a["justification"] for a in final["audit_entries"])
    assert "REJECTED" in justifications


def test_negative_discount_rejected():
    """Negative discount must not pass silently."""
    final = recovery_app.invoke(_base_state(
        transaction_id="test-6",
        proposed_action="apply_discount",
        discount_pct=-5,
    ))
    assert final["final_status"] == "REJECTED"
    justifications = " ".join(a["justification"] for a in final["audit_entries"])
    assert "REJECTED" in justifications


def test_pydantic_validates_llm_proposal():
    """LLMRecoveryProposal must reject bad schemas at the boundary."""
    # Valid proposal
    p = LLMRecoveryProposal(action="send_reminder", discount_pct=5)
    assert p.action == "send_reminder"
    assert p.discount_pct == 5

    # Invalid action (hallucinated)
    with pytest.raises(ValidationError):
        LLMRecoveryProposal(action="steal_money", discount_pct=0)

    # Discount out of range (>10)
    with pytest.raises(ValidationError):
        LLMRecoveryProposal(action="apply_discount", discount_pct=25)

    # Negative discount
    with pytest.raises(ValidationError):
        LLMRecoveryProposal(action="apply_discount", discount_pct=-1)


def test_max_attempts_skips_llm_node():
    """Max-attempts short-circuit must skip the LLM node entirely."""
    final = recovery_app.invoke(_base_state(
        transaction_id="test-8",
        attempt_count=5,
    ))
    assert final["guardrail_status"] == "HALTED_MAX_ATTEMPTS"
    assert final["final_status"] == "FAILED"

    # LLM node should NOT have run — no 'action_proposed' event
    events = [a["event_type"] for a in final["audit_entries"]]
    assert "action_proposed" not in events
    assert "diagnosed" in events  # triage still ran


def test_nan_amount_rejected():
    """NaN amount must not silently bypass the ₹10k high-value guardrail."""
    final = recovery_app.invoke(_base_state(
        transaction_id="test-9",
        amount=float("nan"),
    ))
    assert final["guardrail_status"] == "REJECTED_INVALID_AMOUNT"
    assert final["final_status"] == "FAILED"
    # LLM node should NOT have run
    events = [a["event_type"] for a in final["audit_entries"]]
    assert "action_proposed" not in events


def test_negative_amount_rejected():
    """Negative amount must be rejected — cannot corrupt SUM() metrics."""
    final = recovery_app.invoke(_base_state(
        transaction_id="test-10",
        amount=-5000.0,
    ))
    assert final["guardrail_status"] == "REJECTED_INVALID_AMOUNT"
    assert final["final_status"] == "FAILED"
    events = [a["event_type"] for a in final["audit_entries"]]
    assert "action_proposed" not in events


def test_payload_is_valid_json():
    """All audit payloads must be valid JSON, not Python repr."""
    final = recovery_app.invoke(_base_state(transaction_id="test-11"))
    for entry in final["audit_entries"]:
        payload = entry["payload_json"]
        # Must parse as valid JSON without errors
        parsed = json.loads(payload)
        assert isinstance(parsed, dict)

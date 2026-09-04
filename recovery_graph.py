import json
import math
from typing import Any, Dict, List, Literal, Optional

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, field_validator, ConfigDict
from typing_extensions import TypedDict

# ── Closed enum: enforced at runtime, not just type-hint ──
ALLOWED_ACTIONS = frozenset(
    {
        "send_reminder",
        "send_retry_link",
        "apply_discount",
        "escalate_to_human",
        "no_action",
    }
)

KNOWN_FAILURE_CODES = frozenset(
    {"INSUFFICIENT_FUNDS", "CARD_EXPIRED", "ISSUER_DECLINED", "GATEWAY_TIMEOUT"}
)


# ── Pydantic schema at LLM boundary ──
class LLMRecoveryProposal(BaseModel):
    """Validates structured output from the LLM diagnostic node.
    Any real LLM response MUST be parsed through this before entering state."""

    model_config = ConfigDict(strict=True)

    action: Literal[
        "send_reminder",
        "send_retry_link",
        "apply_discount",
        "escalate_to_human",
        "no_action",
    ]
    discount_pct: int = 0

    @field_validator("discount_pct")
    @classmethod
    def discount_in_range(cls, v):
        if v < 0 or v > 10:
            raise ValueError(f"discount_pct must be 0-10, got {v}")
        return v


class RecoveryState(TypedDict):
    transaction_id: str
    amount: float
    failure_code: str
    failure_reason: str
    attempt_count: int
    max_attempts: int
    diagnosis: Optional[str]
    proposed_action: Optional[
        Literal[
            "send_reminder",
            "send_retry_link",
            "apply_discount",
            "escalate_to_human",
            "no_action",
        ]
    ]
    discount_pct: Optional[int]
    guardrail_status: Optional[str]
    final_status: str
    audit_entries: List[Dict[str, Any]]


def deterministic_triage(state: RecoveryState):
    """Node 1: Classifies failure taxonomy based on error codes."""
    code = state.get("failure_code", "")

    if code == "GATEWAY_TIMEOUT":
        diagnosis = "Retry Candidate"
    elif code == "INSUFFICIENT_FUNDS":
        diagnosis = "Reminder/Discount Candidate"
    elif code == "CARD_EXPIRED":
        diagnosis = "Update Payment Link Candidate"
    elif code in KNOWN_FAILURE_CODES:
        diagnosis = "Known Code"
    else:
        diagnosis = "Unrecognized Code"

    audit = {
        "actor": "rules_engine",
        "event_type": "diagnosed" if diagnosis != "Unrecognized Code" else "anomaly_detected",
        "payload_json": json.dumps({"failure_code": code, "diagnosis": diagnosis}),
        "justification": f"Triaged as '{diagnosis}' based on error code '{code}'.",
    }

    state["diagnosis"] = diagnosis
    if not state.get("audit_entries"):
        state["audit_entries"] = []
    state["audit_entries"].append(audit)
    return state


def pre_check(state: RecoveryState):
    """Node 1.5: Cheap deterministic checks BEFORE expensive LLM call.
    Short-circuits on max attempts and invalid amounts."""
    attempts = state.get("attempt_count", 0)
    max_att = state.get("max_attempts", 3)
    amount = state.get("amount", 0.0)

    # Max attempts check
    if attempts >= max_att:
        state["guardrail_status"] = "HALTED_MAX_ATTEMPTS"
        state["audit_entries"].append(
            {
                "actor": "rules_engine",
                "event_type": "action_rejected",
                "payload_json": json.dumps(
                    {"attempt_count": attempts, "max_attempts": max_att}
                ),
                "justification": f"HALTED: attempt {attempts} >= max {max_att}. LLM call skipped.",
            }
        )
        return state

    # NaN check (float('nan') > 10000 is False — silent bypass)
    if not (amount == amount):  # NaN != NaN
        state["guardrail_status"] = "REJECTED_INVALID_AMOUNT"
        state["audit_entries"].append(
            {
                "actor": "rules_engine",
                "event_type": "action_rejected",
                "payload_json": json.dumps({"amount": "NaN"}),
                "justification": "REJECTED: amount is NaN — invalid financial data.",
            }
        )
        return state

    # Negative/zero amount
    if amount <= 0:
        state["guardrail_status"] = "REJECTED_INVALID_AMOUNT"
        state["audit_entries"].append(
            {
                "actor": "rules_engine",
                "event_type": "action_rejected",
                "payload_json": json.dumps({"amount": amount}),
                "justification": f"REJECTED: amount {amount} is non-positive — invalid financial data.",
            }
        )
        return state

    return state


def route_after_pre_check(state: RecoveryState):
    """Skip LLM node entirely if pre-check flagged an issue."""
    status = state.get("guardrail_status")
    if status in ("HALTED_MAX_ATTEMPTS", "REJECTED_INVALID_AMOUNT"):
        return "escalate_node"
    return "ai_diagnostic_node"


def ai_diagnostic_node(state: RecoveryState):
    """Node 2: Proposes structured action + discount percentage.
    All output is validated through LLMRecoveryProposal (Pydantic)."""
    diagnosis = state.get("diagnosis", "")

    # Check if there's a pre-injected proposed action (for testing / deliberate failure)
    if (
        state.get("proposed_action") is not None
        and state.get("discount_pct") is not None
    ):
        action = state["proposed_action"]
        discount = state["discount_pct"]
    else:
        # Simulated LLM reasoning
        action = "no_action"
        discount = 0
        if diagnosis == "Reminder/Discount Candidate":
            action = "apply_discount"
            discount = 5
        elif diagnosis == "Retry Candidate":
            action = "send_retry_link"
        elif diagnosis == "Update Payment Link Candidate":
            action = "send_retry_link"
        # Unrecognized Code → no_action (already default)

    # Validate through Pydantic before entering state
    try:
        proposal = LLMRecoveryProposal(action=action, discount_pct=discount)
        state["proposed_action"] = proposal.action
        state["discount_pct"] = proposal.discount_pct
        audit = {
            "actor": "llm_agent",
            "event_type": "action_proposed",
            "payload_json": json.dumps(
                {"action": proposal.action, "discount_pct": proposal.discount_pct}
            ),
            "justification": f"Proposed '{proposal.action}' (discount {proposal.discount_pct}%) based on diagnosis '{diagnosis}'. Pydantic-validated.",
        }
    except Exception as e:
        # Pydantic validation failed — reject and log the RAW pre-validation values
        state["proposed_action"] = action  # keep raw for audit visibility
        state["discount_pct"] = discount
        state["guardrail_status"] = "REJECTED_INVALID_PROPOSAL"
        audit = {
            "actor": "llm_agent",
            "event_type": "action_rejected",
            "payload_json": json.dumps(
                {
                    "raw_action": str(action),
                    "raw_discount_pct": discount,
                    "error": str(e),
                }
            ),
            "justification": f"REJECTED: LLM proposal failed Pydantic validation — {e}",
        }

    state["audit_entries"].append(audit)
    return state

def route_after_diagnostic(state: RecoveryState):
    """If Pydantic already rejected the proposal, skip guardrail and escalate."""
    if state.get("guardrail_status") == "REJECTED_INVALID_PROPOSAL":
        return "escalate_node"
    return "guardrail_check"


def guardrail_check(state: RecoveryState):
    """Node 3: Deterministic Security Boundary.
    Ordered: enum → amount NaN/floor → discount range → high-value."""
    action = state.get("proposed_action")
    amount = state.get("amount", 0.0)
    discount = state.get("discount_pct", 0)

    status = "PASSED"
    justification = "All guardrails passed."

    # Rule 1: Action enum validation (THE critical check)
    if action not in ALLOWED_ACTIONS:
        status = "REJECTED_INVALID_ACTION"
        justification = f"REJECTED: '{action}' is outside the closed action enum."
    # Rule 2: NaN amount (defense in depth — also checked in pre_check)
    elif not (amount == amount) or amount <= 0:
        status = "REJECTED_INVALID_AMOUNT"
        justification = f"REJECTED: amount is invalid (NaN or non-positive)."
    # Rule 3: Discount range [0, 10]
    elif discount is not None and (discount > 10 or discount < 0):
        status = "REJECTED_OVER_DISCOUNT"
        justification = (
            f"REJECTED: discount {discount}% is outside allowed range [0, 10]."
        )
    # Rule 4: High-value escalation
    elif amount > 10000:
        # Note: This threshold currently assumes INR. If multi-currency is 
        # supported later, FX conversion must happen before this evaluation.
        status = "ESCALATED_HIGH_VALUE"
        justification = f"ESCALATED: amount ₹{amount:,.0f} exceeds ₹10,000 ceiling → human review."

    audit = {
        "actor": "guardrail",
        "event_type": "action_rejected" if status != "PASSED" else "action_validated",
        "payload_json": json.dumps(
            {
                "guardrail_status": status,
                "action": str(action),
                "discount_pct": discount,
                "amount": amount,
            }
        ),
        "justification": justification,
    }

    state["guardrail_status"] = status
    state["audit_entries"].append(audit)
    return state

def route_after_guardrail(state: RecoveryState):
    if state.get("guardrail_status", "PASSED") == "PASSED":
        return "execute_action"
    return "escalate_node"


def execute_action(state: RecoveryState):
    """Node 4a: Execute action if passed guardrails."""
    proposed = state.get("proposed_action", "no_action")
    state["final_status"] = "RECOVERED" if proposed != "no_action" else "ABANDONED"

    state["audit_entries"].append(
        {
            "actor": "rules_engine",
            "event_type": "action_executed",
            "payload_json": json.dumps(
                {"final_status": state["final_status"], "action": proposed}
            ),
            "justification": f"Executed '{proposed}' successfully.",
        }
    )
    return state

def escalate_node(state: RecoveryState):
    """Node 4b: Escalate if failed guardrails."""
    status = state.get("guardrail_status", "")
    if status in ("HALTED_MAX_ATTEMPTS", "REJECTED_INVALID_AMOUNT"):
        state["final_status"] = "FAILED"
    elif status.startswith("REJECTED"):
        state["final_status"] = "REJECTED"
    else:
        state["final_status"] = "ESCALATED"

    state["audit_entries"].append({
        "actor": "rules_engine",
        "event_type": "escalated" if state["final_status"] == "ESCALATED" else "rejected",
        "payload_json": json.dumps({"final_status": state["final_status"], "guardrail_status": status}),
        "justification": f"Routed to {state['final_status']}. Guardrail: {status}."
    })
    return state

def build_recovery_graph():
    builder = StateGraph(RecoveryState)
    builder.add_node("deterministic_triage", deterministic_triage)
    builder.add_node("pre_check", pre_check)
    builder.add_node("ai_diagnostic_node", ai_diagnostic_node)
    builder.add_node("guardrail_check", guardrail_check)
    builder.add_node("execute_action", execute_action)
    builder.add_node("escalate_node", escalate_node)

    builder.add_edge(START, "deterministic_triage")
    builder.add_edge("deterministic_triage", "pre_check")

    builder.add_conditional_edges(
        "pre_check",
        route_after_pre_check,
        {"ai_diagnostic_node": "ai_diagnostic_node", "escalate_node": "escalate_node"},
    )

    builder.add_conditional_edges(
        "ai_diagnostic_node",
        route_after_diagnostic,
        {"guardrail_check": "guardrail_check", "escalate_node": "escalate_node"},
    )
    builder.add_conditional_edges(
        "guardrail_check",
        route_after_guardrail,
        {"execute_action": "execute_action", "escalate_node": "escalate_node"},
    )
    builder.add_edge("execute_action", END)
    builder.add_edge("escalate_node", END)
    return builder.compile()

recovery_app = build_recovery_graph()
from typing import Optional, List, Dict, Any, Literal
from typing_extensions import TypedDict
from pydantic import BaseModel, field_validator
from langgraph.graph import StateGraph, START, END

# ── Closed enum: enforced at runtime, not just type-hint ──
ALLOWED_ACTIONS = frozenset({
    'send_reminder', 'send_retry_link', 'apply_discount',
    'escalate_to_human', 'no_action'
})

# ── Pydantic schema at LLM boundary (Fix 3) ──
class LLMRecoveryProposal(BaseModel):
    """Validates structured output from the LLM diagnostic node.
    Any real LLM response MUST be parsed through this before entering state."""
    action: Literal[
        'send_reminder', 'send_retry_link', 'apply_discount',
        'escalate_to_human', 'no_action'
    ]
    discount_pct: int = 0

    @field_validator('discount_pct')
    @classmethod
    def discount_in_range(cls, v):
        if v < 0 or v > 10:
            raise ValueError(f'discount_pct must be 0-10, got {v}')
        return v

class RecoveryState(TypedDict):
    transaction_id: str
    amount: float
    failure_code: str
    failure_reason: str
    attempt_count: int
    max_attempts: int
    diagnosis: Optional[str]
    proposed_action: Optional[Literal[
        'send_reminder', 'send_retry_link', 'apply_discount',
        'escalate_to_human', 'no_action'
    ]]
    discount_pct: Optional[int]
    guardrail_status: Optional[str]
    final_status: str
    audit_entries: List[Dict[str, Any]]

def deterministic_triage(state: RecoveryState):
    """Node 1: Classifies failure taxonomy based on error codes."""
    code = state.get("failure_code", "")
    diagnosis = "Unknown"

    if code == "GATEWAY_TIMEOUT":
        diagnosis = "Retry Candidate"
    elif code == "INSUFFICIENT_FUNDS":
        diagnosis = "Reminder/Discount Candidate"
    elif code == "CARD_EXPIRED":
        diagnosis = "Update Payment Link Candidate"

    audit = {
        "actor": "rules_engine",
        "event_type": "diagnosed",
        "payload_json": str({"failure_code": code}),
        "justification": f"Triaged as {diagnosis} based on error code."
    }

    state["diagnosis"] = diagnosis
    if not state.get("audit_entries"):
        state["audit_entries"] = []
    state["audit_entries"].append(audit)

    return state

# ── Fix 4: Early max-attempts short-circuit BEFORE LLM ──
def pre_check(state: RecoveryState):
    """Node 1.5: Cheap deterministic check before expensive LLM call.
    If attempt_count >= max_attempts, mark for short-circuit."""
    attempts = state.get("attempt_count", 0)
    max_att = state.get("max_attempts", 3)

    if attempts >= max_att:
        state["guardrail_status"] = "HALTED_MAX_ATTEMPTS"
        audit = {
            "actor": "rules_engine",
            "event_type": "action_rejected",
            "payload_json": str({"attempt_count": attempts, "max_attempts": max_att}),
            "justification": f"HALTED: attempt {attempts} >= max {max_att}. LLM call skipped."
        }
        state["audit_entries"].append(audit)

    return state

def route_after_pre_check(state: RecoveryState):
    """Skip LLM node entirely if max attempts reached."""
    if state.get("guardrail_status") == "HALTED_MAX_ATTEMPTS":
        return "escalate_node"
    return "ai_diagnostic_node"

def ai_diagnostic_node(state: RecoveryState):
    """Node 2: Proposes structured action + discount percentage.
    All output is validated through LLMRecoveryProposal (Pydantic)."""
    diagnosis = state.get("diagnosis", "")

    # Check if there's a pre-injected proposed action (for testing / deliberate failure)
    if state.get("proposed_action") is not None and state.get("discount_pct") is not None:
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

    # ── Fix 3: Validate through Pydantic before entering state ──
    try:
        proposal = LLMRecoveryProposal(action=action, discount_pct=discount)
        state["proposed_action"] = proposal.action
        state["discount_pct"] = proposal.discount_pct
        audit = {
            "actor": "llm_agent",
            "event_type": "action_proposed",
            "payload_json": str({"action": proposal.action, "discount_pct": proposal.discount_pct}),
            "justification": f"Proposed {proposal.action} based on diagnosis {diagnosis}. Pydantic-validated."
        }
    except Exception as e:
        # Pydantic validation failed — reject and log
        state["proposed_action"] = action  # keep raw for audit visibility
        state["discount_pct"] = discount
        state["guardrail_status"] = "REJECTED_INVALID_PROPOSAL"
        audit = {
            "actor": "llm_agent",
            "event_type": "action_rejected",
            "payload_json": str({"action": action, "discount_pct": discount, "error": str(e)}),
            "justification": f"REJECTED: LLM proposal failed Pydantic validation — {e}"
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
    Checks are ordered: enum → discount → amount."""
    action = state.get("proposed_action")
    amount = state.get("amount", 0.0)
    discount = state.get("discount_pct", 0)

    status = "PASSED"
    justification = "All guardrails passed."

    # ── Fix 1: Action enum validation (THE critical check) ──
    if action not in ALLOWED_ACTIONS:
        status = "REJECTED_INVALID_ACTION"
        justification = f"REJECTED: '{action}' is outside the closed action enum {sorted(ALLOWED_ACTIONS)}."
    # ── Fix 2: Negative discount bypass ──
    elif discount is not None and (discount > 10 or discount < 0):
        status = "REJECTED_OVER_DISCOUNT"
        justification = f"REJECTED: discount {discount}% is outside allowed range [0, 10]."
    elif amount > 10000:
        status = "ESCALATED_HIGH_VALUE"
        justification = f"ESCALATED: amount ₹{amount:,.0f} exceeds ₹10,000 ceiling → human review."

    audit = {
        "actor": "guardrail",
        "event_type": "action_rejected" if status != "PASSED" else "action_validated",
        "payload_json": str({"guardrail_status": status, "action": action, "discount_pct": discount, "amount": amount}),
        "justification": justification
    }

    state["guardrail_status"] = status
    state["audit_entries"].append(audit)

    return state

def route_after_guardrail(state: RecoveryState):
    status = state.get("guardrail_status", "PASSED")
    if status == "PASSED":
        return "execute_action"
    else:
        return "escalate_node"

def execute_action(state: RecoveryState):
    """Node 4a: Execute action if passed guardrails."""
    state["final_status"] = "RECOVERED" if state.get("proposed_action") != "no_action" else "ABANDONED"

    audit = {
        "actor": "rules_engine",
        "event_type": "action_executed",
        "payload_json": str({"final_status": state["final_status"]}),
        "justification": f"Executed {state.get('proposed_action')} successfully."
    }
    state["audit_entries"].append(audit)
    return state

def escalate_node(state: RecoveryState):
    """Node 4b: Escalate if failed guardrails."""
    status = state.get("guardrail_status")
    if status == "HALTED_MAX_ATTEMPTS":
        state["final_status"] = "FAILED"
    else:
        state["final_status"] = "ESCALATED"

    audit = {
        "actor": "rules_engine",
        "event_type": "escalated",
        "payload_json": str({"final_status": state["final_status"], "reason": status}),
        "justification": f"Escalated to human review. Guardrail status: {status}."
    }
    state["audit_entries"].append(audit)
    return state

def build_recovery_graph():
    builder = StateGraph(RecoveryState)

    builder.add_node("deterministic_triage", deterministic_triage)
    builder.add_node("pre_check", pre_check)
    builder.add_node("ai_diagnostic_node", ai_diagnostic_node)
    builder.add_node("guardrail_check", guardrail_check)
    builder.add_node("execute_action", execute_action)
    builder.add_node("escalate_node", escalate_node)

    # Flow: START → triage → pre_check → [LLM or escalate] → [guardrail or escalate] → [execute or escalate] → END
    builder.add_edge(START, "deterministic_triage")
    builder.add_edge("deterministic_triage", "pre_check")

    # Fix 4: Short-circuit before LLM if max attempts reached
    builder.add_conditional_edges(
        "pre_check",
        route_after_pre_check,
        {"ai_diagnostic_node": "ai_diagnostic_node", "escalate_node": "escalate_node"}
    )

    # Fix 3: Short-circuit to escalate if Pydantic rejects proposal
    builder.add_conditional_edges(
        "ai_diagnostic_node",
        route_after_diagnostic,
        {"guardrail_check": "guardrail_check", "escalate_node": "escalate_node"}
    )

    builder.add_conditional_edges(
        "guardrail_check",
        route_after_guardrail,
        {"execute_action": "execute_action", "escalate_node": "escalate_node"}
    )

    builder.add_edge("execute_action", END)
    builder.add_edge("escalate_node", END)

    return builder.compile()

recovery_app = build_recovery_graph()

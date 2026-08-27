from typing import Optional, List, Dict, Any, Literal
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END

class RecoveryState(TypedDict):
    transaction_id: str
    amount: float
    failure_code: str
    failure_reason: str
    attempt_count: int
    diagnosis: Optional[str]
    proposed_action: Optional[Literal['send_reminder', 'send_retry_link', 'apply_discount', 'escalate_to_human', 'no_action']]
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

def ai_diagnostic_node(state: RecoveryState):
    """Node 2: Proposes structured action + discount percentage."""
    diagnosis = state.get("diagnosis", "")
    
    # Check if there's a pre-injected proposed action (for testing deliberate failure)
    if state.get("proposed_action") and state.get("discount_pct"):
        # We skip AI reasoning and use the injected one
        action = state["proposed_action"]
        discount = state["discount_pct"]
    else:
        action = "no_action"
        discount = 0
        
        # Simulated LLM reasoning
        if diagnosis == "Reminder/Discount Candidate":
            if state.get("amount", 0) > 5000:
                action = "apply_discount"
                discount = 5 
            else:
                action = "apply_discount"
                discount = 5
        elif diagnosis == "Retry Candidate":
            action = "send_retry_link"
        elif diagnosis == "Update Payment Link Candidate":
            action = "send_retry_link"
            
    audit = {
        "actor": "llm_agent",
        "event_type": "action_proposed",
        "payload_json": str({"action": action, "discount_pct": discount}),
        "justification": f"Proposed {action} based on diagnosis {diagnosis}."
    }
    
    state["proposed_action"] = action
    state["discount_pct"] = discount
    state["audit_entries"].append(audit)
    
    return state

def guardrail_check(state: RecoveryState):
    """Node 3: Deterministic Security Boundary"""
    amount = state.get("amount", 0.0)
    attempts = state.get("attempt_count", 0)
    discount = state.get("discount_pct", 0)
    
    status = "PASSED"
    justification = "All guardrails passed."
    
    if attempts >= 3:
        status = "HALTED_MAX_ATTEMPTS"
        justification = "Transaction halted due to max attempts."
    elif amount > 10000:
        status = "ESCALATED_HIGH_VALUE"
        justification = "Transaction escalated due to high value."
    elif discount and discount > 10:
        status = "REJECTED_OVER_DISCOUNT"
        justification = "Proposed discount exceeds 10% limit."
        
    audit = {
        "actor": "guardrail",
        "event_type": "action_rejected" if status != "PASSED" else "action_validated",
        "payload_json": str({"guardrail_status": status}),
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
        "justification": "Executed proposed action."
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
        "payload_json": str({"final_status": state["final_status"]}),
        "justification": "Escalated to human or halted."
    }
    state["audit_entries"].append(audit)
    return state

def build_recovery_graph():
    builder = StateGraph(RecoveryState)
    
    builder.add_node("deterministic_triage", deterministic_triage)
    builder.add_node("ai_diagnostic_node", ai_diagnostic_node)
    builder.add_node("guardrail_check", guardrail_check)
    builder.add_node("execute_action", execute_action)
    builder.add_node("escalate_node", escalate_node)
    
    builder.add_edge(START, "deterministic_triage")
    builder.add_edge("deterministic_triage", "ai_diagnostic_node")
    builder.add_edge("ai_diagnostic_node", "guardrail_check")
    
    builder.add_conditional_edges(
        "guardrail_check",
        route_after_guardrail,
        {
            "execute_action": "execute_action",
            "escalate_node": "escalate_node"
        }
    )
    
    builder.add_edge("execute_action", END)
    builder.add_edge("escalate_node", END)
    
    return builder.compile()

recovery_app = build_recovery_graph()

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session, select, func
from typing import List, Dict, Any
from pydantic import BaseModel
from contextlib import asynccontextmanager

from models import create_db_and_tables, get_session, Transaction, AuditLog, RecoveryLedger
from recovery_graph import recovery_app

class TransactionCreate(BaseModel):
    customer_id: str
    amount: float
    currency: str = "INR"
    failure_code: str
    failure_reason: str

@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    yield

app = FastAPI(title="Recon API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/transactions")
def get_transactions(session: Session = Depends(get_session)):
    transactions = session.exec(select(Transaction)).all()
    result = []
    for t in transactions:
        audits = session.exec(select(AuditLog).where(AuditLog.transaction_id == t.id)).all()
        t_dict = t.model_dump()
        t_dict["audit_history"] = [a.model_dump() for a in audits]
        result.append(t_dict)
    return result

@app.get("/api/metrics")
def get_metrics(session: Session = Depends(get_session)):
    at_risk = session.exec(select(func.sum(Transaction.amount)).where(Transaction.status == "FAILED")).first() or 0.0
    recovered = session.exec(select(func.sum(RecoveryLedger.recovered_amount))).first() or 0.0
    
    total_tx = session.exec(select(func.count(Transaction.id))).first() or 0
    recovered_tx = session.exec(select(func.count(Transaction.id)).where(Transaction.status == "RECOVERED")).first() or 0
    
    recovery_rate = (recovered_tx / total_tx * 100) if total_tx > 0 else 0.0
    anomalies = session.exec(select(func.count(AuditLog.id)).where(AuditLog.actor == "guardrail", AuditLog.event_type == "action_rejected")).first() or 0
    
    return {
        "total_revenue_at_risk": at_risk,
        "total_recovered": recovered,
        "recovery_rate_percentage": recovery_rate,
        "guardrail_anomalies_caught": anomalies
    }

@app.post("/api/webhook/simulate-batch")
def simulate_batch(transactions: List[TransactionCreate], session: Session = Depends(get_session)):
    count = 0
    for data in transactions:
        tx = Transaction(**data.model_dump())
        session.add(tx)
        count += 1
    session.commit()
    return {"message": f"Successfully ingested {count} synthetic transactions"}

def process_transaction(t: Transaction, session: Session, injected_action=None, injected_discount=None):
    initial_state = {
        "transaction_id": str(t.id),
        "amount": t.amount,
        "failure_code": t.failure_code,
        "failure_reason": t.failure_reason,
        "attempt_count": t.attempt_count,
        "audit_entries": [],
        "proposed_action": injected_action,
        "discount_pct": injected_discount
    }
    
    final_state = recovery_app.invoke(initial_state)
    
    t.status = final_state["final_status"]
    t.attempt_count += 1
    session.add(t)
    
    for audit_data in final_state["audit_entries"]:
        audit_log = AuditLog(
            transaction_id=t.id,
            actor=audit_data["actor"],
            event_type=audit_data["event_type"],
            payload_json=audit_data["payload_json"],
            justification=audit_data["justification"],
            outcome_amount=t.amount if final_state["final_status"] == "RECOVERED" else None
        )
        session.add(audit_log)
        
    if final_state["final_status"] == "RECOVERED":
        ledger = RecoveryLedger(
            transaction_id=t.id,
            recovered_amount=t.amount,
            recovery_method=final_state["proposed_action"] or "unknown"
        )
        session.add(ledger)
        
    return final_state

@app.post("/api/recovery/process-batch")
def process_batch(session: Session = Depends(get_session)):
    failed_txs = session.exec(select(Transaction).where(Transaction.status == "FAILED")).all()
    count = 0
    for t in failed_txs:
        process_transaction(t, session)
        count += 1
    session.commit()
    return {"message": f"Processed {count} failed transactions."}

class DeliberateFailureInput(BaseModel):
    transaction_id: str
    action: str = "apply_discount"
    discount_pct: int = 30

@app.post("/api/recovery/trigger-deliberate-failure")
def trigger_deliberate_failure(data: DeliberateFailureInput, session: Session = Depends(get_session)):
    import uuid
    t = session.exec(select(Transaction).where(Transaction.id == uuid.UUID(data.transaction_id))).first()
    if not t:
        return {"error": "Transaction not found"}
        
    final_state = process_transaction(t, session, injected_action=data.action, injected_discount=data.discount_pct)
    session.commit()
    return {"message": "Deliberate failure triggered", "state": final_state}

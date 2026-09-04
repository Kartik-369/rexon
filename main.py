import uuid as uuid_mod
import traceback
from datetime import datetime
from typing import List, Literal

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session, select, func
from pydantic import BaseModel, confloat
from contextlib import asynccontextmanager

from models import (
    create_db_and_tables, get_session, Transaction, AuditLog,
    RecoveryLedger, compute_row_hash
)
from recovery_graph import recovery_app, KNOWN_FAILURE_CODES


# ── Validated input schema ──
class TransactionCreate(BaseModel):
    customer_id: str
    amount: confloat(gt=0)  # No negative/zero amounts
    currency: Literal["INR"] = "INR"  # Only INR accepted
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
        audits = session.exec(
            select(AuditLog)
            .where(AuditLog.transaction_id == t.id)
            .order_by(AuditLog.timestamp)
        ).all()
        t_dict = t.model_dump()
        t_dict["audit_history"] = [a.model_dump() for a in audits]
        result.append(t_dict)
    return result


@app.get("/api/metrics")
def get_metrics(session: Session = Depends(get_session)):
    # Total across ALL transactions (the batch total)
    total_all = session.exec(select(func.sum(Transaction.amount))).first() or 0.0
    total_tx = session.exec(select(func.count(Transaction.id))).first() or 0

    # Revenue still at risk = FAILED + ESCALATED + REJECTED (non-recovered statuses)
    at_risk = session.exec(
        select(func.sum(Transaction.amount))
        .where(Transaction.status.in_(["FAILED", "ESCALATED", "REJECTED"]))
    ).first() or 0.0

    # Recovered (net of discount, from ledger)
    recovered = session.exec(
        select(func.sum(RecoveryLedger.recovered_amount))
    ).first() or 0.0

    recovered_tx = session.exec(
        select(func.count(Transaction.id)).where(Transaction.status == "RECOVERED")
    ).first() or 0
    escalated_tx = session.exec(
        select(func.count(Transaction.id)).where(Transaction.status == "ESCALATED")
    ).first() or 0
    failed_tx = session.exec(
        select(func.count(Transaction.id)).where(Transaction.status == "FAILED")
    ).first() or 0
    abandoned_tx = session.exec(
        select(func.count(Transaction.id)).where(Transaction.status == "ABANDONED")
    ).first() or 0
    rejected_tx = session.exec(
        select(func.count(Transaction.id)).where(Transaction.status == "REJECTED")
    ).first() or 0

    recovery_rate = (recovered_tx / total_tx * 100) if total_tx > 0 else 0.0

    anomalies = session.exec(
        select(func.count(AuditLog.id))
        .where(AuditLog.actor == "guardrail", AuditLog.event_type == "action_rejected")
    ).first() or 0

    return {
        "total_batch_amount": total_all,
        "total_revenue_at_risk": at_risk,
        "total_recovered": recovered,
        "recovery_rate_percentage": round(recovery_rate, 2),
        "guardrail_anomalies_caught": anomalies,
        "breakdown": {
            "recovered": recovered_tx,
            "escalated": escalated_tx,
            "failed": failed_tx,
            "abandoned": abandoned_tx,
            "rejected": rejected_tx,
            "total": total_tx,
        },
    }


@app.post("/api/webhook/simulate-batch")
def simulate_batch(
    transactions: List[TransactionCreate], session: Session = Depends(get_session)
):
    count = 0
    for data in transactions:
        tx = Transaction(**data.model_dump())
        session.add(tx)
        count += 1
    session.commit()
    return {"message": f"Successfully ingested {count} synthetic transactions"}


def process_transaction(
    t: Transaction,
    session: Session,
    injected_action=None,
    injected_discount=None,
):
    initial_state = {
        "transaction_id": str(t.id),
        "amount": t.amount,
        "failure_code": t.failure_code,
        "failure_reason": t.failure_reason,
        "attempt_count": t.attempt_count,
        "max_attempts": t.max_attempts,
        "audit_entries": [],
        "proposed_action": injected_action,
        "discount_pct": injected_discount,
    }

    final_state = recovery_app.invoke(initial_state)

    t.status = final_state["final_status"]

    # Only increment attempt_count on actual execution outcomes
    if final_state["final_status"] in ("RECOVERED", "FAILED", "ABANDONED"):
        t.attempt_count += 1

    session.add(t)

    # Net-of-discount recovery amount
    discount_pct = final_state.get("discount_pct", 0) or 0
    is_recovered = final_state["final_status"] == "RECOVERED"
    net_recovered = t.amount * (1 - discount_pct / 100) if is_recovered else None

    # Hash-chain audit entries
    last_audit = session.exec(
        select(AuditLog)
        .where(AuditLog.transaction_id == t.id)
        .order_by(AuditLog.timestamp.desc())
    ).first()
    prev_hash = last_audit.row_hash if last_audit else "GENESIS"

    for audit_data in final_state["audit_entries"]:
        now = datetime.utcnow()
        row_hash = compute_row_hash(
            transaction_id=str(t.id),
            actor=audit_data["actor"],
            event_type=audit_data["event_type"],
            payload_json=audit_data["payload_json"],
            justification=audit_data["justification"],
            timestamp=now.isoformat(),
            prev_hash=prev_hash,
        )
        audit_log = AuditLog(
            transaction_id=t.id,
            timestamp=now,
            actor=audit_data["actor"],
            event_type=audit_data["event_type"],
            payload_json=audit_data["payload_json"],
            justification=audit_data["justification"],
            outcome_amount=net_recovered if is_recovered else None,
            row_hash=row_hash,
            prev_hash=prev_hash,
        )
        session.add(audit_log)
        prev_hash = row_hash

    # Idempotent ledger write with net amount
    if is_recovered:
        existing = session.exec(
            select(RecoveryLedger).where(RecoveryLedger.transaction_id == t.id)
        ).first()
        if not existing:
            ledger = RecoveryLedger(
                transaction_id=t.id,
                recovered_amount=net_recovered,
                recovery_method=final_state["proposed_action"] or "unknown",
            )
            session.add(ledger)

    return final_state


@app.post("/api/recovery/process-batch")
def process_batch(session: Session = Depends(get_session)):
    failed_txs = session.exec(
        select(Transaction).where(Transaction.status == "FAILED")
    ).all()
    processed = 0
    errors = []
    for t in failed_txs:
        try:
            process_transaction(t, session)
            processed += 1
        except Exception as e:
            errors.append({"transaction_id": str(t.id), "error": str(e)})
            session.rollback()
            continue
    session.commit()
    return {
        "message": f"Processed {processed} of {len(failed_txs)} failed transactions.",
        "errors": errors,
    }


class DeliberateFailureInput(BaseModel):
    transaction_id: str
    action: str = "apply_discount"
    discount_pct: int = 30


@app.post("/api/recovery/trigger-deliberate-failure")
def trigger_deliberate_failure(
    data: DeliberateFailureInput, session: Session = Depends(get_session)
):
    t = session.exec(
        select(Transaction).where(Transaction.id == uuid_mod.UUID(data.transaction_id))
    ).first()
    if not t:
        return {"error": "Transaction not found"}

    final_state = process_transaction(
        t, session, injected_action=data.action, injected_discount=data.discount_pct
    )
    session.commit()
    return {"message": "Deliberate failure triggered", "state": final_state}


class VerifyResponse(BaseModel):
    is_valid: bool
    broken_links: List[str]
    message: str

@app.get("/api/audit/verify", response_model=VerifyResponse)
def verify_audit_chain(session: Session = Depends(get_session)):
    transactions = session.exec(select(Transaction)).all()
    broken_links = []
    
    for t in transactions:
        audits = session.exec(
            select(AuditLog)
            .where(AuditLog.transaction_id == t.id)
            .order_by(AuditLog.timestamp)
        ).all()
        
        expected_prev = "GENESIS"
        for a in audits:
            if a.prev_hash != expected_prev:
                broken_links.append(f"Tx {t.id} - Audit {a.id}: prev_hash mismatch")
            
            # Recompute row_hash
            computed_hash = compute_row_hash(
                transaction_id=str(a.transaction_id),
                actor=a.actor,
                event_type=a.event_type,
                payload_json=a.payload_json,
                justification=a.justification,
                timestamp=a.timestamp.isoformat(),
                prev_hash=a.prev_hash
            )
            if a.row_hash != computed_hash:
                broken_links.append(f"Tx {t.id} - Audit {a.id}: row_hash mismatch")
                
            expected_prev = a.row_hash
            
    is_valid = len(broken_links) == 0
    return {
        "is_valid": is_valid,
        "broken_links": broken_links,
        "message": "Audit chain verified successfully." if is_valid else f"Found {len(broken_links)} integrity violations."
    }

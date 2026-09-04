import uuid
import hashlib
from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field, create_engine, Session, UniqueConstraint


class Transaction(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    customer_id: str
    amount: float
    currency: str = Field(default="INR")
    failure_code: str
    failure_reason: str
    status: str = Field(default="FAILED")
    attempt_count: int = Field(default=0)
    max_attempts: int = Field(default=3)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AuditLog(SQLModel, table=True):
    """Append-only audit log with hash-chaining for tamper detection.
    row_hash = SHA-256(transaction_id|actor|event_type|payload|justification|timestamp|prev_hash)
    prev_hash = hash of the previous entry for the same transaction, or 'GENESIS'."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    transaction_id: uuid.UUID = Field(foreign_key="transaction.id")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    actor: str
    event_type: str
    payload_json: str
    justification: str
    outcome_amount: Optional[float] = None
    row_hash: str = Field(default="")
    prev_hash: str = Field(default="GENESIS")


class RecoveryLedger(SQLModel, table=True):
    """Recovery ledger with unique constraint on transaction_id for idempotency."""
    __table_args__ = (UniqueConstraint("transaction_id"),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    transaction_id: uuid.UUID = Field(foreign_key="transaction.id")
    recovered_amount: float
    recovered_at: datetime = Field(default_factory=datetime.utcnow)
    recovery_method: str


def compute_row_hash(
    transaction_id: str,
    actor: str,
    event_type: str,
    payload_json: str,
    justification: str,
    timestamp: str,
    prev_hash: str
) -> str:
    """SHA-256 hash of the audit entry contents + previous hash."""
    data = f"{transaction_id}|{actor}|{event_type}|{payload_json}|{justification}|{timestamp}|{prev_hash}"
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


sqlite_file_name = "rexon.db"
sqlite_url = f"sqlite:///{sqlite_file_name}"

engine = create_engine(sqlite_url, echo=False)


def create_db_and_tables():
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session

import uuid
from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field, create_engine, Session

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
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    transaction_id: uuid.UUID = Field(foreign_key="transaction.id")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    actor: str
    event_type: str
    payload_json: str
    justification: str
    outcome_amount: Optional[float] = None

class RecoveryLedger(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    transaction_id: uuid.UUID = Field(foreign_key="transaction.id")
    recovered_amount: float
    recovered_at: datetime = Field(default_factory=datetime.utcnow)
    recovery_method: str

sqlite_file_name = "recon.db"
sqlite_url = f"sqlite:///{sqlite_file_name}"

engine = create_engine(sqlite_url, echo=False)

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)

def get_session():
    with Session(engine) as session:
        yield session

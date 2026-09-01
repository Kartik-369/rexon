import random
from models import create_db_and_tables, engine, Transaction
from sqlmodel import Session

# 40% INSUFFICIENT_FUNDS, 25% CARD_EXPIRED, 20% ISSUER_DECLINED, 15% GATEWAY_TIMEOUT
failure_codes = [
    ("INSUFFICIENT_FUNDS", 0.40, "Customer account has insufficient balance"),
    ("CARD_EXPIRED", 0.25, "The card on file has expired"),
    ("ISSUER_DECLINED", 0.20, "Bank declined the transaction"),
    ("GATEWAY_TIMEOUT", 0.15, "Payment gateway timed out during processing")
]

def generate_synthetic_data(num_records=100):
    create_db_and_tables()
    
    with Session(engine) as session:
        for i in range(num_records):
            # Pricing tiers (₹499 to ₹25,000)
            amount = random.choice([499.0, 999.0, 1499.0, 4999.0, 9999.0, 14999.0, 24999.0])
            
            # Select failure code based on distribution
            rand_val = random.random()
            cumulative = 0.0
            selected_code = None
            selected_reason = None
            for code, prob, reason in failure_codes:
                cumulative += prob
                if rand_val <= cumulative:
                    selected_code = code
                    selected_reason = reason
                    break
            
            if not selected_code:
                selected_code = failure_codes[-1][0]
                selected_reason = failure_codes[-1][2]
                
            tx = Transaction(
                customer_id=f"CUST_{random.randint(1000, 9999)}",
                amount=amount,
                currency="INR",
                failure_code=selected_code,
                failure_reason=selected_reason,
                status="FAILED",
                attempt_count=0,
                max_attempts=3
            )
            session.add(tx)
            
        session.commit()
        print(f"Successfully seeded {num_records} realistic failed subscription transactions.")

if __name__ == "__main__":
    generate_synthetic_data()

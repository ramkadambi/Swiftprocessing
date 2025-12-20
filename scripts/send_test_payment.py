from __future__ import annotations

import argparse
from decimal import Decimal
from typing import Optional

from canonical import Agent, PaymentEvent, PaymentStatus
from kafka_bus import KafkaProducerWrapper
from orchestrator import topics

print(">>> send_test_payment module loaded")

def build_payment(
    *,
    msg_id: str,
    end_to_end_id: str,
    amount: str,
    currency: str,
    debtor_bic: str,
    creditor_bic: str,
) -> PaymentEvent:
    return PaymentEvent(
        msg_id=msg_id,
        end_to_end_id=end_to_end_id,
        amount=Decimal(amount),
        currency=currency,
        debtor_agent=Agent(id_scheme="BIC", id_value=debtor_bic),
        creditor_agent=Agent(id_scheme="BIC", id_value=creditor_bic),
        status=PaymentStatus.RECEIVED,
    )


def main() -> None:
    print(">>> send_test_payment main() entered")
    parser = argparse.ArgumentParser(description="Send test PaymentEvent into the orchestrator ingress topic.")
    parser.add_argument("--bootstrap-servers", default="localhost:9092", help="Kafka bootstrap servers.")
    parser.add_argument(
        "--topic",
        default=topics.TOPIC_CANONICAL_INGRESS,
        help="Topic to send PaymentEvent to (default: orchestrator ingress).",
    )
    parser.add_argument("--msg-id", default="TESTMSG001", help="MsgId for the payment.")
    parser.add_argument("--e2e-id", default="E2E-TEST-001", help="EndToEndId for the payment.")
    parser.add_argument("--amount", default="1000.00", help="Payment amount as string.")
    parser.add_argument("--currency", default="INR", help="Currency (ISO 4217).")
    parser.add_argument(
        "--debtor-bic",
        default="HDFCINBBXXX",
        help="Debtor BICFI (used as debtor_agent.id_value).",
    )
    parser.add_argument(
        "--creditor-bic",
        default="RKBKINBBXXX",
        help="Creditor BICFI (used as creditor_agent.id_value).",
    )
    parser.add_argument(
        "--scenario",
        choices=["happy", "sanctions_fail", "balance_fail", "posting_fail"],
        default="happy",
        help="Predefined scenario to drive satellites and orchestrator.",
    )

    args = parser.parse_args()

    e2e = args.e2e_id
    # Adjust E2E or amount to trigger different satellite behaviours based on our simulation rules.
    if args.scenario == "sanctions_fail":
        # Our sanctions satellite fails if EndToEndId contains 'SAN'
        e2e = f"{e2e}-SAN"
    elif args.scenario == "balance_fail":
        # Balance check fails if amount > 10000 or E2E ends with 'B'
        args.amount = "20000.00"
    elif args.scenario == "posting_fail":
        # Posting fails if amount > 25000 or E2E ends with 'Z'
        args.amount = "30000.00"

    payment = build_payment(
        msg_id=args.msg_id,
        end_to_end_id=e2e,
        amount=args.amount,
        currency=args.currency,
        debtor_bic=args.debtor_bic,
        creditor_bic=args.creditor_bic,
    )

    print(f"[send_test_payment] Sending PaymentEvent to topic='{args.topic}' with E2E='{payment.end_to_end_id}'")
    producer = KafkaProducerWrapper(bootstrap_servers=args.bootstrap_servers)
    producer.send(args.topic, key=payment.end_to_end_id, value=payment)
    producer.flush()
    print("[send_test_payment] Done.")


if __name__ == "__main__":
    main()



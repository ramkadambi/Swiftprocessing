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
    debtor_country: Optional[str] = None,
    creditor_country: Optional[str] = None,
) -> PaymentEvent:
    return PaymentEvent(
        msg_id=msg_id,
        end_to_end_id=end_to_end_id,
        amount=Decimal(amount),
        currency=currency,
        debtor_agent=Agent(id_scheme="BIC", id_value=debtor_bic, country=debtor_country),
        creditor_agent=Agent(id_scheme="BIC", id_value=creditor_bic, country=creditor_country),
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
        choices=[
            "happy",
            "sanctions_fail",
            "balance_fail",
            "posting_fail",
            "routing_usd_domestic_fed",
            "routing_usd_crossborder_chips",
            "routing_usd_crossborder_fed",
            "routing_usd_fallback_swift",
            "routing_usd_individual",
        ],
        default="happy",
        help="Predefined scenario to drive satellites and orchestrator.",
    )

    args = parser.parse_args()

    e2e = args.e2e_id
    debtor_country = None
    creditor_country = None
    
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
    elif args.scenario == "routing_usd_domestic_fed":
        # USD domestic bank-to-bank → FED direct
        # Use Wells Fargo (WELLSFARGO) as creditor - FED member, US bank
        args.currency = "USD"
        args.creditor_bic = "WFBIUS6SXXX"
        debtor_country = "US"
        creditor_country = "US"
        args.amount = "5000.00"
        e2e = f"{e2e}-FED-DOMESTIC"
    elif args.scenario == "routing_usd_crossborder_chips":
        # USD cross-border high-value → CHIPS with WF intermediary
        # Use Deutsche Bank (DEUTDEFF) - CHIPS member, non-US
        args.currency = "USD"
        args.creditor_bic = "DEUTDEFFXXX"
        debtor_country = "US"
        creditor_country = "DE"
        args.amount = "9999.00"  # High value triggers CHIPS
        e2e = f"{e2e}-CHIPS-CROSSBORDER"
    elif args.scenario == "routing_usd_crossborder_fed":
        # USD cross-border low-value → FED with preferred correspondent
        # Use HSBC (HSBCGB2L) - has preferred correspondent, non-US
        args.currency = "USD"
        args.creditor_bic = "HSBCGB2LXXX"
        debtor_country = "US"
        creditor_country = "GB"
        args.amount = "5000.00"  # Low value, triggers FED substitution
        e2e = f"{e2e}-FED-CROSSBORDER"
    elif args.scenario == "routing_usd_fallback_swift":
        # USD fallback → SWIFT
        # Use a bank not in our lookup (will trigger fallback)
        args.currency = "USD"
        args.creditor_bic = "UNKNOWNBANKXXX"
        debtor_country = "US"
        creditor_country = "FR"
        args.amount = "1000.00"
        e2e = f"{e2e}-SWIFT-FALLBACK"
    elif args.scenario == "routing_usd_individual":
        # USD individual beneficiary → FED
        # Use INDIVIDUAL creditor type (simulated via special BIC)
        args.currency = "USD"
        args.creditor_bic = "INDIVIDUAL"
        debtor_country = "US"
        creditor_country = "US"
        args.amount = "5000.00"
        e2e = f"{e2e}-INDIVIDUAL"

    payment = build_payment(
        msg_id=args.msg_id,
        end_to_end_id=e2e,
        amount=args.amount,
        currency=args.currency,
        debtor_bic=args.debtor_bic,
        creditor_bic=args.creditor_bic,
        debtor_country=debtor_country,
        creditor_country=creditor_country,
    )

    print(f"[send_test_payment] Sending PaymentEvent to topic='{args.topic}' with E2E='{payment.end_to_end_id}'")
    producer = KafkaProducerWrapper(bootstrap_servers=args.bootstrap_servers)
    producer.send(args.topic, key=payment.end_to_end_id, value=payment)
    producer.flush()
    print("[send_test_payment] Done.")


if __name__ == "__main__":
    main()



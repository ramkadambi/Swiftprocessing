"""
Test payment script for routing_rulesV2.json scenarios.

This script covers all 6 routing rules defined in config/routing_rulesV2.json:
- WF-MT103-R1-INTERNAL-CREDIT: Wells Fargo is final beneficiary -> INTERNAL
- WF-MT103-R2-US-INTERMEDIARY-LOOKUP: Wells is intermediary, lookup next US bank
- WF-MT103-R3-CHIPS-DEFAULT: Route via CHIPS when CHIPS ID is available
- WF-MT103-R4-FED-ONLY: Route via FED when only ABA is available
- WF-MT103-R5-CHIPS-OR-FED-OPTIMIZATION: When both CHIPS and FED are available, apply optimization
- WF-MT103-R6-CROSSBORDER-OUT-SWIFT: If ultimate creditor is outside US, forward via SWIFT
"""

from __future__ import annotations

import argparse
import sys
from decimal import Decimal
from pathlib import Path
from typing import Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from canonical import Agent, PaymentEvent, PaymentStatus
from kafka_bus import KafkaProducerWrapper
from orchestrator import topics

# Wells Fargo BIC from routing_rulesV2.json
WF_BIC = "WFBIUS6SXXX"

# BICs that match different scenarios based on bic_lookup.py
# US banks with FED + CHIPS
CHASE_BIC = "CHASUS33XXX"  # Has ABA and CHIPS
BOFA_BIC = "BOFAUS3NXXX"   # Has ABA and CHIPS
CITI_BIC = "CITIUS33XXX"   # Has ABA and CHIPS

# US bank with only FED (no CHIPS) - need to check bic_lookup
# For R4, we need a bank that has ABA but no CHIPS
USBK_BIC = "USBKUS44XXX"   # From bic_lookup, has ABA but may not have CHIPS

# Non-US banks with CHIPS
DEUT_BIC = "DEUTDEFFXXX"   # CHIPS member, non-US
HSBC_BIC = "HSBCGB2LXXX"   # CHIPS member, non-US

# Non-US bank for SWIFT
BANAMEX_BIC = "BAMXMXMMXXX"  # Mexico, for SWIFT routing
SBI_BIC = "SBININBBXXX"      # India, for SWIFT routing


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
    intermediary_bic: Optional[str] = None,
    intermediary_country: Optional[str] = None,
) -> PaymentEvent:
    """Build a PaymentEvent with optional intermediary bank in agent_chain."""
    agent_chain = None
    if intermediary_bic:
        agent_chain = [
            Agent(
                id_scheme="BIC",
                id_value=intermediary_bic,
                country=intermediary_country or "US",
            )
        ]
    
    return PaymentEvent(
        msg_id=msg_id,
        end_to_end_id=end_to_end_id,
        amount=Decimal(amount),
        currency=currency,
        debtor_agent=Agent(id_scheme="BIC", id_value=debtor_bic, country=debtor_country),
        creditor_agent=Agent(id_scheme="BIC", id_value=creditor_bic, country=creditor_country),
        status=PaymentStatus.RECEIVED,
        agent_chain=agent_chain,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Send test PaymentEvent for routing_rulesV2.json scenarios to orchestrator ingress topic."
    )
    parser.add_argument("--bootstrap-servers", default="localhost:9092", help="Kafka bootstrap servers.")
    parser.add_argument(
        "--topic",
        default=topics.TOPIC_CANONICAL_INGRESS,
        help="Topic to send PaymentEvent to (default: orchestrator ingress).",
    )
    parser.add_argument(
        "--scenario",
        choices=[
            "r1_internal_credit",        # WF-MT103-R1: Wells Fargo is final beneficiary -> INTERNAL
            "r2_intermediary_lookup",    # WF-MT103-R2: Wells is intermediary, lookup next US bank
            "r3_chips_default",          # WF-MT103-R3: Route via CHIPS when CHIPS ID is available
            "r4_fed_only",               # WF-MT103-R4: Route via FED when only ABA is available
            "r5_chips_fed_optimization", # WF-MT103-R5: When both CHIPS and FED are available, apply optimization
            "r6_crossborder_swift",      # WF-MT103-R6: If ultimate creditor is outside US, forward via SWIFT
        ],
        required=True,
        help="Routing rule scenario to test.",
    )
    parser.add_argument("--msg-id", help="MsgId for the payment (default: auto-generated).")
    parser.add_argument("--e2e-id", help="EndToEndId for the payment (default: auto-generated).")
    parser.add_argument("--amount", help="Payment amount as string (default: scenario-specific).")
    parser.add_argument("--currency", help="Currency (ISO 4217, default: USD).")
    parser.add_argument("--debtor-bic", help="Debtor BICFI (default: scenario-specific).")
    parser.add_argument("--creditor-bic", help="Creditor BICFI (default: scenario-specific).")

    args = parser.parse_args()

    # Default values based on scenario
    scenario = args.scenario
    msg_id = args.msg_id or f"TEST-V2-{scenario.upper()}"
    e2e_id = args.e2e_id or f"E2E-V2-{scenario.upper()}"
    currency = args.currency or "USD"
    debtor_bic = args.debtor_bic
    creditor_bic = args.creditor_bic
    amount = args.amount
    debtor_country = None
    creditor_country = None
    intermediary_bic = None
    intermediary_country = None

    # Configure scenario-specific parameters
    if scenario == "r1_internal_credit":
        # WF-MT103-R1: Wells Fargo is final beneficiary -> INTERNAL
        # Condition: credit_agent_bic == "WFBIUS6SXXX"
        creditor_bic = creditor_bic or WF_BIC
        debtor_bic = debtor_bic or SBI_BIC  # Foreign bank sending to Wells Fargo
        amount = amount or "5000.00"  # Within balance limits
        debtor_country = "IN"  # Foreign bank
        creditor_country = "US"  # Wells Fargo
        print(f"[Test] Scenario: WF-MT103-R1-INTERNAL-CREDIT - Wells Fargo as final beneficiary -> INTERNAL")
        print(f"      Creditor: {creditor_bic} (Wells Fargo)")
        print(f"      Debtor: {debtor_bic} (Foreign bank)")

    elif scenario == "r2_intermediary_lookup":
        # WF-MT103-R2: Wells is intermediary; lookup next US bank clearing capabilities
        # Condition: intermediary_bic == "WFBIUS6SXXX" AND ultimate_creditor_country == "US"
        # Note: This rule invokes services (BIC_TO_ABA_LOOKUP, BIC_TO_CHIPS_LOOKUP)
        # For testing, we'll use a payment where Wells is intermediary
        creditor_bic = creditor_bic or CHASE_BIC  # US bank (ultimate creditor)
        debtor_bic = debtor_bic or SBI_BIC  # Foreign bank (sender)
        amount = amount or "9999.00"  # Within balance check limit
        debtor_country = "IN"  # Foreign
        creditor_country = "US"  # US bank (ultimate creditor country)
        intermediary_bic = WF_BIC  # Wells Fargo is intermediary
        print(f"[Test] Scenario: WF-MT103-R2-US-INTERMEDIARY-LOOKUP - Wells is intermediary, lookup next US bank")
        print(f"      Debtor: {debtor_bic} (Foreign bank - SBI)")
        print(f"      Intermediary: {intermediary_bic} (Wells Fargo)")
        print(f"      Creditor: {creditor_bic} (US bank - Chase)")
        print(f"      Note: This rule invokes lookup services (BIC_TO_ABA_LOOKUP, BIC_TO_CHIPS_LOOKUP)")

    elif scenario == "r3_chips_default":
        # WF-MT103-R3: Route via CHIPS when CHIPS ID is available (default, cheaper option)
        # Condition: next_bank.chips_id_exists == true
        # Use a bank that has CHIPS ID (Deutsche Bank or HSBC)
        creditor_bic = creditor_bic or DEUT_BIC  # CHIPS member
        debtor_bic = debtor_bic or CHASE_BIC  # US bank as debtor
        amount = amount or "8000.00"  # Within balance check limit
        debtor_country = "US"
        creditor_country = "DE"  # Non-US
        print(f"[Test] Scenario: WF-MT103-R3-CHIPS-DEFAULT - Route via CHIPS when CHIPS ID is available")
        print(f"      Creditor: {creditor_bic} (Deutsche Bank - CHIPS member)")

    elif scenario == "r4_fed_only":
        # WF-MT103-R4: Route via FED when only ABA is available
        # Condition: next_bank.chips_id_exists == false AND next_bank.aba_exists == true
        # Use a US bank that has ABA but no CHIPS relationship
        # USBKUS44 has ABA but may not have CHIPS nostro relationship
        creditor_bic = creditor_bic or USBK_BIC  # US bank with ABA, no CHIPS nostro
        debtor_bic = debtor_bic or CHASE_BIC
        amount = amount or "8000.00"
        debtor_country = "US"
        creditor_country = "US"
        print(f"[Test] Scenario: WF-MT103-R4-FED-ONLY - Route via FED when only ABA is available")
        print(f"      Creditor: {creditor_bic} (US bank with ABA, no CHIPS nostro)")

    elif scenario == "r5_chips_fed_optimization":
        # WF-MT103-R5: When both CHIPS and FED are available, apply Wells operational optimization
        # Condition: next_bank.chips_id_exists == true AND next_bank.aba_exists == true
        # Use a US bank that has both ABA and CHIPS (Chase, BofA, Citi)
        creditor_bic = creditor_bic or CHASE_BIC  # Has both ABA and CHIPS
        debtor_bic = debtor_bic or BOFA_BIC
        amount = amount or "9000.00"  # Within balance check limit
        debtor_country = "US"
        creditor_country = "US"
        print(f"[Test] Scenario: WF-MT103-R5-CHIPS-OR-FED-OPTIMIZATION - Both CHIPS and FED available")
        print(f"      Creditor: {creditor_bic} (Chase - has both ABA and CHIPS)")
        print(f"      Note: Decision matrix will determine routing (CHIPS default unless conditions met)")

    elif scenario == "r6_crossborder_swift":
        # WF-MT103-R6: If ultimate creditor is outside US, forward payment via SWIFT
        # Condition: ultimate_creditor_country != "US"
        creditor_bic = creditor_bic or BANAMEX_BIC  # Mexico bank
        debtor_bic = debtor_bic or CHASE_BIC  # US bank
        amount = amount or "7500.00"  # Within balance check limit
        debtor_country = "US"
        creditor_country = "MX"  # Non-US
        print(f"[Test] Scenario: WF-MT103-R6-CROSSBORDER-OUT-SWIFT - Ultimate creditor outside US -> SWIFT")
        print(f"      Creditor: {creditor_bic} (Banamex - Mexico)")

    payment = build_payment(
        msg_id=msg_id,
        end_to_end_id=e2e_id,
        amount=amount,
        currency=currency,
        debtor_bic=debtor_bic,
        creditor_bic=creditor_bic,
        debtor_country=debtor_country,
        creditor_country=creditor_country,
        intermediary_bic=intermediary_bic,
        intermediary_country=intermediary_country,
    )

    print(f"\n[send_test_payment_rulesV2] Sending PaymentEvent:")
    print(f"  Topic: {args.topic}")
    print(f"  E2E ID: {payment.end_to_end_id}")
    print(f"  Msg ID: {payment.msg_id}")
    print(f"  Amount: {payment.amount} {payment.currency}")
    print(f"  Debtor: {payment.debtor_agent.id_value} ({payment.debtor_agent.country})")
    print(f"  Creditor: {payment.creditor_agent.id_value} ({payment.creditor_agent.country})")
    if payment.agent_chain:
        print(f"  Intermediary: {payment.agent_chain[0].id_value} ({payment.agent_chain[0].country})")
    
    producer = KafkaProducerWrapper(bootstrap_servers=args.bootstrap_servers)
    producer.send(args.topic, key=payment.end_to_end_id, value=payment)
    producer.flush()
    print("[send_test_payment_rulesV2] PaymentEvent sent successfully.")


if __name__ == "__main__":
    main()


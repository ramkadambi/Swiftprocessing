"""
Payment Processing Demo Script

Processes input payment files through the full payment flow and captures egress output.
Shows input samples first, then processes each one and saves outputs.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from canonical import PaymentEvent, PaymentStatus, RoutingNetwork
from egress import payment_egress
from ingress.mx_to_canonical import pacs008_xml_to_payment_event
from ingress.mx_receiver import payment_event_to_json_bytes
from kafka_bus.consumer import payment_event_from_json
from satellites.account_validation import AccountValidationService
from satellites.balance_check import BalanceCheckService
from satellites.payment_posting import PaymentPostingService
from satellites.routing_validation import RoutingValidationService
from satellites.sanctions_check import SanctionsCheckService
from tests.test_mocks import MockKafkaConsumerWrapper, MockKafkaProducerWrapper


def show_input_samples(input_dir: Path) -> None:
    """Display all input samples before processing."""
    print("=" * 80)
    print("INPUT SAMPLES")
    print("=" * 80)
    print()
    
    input_files = sorted(input_dir.glob("*.xml"))
    
    for i, input_file in enumerate(input_files, 1):
        print(f"[{i}] {input_file.name}")
        print("-" * 80)
        
        content = input_file.read_text(encoding="utf-8")
        # Show first 20 lines
        lines = content.split("\n")
        for line in lines[:20]:
            print(line)
        if len(lines) > 20:
            print("...")
        print()
    
    print("=" * 80)
    print(f"Total input files: {len(input_files)}")
    print("=" * 80)
    print()


def process_payment_file(
    input_file: Path,
    output_dir: Path,
    routing_rules_path: Path,
) -> dict[str, Any]:
    """Process a single payment file through the full flow."""
    
    print(f"\n{'='*80}")
    print(f"Processing: {input_file.name}")
    print(f"{'='*80}\n")
    
    # Read input
    xml_content = input_file.read_text(encoding="utf-8")
    print(f"[1] Input File: {input_file.name}")
    print(f"    Size: {len(xml_content)} bytes")
    
    # Convert to PaymentEvent
    try:
        payment = pacs008_xml_to_payment_event(xml_content)
        print(f"[2] Converted to PaymentEvent:")
        print(f"    E2E ID: {payment.end_to_end_id}")
        print(f"    Amount: {payment.amount} {payment.currency}")
        print(f"    Debtor: {payment.debtor_agent.id_value}")
        print(f"    Creditor: {payment.creditor_agent.id_value}")
    except Exception as e:
        print(f"    ERROR: Failed to parse input: {e}")
        return {"error": str(e)}
    
    # Create mock Kafka components
    ingress_producer = MockKafkaProducerWrapper()
    results_producer = MockKafkaProducerWrapper()
    
    # Create satellites with mock consumers/producers
    account_validation_consumer = MockKafkaConsumerWrapper(group_id="account-validation")
    account_validation_producer = MockKafkaProducerWrapper()
    account_validation_service = AccountValidationService(
        consumer=account_validation_consumer,
        producer=account_validation_producer,
    )
    
    routing_validation_consumer = MockKafkaConsumerWrapper(group_id="routing-validation")
    routing_validation_producer = MockKafkaProducerWrapper()
    routing_validation_service = RoutingValidationService(
        consumer=routing_validation_consumer,
        producer=routing_validation_producer,
        routing_rules_path=routing_rules_path,
    )
    
    sanctions_check_consumer = MockKafkaConsumerWrapper(group_id="sanctions-check")
    sanctions_check_producer = MockKafkaProducerWrapper()
    sanctions_check_service = SanctionsCheckService(
        consumer=sanctions_check_consumer,
        producer=sanctions_check_producer,
    )
    
    balance_check_consumer = MockKafkaConsumerWrapper(group_id="balance-check")
    balance_check_producer = MockKafkaProducerWrapper()
    balance_check_service = BalanceCheckService(
        consumer=balance_check_consumer,
        producer=balance_check_producer,
    )
    
    payment_posting_consumer = MockKafkaConsumerWrapper(group_id="payment-posting")
    payment_posting_producer = MockKafkaProducerWrapper()
    payment_posting_service = PaymentPostingService(
        consumer=payment_posting_consumer,
        producer=payment_posting_producer,
    )
    
    from orchestrator import topics as topic_names
    
    # Step 1: Account Validation
    print(f"[3] Running Account Validation...")
    account_payload = payment_event_to_json_bytes(payment)
    account_validation_consumer.add_message(topic_names.TOPIC_ACCOUNT_VALIDATION_IN, payment.end_to_end_id, account_payload)
    account_validation_service.run(max_messages=1)
    
    # Get enriched payment from account validation output
    account_results = account_validation_producer.producer.get_messages(topic_names.TOPIC_ROUTING_VALIDATION_IN)
    if account_results:
        enriched_payment = payment_event_from_json(account_results[0][1])
        payment = enriched_payment
        print(f"    Account enriched: creditor_type={payment.account_validation.creditor_type.value if payment.account_validation else 'N/A'}")
    else:
        print(f"    WARNING: No enriched payment found from account validation")
    
    # Step 2: Routing Validation
    print(f"[4] Running Routing Validation...")
    routing_payload = payment_event_to_json_bytes(payment)
    routing_validation_consumer.add_message(topic_names.TOPIC_ROUTING_VALIDATION_IN, payment.end_to_end_id, routing_payload)
    routing_validation_service.run(max_messages=1)
    
    # Get routed payment from routing validation output
    routing_results = routing_validation_producer.producer.get_messages(topic_names.TOPIC_SANCTIONS_CHECK_IN)
    if routing_results:
        routed_payment = payment_event_from_json(routing_results[0][1])
        payment = routed_payment
        print(f"    Selected Network: {payment.selected_network}")
        print(f"    Routing Rule: {payment.routing_rule_applied}")
        if payment.agent_chain:
            print(f"    Intermediary Agents: {[a.id_value for a in payment.agent_chain]}")
    else:
        print(f"    WARNING: No routed payment found from routing validation")
    
    # Step 3: Sanctions Check
    print(f"[5] Running Sanctions Check...")
    sanctions_payload = payment_event_to_json_bytes(payment)
    sanctions_check_consumer.add_message(topic_names.TOPIC_SANCTIONS_CHECK_IN, payment.end_to_end_id, sanctions_payload)
    sanctions_check_service.run(max_messages=1)
    # Note: Sanctions check doesn't publish PaymentEvent, so we keep using the same payment object
    
    # Step 4: Balance Check
    print(f"[6] Running Balance Check...")
    balance_payload = payment_event_to_json_bytes(payment)
    balance_check_consumer.add_message(topic_names.TOPIC_BALANCE_CHECK_IN, payment.end_to_end_id, balance_payload)
    balance_check_service.run(max_messages=1)
    # Note: Balance check doesn't publish PaymentEvent, so we keep using the same payment object
    
    # Step 5: Payment Posting
    print(f"[7] Running Payment Posting...")
    posting_payload = payment_event_to_json_bytes(payment)
    payment_posting_consumer.add_message(topic_names.TOPIC_PAYMENT_POSTING_IN, payment.end_to_end_id, posting_payload)
    payment_posting_service.run(max_messages=1)
    # Note: Payment posting doesn't publish PaymentEvent, so we keep using the same payment object
    
    # Step 6: Egress (generate output message)
    print(f"[8] Generating Egress Output...")
    network_name, egress_message = payment_egress._dispatch_payment(payment)
    print(f"    Network: {network_name}")
    
    # Save output
    output_file = output_dir / f"{input_file.stem}_OUTPUT.txt"
    
    output_content = []
    output_content.append("=" * 80)
    output_content.append(f"EGRESS OUTPUT: {input_file.name}")
    output_content.append("=" * 80)
    output_content.append("")
    output_content.append(f"Input File: {input_file.name}")
    output_content.append(f"End-to-End ID: {payment.end_to_end_id}")
    output_content.append(f"Selected Network: {payment.selected_network}")
    output_content.append(f"Routing Rule Applied: {payment.routing_rule_applied}")
    if payment.agent_chain:
        output_content.append(f"Intermediary Agents: {[a.id_value for a in payment.agent_chain]}")
    output_content.append("")
    output_content.append(f"Output Network: {network_name}")
    output_content.append("")
    output_content.append("-" * 80)
    output_content.append("EGRESS MESSAGE:")
    output_content.append("-" * 80)
    output_content.append("")
    
    if isinstance(egress_message, bytes):
        try:
            output_content.append(egress_message.decode("utf-8"))
        except:
            output_content.append(f"[Binary content, {len(egress_message)} bytes]")
    else:
        output_content.append(str(egress_message))
    
    output_content.append("")
    output_content.append("=" * 80)
    
    output_file.write_text("\n".join(output_content), encoding="utf-8")
    print(f"    Output saved to: {output_file.name}")
    
    return {
        "input_file": input_file.name,
        "end_to_end_id": payment.end_to_end_id,
        "selected_network": payment.selected_network.value if payment.selected_network else None,
        "routing_rule": payment.routing_rule_applied,
        "output_network": network_name,
        "output_file": output_file.name,
    }


def main() -> None:
    """Main entry point."""
    # Check for lxml dependency
    try:
        import lxml.etree
    except ImportError:
        print("=" * 80)
        print("ERROR: lxml is required for XML parsing")
        print("=" * 80)
        print("\nPlease install lxml:")
        print("  pip install lxml")
        print("\nExiting...")
        return
    
    project_root = Path(__file__).parent.parent
    input_dir = project_root / "samples" / "input"
    output_dir = project_root / "samples" / "output"
    routing_rules_path = project_root / "config" / "routing_rulesV2.json"
    
    # Ensure output directory exists
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Show input samples first
    show_input_samples(input_dir)
    
    # Auto-start processing
    print("\nStarting processing...\n")
    
    # Process each input file
    input_files = sorted(input_dir.glob("*.xml"))
    
    if not input_files:
        print("No input files found!")
        return
    
    results = []
    
    for input_file in input_files:
        try:
            result = process_payment_file(input_file, output_dir, routing_rules_path)
            results.append(result)
        except Exception as e:
            print(f"ERROR processing {input_file.name}: {e}")
            results.append({"input_file": input_file.name, "error": str(e)})
    
    # Summary
    print("\n" + "=" * 80)
    print("PROCESSING SUMMARY")
    print("=" * 80)
    print()
    
    for result in results:
        input_file_name = result.get('input_file', 'UNKNOWN')
        if "error" in result:
            print(f"[FAIL] {input_file_name}: ERROR - {result['error']}")
        else:
            print(f"[PASS] {input_file_name}")
            print(f"   Network: {result.get('selected_network', 'N/A')} -> {result.get('output_network', 'N/A')}")
            print(f"   Rule: {result.get('routing_rule', 'N/A')}")
            print(f"   Output: {result.get('output_file', 'N/A')}")
            print()
    
    print(f"\nAll outputs saved to: {output_dir}")
    print("=" * 80)


if __name__ == "__main__":
    main()


"""
End-to-end integration tests for the full payment processing flow.

Tests the complete flow from ingress through all satellites to final status,
using mocked Kafka components.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from canonical import (
    AccountValidationEnrichment,
    Agent,
    CreditorType,
    PaymentEvent,
    PaymentStatus,
    RoutingNetwork,
    ServiceResult,
    ServiceResultStatus,
)
from pathlib import Path

from ingress.mx_receiver import payment_event_to_json_bytes
from kafka_bus.consumer import payment_event_from_json, service_result_from_json

from orchestrator.orchestrator import PaymentOrchestrator
from satellites.account_validation import AccountValidationService
from satellites.balance_check import BalanceCheckService
from satellites.payment_posting import PaymentPostingService
from satellites.routing_validation import RoutingValidationService
from satellites.sanctions_check import SanctionsCheckService
from tests.test_mocks import MockKafkaConsumerWrapper, MockKafkaProducerWrapper


def create_test_payment_event(
    *,
    end_to_end_id: str = "E2E-TEST-001",
    amount: str = "1000.00",
    currency: str = "USD",
    debtor_bic: str = "CHASUS33XXX",
    creditor_bic: str = "CHASUS33XXX",
    debtor_country: str = "US",
    creditor_country: str = "US",
) -> PaymentEvent:
    """Helper to create a test PaymentEvent."""
    return PaymentEvent(
        msg_id="TEST-MSG-001",
        end_to_end_id=end_to_end_id,
        amount=Decimal(amount),
        currency=currency,
        debtor_agent=Agent(id_scheme="BIC", id_value=debtor_bic, country=debtor_country),
        creditor_agent=Agent(id_scheme="BIC", id_value=creditor_bic, country=creditor_country),
        status=PaymentStatus.RECEIVED,
    )


class TestFullPaymentFlow:
    """Tests for the complete payment processing flow."""

    def test_happy_path_full_flow(self) -> None:
        """Test complete happy path: all satellites PASS."""
        # Create all services with mocked Kafka
        account_consumer = MockKafkaConsumerWrapper(group_id="account-validation")
        account_producer = MockKafkaProducerWrapper()
        account_service = AccountValidationService(consumer=account_consumer, producer=account_producer)

        routing_consumer = MockKafkaConsumerWrapper(group_id="routing-validation")
        routing_producer = MockKafkaProducerWrapper()
        script_dir = Path(__file__).parent.parent
        routing_rules_path = script_dir / "config" / "routing_rules.json"
        routing_service = RoutingValidationService(
            consumer=routing_consumer, producer=routing_producer, routing_rules_path=routing_rules_path
        )

        sanctions_consumer = MockKafkaConsumerWrapper(group_id="sanctions-check")
        sanctions_producer = MockKafkaProducerWrapper()
        sanctions_service = SanctionsCheckService(consumer=sanctions_consumer, producer=sanctions_producer)

        balance_consumer = MockKafkaConsumerWrapper(group_id="balance-check")
        balance_producer = MockKafkaProducerWrapper()
        balance_service = BalanceCheckService(consumer=balance_consumer, producer=balance_producer)

        posting_consumer = MockKafkaConsumerWrapper(group_id="payment-posting")
        posting_producer = MockKafkaProducerWrapper()
        posting_service = PaymentPostingService(consumer=posting_consumer, producer=posting_producer)

        # Create orchestrator
        orchestrator_ingress_consumer = MockKafkaConsumerWrapper(group_id="orchestrator-ingress")
        orchestrator_results_consumer = MockKafkaConsumerWrapper(group_id="orchestrator-results")
        orchestrator_producer = MockKafkaProducerWrapper()
        orchestrator = PaymentOrchestrator(
            ingress_consumer=orchestrator_ingress_consumer,
            results_consumer=orchestrator_results_consumer,
            producer=orchestrator_producer,
        )

        # Step 1: Send payment to orchestrator ingress
        payment = create_test_payment_event(
            end_to_end_id="E2E-HAPPY-001", amount="5000.00", creditor_bic="CHASUS33XXX"
        )
        ingress_payload = payment_event_to_json_bytes(payment)
        orchestrator_ingress_consumer.add_message("payments.orchestrator.in", payment.end_to_end_id, ingress_payload)

        # Step 2: Process orchestrator ingress (should forward to account_validation)
        # Manually call the handler since orchestrator.run() uses threading
        orchestrator._ingress_consumer.run(
            orchestrator._handle_ingress_payment,
            deserializer=payment_event_from_json,
            max_messages=1,
            poll_timeout_s=0.1,
        )

        # Step 3: Check account_validation received the message
        account_messages = orchestrator_producer.producer.get_messages("payments.step.account_validation")
        assert len(account_messages) == 1

        # Step 4: Process account_validation
        account_payload = account_messages[0][1]
        account_consumer.add_message("payments.step.account_validation", payment.end_to_end_id, account_payload)
        account_service.run(max_messages=1)

        # Step 5: Check account_validation published enriched event to routing
        routing_messages = account_producer.producer.get_messages("payments.step.routing_validation")
        assert len(routing_messages) == 1

        # Step 6: Check account_validation published ServiceResult
        account_result_messages = account_producer.producer.get_messages("service.results.account_validation")
        assert len(account_result_messages) == 1
        account_result = service_result_from_json(account_result_messages[0][1])
        assert account_result.status == ServiceResultStatus.PASS

        # Step 7: Send account result to orchestrator
        orchestrator_results_consumer.add_message(
            "service.results.account_validation", payment.end_to_end_id, account_result_messages[0][1]
        )

        # Step 8: Process routing_validation
        routing_payload = routing_messages[0][1]
        routing_consumer.add_message("payments.step.routing_validation", payment.end_to_end_id, routing_payload)
        routing_service.run(max_messages=1)

        # Step 9: Check routing_validation published to sanctions
        sanctions_messages = routing_producer.producer.get_messages("payments.step.sanctions_check")
        assert len(sanctions_messages) == 1

        # Step 10: Check routing_validation published ServiceResult
        routing_result_messages = routing_producer.producer.get_messages("service.results.routing_validation")
        assert len(routing_result_messages) == 1
        routing_result = service_result_from_json(routing_result_messages[0][1])
        assert routing_result.status == ServiceResultStatus.PASS

        # Step 11: Send routing result to orchestrator
        orchestrator_results_consumer.add_message(
            "service.results.routing_validation", payment.end_to_end_id, routing_result_messages[0][1]
        )

        # Step 12: Process sanctions_check
        sanctions_payload = sanctions_messages[0][1]
        sanctions_consumer.add_message("payments.step.sanctions_check", payment.end_to_end_id, sanctions_payload)
        sanctions_service.run(max_messages=1)

        # Step 13: Check sanctions_check published ServiceResult
        sanctions_result_messages = sanctions_producer.producer.get_messages("service.results.sanctions_check")
        assert len(sanctions_result_messages) == 1
        sanctions_result = service_result_from_json(sanctions_result_messages[0][1])
        assert sanctions_result.status == ServiceResultStatus.PASS

        # Step 14: Send sanctions result to orchestrator
        orchestrator_results_consumer.add_message(
            "service.results.sanctions_check", payment.end_to_end_id, sanctions_result_messages[0][1]
        )

        # Step 15: Process balance_check
        # Get the message from orchestrator (it sends PaymentEvent objects, need to serialize)
        balance_messages = orchestrator_producer.producer.get_messages("payments.step.balance_check")
        assert len(balance_messages) > 0
        balance_event = balance_messages[0][1]  # This is a PaymentEvent object (not bytes)
        if not isinstance(balance_event, bytes):
            balance_payload = payment_event_to_json_bytes(balance_event)
        else:
            balance_payload = balance_event
        balance_consumer.add_message("payments.step.balance_check", payment.end_to_end_id, balance_payload)
        balance_service.run(max_messages=1)

        # Step 16: Check balance_check published ServiceResult
        balance_result_messages = balance_producer.producer.get_messages("service.results.balance_check")
        assert len(balance_result_messages) == 1
        balance_result = service_result_from_json(balance_result_messages[0][1])
        assert balance_result.status == ServiceResultStatus.PASS

        # Step 17: Send balance result to orchestrator
        orchestrator_results_consumer.add_message(
            "service.results.balance_check", payment.end_to_end_id, balance_result_messages[0][1]
        )

        # Step 18: Process payment_posting
        # Get the message from orchestrator (it sends PaymentEvent objects, need to serialize)
        posting_messages = orchestrator_producer.producer.get_messages("payments.step.payment_posting")
        assert len(posting_messages) > 0
        posting_event = posting_messages[0][1]  # This is a PaymentEvent object (not bytes)
        if not isinstance(posting_event, bytes):
            posting_payload = payment_event_to_json_bytes(posting_event)
        else:
            posting_payload = posting_event
        posting_consumer.add_message("payments.step.payment_posting", payment.end_to_end_id, posting_payload)
        posting_service.run(max_messages=1)

        # Step 19: Check payment_posting published ServiceResult
        posting_result_messages = posting_producer.producer.get_messages("service.results.payment_posting")
        assert len(posting_result_messages) == 1
        posting_result = service_result_from_json(posting_result_messages[0][1])
        assert posting_result.status == ServiceResultStatus.PASS

        # Step 20: Send posting result to orchestrator
        orchestrator_results_consumer.add_message(
            "service.results.payment_posting", payment.end_to_end_id, posting_result_messages[0][1]
        )

        # Step 21: Process orchestrator results to trigger final status
        orchestrator_results_consumer.run(
            orchestrator._handle_service_result,
            deserializer=service_result_from_json,
            max_messages=5,  # Process all results
            poll_timeout_s=0.1,
        )

        # Step 22: Check final status was emitted
        final_messages = orchestrator_producer.producer.get_messages("payments.final.status")
        assert len(final_messages) > 0

    def test_sanctions_fail_flow(self) -> None:
        """Test flow where sanctions check fails."""
        # Similar setup as happy path, but with sanctions failure
        sanctions_consumer = MockKafkaConsumerWrapper(group_id="sanctions-check")
        sanctions_producer = MockKafkaProducerWrapper()
        sanctions_service = SanctionsCheckService(consumer=sanctions_consumer, producer=sanctions_producer)

        # Create payment that will fail sanctions
        payment = create_test_payment_event(end_to_end_id="E2E-SAN-FAIL", amount="5000.00")

        # Process sanctions check
        payload = payment_event_to_json_bytes(payment)
        sanctions_consumer.add_message("payments.step.sanctions_check", payment.end_to_end_id, payload)
        sanctions_service.run(max_messages=1)

        # Check error was published
        error_messages = sanctions_producer.producer.get_messages("service.errors.sanctions_check")
        assert len(error_messages) == 1

        result = service_result_from_json(error_messages[0][1])
        assert result.status == ServiceResultStatus.FAIL


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


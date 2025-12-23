"""
Unit tests for satellite services.

Tests each satellite independently with mocked Kafka components.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from canonical import (
    AccountValidationEnrichment,
    Agent,
    CreditorType,
    PaymentEvent,
    PaymentStatus,
    RoutingNetwork,
    ServiceResultStatus,
)
from ingress.mx_receiver import payment_event_to_json_bytes
from kafka_bus.consumer import payment_event_from_json, service_result_from_json
from satellites.account_validation import AccountValidationService, simulate_account_validation
from satellites.balance_check import BalanceCheckService, simulate_balance_check
from satellites.payment_posting import PaymentPostingService, simulate_payment_posting
from satellites.sanctions_check import SanctionsCheckService, simulate_sanctions_check
from tests.test_mocks import MockKafkaConsumerWrapper, MockKafkaProducerWrapper


def create_test_payment_event(
    *,
    end_to_end_id: str = "E2E-TEST-001",
    amount: str = "1000.00",
    currency: str = "USD",
    debtor_bic: str = "CHASUS33XXX",
    creditor_bic: str = "WFBIUS6SXXX",
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


class TestAccountValidation:
    """Tests for account validation satellite."""

    def test_simulate_account_validation_pass(self) -> None:
        """Test account validation simulation - PASS case."""
        event = create_test_payment_event(end_to_end_id="E2E-PASS")
        status = simulate_account_validation(event)
        assert status == ServiceResultStatus.PASS

    def test_simulate_account_validation_fail(self) -> None:
        """Test account validation simulation - FAIL case."""
        event = create_test_payment_event(end_to_end_id="E2E-FAILX")
        status = simulate_account_validation(event)
        assert status == ServiceResultStatus.FAIL

    def test_account_validation_service_pass(self) -> None:
        """Test account validation service - PASS case."""
        consumer = MockKafkaConsumerWrapper(group_id="test-group")
        producer = MockKafkaProducerWrapper()
        service = AccountValidationService(consumer=consumer, producer=producer)

        event = create_test_payment_event(end_to_end_id="E2E-PASS", creditor_bic="CHASUS33XXX")
        payload = payment_event_to_json_bytes(event)
        consumer.add_message("payments.step.account_validation", event.end_to_end_id, payload)

        service.run(max_messages=1)

        # Check ServiceResult was published
        result_messages = producer.producer.get_messages("service.results.account_validation")
        assert len(result_messages) == 1

        # Check enriched PaymentEvent was published to routing
        routing_messages = producer.producer.get_messages("payments.step.routing_validation")
        assert len(routing_messages) == 1

        # Verify enrichment
        routing_payload = routing_messages[0][1]
        enriched_event = payment_event_from_json(routing_payload)
        assert enriched_event.account_validation is not None
        assert enriched_event.account_validation.status == ServiceResultStatus.PASS

    def test_account_validation_service_fail(self) -> None:
        """Test account validation service - FAIL case."""
        consumer = MockKafkaConsumerWrapper(group_id="test-group")
        producer = MockKafkaProducerWrapper()
        service = AccountValidationService(consumer=consumer, producer=producer)

        event = create_test_payment_event(end_to_end_id="E2E-FAILX")
        payload = payment_event_to_json_bytes(event)
        consumer.add_message("payments.step.account_validation", event.end_to_end_id, payload)

        service.run(max_messages=1)

        # Check error was published
        error_messages = producer.producer.get_messages("service.errors.account_validation")
        assert len(error_messages) == 1

        # Check no routing message (validation failed)
        routing_messages = producer.producer.get_messages("payments.step.routing_validation")
        assert len(routing_messages) == 0


class TestSanctionsCheck:
    """Tests for sanctions check satellite."""

    def test_simulate_sanctions_check_pass(self) -> None:
        """Test sanctions check simulation - PASS case."""
        event = create_test_payment_event(end_to_end_id="E2E-PASS")
        status = simulate_sanctions_check(event)
        assert status == ServiceResultStatus.PASS

    def test_simulate_sanctions_check_fail(self) -> None:
        """Test sanctions check simulation - FAIL case."""
        event = create_test_payment_event(end_to_end_id="E2E-SAN")
        status = simulate_sanctions_check(event)
        assert status == ServiceResultStatus.FAIL

    def test_sanctions_check_service(self) -> None:
        """Test sanctions check service."""
        consumer = MockKafkaConsumerWrapper(group_id="test-group")
        producer = MockKafkaProducerWrapper()
        service = SanctionsCheckService(consumer=consumer, producer=producer)

        event = create_test_payment_event(end_to_end_id="E2E-PASS")
        payload = payment_event_to_json_bytes(event)
        consumer.add_message("payments.step.sanctions_check", event.end_to_end_id, payload)

        service.run(max_messages=1)

        result_messages = producer.producer.get_messages("service.results.sanctions_check")
        assert len(result_messages) == 1

        result = service_result_from_json(result_messages[0][1])
        assert result.status == ServiceResultStatus.PASS


class TestBalanceCheck:
    """Tests for balance check satellite."""

    def test_simulate_balance_check_pass(self) -> None:
        """Test balance check simulation - PASS case."""
        event = create_test_payment_event(amount="5000.00")
        status = simulate_balance_check(event)
        assert status == ServiceResultStatus.PASS

    def test_simulate_balance_check_fail_amount(self) -> None:
        """Test balance check simulation - FAIL due to amount."""
        event = create_test_payment_event(amount="20000.00")
        status = simulate_balance_check(event)
        assert status == ServiceResultStatus.FAIL

    def test_simulate_balance_check_fail_e2e(self) -> None:
        """Test balance check simulation - FAIL due to E2E ending with 'B'."""
        event = create_test_payment_event(end_to_end_id="E2E-FAILB", amount="5000.00")
        status = simulate_balance_check(event)
        assert status == ServiceResultStatus.FAIL

    def test_balance_check_service(self) -> None:
        """Test balance check service."""
        consumer = MockKafkaConsumerWrapper(group_id="test-group")
        producer = MockKafkaProducerWrapper()
        service = BalanceCheckService(consumer=consumer, producer=producer)

        event = create_test_payment_event(amount="5000.00")
        payload = payment_event_to_json_bytes(event)
        consumer.add_message("payments.step.balance_check", event.end_to_end_id, payload)

        service.run(max_messages=1)

        result_messages = producer.producer.get_messages("service.results.balance_check")
        assert len(result_messages) == 1

        result = service_result_from_json(result_messages[0][1])
        assert result.status == ServiceResultStatus.PASS


class TestPaymentPosting:
    """Tests for payment posting satellite."""

    def test_simulate_payment_posting_pass(self) -> None:
        """Test payment posting simulation - PASS case."""
        event = create_test_payment_event(amount="10000.00")
        status, entries = simulate_payment_posting(event)
        assert status == ServiceResultStatus.PASS
        assert len(entries) == 2  # Debit and credit entries

    def test_simulate_payment_posting_fail_amount(self) -> None:
        """Test payment posting simulation - FAIL due to amount."""
        event = create_test_payment_event(amount="30000.00")
        status, entries = simulate_payment_posting(event)
        assert status == ServiceResultStatus.FAIL
        assert len(entries) == 2

    def test_simulate_payment_posting_fail_e2e(self) -> None:
        """Test payment posting simulation - FAIL due to E2E ending with 'Z'."""
        event = create_test_payment_event(end_to_end_id="E2E-FAILZ", amount="10000.00")
        status, entries = simulate_payment_posting(event)
        assert status == ServiceResultStatus.FAIL
        assert len(entries) == 2

    def test_payment_posting_service(self) -> None:
        """Test payment posting service."""
        consumer = MockKafkaConsumerWrapper(group_id="test-group")
        producer = MockKafkaProducerWrapper()
        service = PaymentPostingService(consumer=consumer, producer=producer)

        event = create_test_payment_event(amount="10000.00")
        payload = payment_event_to_json_bytes(event)
        consumer.add_message("payments.step.payment_posting", event.end_to_end_id, payload)

        service.run(max_messages=1)

        result_messages = producer.producer.get_messages("service.results.payment_posting")
        assert len(result_messages) == 1

        result = service_result_from_json(result_messages[0][1])
        assert result.status == ServiceResultStatus.PASS


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


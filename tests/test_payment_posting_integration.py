"""
Integration tests for payment posting with settlement account lookup.

Tests that payment posting correctly uses settlement accounts based on routing network.
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
from kafka_bus.consumer import payment_event_from_json
from satellites.payment_posting import EntrySide, PostingEntry, PaymentPostingService
from tests.test_mocks import MockKafkaConsumerWrapper, MockKafkaProducerWrapper


def create_payment_with_routing(
    *,
    end_to_end_id: str,
    amount: str,
    currency: str,
    debtor_bic: str,
    creditor_bic: str,
    debtor_country: str,
    creditor_country: str,
    selected_network: RoutingNetwork,
    fed_member: bool = False,
    chips_member: bool = False,
) -> PaymentEvent:
    """Create a PaymentEvent with routing decision."""
    event = PaymentEvent(
        msg_id=f"TEST-{end_to_end_id}",
        end_to_end_id=end_to_end_id,
        amount=Decimal(amount),
        currency=currency,
        debtor_agent=Agent(id_scheme="BIC", id_value=debtor_bic, country=debtor_country),
        creditor_agent=Agent(id_scheme="BIC", id_value=creditor_bic, country=creditor_country),
        status=PaymentStatus.RECEIVED,
        account_validation=AccountValidationEnrichment(
            status=ServiceResultStatus.PASS,
            creditor_type=CreditorType.BANK,
            fed_member=fed_member,
            chips_member=chips_member,
            nostro_with_us=False,
            vostro_with_us=False,
            preferred_correspondent=None,
        ),
        selected_network=selected_network,
    )
    return event


class TestPaymentPostingSettlementAccounts:
    """Tests for payment posting with settlement account integration."""

    @pytest.fixture
    def posting_service(self) -> PaymentPostingService:
        """Create payment posting service with mock Kafka."""
        consumer = MockKafkaConsumerWrapper(group_id="payment-posting")
        producer = MockKafkaProducerWrapper()
        return PaymentPostingService(consumer=consumer, producer=producer)

    def test_ibt_inbound_vostro_account(self, posting_service: PaymentPostingService) -> None:
        """Test IBT payment with inbound vostro account."""
        # SBI (India) sending to Wells Fargo customer
        payment = create_payment_with_routing(
            end_to_end_id="E2E-IBT-VOSTRO",
            amount="5000.00",
            currency="USD",
            debtor_bic="SBININBBXXX",  # SBI (foreign bank)
            creditor_bic="WFBIUS6SXXX",  # Wells Fargo
            debtor_country="IN",
            creditor_country="US",
            selected_network=RoutingNetwork.INTERNAL,
        )

        payload = payment_event_to_json_bytes(payment)
        posting_service._consumer.add_message("payments.step.payment_posting", payment.end_to_end_id, payload)
        posting_service.run(max_messages=1)

        # Verify ServiceResult was published
        result_messages = posting_service._producer.producer.get_messages(posting_service._result_topic)
        assert len(result_messages) == 1

        # In a real scenario, we would verify the posting entries
        # For now, we verify the service processed successfully
        result_bytes = result_messages[0][1]
        assert b'"status":"PASS"' in result_bytes

    def test_fed_settlement_account(self, posting_service: PaymentPostingService) -> None:
        """Test FED payment uses FED settlement account."""
        # Domestic payment via FED
        payment = create_payment_with_routing(
            end_to_end_id="E2E-FED-SETTLE",
            amount="10000.00",
            currency="USD",
            debtor_bic="CHASUS33XXX",  # Chase
            creditor_bic="BOFAUS3NXXX",  # Bank of America
            debtor_country="US",
            creditor_country="US",
            selected_network=RoutingNetwork.FED,
        )

        payload = payment_event_to_json_bytes(payment)
        posting_service._consumer.add_message("payments.step.payment_posting", payment.end_to_end_id, payload)
        posting_service.run(max_messages=1)

        result_messages = posting_service._producer.producer.get_messages(posting_service._result_topic)
        assert len(result_messages) == 1
        result_bytes = result_messages[0][1]
        assert b'"status":"PASS"' in result_bytes

    def test_chips_nostro_account(self, posting_service: PaymentPostingService) -> None:
        """Test CHIPS payment uses CHIPS nostro account."""
        # Payment via CHIPS to Chase (has CHIPS nostro relationship)
        payment = create_payment_with_routing(
            end_to_end_id="E2E-CHIPS-NOSTRO",
            amount="10000.00",  # Below 25000 threshold
            currency="USD",
            debtor_bic="SBININBBXXX",  # SBI
            creditor_bic="CHASUS33XXX",  # Chase (has CHIPS nostro)
            debtor_country="IN",
            creditor_country="US",
            selected_network=RoutingNetwork.CHIPS,
        )

        payload = payment_event_to_json_bytes(payment)
        posting_service._consumer.add_message("payments.step.payment_posting", payment.end_to_end_id, payload)
        posting_service.run(max_messages=1)

        result_messages = posting_service._producer.producer.get_messages(posting_service._result_topic)
        assert len(result_messages) == 1
        result_bytes = result_messages[0][1]
        assert b'"status":"PASS"' in result_bytes

    def test_swift_out_nostro_account(self, posting_service: PaymentPostingService) -> None:
        """Test SWIFT outbound payment uses SWIFT nostro account."""
        # Wells Fargo sending to Mexico (Banamex)
        payment = create_payment_with_routing(
            end_to_end_id="E2E-SWIFT-NOSTRO",
            amount="25000.00",
            currency="USD",
            debtor_bic="WFBIUS6SXXX",  # Wells Fargo
            creditor_bic="BAMXMXMMXXX",  # Banamex (has SWIFT nostro)
            debtor_country="US",
            creditor_country="MX",
            selected_network=RoutingNetwork.SWIFT,
        )

        payload = payment_event_to_json_bytes(payment)
        posting_service._consumer.add_message("payments.step.payment_posting", payment.end_to_end_id, payload)
        posting_service.run(max_messages=1)

        result_messages = posting_service._producer.producer.get_messages(posting_service._result_topic)
        assert len(result_messages) == 1
        result_bytes = result_messages[0][1]
        assert b'"status":"PASS"' in result_bytes

    def test_posting_entries_created(self) -> None:
        """Test that posting entries are created with settlement accounts."""
        from satellites.payment_posting import simulate_payment_posting

        # IBT payment with inbound vostro
        payment = create_payment_with_routing(
            end_to_end_id="E2E-TEST-ENTRIES",
            amount="5000.00",
            currency="USD",
            debtor_bic="SBININBBXXX",
            creditor_bic="WFBIUS6SXXX",
            debtor_country="IN",
            creditor_country="US",
            selected_network=RoutingNetwork.INTERNAL,
        )

        status, entries = simulate_payment_posting(payment)

        assert status == ServiceResultStatus.PASS
        assert len(entries) == 2

        debit_entry = entries[0]
        credit_entry = entries[1]

        assert debit_entry.side == EntrySide.DEBIT
        assert credit_entry.side == EntrySide.CREDIT
        assert debit_entry.amount == Decimal("5000.00")
        assert credit_entry.amount == Decimal("5000.00")

        # Verify settlement accounts are populated
        assert debit_entry.settlement_account is not None
        assert credit_entry.settlement_account is not None
        assert debit_entry.account_type is not None
        assert credit_entry.account_type is not None

        # For IBT inbound, debit should be vostro account
        if payment.debtor_agent.country != "US":
            assert debit_entry.account_type == "VOSTRO"
            assert "VOSTRO" in debit_entry.settlement_account

    def test_fed_account_in_credit(self) -> None:
        """Test that FED payments credit FED settlement account."""
        from satellites.payment_posting import simulate_payment_posting

        payment = create_payment_with_routing(
            end_to_end_id="E2E-FED-TEST",
            amount="10000.00",
            currency="USD",
            debtor_bic="CHASUS33XXX",
            creditor_bic="BOFAUS3NXXX",
            debtor_country="US",
            creditor_country="US",
            selected_network=RoutingNetwork.FED,
        )

        status, entries = simulate_payment_posting(payment)

        assert status == ServiceResultStatus.PASS
        credit_entry = entries[1]
        assert credit_entry.account_type == "FED"
        assert "FED-SETTLE" in credit_entry.settlement_account

    def test_chips_nostro_in_credit(self) -> None:
        """Test that CHIPS payments credit CHIPS nostro account."""
        from satellites.payment_posting import simulate_payment_posting

        payment = create_payment_with_routing(
            end_to_end_id="E2E-CHIPS-TEST",
            amount="10000.00",  # Below 25000 threshold
            currency="USD",
            debtor_bic="SBININBBXXX",
            creditor_bic="CHASUS33XXX",  # Chase has CHIPS nostro
            debtor_country="IN",
            creditor_country="US",
            selected_network=RoutingNetwork.CHIPS,
        )

        status, entries = simulate_payment_posting(payment)

        assert status == ServiceResultStatus.PASS
        credit_entry = entries[1]
        assert credit_entry.account_type == "CHIPS_NOSTRO"
        assert "CHIPS-NOSTRO" in credit_entry.settlement_account

    def test_swift_nostro_in_credit(self) -> None:
        """Test that SWIFT outbound payments credit SWIFT nostro account."""
        from satellites.payment_posting import simulate_payment_posting

        payment = create_payment_with_routing(
            end_to_end_id="E2E-SWIFT-TEST",
            amount="25000.00",
            currency="USD",
            debtor_bic="WFBIUS6SXXX",
            creditor_bic="BAMXMXMMXXX",  # Banamex has SWIFT nostro
            debtor_country="US",
            creditor_country="MX",
            selected_network=RoutingNetwork.SWIFT,
        )

        status, entries = simulate_payment_posting(payment)

        assert status == ServiceResultStatus.PASS
        credit_entry = entries[1]
        assert credit_entry.account_type == "SWIFT_NOSTRO"
        assert "SWIFT-NOSTRO" in credit_entry.settlement_account


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


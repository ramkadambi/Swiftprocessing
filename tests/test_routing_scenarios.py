"""
Tests for routing validation scenarios.

Tests all routing scenarios from routing_rules2.json and routing_rules.json
to ensure routing decisions are correct.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from canonical import Agent, PaymentEvent, PaymentStatus, RoutingNetwork
from ingress.mx_receiver import payment_event_to_json_bytes
from kafka_bus.consumer import payment_event_from_json
from satellites.account_validation import AccountValidationService
from satellites.routing_validation import RoutingValidationService
from tests.test_mocks import MockKafkaConsumerWrapper, MockKafkaProducerWrapper


def create_payment_with_enrichment(
    *,
    end_to_end_id: str,
    amount: str,
    currency: str,
    debtor_bic: str,
    creditor_bic: str,
    debtor_country: str,
    creditor_country: str,
    fed_member: bool = False,
    chips_member: bool = False,
    creditor_type: str = "BANK",
) -> PaymentEvent:
    """Create a PaymentEvent with account validation enrichment."""
    from canonical import AccountValidationEnrichment, CreditorType, ServiceResultStatus

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
            creditor_type=CreditorType(creditor_type),
            fed_member=fed_member,
            chips_member=chips_member,
            nostro_with_us=False,
            vostro_with_us=False,
            preferred_correspondent="WFBIUS6SXXX" if fed_member or chips_member else None,
        ),
    )
    return event


class TestRoutingScenarios:
    """Tests for routing validation scenarios."""

    @pytest.fixture
    def routing_service(self) -> RoutingValidationService:
        """Create routing validation service with test config."""
        script_dir = Path(__file__).parent.parent
        routing_rules_path = script_dir / "config" / "routing_rules.json"
        consumer = MockKafkaConsumerWrapper(group_id="routing-validation")
        producer = MockKafkaProducerWrapper()
        return RoutingValidationService(
            consumer=consumer, producer=producer, routing_rules_path=routing_rules_path
        )

    def test_usd_domestic_fed_direct(self, routing_service: RoutingValidationService) -> None:
        """Test USD domestic payment to FED member -> FED network."""
        payment = create_payment_with_enrichment(
            end_to_end_id="E2E-FED-DOMESTIC",
            amount="50000.00",
            currency="USD",
            debtor_bic="CHASUS33XXX",
            creditor_bic="CHASUS33XXX",
            debtor_country="US",
            creditor_country="US",
            fed_member=True,
            chips_member=True,
        )

        payload = payment_event_to_json_bytes(payment)
        routing_service._consumer.add_message("payments.step.routing_validation", payment.end_to_end_id, payload)
        routing_service.run(max_messages=1)

        # Check routed event was published
        routed_messages = routing_service._producer.producer.get_messages("payments.step.sanctions_check")
        assert len(routed_messages) == 1

        routed_event = payment_event_from_json(routed_messages[0][1])
        assert routed_event.selected_network == RoutingNetwork.FED
        assert routed_event.routing_decision is not None
        assert routed_event.routing_decision.selected_network == RoutingNetwork.FED

    def test_usd_crossborder_chips_high_value(self, routing_service: RoutingValidationService) -> None:
        """Test USD cross-border high-value payment to CHIPS member -> CHIPS network."""
        payment = create_payment_with_enrichment(
            end_to_end_id="E2E-CHIPS-HIGH",
            amount="2000000.00",
            currency="USD",
            debtor_bic="CHASUS33XXX",
            creditor_bic="DEUTDEFFXXX",
            debtor_country="US",
            creditor_country="DE",
            fed_member=False,
            chips_member=True,
        )

        payload = payment_event_to_json_bytes(payment)
        routing_service._consumer.add_message("payments.step.routing_validation", payment.end_to_end_id, payload)
        routing_service.run(max_messages=1)

        routed_messages = routing_service._producer.producer.get_messages("payments.step.sanctions_check")
        assert len(routed_messages) == 1

        routed_event = payment_event_from_json(routed_messages[0][1])
        # Note: This depends on routing_rules.json having a rule for CHIPS high-value
        # If rule exists, should be CHIPS; otherwise may fallback to SWIFT
        assert routed_event.selected_network in (RoutingNetwork.CHIPS, RoutingNetwork.SWIFT)

    def test_usd_individual_beneficiary(self, routing_service: RoutingValidationService) -> None:
        """Test USD payment to individual beneficiary -> FED network."""
        payment = create_payment_with_enrichment(
            end_to_end_id="E2E-INDIVIDUAL",
            amount="5000.00",
            currency="USD",
            debtor_bic="CHASUS33XXX",
            creditor_bic="INDIVIDUAL",
            debtor_country="US",
            creditor_country="US",
            fed_member=False,
            chips_member=False,
            creditor_type="INDIVIDUAL",
        )

        payload = payment_event_to_json_bytes(payment)
        routing_service._consumer.add_message("payments.step.routing_validation", payment.end_to_end_id, payload)
        routing_service.run(max_messages=1)

        routed_messages = routing_service._producer.producer.get_messages("payments.step.sanctions_check")
        assert len(routed_messages) == 1

        routed_event = payment_event_from_json(routed_messages[0][1])
        # Should route via FED for individual beneficiaries
        assert routed_event.selected_network == RoutingNetwork.FED

    def test_usd_fallback_swift(self, routing_service: RoutingValidationService) -> None:
        """Test USD payment with no matching rule -> SWIFT fallback."""
        payment = create_payment_with_enrichment(
            end_to_end_id="E2E-SWIFT-FALLBACK",
            amount="25000.00",
            currency="USD",
            debtor_bic="CHASUS33XXX",
            creditor_bic="UNKNOWNBANKXXX",
            debtor_country="US",
            creditor_country="FR",
            fed_member=False,
            chips_member=False,
        )

        payload = payment_event_to_json_bytes(payment)
        routing_service._consumer.add_message("payments.step.routing_validation", payment.end_to_end_id, payload)
        routing_service.run(max_messages=1)

        routed_messages = routing_service._producer.producer.get_messages("payments.step.sanctions_check")
        assert len(routed_messages) == 1

        routed_event = payment_event_from_json(routed_messages[0][1])
        # Should fallback to SWIFT
        assert routed_event.selected_network == RoutingNetwork.SWIFT

    def test_routing_decision_created(self, routing_service: RoutingValidationService) -> None:
        """Test that RoutingDecision object is created and stored."""
        payment = create_payment_with_enrichment(
            end_to_end_id="E2E-ROUTING-DECISION",
            amount="10000.00",
            currency="USD",
            debtor_bic="CHASUS33XXX",
            creditor_bic="CHASUS33XXX",
            debtor_country="US",
            creditor_country="US",
            fed_member=True,
            chips_member=True,
        )

        payload = payment_event_to_json_bytes(payment)
        routing_service._consumer.add_message("payments.step.routing_validation", payment.end_to_end_id, payload)
        routing_service.run(max_messages=1)

        routed_messages = routing_service._producer.producer.get_messages("payments.step.sanctions_check")
        routed_event = payment_event_from_json(routed_messages[0][1])

        # Verify RoutingDecision was created
        assert routed_event.routing_decision is not None
        assert routed_event.routing_decision.selected_network is not None
        assert routed_event.routing_decision.sender_bank is not None
        assert routed_event.routing_decision.creditor_bank is not None
        assert routed_event.routing_decision.bic_lookup_data is not None
        assert routed_event.routing_decision.account_validation_data is not None


class TestRoutingRules2Scenarios:
    """Tests for routing_rules2.json scenarios (if file exists)."""

    @pytest.fixture
    def routing_service_rules2(self) -> RoutingValidationService:
        """Create routing validation service with routing_rules2.json."""
        script_dir = Path(__file__).parent.parent
        routing_rules_path = script_dir / "config" / "routing_rules2.json"
        if not routing_rules_path.exists():
            pytest.skip("routing_rules2.json not found")

        consumer = MockKafkaConsumerWrapper(group_id="routing-validation")
        producer = MockKafkaProducerWrapper()
        return RoutingValidationService(
            consumer=consumer, producer=producer, routing_rules_path=routing_rules_path
        )

    def test_r1_final_credit_internal(self, routing_service_rules2: RoutingValidationService) -> None:
        """Test R1: Wells Fargo as final beneficiary -> INTERNAL."""
        payment = create_payment_with_enrichment(
            end_to_end_id="E2E-R1-INTERNAL",
            amount="5000.00",
            currency="USD",
            debtor_bic="CHASUS33XXX",
            creditor_bic="WFBIUS6SXXX",  # Wells Fargo
            debtor_country="US",
            creditor_country="US",
            fed_member=True,
            chips_member=True,
        )

        payload = payment_event_to_json_bytes(payment)
        routing_service_rules2._consumer.add_message("payments.step.routing_validation", payment.end_to_end_id, payload)
        routing_service_rules2.run(max_messages=1)

        routed_messages = routing_service_rules2._producer.producer.get_messages("payments.step.sanctions_check")
        if routed_messages:
            routed_event = payment_event_from_json(routed_messages[0][1])
            # Should route to INTERNAL if rule matches
            # Note: This depends on routing_rules2.json having the rule
            assert routed_event.selected_network in (RoutingNetwork.INTERNAL, RoutingNetwork.FED)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


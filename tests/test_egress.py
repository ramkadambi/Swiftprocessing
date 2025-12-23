"""
Comprehensive tests for payment egress service.

Tests all network dispatch scenarios:
- INTERNAL (IBT): Internal notification
- FED: pacs.008 generation
- CHIPS: pacs.009 generation
- SWIFT: MT103, MT202, MT202COV generation based on payment characteristics
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from canonical import Agent, PaymentEvent, PaymentStatus, RoutingNetwork
from egress import (
    canonical_to_mt103,
    canonical_to_mt202,
    canonical_to_mt202cov,
    canonical_to_mx,
    canonical_to_pacs009,
    payment_egress,
)
from tests.test_mocks import MockKafkaConsumerWrapper


def create_test_payment(
    *,
    end_to_end_id: str,
    amount: str,
    currency: str,
    debtor_bic: str,
    creditor_bic: str,
    selected_network: RoutingNetwork,
    debtor_country: str = "US",
    creditor_country: str = "US",
    intermediary_bic: str | None = None,
) -> PaymentEvent:
    """Create a test PaymentEvent."""
    agent_chain = None
    if intermediary_bic:
        agent_chain = [Agent(id_scheme="BIC", id_value=intermediary_bic, country="US")]

    return PaymentEvent(
        msg_id=f"TEST-{end_to_end_id}",
        end_to_end_id=end_to_end_id,
        amount=Decimal(amount),
        currency=currency,
        debtor_agent=Agent(id_scheme="BIC", id_value=debtor_bic, country=debtor_country),
        creditor_agent=Agent(id_scheme="BIC", id_value=creditor_bic, country=creditor_country),
        status=PaymentStatus.ACCEPTED,
        selected_network=selected_network,
        agent_chain=agent_chain,
    )


class TestEgressMessageFormatters:
    """Tests for individual message formatters."""

    def test_pacs008_fed(self) -> None:
        """Test pacs.008 generation for FED network."""
        payment = create_test_payment(
            end_to_end_id="E2E-FED-001",
            amount="10000.00",
            currency="USD",
            debtor_bic="CHASUS33XXX",
            creditor_bic="BOFAUS3NXXX",
            selected_network=RoutingNetwork.FED,
        )

        xml = canonical_to_mx.payment_event_to_pacs008_xml(payment)
        assert isinstance(xml, bytes)
        xml_str = xml.decode("utf-8")
        assert "pacs.008" in xml_str or "FIToFICstmrCdtTrf" in xml_str
        assert "E2E-FED-001" in xml_str
        assert "10000.00" in xml_str
        assert "CHASUS33XXX" in xml_str
        assert "BOFAUS3NXXX" in xml_str

    def test_pacs009_chips(self) -> None:
        """Test pacs.009 generation for CHIPS network."""
        payment = create_test_payment(
            end_to_end_id="E2E-CHIPS-001",
            amount="50000.00",
            currency="USD",
            debtor_bic="CHASUS33XXX",
            creditor_bic="BOFAUS3NXXX",
            selected_network=RoutingNetwork.CHIPS,
        )

        xml = canonical_to_pacs009.payment_event_to_pacs009_xml(payment)
        assert isinstance(xml, bytes)
        xml_str = xml.decode("utf-8")
        assert "pacs.009" in xml_str or "FICdtTrf" in xml_str
        assert "E2E-CHIPS-001" in xml_str
        assert "50000.00" in xml_str
        assert "CHASUS33XXX" in xml_str
        assert "BOFAUS3NXXX" in xml_str

    def test_mt103_direct_customer_transfer(self) -> None:
        """Test MT103 generation for direct customer credit transfer (no intermediary)."""
        payment = create_test_payment(
            end_to_end_id="E2E-MT103-001",
            amount="25000.00",
            currency="USD",
            debtor_bic="CHASUS33XXX",
            creditor_bic="SBININBBXXX",
            selected_network=RoutingNetwork.SWIFT,
            debtor_country="US",
            creditor_country="IN",
            intermediary_bic=None,  # No intermediary = direct transfer
        )

        mt103 = canonical_to_mt103.payment_event_to_mt103(payment)
        assert isinstance(mt103, str)
        assert ":20:TEST-E2E-MT103-001" in mt103
        assert ":23B:CRED" in mt103
        assert "USD25000,00" in mt103
        assert ":57A:SBININBBXXX" in mt103
        assert ":59:" in mt103  # Beneficiary

    def test_mt202_domestic_cover_payment(self) -> None:
        """Test MT202 generation for domestic (US to US) cover payment."""
        payment = create_test_payment(
            end_to_end_id="E2E-MT202-001",
            amount="75000.00",
            currency="USD",
            debtor_bic="CHASUS33XXX",
            creditor_bic="BOFAUS3NXXX",
            selected_network=RoutingNetwork.SWIFT,
            debtor_country="US",
            creditor_country="US",
            intermediary_bic="WFBIUS6SXXX",  # Has intermediary = cover payment
        )

        mt202 = canonical_to_mt202.payment_event_to_mt202(payment)
        assert isinstance(mt202, str)
        assert ":20:TEST-E2E-MT202-001" in mt202
        assert ":21:E2E-MT202-001" in mt202
        assert "USD75000,00" in mt202
        assert ":56A:WFBIUS6SXXX" in mt202  # Intermediary
        assert ":57A:BOFAUS3NXXX" in mt202
        assert ":58A:BOFAUS3NXXX" in mt202

    def test_mt202cov_international_cover_payment(self) -> None:
        """Test MT202COV generation for international cover payment."""
        payment = create_test_payment(
            end_to_end_id="E2E-MT202COV-001",
            amount="100000.00",
            currency="USD",
            debtor_bic="CHASUS33XXX",
            creditor_bic="SBININBBXXX",
            selected_network=RoutingNetwork.SWIFT,
            debtor_country="US",
            creditor_country="IN",  # International
            intermediary_bic="WFBIUS6SXXX",  # Has intermediary = cover payment
        )

        mt202cov = canonical_to_mt202cov.payment_event_to_mt202cov(payment)
        assert isinstance(mt202cov, str)
        assert ":20:TEST-E2E-MT202COV-001" in mt202cov
        assert ":21:E2E-MT202COV-001" in mt202cov
        assert "USD100000,00" in mt202cov
        assert ":56A:WFBIUS6SXXX" in mt202cov  # Intermediary
        assert ":50K:" in mt202cov  # Ordering customer (underlying)
        assert ":59:" in mt202cov  # Beneficiary customer (underlying)


class TestEgressDispatchLogic:
    """Tests for egress dispatch decision logic."""

    def test_determine_swift_message_type_mt103(self) -> None:
        """Test MT103 selection for direct customer transfer (no intermediary)."""
        payment = create_test_payment(
            end_to_end_id="E2E-SWIFT-001",
            amount="5000.00",
            currency="USD",
            debtor_bic="CHASUS33XXX",
            creditor_bic="SBININBBXXX",
            selected_network=RoutingNetwork.SWIFT,
            debtor_country="US",
            creditor_country="IN",
            intermediary_bic=None,  # No intermediary
        )

        msg_type = payment_egress._determine_swift_message_type(payment)
        assert msg_type == "MT103"

    def test_determine_swift_message_type_mt202_domestic(self) -> None:
        """Test MT202 selection for domestic cover payment."""
        payment = create_test_payment(
            end_to_end_id="E2E-SWIFT-002",
            amount="10000.00",
            currency="USD",
            debtor_bic="CHASUS33XXX",
            creditor_bic="BOFAUS3NXXX",
            selected_network=RoutingNetwork.SWIFT,
            debtor_country="US",
            creditor_country="US",  # Domestic
            intermediary_bic="WFBIUS6SXXX",  # Has intermediary
        )

        msg_type = payment_egress._determine_swift_message_type(payment)
        assert msg_type == "MT202"

    def test_determine_swift_message_type_mt202cov_international(self) -> None:
        """Test MT202COV selection for international cover payment."""
        payment = create_test_payment(
            end_to_end_id="E2E-SWIFT-003",
            amount="15000.00",
            currency="USD",
            debtor_bic="CHASUS33XXX",
            creditor_bic="SBININBBXXX",
            selected_network=RoutingNetwork.SWIFT,
            debtor_country="US",
            creditor_country="IN",  # International
            intermediary_bic="WFBIUS6SXXX",  # Has intermediary
        )

        msg_type = payment_egress._determine_swift_message_type(payment)
        assert msg_type == "MT202COV"

    def test_dispatch_internal(self) -> None:
        """Test INTERNAL network dispatch."""
        payment = create_test_payment(
            end_to_end_id="E2E-INTERNAL-001",
            amount="5000.00",
            currency="USD",
            debtor_bic="SBININBBXXX",
            creditor_bic="WFBIUS6SXXX",
            selected_network=RoutingNetwork.INTERNAL,
        )

        network_name, message = payment_egress._dispatch_payment(payment)
        assert network_name == "INTERNAL"
        assert isinstance(message, str)
        assert "INTERNAL_NOTIFICATION" in message
        assert "E2E-INTERNAL-001" in message

    def test_dispatch_fed(self) -> None:
        """Test FED network dispatch."""
        payment = create_test_payment(
            end_to_end_id="E2E-FED-002",
            amount="20000.00",
            currency="USD",
            debtor_bic="CHASUS33XXX",
            creditor_bic="BOFAUS3NXXX",
            selected_network=RoutingNetwork.FED,
        )

        network_name, message = payment_egress._dispatch_payment(payment)
        assert network_name == "FED"
        assert isinstance(message, bytes)
        xml_str = message.decode("utf-8")
        assert "FIToFICstmrCdtTrf" in xml_str

    def test_dispatch_chips(self) -> None:
        """Test CHIPS network dispatch."""
        payment = create_test_payment(
            end_to_end_id="E2E-CHIPS-002",
            amount="30000.00",
            currency="USD",
            debtor_bic="CHASUS33XXX",
            creditor_bic="BOFAUS3NXXX",
            selected_network=RoutingNetwork.CHIPS,
        )

        network_name, message = payment_egress._dispatch_payment(payment)
        assert network_name == "CHIPS"
        assert isinstance(message, bytes)
        xml_str = message.decode("utf-8")
        assert "FICdtTrf" in xml_str

    def test_dispatch_swift_mt103(self) -> None:
        """Test SWIFT MT103 dispatch."""
        payment = create_test_payment(
            end_to_end_id="E2E-SWIFT-MT103",
            amount="40000.00",
            currency="USD",
            debtor_bic="CHASUS33XXX",
            creditor_bic="SBININBBXXX",
            selected_network=RoutingNetwork.SWIFT,
            debtor_country="US",
            creditor_country="IN",
            intermediary_bic=None,
        )

        network_name, message = payment_egress._dispatch_payment(payment)
        assert network_name == "SWIFT_MT103"
        assert isinstance(message, str)
        assert ":23B:CRED" in message

    def test_dispatch_swift_mt202(self) -> None:
        """Test SWIFT MT202 dispatch."""
        payment = create_test_payment(
            end_to_end_id="E2E-SWIFT-MT202",
            amount="50000.00",
            currency="USD",
            debtor_bic="CHASUS33XXX",
            creditor_bic="BOFAUS3NXXX",
            selected_network=RoutingNetwork.SWIFT,
            debtor_country="US",
            creditor_country="US",
            intermediary_bic="WFBIUS6SXXX",
        )

        network_name, message = payment_egress._dispatch_payment(payment)
        assert network_name == "SWIFT_MT202"
        assert isinstance(message, str)
        assert ":58A:" in message

    def test_dispatch_swift_mt202cov(self) -> None:
        """Test SWIFT MT202COV dispatch."""
        payment = create_test_payment(
            end_to_end_id="E2E-SWIFT-MT202COV",
            amount="60000.00",
            currency="USD",
            debtor_bic="CHASUS33XXX",
            creditor_bic="SBININBBXXX",
            selected_network=RoutingNetwork.SWIFT,
            debtor_country="US",
            creditor_country="IN",
            intermediary_bic="WFBIUS6SXXX",
        )

        network_name, message = payment_egress._dispatch_payment(payment)
        assert network_name == "SWIFT_MT202COV"
        assert isinstance(message, str)
        assert ":50K:" in message  # Underlying customer details
        assert ":59:" in message


class TestPaymentEgressService:
    """Tests for PaymentEgressService integration."""

    @pytest.fixture
    def egress_service(self) -> payment_egress.PaymentEgressService:
        """Create egress service with mock consumer."""
        consumer = MockKafkaConsumerWrapper(group_id="test-egress")
        return payment_egress.PaymentEgressService(consumer=consumer)

    def test_egress_service_handles_fed_payment(self, egress_service: payment_egress.PaymentEgressService) -> None:
        """Test egress service processes FED payment."""
        payment = create_test_payment(
            end_to_end_id="E2E-EGRESS-FED",
            amount="10000.00",
            currency="USD",
            debtor_bic="CHASUS33XXX",
            creditor_bic="BOFAUS3NXXX",
            selected_network=RoutingNetwork.FED,
        )

        from ingress.mx_receiver import payment_event_to_json_bytes

        payload = payment_event_to_json_bytes(payment)
        egress_service._consumer.add_message("payments.final", payment.end_to_end_id, payload)
        egress_service.run(max_messages=1)

        # Service should have processed the payment without errors
        # (we can't easily verify the dispatch without network adapters, but no exception = success)

    def test_egress_service_handles_swift_mt103(self, egress_service: payment_egress.PaymentEgressService) -> None:
        """Test egress service processes SWIFT MT103 payment."""
        payment = create_test_payment(
            end_to_end_id="E2E-EGRESS-SWIFT-MT103",
            amount="20000.00",
            currency="USD",
            debtor_bic="CHASUS33XXX",
            creditor_bic="SBININBBXXX",
            selected_network=RoutingNetwork.SWIFT,
            debtor_country="US",
            creditor_country="IN",
            intermediary_bic=None,
        )

        from ingress.mx_receiver import payment_event_to_json_bytes

        payload = payment_event_to_json_bytes(payment)
        egress_service._consumer.add_message("payments.final", payment.end_to_end_id, payload)
        egress_service.run(max_messages=1)

        # Service should have processed the payment without errors


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


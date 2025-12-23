"""
Integration tests for ledger service with balance check and payment posting.

Tests the full flow:
1. Balance check reads from ledger
2. Payment posting writes to ledger
3. Double posting detection works
"""

from __future__ import annotations

import tempfile
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
from satellites.balance_check import BalanceCheckService, simulate_balance_check
from satellites.ledger_service import (
    get_account_balance,
    initialize_account,
    is_transaction_processed,
)
from satellites.payment_posting import PaymentPostingService, simulate_payment_posting
from tests.test_mocks import MockKafkaConsumerWrapper, MockKafkaProducerWrapper


@pytest.fixture
def temp_ledger_file() -> Path:
    """Create a temporary ledger file with test accounts."""
    import tempfile
    import satellites.ledger_service
    
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        f.write('{"accounts": {}, "processed_transactions": {}}')
        temp_path = Path(f.name)
    
    # Save original path and set temp path
    original_path = satellites.ledger_service.DEFAULT_LEDGER_PATH
    satellites.ledger_service.DEFAULT_LEDGER_PATH = temp_path
    
    # Initialize test accounts
    initialize_account("WF-VOSTRO-SBI-USD-001", Decimal("1000000.00"), ledger_path=temp_path)
    initialize_account("WFBIUS6S", Decimal("50000.00"), ledger_path=temp_path)
    initialize_account("WF-FED-SETTLE-001", Decimal("50000000.00"), ledger_path=temp_path)
    
    yield temp_path
    
    # Restore original path
    satellites.ledger_service.DEFAULT_LEDGER_PATH = original_path
    
    # Cleanup
    if temp_path.exists():
        temp_path.unlink()


class TestBalanceCheckWithLedger:
    """Tests for balance check using ledger."""

    def test_balance_check_sufficient_funds(self, temp_ledger_file: Path) -> None:
        """Test balance check passes when account has sufficient funds."""
        try:
            payment = PaymentEvent(
                msg_id="TEST-001",
                end_to_end_id="E2E-001",
                amount=Decimal("5000.00"),
                currency="USD",
                debtor_agent=Agent(id_scheme="BIC", id_value="SBININBBXXX", country="IN"),
                creditor_agent=Agent(id_scheme="BIC", id_value="WFBIUS6SXXX", country="US"),
                status=PaymentStatus.RECEIVED,
                account_validation=AccountValidationEnrichment(
                    status=ServiceResultStatus.PASS,
                    creditor_type=CreditorType.BANK,
                    fed_member=False,
                    chips_member=False,
                    nostro_with_us=False,
                    vostro_with_us=False,
                    preferred_correspondent=None,
                ),
                selected_network=RoutingNetwork.INTERNAL,
            )
            
            status = simulate_balance_check(payment)
            assert status == ServiceResultStatus.PASS
        finally:
            pass  # Fixture handles cleanup

    def test_balance_check_insufficient_funds(self, temp_ledger_file: Path) -> None:
        """Test balance check fails when account has insufficient funds."""
        try:
            # Try to debit more than available
            payment = PaymentEvent(
                msg_id="TEST-002",
                end_to_end_id="E2E-002",
                amount=Decimal("2000000.00"),  # More than available in vostro account
                currency="USD",
                debtor_agent=Agent(id_scheme="BIC", id_value="SBININBBXXX", country="IN"),
                creditor_agent=Agent(id_scheme="BIC", id_value="WFBIUS6SXXX", country="US"),
                status=PaymentStatus.RECEIVED,
                account_validation=AccountValidationEnrichment(
                    status=ServiceResultStatus.PASS,
                    creditor_type=CreditorType.BANK,
                    fed_member=False,
                    chips_member=False,
                    nostro_with_us=False,
                    vostro_with_us=False,
                    preferred_correspondent=None,
                ),
                selected_network=RoutingNetwork.INTERNAL,
            )
            
            status = simulate_balance_check(payment)
            assert status == ServiceResultStatus.FAIL
        finally:
            pass  # Fixture handles cleanup


class TestPaymentPostingWithLedger:
    """Tests for payment posting with ledger integration."""

    def test_payment_posting_updates_ledger(self, temp_ledger_file: Path) -> None:
        """Test payment posting successfully updates ledger balances."""
        try:
            import uuid
            unique_id = f"E2E-TEST-{uuid.uuid4().hex[:8]}"
            payment = PaymentEvent(
                msg_id=f"TEST-{unique_id}",
                end_to_end_id=unique_id,
                amount=Decimal("10000.00"),
                currency="USD",
                debtor_agent=Agent(id_scheme="BIC", id_value="SBININBBXXX", country="IN"),
                creditor_agent=Agent(id_scheme="BIC", id_value="WFBIUS6SXXX", country="US"),
                status=PaymentStatus.RECEIVED,
                account_validation=AccountValidationEnrichment(
                    status=ServiceResultStatus.PASS,
                    creditor_type=CreditorType.BANK,
                    fed_member=False,
                    chips_member=False,
                    nostro_with_us=False,
                    vostro_with_us=False,
                    preferred_correspondent=None,
                ),
                selected_network=RoutingNetwork.INTERNAL,
            )
            
            # Get initial balances (read directly from temp file)
            import satellites.ledger_service as ledger_svc
            assert ledger_svc.DEFAULT_LEDGER_PATH == temp_ledger_file
            
            initial_debit = get_account_balance("WF-VOSTRO-SBI-USD-001", temp_ledger_file)
            initial_credit = get_account_balance("WFBIUS6S", temp_ledger_file)
            
            # Simulate posting
            status, entries = simulate_payment_posting(payment)
            assert status == ServiceResultStatus.PASS
            assert len(entries) == 2
            
            # Create service and post to ledger
            consumer = MockKafkaConsumerWrapper(group_id="test-posting")
            producer = MockKafkaProducerWrapper()
            service = PaymentPostingService(consumer=consumer, producer=producer)
            
            # Handle event (this will post to ledger)
            result = service._handle_event(payment)
            
            assert result.status == ServiceResultStatus.PASS
            
            # Verify balances updated (re-read using temp ledger file)
            # Force re-read by ensuring we use the temp file
            final_debit = get_account_balance("WF-VOSTRO-SBI-USD-001", temp_ledger_file)
            final_credit = get_account_balance("WFBIUS6S", temp_ledger_file)
            
            # Convert to Decimal for comparison
            expected_debit = Decimal(str(initial_debit)) - payment.amount
            expected_credit = Decimal(str(initial_credit)) + payment.amount
            
            assert final_debit == expected_debit
            assert final_credit == expected_credit
            
            # Verify transaction marked as processed
            assert is_transaction_processed(unique_id, temp_ledger_file) is True
        finally:
            pass  # Fixture handles cleanup

    def test_payment_posting_double_posting_detection(self, temp_ledger_file: Path) -> None:
        """Test payment posting detects double posting."""
        try:
            import uuid
            unique_id = f"E2E-TEST-{uuid.uuid4().hex[:8]}"
            payment = PaymentEvent(
                msg_id=f"TEST-{unique_id}",
                end_to_end_id=unique_id,
                amount=Decimal("5000.00"),
                currency="USD",
                debtor_agent=Agent(id_scheme="BIC", id_value="SBININBBXXX", country="IN"),
                creditor_agent=Agent(id_scheme="BIC", id_value="WFBIUS6SXXX", country="US"),
                status=PaymentStatus.RECEIVED,
                account_validation=AccountValidationEnrichment(
                    status=ServiceResultStatus.PASS,
                    creditor_type=CreditorType.BANK,
                    fed_member=False,
                    chips_member=False,
                    nostro_with_us=False,
                    vostro_with_us=False,
                    preferred_correspondent=None,
                ),
                selected_network=RoutingNetwork.INTERNAL,
            )
            
            # Get initial balances
            initial_debit = get_account_balance("WF-VOSTRO-SBI-USD-001", temp_ledger_file)
            initial_credit = get_account_balance("WFBIUS6S", temp_ledger_file)
            
            # First posting
            consumer1 = MockKafkaConsumerWrapper(group_id="test-posting-1")
            producer1 = MockKafkaProducerWrapper()
            service1 = PaymentPostingService(consumer=consumer1, producer=producer1)
            result1 = service1._handle_event(payment)
            
            assert result1.status == ServiceResultStatus.PASS
            
            # Second posting (double posting attempt)
            consumer2 = MockKafkaConsumerWrapper(group_id="test-posting-2")
            producer2 = MockKafkaProducerWrapper()
            service2 = PaymentPostingService(consumer=consumer2, producer=producer2)
            result2 = service2._handle_event(payment)
            
            assert result2.status == ServiceResultStatus.ERROR  # Should detect double posting
            
            # Verify balances only updated once (re-read using temp ledger file)
            final_debit = get_account_balance("WF-VOSTRO-SBI-USD-001", temp_ledger_file)
            final_credit = get_account_balance("WFBIUS6S", temp_ledger_file)
            
            # Convert to Decimal for comparison
            expected_debit = Decimal(str(initial_debit)) - payment.amount
            expected_credit = Decimal(str(initial_credit)) + payment.amount
            
            assert final_debit == expected_debit
            assert final_credit == expected_credit
        finally:
            pass  # Fixture handles cleanup


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


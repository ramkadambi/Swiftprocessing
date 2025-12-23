"""
Tests for ledger service functionality.

Tests account balance management, transaction posting, and double-posting detection.
"""

from __future__ import annotations

import json
import tempfile
from decimal import Decimal
from pathlib import Path

import pytest

from satellites.ledger_service import (
    get_account_balance,
    get_ledger_summary,
    has_sufficient_balance,
    initialize_account,
    is_transaction_processed,
    post_transaction,
)
from satellites.payment_posting import EntrySide, PostingEntry


@pytest.fixture
def temp_ledger_file() -> Path:
    """Create a temporary ledger file for testing."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        f.write(json.dumps({"accounts": {}, "processed_transactions": {}}))
        temp_path = Path(f.name)
    
    yield temp_path
    
    # Cleanup
    if temp_path.exists():
        temp_path.unlink()


class TestLedgerAccountManagement:
    """Tests for account initialization and balance queries."""

    def test_initialize_account(self, temp_ledger_file: Path) -> None:
        """Test initializing an account with opening balance."""
        initialize_account(
            "TEST-ACCOUNT-001",
            opening_balance=Decimal("1000.00"),
            currency="USD",
            account_type="CUSTOMER",
            ledger_path=temp_ledger_file,
        )
        
        balance = get_account_balance("TEST-ACCOUNT-001", temp_ledger_file)
        assert balance == Decimal("1000.00")

    def test_get_account_balance_existing(self, temp_ledger_file: Path) -> None:
        """Test getting balance for existing account."""
        initialize_account("TEST-ACCOUNT-002", Decimal("5000.00"), ledger_path=temp_ledger_file)
        
        balance = get_account_balance("TEST-ACCOUNT-002", temp_ledger_file)
        assert balance == Decimal("5000.00")

    def test_get_account_balance_nonexistent(self, temp_ledger_file: Path) -> None:
        """Test getting balance for non-existent account returns None."""
        balance = get_account_balance("NONEXISTENT", temp_ledger_file)
        assert balance is None

    def test_has_sufficient_balance_sufficient(self, temp_ledger_file: Path) -> None:
        """Test sufficient balance check when account has enough funds."""
        initialize_account("TEST-ACCOUNT-003", Decimal("10000.00"), ledger_path=temp_ledger_file)
        
        assert has_sufficient_balance("TEST-ACCOUNT-003", Decimal("5000.00"), temp_ledger_file) is True
        assert has_sufficient_balance("TEST-ACCOUNT-003", Decimal("10000.00"), temp_ledger_file) is True

    def test_has_sufficient_balance_insufficient(self, temp_ledger_file: Path) -> None:
        """Test sufficient balance check when account has insufficient funds."""
        initialize_account("TEST-ACCOUNT-004", Decimal("1000.00"), ledger_path=temp_ledger_file)
        
        assert has_sufficient_balance("TEST-ACCOUNT-004", Decimal("2000.00"), temp_ledger_file) is False

    def test_has_sufficient_balance_nonexistent_account(self, temp_ledger_file: Path) -> None:
        """Test sufficient balance check for non-existent account returns False."""
        assert has_sufficient_balance("NONEXISTENT", Decimal("100.00"), temp_ledger_file) is False


class TestTransactionPosting:
    """Tests for transaction posting and double-posting detection."""

    def test_post_transaction_success(self, temp_ledger_file: Path) -> None:
        """Test successful transaction posting."""
        # Initialize accounts
        initialize_account("DEBIT-ACCOUNT", Decimal("10000.00"), ledger_path=temp_ledger_file)
        initialize_account("CREDIT-ACCOUNT", Decimal("5000.00"), ledger_path=temp_ledger_file)
        
        # Create posting entries
        entries = [
            PostingEntry(
                end_to_end_id="E2E-001",
                side=EntrySide.DEBIT,
                agent_id="DEBIT-AGENT",
                amount=Decimal("2000.00"),
                currency="USD",
                settlement_account="DEBIT-ACCOUNT",
                account_type="CUSTOMER",
            ),
            PostingEntry(
                end_to_end_id="E2E-001",
                side=EntrySide.CREDIT,
                agent_id="CREDIT-AGENT",
                amount=Decimal("2000.00"),
                currency="USD",
                settlement_account="CREDIT-ACCOUNT",
                account_type="CUSTOMER",
            ),
        ]
        
        # Post transaction
        success, error = post_transaction(entries, "E2E-001", temp_ledger_file)
        
        assert success is True
        assert error is None
        
        # Verify balances updated
        assert get_account_balance("DEBIT-ACCOUNT", temp_ledger_file) == Decimal("8000.00")
        assert get_account_balance("CREDIT-ACCOUNT", temp_ledger_file) == Decimal("7000.00")
        
        # Verify transaction marked as processed
        assert is_transaction_processed("E2E-001", temp_ledger_file) is True

    def test_post_transaction_double_posting(self, temp_ledger_file: Path) -> None:
        """Test double posting detection."""
        # Initialize accounts
        initialize_account("DEBIT-ACCOUNT", Decimal("10000.00"), ledger_path=temp_ledger_file)
        initialize_account("CREDIT-ACCOUNT", Decimal("5000.00"), ledger_path=temp_ledger_file)
        
        entries = [
            PostingEntry(
                end_to_end_id="E2E-002",
                side=EntrySide.DEBIT,
                agent_id="DEBIT-AGENT",
                amount=Decimal("1000.00"),
                currency="USD",
                settlement_account="DEBIT-ACCOUNT",
                account_type="CUSTOMER",
            ),
            PostingEntry(
                end_to_end_id="E2E-002",
                side=EntrySide.CREDIT,
                agent_id="CREDIT-AGENT",
                amount=Decimal("1000.00"),
                currency="USD",
                settlement_account="CREDIT-ACCOUNT",
                account_type="CUSTOMER",
            ),
        ]
        
        # First posting should succeed
        success1, error1 = post_transaction(entries, "E2E-002", temp_ledger_file)
        assert success1 is True
        
        # Second posting should fail (double posting)
        success2, error2 = post_transaction(entries, "E2E-002", temp_ledger_file)
        assert success2 is False
        assert "already processed" in error2.lower() if error2 else False
        
        # Verify balances only updated once
        assert get_account_balance("DEBIT-ACCOUNT", temp_ledger_file) == Decimal("9000.00")
        assert get_account_balance("CREDIT-ACCOUNT", temp_ledger_file) == Decimal("6000.00")

    def test_post_transaction_insufficient_balance(self, temp_ledger_file: Path) -> None:
        """Test posting fails when debit account has insufficient balance."""
        initialize_account("DEBIT-ACCOUNT", Decimal("1000.00"), ledger_path=temp_ledger_file)
        initialize_account("CREDIT-ACCOUNT", Decimal("5000.00"), ledger_path=temp_ledger_file)
        
        entries = [
            PostingEntry(
                end_to_end_id="E2E-003",
                side=EntrySide.DEBIT,
                agent_id="DEBIT-AGENT",
                amount=Decimal("2000.00"),  # More than available
                currency="USD",
                settlement_account="DEBIT-ACCOUNT",
                account_type="CUSTOMER",
            ),
            PostingEntry(
                end_to_end_id="E2E-003",
                side=EntrySide.CREDIT,
                agent_id="CREDIT-AGENT",
                amount=Decimal("2000.00"),
                currency="USD",
                settlement_account="CREDIT-ACCOUNT",
                account_type="CUSTOMER",
            ),
        ]
        
        success, error = post_transaction(entries, "E2E-003", temp_ledger_file)
        
        assert success is False
        assert "insufficient balance" in error.lower() if error else False
        
        # Verify balances unchanged
        assert get_account_balance("DEBIT-ACCOUNT", temp_ledger_file) == Decimal("1000.00")
        assert get_account_balance("CREDIT-ACCOUNT", temp_ledger_file) == Decimal("5000.00")

    def test_post_transaction_missing_account(self, temp_ledger_file: Path) -> None:
        """Test posting fails when account doesn't exist."""
        initialize_account("CREDIT-ACCOUNT", Decimal("5000.00"), ledger_path=temp_ledger_file)
        
        entries = [
            PostingEntry(
                end_to_end_id="E2E-004",
                side=EntrySide.DEBIT,
                agent_id="DEBIT-AGENT",
                amount=Decimal("1000.00"),
                currency="USD",
                settlement_account="NONEXISTENT-ACCOUNT",
                account_type="CUSTOMER",
            ),
            PostingEntry(
                end_to_end_id="E2E-004",
                side=EntrySide.CREDIT,
                agent_id="CREDIT-AGENT",
                amount=Decimal("1000.00"),
                currency="USD",
                settlement_account="CREDIT-ACCOUNT",
                account_type="CUSTOMER",
            ),
        ]
        
        success, error = post_transaction(entries, "E2E-004", temp_ledger_file)
        
        assert success is False
        assert "not found" in error.lower() if error else False

    def test_post_transaction_missing_entries(self, temp_ledger_file: Path) -> None:
        """Test posting fails when debit or credit entry is missing."""
        initialize_account("DEBIT-ACCOUNT", Decimal("10000.00"), ledger_path=temp_ledger_file)
        
        # Only debit entry, no credit
        entries = [
            PostingEntry(
                end_to_end_id="E2E-005",
                side=EntrySide.DEBIT,
                agent_id="DEBIT-AGENT",
                amount=Decimal("1000.00"),
                currency="USD",
                settlement_account="DEBIT-ACCOUNT",
                account_type="CUSTOMER",
            ),
        ]
        
        success, error = post_transaction(entries, "E2E-005", temp_ledger_file)
        
        assert success is False
        assert "missing" in error.lower() if error else False


class TestLedgerSummary:
    """Tests for ledger summary functionality."""

    def test_get_ledger_summary(self, temp_ledger_file: Path) -> None:
        """Test getting ledger summary."""
        initialize_account("ACCOUNT-001", Decimal("1000.00"), ledger_path=temp_ledger_file)
        initialize_account("ACCOUNT-002", Decimal("2000.00"), ledger_path=temp_ledger_file)
        
        summary = get_ledger_summary(temp_ledger_file)
        
        assert summary["total_accounts"] == 2
        assert summary["total_processed_transactions"] == 0
        assert "ACCOUNT-001" in summary["accounts"]
        assert "ACCOUNT-002" in summary["accounts"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


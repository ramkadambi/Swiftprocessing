"""
Tests for settlement account lookup utility.

Tests all lookup functions for:
- Vostro accounts (foreign bank accounts at Wells Fargo for inbound)
- FED account (Wells Fargo's Federal Reserve settlement account)
- CHIPS nostro accounts (CHIPS participant accounts at Wells Fargo)
- SWIFT out nostro accounts (foreign bank accounts at Wells Fargo for outbound)
"""

from __future__ import annotations

import pytest

from satellites.settlement_account_lookup import (
    get_chips_nostro_account_number,
    get_fed_account_number,
    get_swift_out_nostro_account_number,
    get_vostro_account_number,
    has_chips_nostro_relationship,
    has_swift_out_nostro_account,
    has_vostro_account,
    lookup_chips_nostro_account,
    lookup_fed_account,
    lookup_swift_out_nostro_account,
    lookup_vostro_account,
)


class TestVostroAccountLookup:
    """Tests for vostro account lookup (foreign bank accounts for inbound payments)."""

    def test_lookup_existing_vostro_account(self) -> None:
        """Test lookup of existing vostro account."""
        result = lookup_vostro_account("SBININBBXXX")
        assert result is not None
        assert result["account_number"] == "WF-VOSTRO-SBI-USD-001"
        assert result["bank_name"] == "State Bank of India"
        assert result["currency"] == "USD"
        assert result["country"] == "IN"

    def test_lookup_nonexistent_vostro_account(self) -> None:
        """Test lookup of non-existent vostro account."""
        result = lookup_vostro_account("UNKNOWNBANK")
        assert result is None

    def test_get_vostro_account_number(self) -> None:
        """Test helper function to get account number."""
        account_num = get_vostro_account_number("SBININBBXXX")
        assert account_num == "WF-VOSTRO-SBI-USD-001"

    def test_has_vostro_account(self) -> None:
        """Test helper function to check if vostro account exists."""
        assert has_vostro_account("SBININBBXXX") is True
        assert has_vostro_account("UNKNOWNBANK") is False


class TestFedAccountLookup:
    """Tests for FED account lookup (Wells Fargo's Federal Reserve settlement account)."""

    def test_lookup_fed_account(self) -> None:
        """Test lookup of FED account."""
        result = lookup_fed_account()
        assert result is not None
        assert result["account_number"] == "WF-FED-SETTLE-001"
        assert result["account_name"] == "Wells Fargo FED Settlement Account"
        assert result["routing_number"] == "121000248"

    def test_get_fed_account_number(self) -> None:
        """Test helper function to get FED account number."""
        account_num = get_fed_account_number()
        assert account_num == "WF-FED-SETTLE-001"


class TestChipsNostroAccountLookup:
    """Tests for CHIPS nostro account lookup (CHIPS participant accounts at Wells Fargo)."""

    def test_lookup_existing_chips_nostro_account(self) -> None:
        """Test lookup of existing CHIPS nostro account."""
        result = lookup_chips_nostro_account("CHASUS33XXX")
        assert result is not None
        assert result["account_number"] == "WF-CHIPS-NOSTRO-CHASE-001"
        assert result["bank_name"] == "JPMorgan Chase Bank NA"
        assert result["chips_uid"] == "0002"
        assert result["currency"] == "USD"

    def test_lookup_nonexistent_chips_nostro_account(self) -> None:
        """Test lookup of non-existent CHIPS nostro account (should route via FED)."""
        result = lookup_chips_nostro_account("UNKNOWNBANK")
        assert result is None

    def test_get_chips_nostro_account_number(self) -> None:
        """Test helper function to get CHIPS nostro account number."""
        account_num = get_chips_nostro_account_number("CHASUS33XXX")
        assert account_num == "WF-CHIPS-NOSTRO-CHASE-001"

    def test_has_chips_nostro_relationship(self) -> None:
        """Test helper function to check if CHIPS nostro relationship exists."""
        assert has_chips_nostro_relationship("CHASUS33XXX") is True
        assert has_chips_nostro_relationship("UNKNOWNBANK") is False


class TestSwiftOutNostroAccountLookup:
    """Tests for SWIFT out nostro account lookup (foreign bank accounts for outbound payments)."""

    def test_lookup_existing_swift_out_nostro_account(self) -> None:
        """Test lookup of existing SWIFT out nostro account."""
        result = lookup_swift_out_nostro_account("BAMXMXMMXXX")
        assert result is not None
        assert result["account_number"] == "WF-SWIFT-NOSTRO-BANAMEX-001"
        assert result["bank_name"] == "Banco Nacional de Mexico"
        assert result["currency"] == "USD"
        assert result["country"] == "MX"

    def test_lookup_nonexistent_swift_out_nostro_account(self) -> None:
        """Test lookup of non-existent SWIFT out nostro account."""
        result = lookup_swift_out_nostro_account("UNKNOWNBANK")
        assert result is None

    def test_get_swift_out_nostro_account_number(self) -> None:
        """Test helper function to get SWIFT out nostro account number."""
        account_num = get_swift_out_nostro_account_number("BAMXMXMMXXX")
        assert account_num == "WF-SWIFT-NOSTRO-BANAMEX-001"

    def test_has_swift_out_nostro_account(self) -> None:
        """Test helper function to check if SWIFT out nostro account exists."""
        assert has_swift_out_nostro_account("BAMXMXMMXXX") is True
        assert has_swift_out_nostro_account("UNKNOWNBANK") is False


class TestBicNormalization:
    """Tests for BIC normalization (BIC8 vs BIC11)."""

    def test_bic8_vs_bic11_vostro(self) -> None:
        """Test that BIC8 and BIC11 both work for lookup."""
        result8 = lookup_vostro_account("SBININBB")
        result11 = lookup_vostro_account("SBININBBXXX")
        assert result8 == result11
        assert result8 is not None

    def test_bic8_vs_bic11_chips(self) -> None:
        """Test that BIC8 and BIC11 both work for CHIPS lookup."""
        result8 = lookup_chips_nostro_account("CHASUS33")
        result11 = lookup_chips_nostro_account("CHASUS33XXX")
        assert result8 == result11
        assert result8 is not None

    def test_bic8_vs_bic11_swift_out(self) -> None:
        """Test that BIC8 and BIC11 both work for SWIFT out lookup."""
        result8 = lookup_swift_out_nostro_account("BAMXMXMM")
        result11 = lookup_swift_out_nostro_account("BAMXMXMMXXX")
        assert result8 == result11
        assert result8 is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


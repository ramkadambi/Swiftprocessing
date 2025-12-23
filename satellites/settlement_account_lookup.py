"""
Settlement Account Lookup utility service for Wells Fargo internal accounts.

Provides lookup functionality for:
- Vostro accounts: Foreign bank accounts maintained at Wells Fargo (for inbound payments)
- FED account: Wells Fargo's Federal Reserve settlement account
- CHIPS nostro accounts: CHIPS participant accounts maintained at Wells Fargo
- SWIFT out nostro accounts: Foreign bank accounts maintained at Wells Fargo (for outbound payments)

In production, this would query Wells Fargo's internal account management system.
"""

from typing import Optional


# Wells Fargo's FED settlement account (single account for all FED operations)
_FED_ACCOUNT: dict[str, str] = {
    "account_number": "WF-FED-SETTLE-001",
    "account_name": "Wells Fargo FED Settlement Account",
    "routing_number": "121000248",  # Wells Fargo main routing number
}


# Vostro accounts: Foreign bank accounts maintained at Wells Fargo (for inbound payments)
# When foreign bank sends money TO Wells Fargo customers, debit from their vostro account
_VOSTRO_ACCOUNTS: dict[str, dict] = {
    # State Bank of India
    "SBININBB": {
        "account_number": "WF-VOSTRO-SBI-USD-001",
        "account_name": "State Bank of India Vostro Account",
        "currency": "USD",
        "bank_name": "State Bank of India",
        "country": "IN",
    },
    # Deutsche Bank
    "DEUTDEFF": {
        "account_number": "WF-VOSTRO-DEUT-USD-001",
        "account_name": "Deutsche Bank AG Vostro Account",
        "currency": "USD",
        "bank_name": "Deutsche Bank AG",
        "country": "DE",
    },
    # HSBC
    "HSBCGB2L": {
        "account_number": "WF-VOSTRO-HSBC-USD-001",
        "account_name": "HSBC Bank plc Vostro Account",
        "currency": "USD",
        "bank_name": "HSBC Bank plc",
        "country": "GB",
    },
    # Banamex (Mexico)
    "BAMXMXMM": {
        "account_number": "WF-VOSTRO-BANAMEX-USD-001",
        "account_name": "Banco Nacional de Mexico Vostro Account",
        "currency": "USD",
        "bank_name": "Banco Nacional de Mexico",
        "country": "MX",
    },
    # Standard Chartered
    "SCBLUS33": {
        "account_number": "WF-VOSTRO-SCBL-USD-001",
        "account_name": "Standard Chartered Bank Vostro Account",
        "currency": "USD",
        "bank_name": "Standard Chartered Bank",
        "country": "GB",
    },
}


# CHIPS nostro accounts: CHIPS participant accounts maintained at Wells Fargo
# Only for CHIPS participants with regular traffic/relationships
# If not found, route via FED (cost consideration)
_CHIPS_NOSTRO_ACCOUNTS: dict[str, dict] = {
    # Chase (regular CHIPS traffic)
    "CHASUS33": {
        "account_number": "WF-CHIPS-NOSTRO-CHASE-001",
        "account_name": "JPMorgan Chase Bank NA CHIPS Nostro Account",
        "currency": "USD",
        "bank_name": "JPMorgan Chase Bank NA",
        "chips_uid": "0002",
        "country": "US",
    },
    # Bank of America (regular CHIPS traffic)
    "BOFAUS3N": {
        "account_number": "WF-CHIPS-NOSTRO-BOFA-001",
        "account_name": "Bank of America NA CHIPS Nostro Account",
        "currency": "USD",
        "bank_name": "Bank of America NA",
        "chips_uid": "0003",
        "country": "US",
    },
    # Citibank (regular CHIPS traffic)
    "CITIUS33": {
        "account_number": "WF-CHIPS-NOSTRO-CITI-001",
        "account_name": "Citibank NA CHIPS Nostro Account",
        "currency": "USD",
        "bank_name": "Citibank NA",
        "chips_uid": "0004",
        "country": "US",
    },
    # Deutsche Bank (regular CHIPS traffic)
    "DEUTDEFF": {
        "account_number": "WF-CHIPS-NOSTRO-DEUT-001",
        "account_name": "Deutsche Bank AG CHIPS Nostro Account",
        "currency": "USD",
        "bank_name": "Deutsche Bank AG",
        "chips_uid": "0407",
        "country": "DE",
    },
    # HSBC (regular CHIPS traffic)
    "HSBCGB2L": {
        "account_number": "WF-CHIPS-NOSTRO-HSBC-001",
        "account_name": "HSBC Bank plc CHIPS Nostro Account",
        "currency": "USD",
        "bank_name": "HSBC Bank plc",
        "chips_uid": "0408",
        "country": "GB",
    },
}


# SWIFT out nostro accounts: Foreign bank accounts maintained at Wells Fargo (for outbound payments)
# When Wells Fargo sends money TO foreign bank, credit their nostro account
_SWIFT_OUT_NOSTRO_ACCOUNTS: dict[str, dict] = {
    # Banamex (Mexico)
    "BAMXMXMM": {
        "account_number": "WF-SWIFT-NOSTRO-BANAMEX-001",
        "account_name": "Banco Nacional de Mexico Nostro Account",
        "currency": "USD",
        "bank_name": "Banco Nacional de Mexico",
        "country": "MX",
    },
    # State Bank of India
    "SBININBB": {
        "account_number": "WF-SWIFT-NOSTRO-SBI-001",
        "account_name": "State Bank of India Nostro Account",
        "currency": "USD",
        "bank_name": "State Bank of India",
        "country": "IN",
    },
    # Deutsche Bank
    "DEUTDEFF": {
        "account_number": "WF-SWIFT-NOSTRO-DEUT-001",
        "account_name": "Deutsche Bank AG Nostro Account",
        "currency": "USD",
        "bank_name": "Deutsche Bank AG",
        "country": "DE",
    },
    # HSBC
    "HSBCGB2L": {
        "account_number": "WF-SWIFT-NOSTRO-HSBC-001",
        "account_name": "HSBC Bank plc Nostro Account",
        "currency": "USD",
        "bank_name": "HSBC Bank plc",
        "country": "GB",
    },
    # Standard Chartered
    "SCBLUS33": {
        "account_number": "WF-SWIFT-NOSTRO-SCBL-001",
        "account_name": "Standard Chartered Bank Nostro Account",
        "currency": "USD",
        "bank_name": "Standard Chartered Bank",
        "country": "GB",
    },
}


def lookup_vostro_account(bic: str) -> Optional[dict]:
    """
    Lookup vostro account for a foreign bank.
    
    Vostro accounts are foreign bank accounts maintained at Wells Fargo.
    Used when foreign bank sends money TO Wells Fargo customers.
    
    Args:
        bic: Foreign bank BIC code (BIC8 or BIC11 format)
    
    Returns:
        Dictionary with account data or None if not found.
        Keys: account_number, account_name, currency, bank_name, country
    """
    if not bic:
        return None
    
    # Normalize BIC to BIC8 (first 8 chars) for lookup
    bic8 = bic.strip().upper()[:8]
    return _VOSTRO_ACCOUNTS.get(bic8)


def lookup_fed_account() -> dict:
    """
    Lookup Wells Fargo's FED settlement account.
    
    This is Wells Fargo's single settlement account with the Federal Reserve.
    Used for all FED network payments.
    
    Returns:
        Dictionary with FED account data.
        Keys: account_number, account_name, routing_number
    """
    return _FED_ACCOUNT.copy()


def lookup_chips_nostro_account(bic: str) -> Optional[dict]:
    """
    Lookup CHIPS nostro account for a CHIPS participant bank.
    
    CHIPS nostro accounts are CHIPS participant accounts maintained at Wells Fargo.
    Only maintained for CHIPS participants with regular traffic/relationships.
    If not found, payment should be routed via FED (cost consideration).
    
    Args:
        bic: CHIPS participant bank BIC code (BIC8 or BIC11 format)
    
    Returns:
        Dictionary with account data or None if not found (route via FED).
        Keys: account_number, account_name, currency, bank_name, chips_uid, country
    """
    if not bic:
        return None
    
    # Normalize BIC to BIC8 (first 8 chars) for lookup
    bic8 = bic.strip().upper()[:8]
    return _CHIPS_NOSTRO_ACCOUNTS.get(bic8)


def lookup_swift_out_nostro_account(bic: str) -> Optional[dict]:
    """
    Lookup SWIFT out nostro account for a foreign bank.
    
    SWIFT out nostro accounts are foreign bank accounts maintained at Wells Fargo.
    Used when Wells Fargo sends money TO foreign bank via SWIFT.
    
    Args:
        bic: Foreign bank BIC code (BIC8 or BIC11 format)
    
    Returns:
        Dictionary with account data or None if not found.
        Keys: account_number, account_name, currency, bank_name, country
    """
    if not bic:
        return None
    
    # Normalize BIC to BIC8 (first 8 chars) for lookup
    bic8 = bic.strip().upper()[:8]
    return _SWIFT_OUT_NOSTRO_ACCOUNTS.get(bic8)


def get_vostro_account_number(bic: str) -> Optional[str]:
    """Get vostro account number for a foreign bank."""
    data = lookup_vostro_account(bic)
    return data.get("account_number") if data else None


def get_fed_account_number() -> str:
    """Get Wells Fargo's FED settlement account number."""
    return _FED_ACCOUNT["account_number"]


def get_chips_nostro_account_number(bic: str) -> Optional[str]:
    """Get CHIPS nostro account number for a CHIPS participant bank."""
    data = lookup_chips_nostro_account(bic)
    return data.get("account_number") if data else None


def get_swift_out_nostro_account_number(bic: str) -> Optional[str]:
    """Get SWIFT out nostro account number for a foreign bank."""
    data = lookup_swift_out_nostro_account(bic)
    return data.get("account_number") if data else None


def has_chips_nostro_relationship(bic: str) -> bool:
    """
    Check if Wells Fargo has a CHIPS nostro account relationship with a bank.
    
    If False, payment should be routed via FED (cost consideration).
    """
    return lookup_chips_nostro_account(bic) is not None


def has_vostro_account(bic: str) -> bool:
    """Check if a foreign bank has a vostro account at Wells Fargo."""
    return lookup_vostro_account(bic) is not None


def has_swift_out_nostro_account(bic: str) -> bool:
    """Check if a foreign bank has a SWIFT out nostro account at Wells Fargo."""
    return lookup_swift_out_nostro_account(bic) is not None


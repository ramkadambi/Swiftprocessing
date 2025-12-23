"""
CHIPS (Clearing House Interbank Payments System) lookup utility service.

Provides lookup functionality for CHIPS UID to retrieve:
- Bank name
- BIC code
- CHIPS participant status
- Settlement account information

In production, this would query the CHIPS participant directory.
"""

from typing import Optional


# In-memory CHIPS lookup: CHIPS UID -> bank data
# In production, this would query the CHIPS participant directory
_CHIPS_LOOKUP: dict[str, dict] = {
    # Wells Fargo
    "0001": {
        "bank_name": "Wells Fargo Bank NA",
        "bic": "WFBIUS6SXXX",
        "chips_participant": True,
        "settlement_account": "WF-SETTLE-001",
    },
    # Chase
    "0002": {
        "bank_name": "JPMorgan Chase Bank NA",
        "bic": "CHASUS33XXX",
        "chips_participant": True,
        "settlement_account": "CH-SETTLE-001",
    },
    # Bank of America
    "0003": {
        "bank_name": "Bank of America NA",
        "bic": "BOFAUS3NXXX",
        "chips_participant": True,
        "settlement_account": "BOFA-SETTLE-001",
    },
    # Deutsche Bank
    "0407": {
        "bank_name": "Deutsche Bank AG",
        "bic": "DEUTDEFFXXX",
        "chips_participant": True,
        "settlement_account": "DB-SETTLE-001",
    },
    # HSBC
    "0408": {
        "bank_name": "HSBC Bank plc",
        "bic": "HSBCGB2LXXX",
        "chips_participant": True,
        "settlement_account": "HSBC-SETTLE-001",
    },
    # Citibank
    "0004": {
        "bank_name": "Citibank NA",
        "bic": "CITIUS33XXX",
        "chips_participant": True,
        "settlement_account": "CITI-SETTLE-001",
    },
}


def lookup_chips(chips_uid: str) -> Optional[dict]:
    """
    Lookup bank data by CHIPS UID.
    
    Args:
        chips_uid: CHIPS participant UID (4-digit code)
    
    Returns:
        Dictionary with bank data or None if not found.
        Keys: bank_name, bic, chips_participant, settlement_account
    """
    if not chips_uid:
        return None
    
    # Normalize CHIPS UID (remove leading zeros padding, ensure 4 digits)
    chips_clean = chips_uid.strip()
    if chips_clean.isdigit():
        # Pad to 4 digits if needed
        chips_clean = chips_clean.zfill(4)
    
    return _CHIPS_LOOKUP.get(chips_clean)


def get_bic_from_chips(chips_uid: str) -> Optional[str]:
    """Get BIC code from CHIPS UID."""
    data = lookup_chips(chips_uid)
    if data:
        return data.get("bic")
    return None


def is_chips_participant(chips_uid: str) -> bool:
    """Check if CHIPS UID is an active participant."""
    data = lookup_chips(chips_uid)
    return data is not None and data.get("chips_participant", False)


def get_settlement_account(chips_uid: str) -> Optional[str]:
    """Get settlement account for CHIPS participant."""
    data = lookup_chips(chips_uid)
    if data:
        return data.get("settlement_account")
    return None


def get_bank_name_from_chips(chips_uid: str) -> Optional[str]:
    """Get bank name from CHIPS UID."""
    data = lookup_chips(chips_uid)
    if data:
        return data.get("bank_name")
    return None


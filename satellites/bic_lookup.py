"""
BIC (Bank Identifier Code) lookup utility service.

Provides lookup functionality for BIC codes to retrieve:
- Bank name
- Country
- FED membership
- CHIPS membership
- ABA routing number (for US banks)
- CHIPS UID (for CHIPS members)

In production, this would query a real BIC directory database.
"""

from typing import Optional


# In-memory BIC lookup: BIC8 -> bank data
# In production, this would be a database query
_BIC_LOOKUP: dict[str, dict] = {
    # Wells Fargo
    "WFBIUS6S": {
        "bank_name": "Wells Fargo Bank NA",
        "country": "US",
        "fed_member": True,
        "chips_member": True,
        "aba_routing": "121000248",  # Wells Fargo main routing number
        "chips_uid": "0001",  # Wells Fargo CHIPS UID
    },
    # Chase
    "CHASUS33": {
        "bank_name": "JPMorgan Chase Bank NA",
        "country": "US",
        "fed_member": True,
        "chips_member": True,
        "aba_routing": "021000021",
        "chips_uid": "0002",
    },
    # Bank of America
    "BOFAUS3N": {
        "bank_name": "Bank of America NA",
        "country": "US",
        "fed_member": True,
        "chips_member": True,
        "aba_routing": "026009593",
        "chips_uid": "0003",
    },
    # Deutsche Bank
    "DEUTDEFF": {
        "bank_name": "Deutsche Bank AG",
        "country": "DE",
        "fed_member": False,
        "chips_member": True,
        "aba_routing": None,
        "chips_uid": "0407",
    },
    # HSBC
    "HSBCGB2L": {
        "bank_name": "HSBC Bank plc",
        "country": "GB",
        "fed_member": False,
        "chips_member": True,
        "aba_routing": None,
        "chips_uid": "0408",
    },
    # State Bank of India
    "SBININBB": {
        "bank_name": "State Bank of India",
        "country": "IN",
        "fed_member": False,
        "chips_member": False,
        "aba_routing": None,
        "chips_uid": None,
    },
    # Banamex (Mexico)
    "BAMXMXMM": {
        "bank_name": "Banco Nacional de Mexico",
        "country": "MX",
        "fed_member": False,
        "chips_member": False,
        "aba_routing": None,
        "chips_uid": None,
    },
    # US Bank (FED member, no CHIPS)
    "USBKUS44": {
        "bank_name": "US Bank NA",
        "country": "US",
        "fed_member": True,
        "chips_member": False,
        "aba_routing": "091000019",
        "chips_uid": None,
    },
}


def lookup_bic(bic: str) -> Optional[dict]:
    """
    Lookup BIC data by BIC code.
    
    Args:
        bic: BIC code (BIC8 or BIC11 format)
    
    Returns:
        Dictionary with bank data or None if not found.
        Keys: bank_name, country, fed_member, chips_member, aba_routing, chips_uid
    """
    if not bic:
        return None
    
    # Normalize BIC to BIC8 (first 8 chars) for lookup
    bic8 = bic.strip().upper()[:8]
    return _BIC_LOOKUP.get(bic8)


def is_fed_member(bic: str) -> bool:
    """Check if BIC is a FED member."""
    data = lookup_bic(bic)
    return data is not None and data.get("fed_member", False)


def is_chips_member(bic: str) -> bool:
    """Check if BIC is a CHIPS member."""
    data = lookup_bic(bic)
    return data is not None and data.get("chips_member", False)


def get_aba_routing(bic: str) -> Optional[str]:
    """Get ABA routing number for US bank BIC."""
    data = lookup_bic(bic)
    if data:
        return data.get("aba_routing")
    return None


def get_chips_uid(bic: str) -> Optional[str]:
    """Get CHIPS UID for CHIPS member BIC."""
    data = lookup_bic(bic)
    if data:
        return data.get("chips_uid")
    return None


def get_bank_country(bic: str) -> Optional[str]:
    """Get bank country code from BIC."""
    data = lookup_bic(bic)
    if data:
        return data.get("country")
    return None


def get_bank_name(bic: str) -> Optional[str]:
    """Get bank name from BIC."""
    data = lookup_bic(bic)
    if data:
        return data.get("bank_name")
    return None


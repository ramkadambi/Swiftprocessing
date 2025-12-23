"""
ABA (American Bankers Association) routing number lookup utility service.

Provides lookup functionality for ABA routing numbers to retrieve:
- Bank name
- BIC code
- FED membership status
- Bank location

In production, this would query the Federal Reserve's routing directory.
"""

from typing import Optional


# In-memory ABA routing lookup: ABA routing number -> bank data
# In production, this would query the Federal Reserve routing directory
_ABA_LOOKUP: dict[str, dict] = {
    # Wells Fargo
    "121000248": {
        "bank_name": "Wells Fargo Bank NA",
        "bic": "WFBIUS6SXXX",
        "fed_member": True,
        "city": "San Francisco",
        "state": "CA",
    },
    # Chase
    "021000021": {
        "bank_name": "JPMorgan Chase Bank NA",
        "bic": "CHASUS33XXX",
        "fed_member": True,
        "city": "New York",
        "state": "NY",
    },
    # Bank of America
    "026009593": {
        "bank_name": "Bank of America NA",
        "bic": "BOFAUS3NXXX",
        "fed_member": True,
        "city": "Charlotte",
        "state": "NC",
    },
    # Citibank
    "021000089": {
        "bank_name": "Citibank NA",
        "bic": "CITIUS33XXX",
        "fed_member": True,
        "city": "New York",
        "state": "NY",
    },
    # US Bank
    "091000019": {
        "bank_name": "US Bank NA",
        "bic": "USBKUS44XXX",
        "fed_member": True,
        "city": "Minneapolis",
        "state": "MN",
    },
}


def lookup_aba(aba_routing: str) -> Optional[dict]:
    """
    Lookup bank data by ABA routing number.
    
    Args:
        aba_routing: 9-digit ABA routing number
    
    Returns:
        Dictionary with bank data or None if not found.
        Keys: bank_name, bic, fed_member, city, state
    """
    if not aba_routing:
        return None
    
    # Normalize ABA routing (remove dashes, spaces)
    aba_clean = aba_routing.strip().replace("-", "").replace(" ", "")
    
    # Validate format (9 digits)
    if not aba_clean.isdigit() or len(aba_clean) != 9:
        return None
    
    return _ABA_LOOKUP.get(aba_clean)


def get_bic_from_aba(aba_routing: str) -> Optional[str]:
    """Get BIC code from ABA routing number."""
    data = lookup_aba(aba_routing)
    if data:
        return data.get("bic")
    return None


def is_fed_member_by_aba(aba_routing: str) -> bool:
    """Check if bank is FED member by ABA routing number."""
    data = lookup_aba(aba_routing)
    return data is not None and data.get("fed_member", False)


def get_bank_name_from_aba(aba_routing: str) -> Optional[str]:
    """Get bank name from ABA routing number."""
    data = lookup_aba(aba_routing)
    if data:
        return data.get("bank_name")
    return None


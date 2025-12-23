"""
In-memory account lookup for account validation enrichment.

This simulates a database lookup for account/creditor information needed for
clearing and routing decisions. In production, this would query a real database.
"""

from canonical import AccountValidationEnrichment, CreditorType, ServiceResultStatus
from satellites import bic_lookup


# In-memory lookup: creditor BIC -> enrichment data
# In production, this would be a database query
_ACCOUNT_LOOKUP: dict[str, dict] = {
    # US Banks - FED members
    "WELLSFARGO": {
        "creditor_type": CreditorType.BANK,
        "fed_member": True,
        "chips_member": True,
        "nostro_with_us": True,
        "vostro_with_us": False,
        "preferred_correspondent": "WFBIUS6SXXX",
    },
    "CHASUS33": {
        "creditor_type": CreditorType.BANK,
        "fed_member": True,
        "chips_member": True,
        "nostro_with_us": True,
        "vostro_with_us": False,
        "preferred_correspondent": "CHASUS33XXX",
    },
    "BOFAUS3N": {
        "creditor_type": CreditorType.BANK,
        "fed_member": True,
        "chips_member": True,
        "nostro_with_us": True,
        "vostro_with_us": False,
        "preferred_correspondent": "BOFAUS3NXXX",
    },
    "USBKUS44": {
        "creditor_type": CreditorType.BANK,
        "fed_member": True,
        "chips_member": False,
        "nostro_with_us": True,
        "vostro_with_us": False,
        "preferred_correspondent": "USBKUS44XXX",
    },
    "WFBIUS6S": {
        "creditor_type": CreditorType.BANK,
        "fed_member": True,
        "chips_member": True,
        "nostro_with_us": True,
        "vostro_with_us": False,
        "preferred_correspondent": "WFBIUS6SXXX",
    },
    # Foreign banks - CHIPS only
    "DEUTDEFF": {
        "creditor_type": CreditorType.BANK,
        "fed_member": False,
        "chips_member": True,
        "nostro_with_us": False,
        "vostro_with_us": True,
        "preferred_correspondent": "DEUTDEFFXXX",
    },
    "SBININBB": {
        "creditor_type": CreditorType.BANK,
        "fed_member": False,
        "chips_member": False,
        "nostro_with_us": False,
        "vostro_with_us": True,
        "preferred_correspondent": "SBININBBXXX",
    },
    "BAMXMXMM": {
        "creditor_type": CreditorType.BANK,
        "fed_member": False,
        "chips_member": False,
        "nostro_with_us": False,
        "vostro_with_us": False,
        "preferred_correspondent": "BAMXMXMMXXX",
    },
    "HSBCGB2L": {
        "creditor_type": CreditorType.BANK,
        "fed_member": False,
        "chips_member": True,
        "nostro_with_us": False,
        "vostro_with_us": True,
        "preferred_correspondent": "HSBCGB2LXXX",
    },
    # Individual accounts (no clearing membership)
    "INDIVIDUAL": {
        "creditor_type": CreditorType.INDIVIDUAL,
        "fed_member": False,
        "chips_member": False,
        "nostro_with_us": False,
        "vostro_with_us": False,
        "preferred_correspondent": None,
    },
}


def lookup_account_enrichment(creditor_bic: str) -> dict | None:
    """
    Lookup account enrichment data by creditor BIC.
    
    Uses BIC lookup utility to get FED/CHIPS membership, then enriches with
    account-specific data (nostro/vostro, preferred correspondent).
    
    Returns None if account not found (will result in validation FAIL).
    """
    if not creditor_bic:
        return None
    
    # Normalize BIC to BIC8 (first 8 chars) for lookup
    bic8 = creditor_bic.strip().upper()[:8]
    
    # Get base account data
    account_data = _ACCOUNT_LOOKUP.get(bic8)
    if account_data is None:
        return None
    
    # Enrich with BIC lookup data (FED/CHIPS membership from BIC directory)
    bic_data = bic_lookup.lookup_bic(creditor_bic)
    if bic_data:
        # Override FED/CHIPS membership from BIC lookup (more authoritative)
        account_data = account_data.copy()
        account_data["fed_member"] = bic_data.get("fed_member", account_data.get("fed_member", False))
        account_data["chips_member"] = bic_data.get("chips_member", account_data.get("chips_member", False))
    
    return account_data


def enrich_payment_event(
    event, validation_status: ServiceResultStatus, creditor_bic: str
) -> AccountValidationEnrichment | None:
    """
    Create AccountValidationEnrichment from lookup data.
    
    Returns None if validation failed or account not found.
    """
    if validation_status != ServiceResultStatus.PASS:
        return None
    
    lookup_data = lookup_account_enrichment(creditor_bic)
    if lookup_data is None:
        # Account not found - validation should have failed
        return None
    
    return AccountValidationEnrichment(
        status=validation_status,
        creditor_type=lookup_data["creditor_type"],
        fed_member=lookup_data["fed_member"],
        chips_member=lookup_data["chips_member"],
        nostro_with_us=lookup_data["nostro_with_us"],
        vostro_with_us=lookup_data["vostro_with_us"],
        preferred_correspondent=lookup_data["preferred_correspondent"],
    )


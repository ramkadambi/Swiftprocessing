"""
In-memory account lookup for account validation enrichment.

This simulates a database lookup for account/creditor information needed for
clearing and routing decisions. In production, this would query a real database.
"""

from canonical import AccountValidationEnrichment, CreditorType, ServiceResultStatus


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
    "CHASEUS33": {
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
    # Foreign banks - CHIPS only
    "DEUTDEFF": {
        "creditor_type": CreditorType.BANK,
        "fed_member": False,
        "chips_member": True,
        "nostro_with_us": False,
        "vostro_with_us": True,
        "preferred_correspondent": "DEUTDEFFXXX",
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
    
    Returns None if account not found (will result in validation FAIL).
    """
    if not creditor_bic:
        return None
    
    # Normalize BIC to BIC8 (first 8 chars) for lookup
    bic8 = creditor_bic.strip().upper()[:8]
    return _ACCOUNT_LOOKUP.get(bic8)


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


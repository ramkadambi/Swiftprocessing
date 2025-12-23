"""
Generate SWIFT MT103 (Customer Credit Transfer) from PaymentEvent.

MT103 is used for direct customer credit transfers via SWIFT network.
This message includes customer/beneficiary details.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from canonical import PaymentEvent


def payment_event_to_mt103(event: PaymentEvent, *, created_at: Optional[datetime] = None) -> str:
    """
    Generate a SWIFT MT103 message from a canonical PaymentEvent.

    MT103 format:
    :20: Sender's Reference
    :23B: Bank Operation Code
    :32A: Value Date, Currency Code, Amount
    :50A: Ordering Customer
    :52A: Ordering Institution
    :53A: Sender's Correspondent
    :54A: Receiver's Correspondent
    :56A: Intermediary
    :57A: Account With Institution
    :59: Beneficiary Customer
    :70: Remittance Information
    :71A: Details of Charges
    :72: Sender to Receiver Information
    """

    if created_at is None:
        created_at = datetime.now(timezone.utc)

    # Extract BICs
    debtor_bic = (event.debtor_agent.id_value or "").strip().upper()
    creditor_bic = (event.creditor_agent.id_value or "").strip().upper()
    
    if not debtor_bic or not creditor_bic:
        raise ValueError("Both debtor_agent.id_value and creditor_agent.id_value must be set (BIC).")

    if not isinstance(event.amount, Decimal):
        raise TypeError("event.amount must be decimal.Decimal.")

    # Format amount: always 2 decimals for currency
    amount_str = format(event.amount, ".2f").replace(".", ",")  # SWIFT uses comma for decimal

    # Format date: YYMMDD
    value_date = created_at.strftime("%y%m%d")

    lines = []
    
    # :20: Sender's Reference (MsgId)
    lines.append(f":20:{event.msg_id}")
    
    # :23B: Bank Operation Code (CRED for credit transfer)
    lines.append(":23B:CRED")
    
    # :32A: Value Date, Currency Code, Amount
    lines.append(f":32A:{value_date}{event.currency}{amount_str}")
    
    # :50A: Ordering Customer (Debtor Bank)
    lines.append(f":50A:{debtor_bic}")
    
    # :52A: Ordering Institution (Debtor Bank)
    lines.append(f":52A:{debtor_bic}")
    
    # :56A: Intermediary (if present)
    if event.agent_chain and len(event.agent_chain) > 0:
        intermediary_bic = (event.agent_chain[0].id_value or "").strip().upper()
        if intermediary_bic:
            lines.append(f":56A:{intermediary_bic}")
    
    # :57A: Account With Institution (Creditor Bank)
    lines.append(f":57A:{creditor_bic}")
    
    # :59: Beneficiary Customer (use creditor BIC as placeholder, in production would have actual beneficiary)
    # Format: /AccountNumber\nBeneficiary Name\nAddress
    beneficiary_account = creditor_bic[:8]  # Use BIC8 as account placeholder
    beneficiary_name = event.creditor_agent.name or creditor_bic
    lines.append(f":59:/{beneficiary_account}\n{beneficiary_name}")
    
    # :70: Remittance Information (EndToEndId)
    lines.append(f":70:{event.end_to_end_id}")
    
    # :71A: Details of Charges (SHAR = shared)
    lines.append(":71A:SHAR")
    
    # Join with newline and add final newline
    return "\n".join(lines) + "\n"


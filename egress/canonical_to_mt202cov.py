"""
Generate SWIFT MT202COV (Cover Payment) from PaymentEvent.

MT202COV is used for international (cross-border) bank-to-bank cover payments
with underlying customer transaction details for compliance/AML purposes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from canonical import PaymentEvent


def payment_event_to_mt202cov(event: PaymentEvent, *, created_at: Optional[datetime] = None) -> str:
    """
    Generate a SWIFT MT202COV message from a canonical PaymentEvent.

    MT202COV format (Cover Payment with underlying customer details):
    :20: Transaction Reference
    :21: Related Reference
    :32A: Value Date, Currency Code, Amount
    :52A: Ordering Institution
    :53A: Sender's Correspondent
    :56A: Intermediary
    :57A: Account With Institution
    :58A: Beneficiary Institution
    :72: Sender to Receiver Information
    :50K: Ordering Customer (underlying)
    :52A: Ordering Institution (underlying)
    :59: Beneficiary Customer (underlying)
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
    
    # :20: Transaction Reference (MsgId)
    lines.append(f":20:{event.msg_id}")
    
    # :21: Related Reference (EndToEndId)
    lines.append(f":21:{event.end_to_end_id}")
    
    # :32A: Value Date, Currency Code, Amount
    lines.append(f":32A:{value_date}{event.currency}{amount_str}")
    
    # :52A: Ordering Institution (Debtor Bank)
    lines.append(f":52A:{debtor_bic}")
    
    # :56A: Intermediary (if present)
    if event.agent_chain and len(event.agent_chain) > 0:
        intermediary_bic = (event.agent_chain[0].id_value or "").strip().upper()
        if intermediary_bic:
            lines.append(f":56A:{intermediary_bic}")
    
    # :57A: Account With Institution (Creditor Bank)
    lines.append(f":57A:{creditor_bic}")
    
    # :58A: Beneficiary Institution (Creditor Bank)
    lines.append(f":58A:{creditor_bic}")
    
    # :50K: Ordering Customer (underlying customer details for compliance)
    debtor_name = event.debtor_agent.name or debtor_bic
    debtor_country = event.debtor_agent.country or "XX"
    lines.append(f":50K:/{debtor_bic[:8]}\n{debtor_name}\n{debtor_country}")
    
    # :52A: Ordering Institution (underlying - same as cover)
    lines.append(f":52A:{debtor_bic}")
    
    # :59: Beneficiary Customer (underlying customer details for compliance)
    creditor_name = event.creditor_agent.name or creditor_bic
    creditor_country = event.creditor_agent.country or "XX"
    lines.append(f":59:/{creditor_bic[:8]}\n{creditor_name}\n{creditor_country}")
    
    # :72: Sender to Receiver Information
    lines.append(f":72:COVER PAYMENT REF {event.end_to_end_id}")
    
    # Join with newline and add final newline
    return "\n".join(lines) + "\n"


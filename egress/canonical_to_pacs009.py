"""
Generate ISO 20022 pacs.009 (Financial Institution Credit Transfer) from PaymentEvent.

pacs.009 is used for CHIPS network payments - financial institution transfers
without underlying customer transaction details.
"""

from __future__ import annotations

import importlib
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from canonical import PaymentEvent


def _lxml_etree() -> Any:
    try:
        return importlib.import_module("lxml.etree")
    except ModuleNotFoundError as e:
        raise RuntimeError("lxml is required. Install it (e.g., `pip install lxml`).") from e


def payment_event_to_pacs009_xml(
    event: PaymentEvent,
    *,
    message_namespace: str = "urn:iso:std:iso:20022:tech:xsd:pacs.009.001.08",
    created_at: Optional[datetime] = None,
    include_xml_declaration: bool = True,
    pretty_print: bool = True,
) -> bytes:
    """
    Generate a SWIFT MX pacs.009 XML document from a canonical PaymentEvent.

    pacs.009 is used for financial institution credit transfers (CHIPS network).
    This message type does not include underlying customer transaction details.
    """

    etree = _lxml_etree()

    ns = message_namespace
    nsmap = {None: ns}

    if created_at is None:
        created_at = datetime.now(timezone.utc)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)

    # Canonical provides BIC in Agent.id_value
    dbic = (event.debtor_agent.id_value or "").strip().upper()
    cbic = (event.creditor_agent.id_value or "").strip().upper()
    if not dbic or not cbic:
        raise ValueError("Both debtor_agent.id_value and creditor_agent.id_value must be set (BIC).")

    if not isinstance(event.amount, Decimal):
        raise TypeError("event.amount must be decimal.Decimal.")

    # Create Document
    doc = etree.Element(etree.QName(ns, "Document"), nsmap=nsmap)
    root = etree.SubElement(doc, etree.QName(ns, "FICdtTrf"))

    # GrpHdr
    grp_hdr = etree.SubElement(root, etree.QName(ns, "GrpHdr"))
    etree.SubElement(grp_hdr, etree.QName(ns, "MsgId")).text = event.msg_id
    etree.SubElement(grp_hdr, etree.QName(ns, "CreDtTm")).text = created_at.isoformat().replace("+00:00", "Z")
    etree.SubElement(grp_hdr, etree.QName(ns, "NbOfTxs")).text = "1"
    sttlm_inf = etree.SubElement(grp_hdr, etree.QName(ns, "SttlmInf"))
    etree.SubElement(sttlm_inf, etree.QName(ns, "SttlmMtd")).text = "CLRG"

    # CdtTrfTxInf (single)
    tx = etree.SubElement(root, etree.QName(ns, "CdtTrfTxInf"))
    pmt_id = etree.SubElement(tx, etree.QName(ns, "PmtId"))
    etree.SubElement(pmt_id, etree.QName(ns, "EndToEndId")).text = event.end_to_end_id

    # Amount: IntrBkSttlmAmt
    amt = etree.SubElement(tx, etree.QName(ns, "IntrBkSttlmAmt"))
    amt.set("Ccy", event.currency)
    amt.text = format(event.amount, "f")

    # InstgAgt (Instructing Agent - debtor bank)
    instg_agt = etree.SubElement(tx, etree.QName(ns, "InstgAgt"))
    instg_fin = etree.SubElement(instg_agt, etree.QName(ns, "FinInstnId"))
    etree.SubElement(instg_fin, etree.QName(ns, "BICFI")).text = dbic

    # InstdAgt (Instructed Agent - creditor bank)
    instd_agt = etree.SubElement(tx, etree.QName(ns, "InstdAgt"))
    instd_fin = etree.SubElement(instd_agt, etree.QName(ns, "FinInstnId"))
    etree.SubElement(instd_fin, etree.QName(ns, "BICFI")).text = cbic

    # Intermediary bank if present
    if event.agent_chain and len(event.agent_chain) > 0:
        intrmy_agt = etree.SubElement(tx, etree.QName(ns, "IntrmyAgt1"))
        intrmy_fin = etree.SubElement(intrmy_agt, etree.QName(ns, "FinInstnId"))
        intermediary_bic = event.agent_chain[0].id_value or ""
        etree.SubElement(intrmy_fin, etree.QName(ns, "BICFI")).text = intermediary_bic.strip().upper()

    xml_bytes: bytes = etree.tostring(
        doc,
        xml_declaration=include_xml_declaration,
        encoding="UTF-8",
        pretty_print=pretty_print,
    )
    return xml_bytes


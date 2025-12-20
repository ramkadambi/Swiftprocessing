from __future__ import annotations

import importlib
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional, Union

from canonical import PaymentEvent


def _lxml_etree() -> Any:
    try:
        return importlib.import_module("lxml.etree")
    except ModuleNotFoundError as e:
        raise RuntimeError("lxml is required. Install it (e.g., `pip install lxml`).") from e


def payment_event_to_pacs008_xml(
    event: PaymentEvent,
    *,
    message_namespace: str = "urn:iso:std:iso:20022:tech:xsd:pacs.008.001.08",
    created_at: Optional[datetime] = None,
    include_xml_declaration: bool = True,
    pretty_print: bool = True,
) -> bytes:
    """
    Generate a SWIFT MX pacs.008 XML document from a canonical PaymentEvent.

    Notes:
    - No SWIFT Alliance headers (AppHdr/BAH) are included (POC requirement).
    - The structure is ISO 20022 pacs.008-like and populates:
      MsgId, EndToEndId, amount+currency, DbtrAgt BICFI, CdtrAgt BICFI
    """

    etree = _lxml_etree()

    ns = message_namespace
    nsmap = {None: ns}

    if created_at is None:
        created_at = datetime.now(timezone.utc)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)

    # Canonical provides BIC in Agent.id_value (id_scheme="BIC" for MX ingress)
    dbic = (event.debtor_agent.id_value or "").strip().upper()
    cbic = (event.creditor_agent.id_value or "").strip().upper()
    if not dbic or not cbic:
        raise ValueError("Both debtor_agent.id_value and creditor_agent.id_value must be set (BIC).")

    if not isinstance(event.amount, Decimal):
        raise TypeError("event.amount must be decimal.Decimal.")

    # Create Document
    doc = etree.Element(etree.QName(ns, "Document"), nsmap=nsmap)
    root = etree.SubElement(doc, etree.QName(ns, "FIToFICstmrCdtTrf"))

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

    # Amount: include InstdAmt (as requested). Use normalized string.
    amt = etree.SubElement(tx, etree.QName(ns, "Amt"))
    instd_amt = etree.SubElement(amt, etree.QName(ns, "InstdAmt"))
    instd_amt.set("Ccy", event.currency)
    instd_amt.text = format(event.amount, "f")

    # Agents
    dbtr_agt = etree.SubElement(tx, etree.QName(ns, "DbtrAgt"))
    dbtr_fin = etree.SubElement(dbtr_agt, etree.QName(ns, "FinInstnId"))
    etree.SubElement(dbtr_fin, etree.QName(ns, "BICFI")).text = dbic

    cdtr_agt = etree.SubElement(tx, etree.QName(ns, "CdtrAgt"))
    cdtr_fin = etree.SubElement(cdtr_agt, etree.QName(ns, "FinInstnId"))
    etree.SubElement(cdtr_fin, etree.QName(ns, "BICFI")).text = cbic

    xml_bytes: bytes = etree.tostring(
        doc,
        xml_declaration=include_xml_declaration,
        encoding="UTF-8",
        pretty_print=pretty_print,
    )
    return xml_bytes



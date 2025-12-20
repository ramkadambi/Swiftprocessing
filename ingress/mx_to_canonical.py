from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import importlib
from typing import Any, Optional, Union

from canonical import Agent, PaymentEvent, PaymentStatus


class Pacs008ParseError(ValueError):
    """Raised when required pacs.008 fields cannot be extracted."""


def _lxml_etree() -> Any:
    """
    Runtime import so this module can be imported in environments where lxml is
    not installed (e.g., for type-checking or partial tooling).
    """

    try:
        return importlib.import_module("lxml.etree")
    except ModuleNotFoundError as e:
        raise RuntimeError("lxml is required. Install it (e.g., `pip install lxml`).") from e


def _first_text(node: Any, xpath_expr: str) -> Optional[str]:
    vals = node.xpath(xpath_expr)
    if not vals:
        return None
    v = vals[0]
    # v may be an Element or a scalar (string/number) depending on xpath.
    if hasattr(v, "text"):
        txt = v.text
    else:
        txt = str(v)
    if txt is None:
        return None
    txt = txt.strip()
    return txt or None


def _first_elem(node: Any, xpath_expr: str) -> Optional[Any]:
    vals = node.xpath(xpath_expr)
    if not vals:
        return None
    el = vals[0]
    return el if hasattr(el, "xpath") else None


@dataclass(frozen=True, slots=True)
class Pacs008Extract:
    msg_id: str
    end_to_end_id: str
    amount: Decimal
    currency: str
    debtor_bic: str
    creditor_bic: str


def extract_pacs008_fields(xml: Union[str, bytes]) -> Pacs008Extract:
    """
    Extract the required canonical fields from an ISO 20022 pacs.008 XML payload.

    Assumptions (per requirements):
    - MsgId (GrpHdr/MsgId)
    - EndToEndId (CdtTrfTxInf/PmtId/EndToEndId)
    - IntrBkSttlmAmt + @Ccy (CdtTrfTxInf/IntrBkSttlmAmt)
    - DbtrAgt BICFI (CdtTrfTxInf/DbtrAgt/FinInstnId/BICFI)
    - CdtrAgt BICFI (CdtTrfTxInf/CdtrAgt/FinInstnId/BICFI)
    """

    if isinstance(xml, str):
        xml_bytes = xml.encode("utf-8")
    else:
        xml_bytes = xml

    etree = _lxml_etree()
    parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=False)
    try:
        root = etree.fromstring(xml_bytes, parser=parser)
    except etree.XMLSyntaxError as e:
        raise Pacs008ParseError(f"Invalid XML: {e}") from e

    # Namespace-agnostic navigation: match by element local-name so this works
    # across pacs.008 schema versions with different default namespaces.
    msg_id = _first_text(
        root,
        "/*[local-name()='Document']"
        "/*[local-name()='FIToFICstmrCdtTrf']"
        "/*[local-name()='GrpHdr']"
        "/*[local-name()='MsgId']/text()",
    )

    tx = _first_elem(
        root,
        "/*[local-name()='Document']"
        "/*[local-name()='FIToFICstmrCdtTrf']"
        "/*[local-name()='CdtTrfTxInf'][1]",
    )

    if tx is None:
        raise Pacs008ParseError("Missing CdtTrfTxInf (no credit transfer transaction found).")

    end_to_end_id = _first_text(
        tx,
        "./*[local-name()='PmtId']/*[local-name()='EndToEndId']/text()",
    )

    intr_bk_amt_el = _first_elem(
        tx,
        "./*[local-name()='IntrBkSttlmAmt']",
    )
    amount_txt = intr_bk_amt_el.text.strip() if intr_bk_amt_el is not None and intr_bk_amt_el.text else None
    currency = intr_bk_amt_el.get("Ccy") if intr_bk_amt_el is not None else None

    debtor_bic = _first_text(
        tx,
        "./*[local-name()='DbtrAgt']"
        "/*[local-name()='FinInstnId']"
        "/*[local-name()='BICFI']/text()",
    )

    creditor_bic = _first_text(
        tx,
        "./*[local-name()='CdtrAgt']"
        "/*[local-name()='FinInstnId']"
        "/*[local-name()='BICFI']/text()",
    )

    missing = []
    if not msg_id:
        missing.append("GrpHdr/MsgId")
    if not end_to_end_id:
        missing.append("CdtTrfTxInf/PmtId/EndToEndId")
    if not amount_txt:
        missing.append("CdtTrfTxInf/IntrBkSttlmAmt")
    if not currency:
        missing.append("CdtTrfTxInf/IntrBkSttlmAmt@Ccy")
    if not debtor_bic:
        missing.append("CdtTrfTxInf/DbtrAgt/FinInstnId/BICFI")
    if not creditor_bic:
        missing.append("CdtTrfTxInf/CdtrAgt/FinInstnId/BICFI")
    if missing:
        raise Pacs008ParseError("Missing required pacs.008 fields: " + ", ".join(missing))

    try:
        amount = Decimal(amount_txt)
    except (InvalidOperation, TypeError) as e:
        raise Pacs008ParseError(f"Invalid IntrBkSttlmAmt '{amount_txt}'") from e

    return Pacs008Extract(
        msg_id=msg_id,
        end_to_end_id=end_to_end_id,
        amount=amount,
        currency=currency,
        debtor_bic=debtor_bic,
        creditor_bic=creditor_bic,
    )


def pacs008_xml_to_payment_event(xml: Union[str, bytes]) -> PaymentEvent:
    """
    Convert a SWIFT MX pacs.008 XML into a canonical PaymentEvent.
    """

    data = extract_pacs008_fields(xml)
    return PaymentEvent(
        msg_id=data.msg_id,
        end_to_end_id=data.end_to_end_id,
        amount=data.amount,
        currency=data.currency,
        debtor_agent=Agent(id_scheme="BIC", id_value=data.debtor_bic),
        creditor_agent=Agent(id_scheme="BIC", id_value=data.creditor_bic),
        status=PaymentStatus.RECEIVED,
    )



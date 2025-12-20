from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
import re
from typing import Optional


_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")


class PaymentStatus(str, Enum):
    """
    Canonical, SWIFT-network agnostic payment lifecycle status.

    Keep this intentionally generic so it can map to/from multiple ISO 20022
    message families (pacs/camt/pain) and network-specific status codes.
    """

    RECEIVED = "RECEIVED"
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    SETTLED = "SETTLED"
    RETURNED = "RETURNED"
    REVERSED = "REVERSED"


class ServiceResultStatus(str, Enum):
    """
    Canonical satellite/service execution status.
    """

    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"


@dataclass(frozen=True, slots=True)
class Agent:
    """
    Network-agnostic representation of a financial institution/agent.

    This intentionally does NOT assume BIC/SWIFT addressing. If you have a BIC,
    LEI, national clearing member id, etc., set it as (id_scheme, id_value).
    """

    id_scheme: Optional[str] = None
    id_value: Optional[str] = None
    name: Optional[str] = None
    country: Optional[str] = None  # ISO 3166-1 alpha-2 recommended

    def __post_init__(self) -> None:
        if (self.id_scheme is None) ^ (self.id_value is None):
            raise ValueError("Agent.id_scheme and Agent.id_value must be set together or both None.")
        if self.id_scheme is not None and not self.id_scheme.strip():
            raise ValueError("Agent.id_scheme must be non-empty when provided.")
        if self.id_value is not None and not self.id_value.strip():
            raise ValueError("Agent.id_value must be non-empty when provided.")


@dataclass(frozen=True, slots=True)
class PaymentEvent:
    """
    Canonical ISO 20022-inspired payment event.

    Required fields are intentionally minimal and network-agnostic to support
    multiple payment rails and message sources.
    """

    msg_id: str
    end_to_end_id: str
    amount: Decimal
    currency: str
    debtor_agent: Agent
    creditor_agent: Agent
    status: PaymentStatus

    def __post_init__(self) -> None:
        if not isinstance(self.msg_id, str) or not self.msg_id.strip():
            raise ValueError("msg_id must be a non-empty string.")
        if not isinstance(self.end_to_end_id, str) or not self.end_to_end_id.strip():
            raise ValueError("end_to_end_id must be a non-empty string.")

        if not isinstance(self.amount, Decimal):
            raise TypeError("amount must be decimal.Decimal.")
        if self.amount.is_nan() or self.amount.is_infinite():
            raise ValueError("amount must be a finite Decimal.")
        if self.amount <= Decimal("0"):
            raise ValueError("amount must be > 0.")

        if not isinstance(self.currency, str):
            raise TypeError("currency must be a string.")
        ccy = self.currency.strip().upper()
        if not _CURRENCY_RE.match(ccy):
            raise ValueError("currency must be an ISO 4217 alphabetic code (e.g., 'USD').")
        object.__setattr__(self, "currency", ccy)

        if not isinstance(self.debtor_agent, Agent):
            raise TypeError("debtor_agent must be an Agent.")
        if not isinstance(self.creditor_agent, Agent):
            raise TypeError("creditor_agent must be an Agent.")

        if not isinstance(self.status, PaymentStatus):
            raise TypeError("status must be a PaymentStatus.")


@dataclass(frozen=True, slots=True)
class ServiceResult:
    """
    Canonical result emitted by a satellite/service processing a PaymentEvent.
    """

    end_to_end_id: str
    service_name: str
    status: ServiceResultStatus

    def __post_init__(self) -> None:
        if not isinstance(self.end_to_end_id, str) or not self.end_to_end_id.strip():
            raise ValueError("end_to_end_id must be a non-empty string.")
        if not isinstance(self.service_name, str) or not self.service_name.strip():
            raise ValueError("service_name must be a non-empty string.")
        if not isinstance(self.status, ServiceResultStatus):
            raise TypeError("status must be a ServiceResultStatus.")


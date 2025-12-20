from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from threading import RLock
from typing import Dict, Optional

from canonical import PaymentEvent, ServiceResult, ServiceResultStatus


class PaymentProcessingState(str, Enum):
    RECEIVED = "RECEIVED"
    CONTROL_OK = "CONTROL_OK"
    ACCOUNT_OK = "ACCOUNT_OK"
    FUNDS_OK = "FUNDS_OK"
    POSTED = "POSTED"
    CREDIT_CONFIRMED = "CREDIT_CONFIRMED"


_STATE_ORDER: list[PaymentProcessingState] = [
    PaymentProcessingState.RECEIVED,
    PaymentProcessingState.CONTROL_OK,
    PaymentProcessingState.ACCOUNT_OK,
    PaymentProcessingState.FUNDS_OK,
    PaymentProcessingState.POSTED,
    PaymentProcessingState.CREDIT_CONFIRMED,
]


@dataclass(frozen=True, slots=True)
class PaymentStateSnapshot:
    end_to_end_id: str
    state: PaymentProcessingState
    # Latest result statuses captured by the state machine (PASS/FAIL/ERROR)
    control_status: Optional[ServiceResultStatus] = None
    account_status: Optional[ServiceResultStatus] = None
    funds_status: Optional[ServiceResultStatus] = None
    posted_status: Optional[ServiceResultStatus] = None
    credit_confirmed: bool = False


@dataclass(slots=True)
class _PaymentStateRecord:
    end_to_end_id: str
    received: bool = False
    # Store the latest status for each processing step
    control_status: Optional[ServiceResultStatus] = None
    account_status: Optional[ServiceResultStatus] = None
    funds_status: Optional[ServiceResultStatus] = None
    posted_status: Optional[ServiceResultStatus] = None
    credit_confirmed: bool = False


class PaymentStateMachine:
    """
    In-memory payment state machine keyed by end_to_end_id.

    The state is derived from the *highest contiguous* satisfied step:
      RECEIVED -> CONTROL_OK -> ACCOUNT_OK -> FUNDS_OK -> POSTED -> CREDIT_CONFIRMED

    Inputs:
    - PaymentEvent marks RECEIVED
    - ServiceResult updates step statuses (PASS/FAIL/ERROR)
    - mark_credit_confirmed() sets CREDIT_CONFIRMED once prior steps are satisfied
    """

    def __init__(self) -> None:
        self._lock = RLock()
        self._by_e2e: Dict[str, _PaymentStateRecord] = {}

    def _get_or_create(self, end_to_end_id: str) -> _PaymentStateRecord:
        if not end_to_end_id or not end_to_end_id.strip():
            raise ValueError("end_to_end_id must be a non-empty string.")
        e2e = end_to_end_id.strip()
        rec = self._by_e2e.get(e2e)
        if rec is None:
            rec = _PaymentStateRecord(end_to_end_id=e2e)
            self._by_e2e[e2e] = rec
        return rec

    def ingest_payment_event(self, event: PaymentEvent) -> PaymentStateSnapshot:
        with self._lock:
            rec = self._get_or_create(event.end_to_end_id)
            rec.received = True
            return self.snapshot(event.end_to_end_id)

    def ingest_service_result(self, result: ServiceResult) -> PaymentStateSnapshot:
        """
        Map service_name -> step:
        - sanctions_check -> CONTROL_OK
        - account_validation -> ACCOUNT_OK
        - balance_check -> FUNDS_OK
        - payment_posting -> POSTED
        """

        service = result.service_name.strip().lower()
        with self._lock:
            rec = self._get_or_create(result.end_to_end_id)
            # Service results imply the payment has been received upstream; allow progression
            # even if ingest_payment_event() was not called (aggregator might only read results).
            rec.received = True

            if service == "sanctions_check":
                rec.control_status = result.status
            elif service == "account_validation":
                rec.account_status = result.status
            elif service == "balance_check":
                rec.funds_status = result.status
            elif service == "payment_posting":
                rec.posted_status = result.status
            else:
                # Unknown service: store nothing but keep record; caller can still query snapshot.
                pass

            return self.snapshot(result.end_to_end_id)

    def mark_credit_confirmed(self, end_to_end_id: str, confirmed: bool = True) -> PaymentStateSnapshot:
        with self._lock:
            rec = self._get_or_create(end_to_end_id)
            rec.credit_confirmed = bool(confirmed)
            return self.snapshot(end_to_end_id)

    def _derive_state(self, rec: _PaymentStateRecord) -> PaymentProcessingState:
        if not rec.received:
            # If nothing received yet, we treat as RECEIVED only when a PaymentEvent arrives.
            return PaymentProcessingState.RECEIVED

        # Must be PASS to move to each subsequent OK state.
        if rec.control_status != ServiceResultStatus.PASS:
            return PaymentProcessingState.RECEIVED
        if rec.account_status != ServiceResultStatus.PASS:
            return PaymentProcessingState.CONTROL_OK
        if rec.funds_status != ServiceResultStatus.PASS:
            return PaymentProcessingState.ACCOUNT_OK
        if rec.posted_status != ServiceResultStatus.PASS:
            return PaymentProcessingState.FUNDS_OK
        if not rec.credit_confirmed:
            return PaymentProcessingState.POSTED
        return PaymentProcessingState.CREDIT_CONFIRMED

    def snapshot(self, end_to_end_id: str) -> PaymentStateSnapshot:
        with self._lock:
            rec = self._get_or_create(end_to_end_id)
            state = self._derive_state(rec)
            return PaymentStateSnapshot(
                end_to_end_id=rec.end_to_end_id,
                state=state,
                control_status=rec.control_status,
                account_status=rec.account_status,
                funds_status=rec.funds_status,
                posted_status=rec.posted_status,
                credit_confirmed=rec.credit_confirmed,
            )

    def get_state(self, end_to_end_id: str) -> PaymentProcessingState:
        return self.snapshot(end_to_end_id).state

    def reset(self, end_to_end_id: str) -> None:
        with self._lock:
            e2e = end_to_end_id.strip()
            self._by_e2e.pop(e2e, None)

    def clear(self) -> None:
        with self._lock:
            self._by_e2e.clear()


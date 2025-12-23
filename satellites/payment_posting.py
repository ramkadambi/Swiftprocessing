from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from decimal import Decimal
from enum import Enum
from typing import Any, Callable, Optional, Union

from canonical import PaymentEvent, RoutingNetwork, ServiceResult, ServiceResultStatus
from kafka_bus import KafkaConsumerWrapper, KafkaProducerWrapper
from orchestrator import topics
from satellites import bic_lookup, settlement_account_lookup
from satellites.ledger_service import is_transaction_processed, post_transaction


SERVICE_NAME = "payment_posting"
DEFAULT_INPUT_TOPIC = topics.TOPIC_PAYMENT_POSTING_IN
DEFAULT_RESULT_TOPIC = topics.TOPIC_PAYMENT_POSTING_OUT
DEFAULT_ERROR_TOPIC = topics.TOPIC_PAYMENT_POSTING_ERR


class EntrySide(str, Enum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


@dataclass(frozen=True, slots=True)
class PostingEntry:
    """
    Internal representation of a posting ledger entry created by the posting service.
    """

    end_to_end_id: str
    side: EntrySide
    agent_id: str  # e.g., BIC or other identifier (network agnostic)
    amount: Decimal
    currency: str
    settlement_account: Optional[str] = None  # Wells Fargo internal settlement account
    account_type: Optional[str] = None  # VOSTRO, NOSTRO, FED, CHIPS_NOSTRO, SWIFT_NOSTRO


def _service_result_to_json_bytes(result: ServiceResult) -> bytes:
    d = asdict(result)
    st = d.get("status")
    if hasattr(st, "value"):
        d["status"] = st.value
    return json.dumps(d, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _determine_settlement_accounts(
    event: PaymentEvent,
) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """
    Determine settlement accounts based on payment routing network and direction.
    
    Returns:
        Tuple of (debit_account, debit_account_type, credit_account, credit_account_type)
    """
    selected_network = event.selected_network
    debtor_bic = (event.debtor_agent.id_value or "").strip().upper()[:8]
    creditor_bic = (event.creditor_agent.id_value or "").strip().upper()[:8]
    debtor_country = event.debtor_agent.country or ""
    creditor_country = event.creditor_agent.country or ""
    
    # Wells Fargo BIC
    WELLS_BIC = "WFBIUS6S"
    
    debit_account: Optional[str] = None
    debit_account_type: Optional[str] = None
    credit_account: Optional[str] = None
    credit_account_type: Optional[str] = None
    
    # Determine if this is an inbound payment (foreign bank sending to Wells Fargo)
    is_inbound = debtor_country != "US" and creditor_bic == WELLS_BIC
    is_outbound = debtor_bic == WELLS_BIC and creditor_country != "US"
    
    if selected_network == RoutingNetwork.INTERNAL:
        # IBT: Internal Bank Transfer
        # Debit: Foreign bank's vostro account (if inbound) or customer account
        # Credit: Wells Fargo customer account or internal account
        
        if is_inbound:
            # Foreign bank sending to Wells Fargo customer
            # Debit from foreign bank's vostro account
            vostro = settlement_account_lookup.lookup_vostro_account(debtor_bic)
            if vostro:
                debit_account = vostro["account_number"]
                debit_account_type = "VOSTRO"
            else:
                # Fallback to debtor BIC if no vostro account
                debit_account = debtor_bic
                debit_account_type = "EXTERNAL"
            
            # Credit to Wells Fargo customer (creditor is Wells Fargo, but actual beneficiary is customer)
            credit_account = creditor_bic  # Will be resolved to customer account in production
            credit_account_type = "CUSTOMER"
        else:
            # Internal transfer within Wells Fargo
            debit_account = debtor_bic
            debit_account_type = "INTERNAL"
            credit_account = creditor_bic
            credit_account_type = "INTERNAL"
    
    elif selected_network == RoutingNetwork.FED:
        # FED: Federal Reserve Network
        # Credit: Wells Fargo's FED settlement account
        fed_account = settlement_account_lookup.lookup_fed_account()
        credit_account = fed_account["account_number"]
        credit_account_type = "FED"
        
        # Debit: Source account (could be vostro if inbound, or customer account)
        if is_inbound:
            vostro = settlement_account_lookup.lookup_vostro_account(debtor_bic)
            if vostro:
                debit_account = vostro["account_number"]
                debit_account_type = "VOSTRO"
            else:
                debit_account = debtor_bic
                debit_account_type = "EXTERNAL"
        else:
            debit_account = debtor_bic
            debit_account_type = "CUSTOMER"
    
    elif selected_network == RoutingNetwork.CHIPS:
        # CHIPS: Clearing House Interbank Payments System
        # Credit: CHIPS participant's nostro account (if relationship exists)
        chips_nostro = settlement_account_lookup.lookup_chips_nostro_account(creditor_bic)
        if chips_nostro:
            credit_account = chips_nostro["account_number"]
            credit_account_type = "CHIPS_NOSTRO"
        else:
            # No CHIPS nostro relationship - should have been routed via FED
            # But if we're here, use creditor BIC as fallback
            credit_account = creditor_bic
            credit_account_type = "EXTERNAL"
        
        # Debit: Source account
        if is_inbound:
            vostro = settlement_account_lookup.lookup_vostro_account(debtor_bic)
            if vostro:
                debit_account = vostro["account_number"]
                debit_account_type = "VOSTRO"
            else:
                debit_account = debtor_bic
                debit_account_type = "EXTERNAL"
        else:
            debit_account = debtor_bic
            debit_account_type = "CUSTOMER"
    
    elif selected_network == RoutingNetwork.SWIFT:
        # SWIFT: International payment network
        if is_outbound:
            # Wells Fargo sending to foreign bank
            # Credit: Foreign bank's nostro account at Wells Fargo
            swift_nostro = settlement_account_lookup.lookup_swift_out_nostro_account(creditor_bic)
            if swift_nostro:
                credit_account = swift_nostro["account_number"]
                credit_account_type = "SWIFT_NOSTRO"
            else:
                # No nostro account - use creditor BIC
                credit_account = creditor_bic
                credit_account_type = "EXTERNAL"
            
            # Debit: Source account (customer or internal)
            debit_account = debtor_bic
            debit_account_type = "CUSTOMER"
        else:
            # Inbound SWIFT (foreign bank sending to Wells Fargo)
            # Debit: Foreign bank's vostro account
            vostro = settlement_account_lookup.lookup_vostro_account(debtor_bic)
            if vostro:
                debit_account = vostro["account_number"]
                debit_account_type = "VOSTRO"
            else:
                debit_account = debtor_bic
                debit_account_type = "EXTERNAL"
            
            # Credit: Wells Fargo customer account
            credit_account = creditor_bic
            credit_account_type = "CUSTOMER"
    
    else:
        # Unknown network - use default behavior
        debit_account = debtor_bic
        debit_account_type = "EXTERNAL"
        credit_account = creditor_bic
        credit_account_type = "EXTERNAL"
    
    return debit_account, debit_account_type, credit_account, credit_account_type


def simulate_payment_posting(event: PaymentEvent) -> tuple[ServiceResultStatus, list[PostingEntry]]:
    """
    Payment posting with settlement account integration.
    
    Creates debit and credit entries using Wells Fargo internal settlement accounts
    based on the selected routing network (IBT, FED, CHIPS, SWIFT).
    
    Rules:
    - FAIL if amount > 25000 (simple control threshold) OR end_to_end_id ends with 'Z'
    - ERROR if agent identifiers are missing
    - PASS otherwise
    """

    dbic = (event.debtor_agent.id_value or "").strip()
    cbic = (event.creditor_agent.id_value or "").strip()
    if not dbic or not cbic:
        return ServiceResultStatus.ERROR, []

    # Determine settlement accounts based on routing network
    debit_account, debit_account_type, credit_account, credit_account_type = _determine_settlement_accounts(
        event
    )

    entries = [
        PostingEntry(
            end_to_end_id=event.end_to_end_id,
            side=EntrySide.DEBIT,
            agent_id=dbic,
            amount=event.amount,
            currency=event.currency,
            settlement_account=debit_account,
            account_type=debit_account_type,
        ),
        PostingEntry(
            end_to_end_id=event.end_to_end_id,
            side=EntrySide.CREDIT,
            agent_id=cbic,
            amount=event.amount,
            currency=event.currency,
            settlement_account=credit_account,
            account_type=credit_account_type,
        ),
    ]

    try:
        if event.amount > Decimal("25000"):
            return ServiceResultStatus.FAIL, entries
    except Exception:
        return ServiceResultStatus.ERROR, entries

    if event.end_to_end_id.strip().upper().endswith("Z"):
        return ServiceResultStatus.FAIL, entries

    return ServiceResultStatus.PASS, entries


class PaymentPostingService:
    """
    Kafka consumer for payment posting:
    - consume PaymentEvent
    - simulate posting by creating debit+credit entries
    - publish ServiceResult {end_to_end_id, service_name, status}
    """

    def __init__(
        self,
        *,
        consumer: KafkaConsumerWrapper,
        producer: KafkaProducerWrapper,
        input_topics: Optional[list[str]] = None,
        result_topic: str = DEFAULT_RESULT_TOPIC,
        error_topic: str = DEFAULT_ERROR_TOPIC,
        service_name: str = SERVICE_NAME,
        key_fn: Optional[Callable[[PaymentEvent], Optional[Union[str, bytes]]]] = None,
    ) -> None:
        self._consumer = consumer
        self._producer = producer
        self._result_topic = result_topic
        self._error_topic = error_topic
        self._service_name = service_name
        self._key_fn = key_fn

        self._consumer.subscribe(input_topics or [DEFAULT_INPUT_TOPIC])

    def _handle_event(self, event: PaymentEvent) -> Any:
        print(
            f"[PaymentPosting] Processing payment: E2E={event.end_to_end_id}, "
            f"Network={event.selected_network.value if event.selected_network else 'NONE'}, "
            f"Amount={event.amount} {event.currency}"
        )
        
        status, entries = simulate_payment_posting(event)
        
        # Log settlement accounts used
        if entries:
            debit_entry = entries[0]
            credit_entry = entries[1]
            print(
                f"[PaymentPosting] Debit: {debit_entry.settlement_account} ({debit_entry.account_type}), "
                f"Credit: {credit_entry.settlement_account} ({credit_entry.account_type})"
            )
        
        # Post to ledger if status is PASS
        if status == ServiceResultStatus.PASS and entries:
            # Check for double posting
            if is_transaction_processed(event.end_to_end_id):
                print(
                    f"[PaymentPosting] ERROR: Transaction {event.end_to_end_id} already processed (double posting detected)"
                )
                status = ServiceResultStatus.ERROR
            else:
                # Post transaction to ledger
                success, error_msg = post_transaction(entries, event.end_to_end_id)
                if not success:
                    print(f"[PaymentPosting] ERROR posting to ledger: {error_msg}")
                    status = ServiceResultStatus.ERROR
                else:
                    print(f"[PaymentPosting] Successfully posted transaction {event.end_to_end_id} to ledger")
        
        result = ServiceResult(end_to_end_id=event.end_to_end_id, service_name=self._service_name, status=status)
        payload = _service_result_to_json_bytes(result)
        key = self._key_fn(event) if self._key_fn else event.end_to_end_id
        self._producer.send_bytes(self._result_topic, key, payload)
        if status in (ServiceResultStatus.FAIL, ServiceResultStatus.ERROR):
            self._producer.send_bytes(self._error_topic, key, payload)
        return result

    def run(
        self,
        *,
        poll_timeout_s: float = 1.0,
        max_messages: Optional[int] = None,
        on_error: Optional[Callable[[Exception], Any]] = None,
    ) -> int:
        from kafka_bus.consumer import payment_event_from_json
        
        return self._consumer.run(
            self._handle_event,
            deserializer=payment_event_from_json,
            poll_timeout_s=poll_timeout_s,
            max_messages=max_messages,
            on_error=on_error,
        )

    def close(self) -> None:
        self._consumer.close()
        self._producer.flush()



def main():
    print("Starting Posting Check Service...")
    service = PaymentPostingService(
        consumer=KafkaConsumerWrapper(
            group_id="posting-check",
            bootstrap_servers="localhost:9092",
        ),
        producer=KafkaProducerWrapper(
            bootstrap_servers="localhost:9092",
        ),
    )
    service.run()

if __name__ == "__main__":
    main()

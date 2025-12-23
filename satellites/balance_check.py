from __future__ import annotations

import json
from dataclasses import asdict
from decimal import Decimal
from typing import Any, Callable, Optional, Union

from canonical import PaymentEvent, ServiceResult, ServiceResultStatus
from kafka_bus import KafkaConsumerWrapper, KafkaProducerWrapper
from orchestrator import topics
from satellites import settlement_account_lookup
from satellites.ledger_service import get_account_balance, has_sufficient_balance


SERVICE_NAME = "balance_check"
DEFAULT_INPUT_TOPIC = topics.TOPIC_BALANCE_CHECK_IN
DEFAULT_RESULT_TOPIC = topics.TOPIC_BALANCE_CHECK_OUT
DEFAULT_ERROR_TOPIC = topics.TOPIC_BALANCE_CHECK_ERR


def _service_result_to_json_bytes(result: ServiceResult) -> bytes:
    d = asdict(result)
    st = d.get("status")
    if hasattr(st, "value"):
        d["status"] = st.value
    return json.dumps(d, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def simulate_balance_check(event: PaymentEvent) -> ServiceResultStatus:
    """
    Balance check using ledger service to validate sufficient funds.
    
    Determines the debit account based on payment routing and checks if it has
    sufficient balance in the ledger.
    
    Rules:
    - FAIL if insufficient balance in debit account
    - FAIL if debit account not found in ledger
    - FAIL if end_to_end_id ends with 'B' (case-insensitive) - legacy rule
    - ERROR if account lookup fails
    - PASS otherwise
    """
    
    # Legacy rule: fail if end_to_end_id ends with 'B'
    if event.end_to_end_id.strip().upper().endswith("B"):
        return ServiceResultStatus.FAIL
    
    # Determine debit account from payment event
    # This should match the logic in payment_posting._determine_settlement_accounts
    debtor_bic = (event.debtor_agent.id_value or "").strip().upper()[:8]
    creditor_bic = (event.creditor_agent.id_value or "").strip().upper()[:8]
    debtor_country = event.debtor_agent.country or ""
    creditor_country = event.creditor_agent.country or ""
    
    WELLS_BIC = "WFBIUS6S"
    is_inbound = debtor_country != "US" and creditor_bic == WELLS_BIC
    is_outbound = debtor_bic == WELLS_BIC and creditor_country != "US"
    
    debit_account_id: Optional[str] = None
    
    # Determine debit account based on routing network
    if event.selected_network:
        if event.selected_network.value == "INTERNAL":
            if is_inbound:
                # Debit from foreign bank's vostro account
                vostro = settlement_account_lookup.lookup_vostro_account(debtor_bic)
                if vostro:
                    debit_account_id = vostro["account_number"]
                else:
                    debit_account_id = debtor_bic
            else:
                debit_account_id = debtor_bic
        elif event.selected_network.value == "FED":
            if is_inbound:
                vostro = settlement_account_lookup.lookup_vostro_account(debtor_bic)
                if vostro:
                    debit_account_id = vostro["account_number"]
                else:
                    debit_account_id = debtor_bic
            else:
                debit_account_id = debtor_bic
        elif event.selected_network.value == "CHIPS":
            if is_inbound:
                vostro = settlement_account_lookup.lookup_vostro_account(debtor_bic)
                if vostro:
                    debit_account_id = vostro["account_number"]
                else:
                    debit_account_id = debtor_bic
            else:
                debit_account_id = debtor_bic
        elif event.selected_network.value == "SWIFT":
            if is_outbound:
                debit_account_id = debtor_bic
            else:
                vostro = settlement_account_lookup.lookup_vostro_account(debtor_bic)
                if vostro:
                    debit_account_id = vostro["account_number"]
                else:
                    debit_account_id = debtor_bic
        else:
            debit_account_id = debtor_bic
    else:
        # No routing network selected yet - use debtor BIC
        debit_account_id = debtor_bic
    
    if not debit_account_id:
        return ServiceResultStatus.ERROR
    
    # Check balance in ledger
    if not has_sufficient_balance(debit_account_id, event.amount):
        print(
            f"[BalanceCheck] Insufficient balance: account={debit_account_id}, "
            f"required={event.amount}, available={get_account_balance(debit_account_id) or 0}"
        )
        return ServiceResultStatus.FAIL
    
    print(
        f"[BalanceCheck] Sufficient balance: account={debit_account_id}, "
        f"required={event.amount}, available={get_account_balance(debit_account_id) or 0}"
    )
    return ServiceResultStatus.PASS


class BalanceCheckService:
    """
    Kafka consumer for the balance check satellite:
    - consume PaymentEvent
    - simulate funds availability check
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
        status = simulate_balance_check(event)
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
    print("Starting Balance Check Service...")
    service = BalanceCheckService(
        consumer=KafkaConsumerWrapper(
            group_id="balance-check",
            bootstrap_servers="localhost:9092",
        ),
        producer=KafkaProducerWrapper(
            bootstrap_servers="localhost:9092",
        ),
    )
    service.run()

if __name__ == "__main__":
    main()

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any, Callable, Optional, Union

from canonical import AccountValidationEnrichment, PaymentEvent, ServiceResult, ServiceResultStatus
from ingress.mx_receiver import payment_event_to_json_bytes
from kafka_bus import KafkaConsumerWrapper, KafkaProducerWrapper
from orchestrator import topics

from .account_lookup import enrich_payment_event


SERVICE_NAME = "account_validation"
DEFAULT_INPUT_TOPIC = topics.TOPIC_ACCOUNT_VALIDATION_IN
DEFAULT_RESULT_TOPIC = topics.TOPIC_ACCOUNT_VALIDATION_OUT
DEFAULT_ERROR_TOPIC = topics.TOPIC_ACCOUNT_VALIDATION_ERR
DEFAULT_ROUTING_TOPIC = topics.TOPIC_ROUTING_VALIDATION_IN


def _service_result_to_json_bytes(result: ServiceResult) -> bytes:
    d = asdict(result)
    st = d.get("status")
    if hasattr(st, "value"):
        d["status"] = st.value
    return json.dumps(d, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def simulate_account_validation(event: PaymentEvent) -> ServiceResultStatus:
    """
    Control-check simulation. Deterministic and side-effect free.

    Current rule:
    - FAIL if end_to_end_id ends with 'X' (case-insensitive)
    - PASS otherwise
    """

    if event.end_to_end_id.strip().upper().endswith("X"):
        return ServiceResultStatus.FAIL
    return ServiceResultStatus.PASS


class AccountValidationService:
    """
    Kafka consumer for the account validation satellite:
    - consume PaymentEvent
    - simulate validation
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
        routing_topic: str = DEFAULT_ROUTING_TOPIC,
        service_name: str = SERVICE_NAME,
        key_fn: Optional[Callable[[PaymentEvent], Optional[Union[str, bytes]]]] = None,
    ) -> None:
        self._consumer = consumer
        self._producer = producer
        self._result_topic = result_topic
        self._error_topic = error_topic
        self._routing_topic = routing_topic
        self._service_name = service_name
        self._key_fn = key_fn

        topics_to_subscribe = input_topics or [DEFAULT_INPUT_TOPIC]
        print(f"[AccountValidation] Subscribing to topics: {topics_to_subscribe}")
        self._consumer.subscribe(topics_to_subscribe)

    def _handle_event(self, event: PaymentEvent) -> Any:
        print(f"[AccountValidation] Received PaymentEvent: E2E={event.end_to_end_id}, MsgId={event.msg_id}, Amount={event.amount} {event.currency}")
        
        # Step 1: Validate account (existing logic)
        status = simulate_account_validation(event)
        print(f"[AccountValidation] Validation result: {status.value}")
        
        # Step 2: Enrich PaymentEvent with account data (if validation PASS)
        creditor_bic = (event.creditor_agent.id_value or "").strip()
        enrichment = None
        enriched_event = event
        
        if status == ServiceResultStatus.PASS:
            enrichment = enrich_payment_event(event, status, creditor_bic)
            if enrichment:
                # Create enriched PaymentEvent with account_validation data
                enriched_event = PaymentEvent(
                    msg_id=event.msg_id,
                    end_to_end_id=event.end_to_end_id,
                    amount=event.amount,
                    currency=event.currency,
                    debtor_agent=event.debtor_agent,
                    creditor_agent=event.creditor_agent,
                    status=event.status,
                    account_validation=enrichment,
                )
                print(f"[AccountValidation] Enriched PaymentEvent: creditor_type={enrichment.creditor_type.value}, "
                      f"fed_member={enrichment.fed_member}, chips_member={enrichment.chips_member}, "
                      f"nostro={enrichment.nostro_with_us}, vostro={enrichment.vostro_with_us}")
            else:
                print(f"[AccountValidation] WARNING: Account not found in lookup for BIC={creditor_bic}")
                # If account not found, treat as validation failure
                status = ServiceResultStatus.FAIL
        
        # Step 3: Publish ServiceResult for orchestrator sequencing
        result = ServiceResult(end_to_end_id=event.end_to_end_id, service_name=self._service_name, status=status)
        payload = _service_result_to_json_bytes(result)
        key = self._key_fn(event) if self._key_fn else event.end_to_end_id
        print(f"[AccountValidation] Publishing ServiceResult to topic='{self._result_topic}'")
        self._producer.send_bytes(self._result_topic, key, payload)
        
        # Step 4: If validation PASS, publish enriched PaymentEvent to routing_validation topic
        if status == ServiceResultStatus.PASS and enrichment:
            enriched_payload = payment_event_to_json_bytes(enriched_event)
            print(f"[AccountValidation] Publishing enriched PaymentEvent to routing topic='{self._routing_topic}'")
            self._producer.send_bytes(self._routing_topic, key, enriched_payload)
        elif status in (ServiceResultStatus.FAIL, ServiceResultStatus.ERROR):
            print(f"[AccountValidation] Publishing error to topic='{self._error_topic}'")
            self._producer.send_bytes(self._error_topic, key, payload)
        
        print(f"[AccountValidation] Completed processing E2E={event.end_to_end_id}")
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
    print("[AccountValidation] Starting Account Validation Service...")
    consumer = KafkaConsumerWrapper(
        group_id="account-validation",
        bootstrap_servers="localhost:9092",
        auto_offset_reset="earliest",
    )
    producer = KafkaProducerWrapper(
        bootstrap_servers="localhost:9092",
    )
    service = AccountValidationService(
        consumer=consumer,
        producer=producer,
    )
    print("[AccountValidation] Account Validation Service started. Listening to Kafka...")
    service.run()

if __name__ == "__main__":
    main()



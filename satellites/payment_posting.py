from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from decimal import Decimal
from enum import Enum
from typing import Any, Callable, Optional, Union

from canonical import PaymentEvent, ServiceResult, ServiceResultStatus
from kafka_bus import KafkaConsumerWrapper, KafkaProducerWrapper
from orchestrator import topics


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


def _service_result_to_json_bytes(result: ServiceResult) -> bytes:
    d = asdict(result)
    st = d.get("status")
    if hasattr(st, "value"):
        d["status"] = st.value
    return json.dumps(d, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def simulate_payment_posting(event: PaymentEvent) -> tuple[ServiceResultStatus, list[PostingEntry]]:
    """
    Control-check simulation for payment posting with debit+credit entries.

    Current rule:
    - Always create two entries: DEBIT debtor_agent, CREDIT creditor_agent
    - FAIL if amount > 25000 (simple control threshold) OR end_to_end_id ends with 'Z' (case-insensitive)
    - ERROR if agent identifiers are missing
    - PASS otherwise
    """

    dbic = (event.debtor_agent.id_value or "").strip()
    cbic = (event.creditor_agent.id_value or "").strip()
    if not dbic or not cbic:
        return ServiceResultStatus.ERROR, []

    entries = [
        PostingEntry(
            end_to_end_id=event.end_to_end_id,
            side=EntrySide.DEBIT,
            agent_id=dbic,
            amount=event.amount,
            currency=event.currency,
        ),
        PostingEntry(
            end_to_end_id=event.end_to_end_id,
            side=EntrySide.CREDIT,
            agent_id=cbic,
            amount=event.amount,
            currency=event.currency,
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
        status, _entries = simulate_payment_posting(event)
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
        return self._consumer.run(
            self._handle_event,
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

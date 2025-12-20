from __future__ import annotations

import json
from dataclasses import asdict
from decimal import Decimal
from typing import Any, Callable, Optional, Union

from canonical import PaymentEvent, ServiceResult, ServiceResultStatus
from kafka_bus import KafkaConsumerWrapper, KafkaProducerWrapper
from orchestrator import topics


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
    Control-check simulation for funds availability. Deterministic and side-effect free.

    Current rule:
    - FAIL if amount > 10000 (in the given currency) OR end_to_end_id ends with 'B' (case-insensitive)
    - PASS otherwise
    """

    try:
        if event.amount > Decimal("10000"):
            return ServiceResultStatus.FAIL
    except Exception:
        return ServiceResultStatus.ERROR

    if event.end_to_end_id.strip().upper().endswith("B"):
        return ServiceResultStatus.FAIL

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

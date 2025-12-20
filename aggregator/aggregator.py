from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any, Callable, Optional, Union

from canonical import ServiceResult
from kafka_bus import KafkaConsumerWrapper, KafkaProducerWrapper
from kafka_bus.consumer import service_result_from_json

from .payment_state import PaymentProcessingState, PaymentStateMachine, PaymentStateSnapshot


DEFAULT_SERVICE_RESULTS_TOPIC = "service.results"
DEFAULT_FINAL_TOPIC = "payments.final"


def payment_state_snapshot_to_json_bytes(snapshot: PaymentStateSnapshot) -> bytes:
    d = asdict(snapshot)
    # Enums -> .value
    st = d.get("state")
    if hasattr(st, "value"):
        d["state"] = st.value
    for k in ("control_status", "account_status", "funds_status", "posted_status"):
        v = d.get(k)
        if hasattr(v, "value"):
            d[k] = v.value
    return json.dumps(d, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


class ServiceResultAggregator:
    """
    Aggregator that consumes ServiceResult events, updates the in-memory payment state,
    and emits a final status when all services succeed.

    Final condition (default): state == POSTED (i.e., all control checks + posting PASS).
    """

    def __init__(
        self,
        *,
        consumer: KafkaConsumerWrapper,
        producer: KafkaProducerWrapper,
        state_machine: Optional[PaymentStateMachine] = None,
        results_topic: str = DEFAULT_SERVICE_RESULTS_TOPIC,
        final_topic: str = DEFAULT_FINAL_TOPIC,
        emit_state: PaymentProcessingState = PaymentProcessingState.POSTED,
        key_fn: Optional[Callable[[PaymentStateSnapshot], Optional[Union[str, bytes]]]] = None,
    ) -> None:
        self._consumer = consumer
        self._producer = producer
        self._sm = state_machine or PaymentStateMachine()
        self._final_topic = final_topic
        self._emit_state = emit_state
        self._key_fn = key_fn
        self._emitted: set[str] = set()

        self._consumer.subscribe([results_topic])

    @property
    def state_machine(self) -> PaymentStateMachine:
        return self._sm

    def _maybe_emit_final(self, snapshot: PaymentStateSnapshot) -> None:
        if snapshot.state != self._emit_state:
            return
        e2e = snapshot.end_to_end_id
        if e2e in self._emitted:
            return
        self._emitted.add(e2e)

        payload = payment_state_snapshot_to_json_bytes(snapshot)
        key = self._key_fn(snapshot) if self._key_fn else e2e
        self._producer.send_bytes(self._final_topic, key, payload)

    def _handle_result(self, result: ServiceResult) -> Any:
        snapshot = self._sm.ingest_service_result(result)
        self._maybe_emit_final(snapshot)
        return snapshot

    def run(
        self,
        *,
        poll_timeout_s: float = 1.0,
        max_messages: Optional[int] = None,
        on_error: Optional[Callable[[Exception], Any]] = None,
    ) -> int:
        return self._consumer.run(
            self._handle_result,
            deserializer=service_result_from_json,
            poll_timeout_s=poll_timeout_s,
            max_messages=max_messages,
            on_error=on_error,
        )

    def close(self) -> None:
        self._consumer.close()
        self._producer.flush()



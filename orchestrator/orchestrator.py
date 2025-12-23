from __future__ import annotations

import threading
from typing import Any, Callable, Optional, Union

from aggregator.aggregator import payment_state_snapshot_to_json_bytes
from aggregator.payment_state import PaymentProcessingState, PaymentStateMachine, PaymentStateSnapshot
from canonical import PaymentEvent, ServiceResult, ServiceResultStatus
from kafka_bus import KafkaConsumerWrapper, KafkaProducerWrapper
from kafka_bus.consumer import payment_event_from_json, service_result_from_json

from . import topics


class PaymentOrchestrator:
    """
    Sequential orchestrator:
    - consumes canonical PaymentEvent from TOPIC_CANONICAL_INGRESS
    - sends to account_validation input topic
    - waits for each service result (PASS) before sending to the next service
    - emits final status when all services succeed

    Satellites remain unaware of sequencing; they only listen to their own input topic
    and publish ServiceResult to their own output topic (and error topic on FAIL/ERROR).
    """

    def __init__(
        self,
        *,
        ingress_consumer: KafkaConsumerWrapper,
        results_consumer: KafkaConsumerWrapper,
        producer: KafkaProducerWrapper,
        state_machine: Optional[PaymentStateMachine] = None,
        final_topic: str = topics.TOPIC_FINAL_STATUS,
        key_fn: Optional[Callable[[PaymentStateSnapshot], Optional[Union[str, bytes]]]] = None,
    ) -> None:
        self._ingress_consumer = ingress_consumer
        self._results_consumer = results_consumer
        self._producer = producer
        self._sm = state_machine or PaymentStateMachine()
        self._final_topic = final_topic
        self._key_fn = key_fn

        # Cache canonical PaymentEvent so we can forward it to the next step
        self._events: dict[str, PaymentEvent] = {}
        self._lock = threading.RLock()
        self._final_emitted: set[str] = set()

        ingress_topics = [topics.TOPIC_CANONICAL_INGRESS]
        results_topics = [
            topics.TOPIC_ACCOUNT_VALIDATION_OUT,
            topics.TOPIC_ROUTING_VALIDATION_OUT,
            topics.TOPIC_SANCTIONS_CHECK_OUT,
            topics.TOPIC_BALANCE_CHECK_OUT,
            topics.TOPIC_PAYMENT_POSTING_OUT,
            topics.TOPIC_ACCOUNT_VALIDATION_ERR,
            topics.TOPIC_ROUTING_VALIDATION_ERR,
            topics.TOPIC_SANCTIONS_CHECK_ERR,
            topics.TOPIC_BALANCE_CHECK_ERR,
            topics.TOPIC_PAYMENT_POSTING_ERR,
        ]

        print(f"[Orchestrator] Subscribing ingress consumer to: {ingress_topics}")
        self._ingress_consumer.subscribe(ingress_topics)

        print(f"[Orchestrator] Subscribing results consumer to: {results_topics}")
        self._results_consumer.subscribe(results_topics)

    @property
    def state_machine(self) -> PaymentStateMachine:
        return self._sm

    def _publish_to_step(self, topic: str, event: PaymentEvent) -> None:
        # Use the existing PaymentEvent send method (JSON serialization)
        print(f"[Orchestrator] Forwarding E2E={event.end_to_end_id} to step topic='{topic}'")
        self._producer.send(topic, event.end_to_end_id, event)

    def _handle_ingress_payment(self, event: PaymentEvent) -> Any:
        with self._lock:
            self._events[event.end_to_end_id] = event
        print(f"[Orchestrator] Ingress PaymentEvent received: E2E={event.end_to_end_id}, MsgId={event.msg_id}")
        self._sm.ingest_payment_event(event)
        self._publish_to_step(topics.TOPIC_ACCOUNT_VALIDATION_IN, event)
        return event

    def _emit_final_once(self, snapshot: PaymentStateSnapshot, event: Optional[PaymentEvent] = None) -> None:
        e2e = snapshot.end_to_end_id
        if snapshot.state != PaymentProcessingState.POSTED:
            return
        with self._lock:
            if e2e in self._final_emitted:
                return
            self._final_emitted.add(e2e)
            # Get PaymentEvent from cache if not provided
            if event is None:
                event = self._events.get(e2e)

        # Publish PaymentEvent to final topic for egress service
        # The egress service needs the full PaymentEvent to generate network messages
        if event:
            print(f"[Orchestrator] Emitting FINAL PaymentEvent for E2E={e2e}, state={snapshot.state.value}")
            self._producer.send(self._final_topic, e2e, event)
        else:
            # Fallback: publish snapshot if event not available
            payload = payment_state_snapshot_to_json_bytes(snapshot)
            key = self._key_fn(snapshot) if self._key_fn else e2e
            print(f"[Orchestrator] Emitting FINAL state (no event) for E2E={e2e}, state={snapshot.state.value}")
            self._producer.send_bytes(self._final_topic, key, payload)

    def _handle_service_result(self, result: ServiceResult) -> Any:
        snapshot = self._sm.ingest_service_result(result)
        print(
            f"[Orchestrator] ServiceResult received: "
            f"service={result.service_name}, E2E={result.end_to_end_id}, status={result.status.value}"
        )

        # On FAIL/ERROR: stop progression (satellites already publish to per-service error topics).
        if result.status in (ServiceResultStatus.FAIL, ServiceResultStatus.ERROR):
            print(
                f"[Orchestrator] Halting progression for E2E={result.end_to_end_id} "
                f"due to status={result.status.value}"
            )
            return snapshot

        with self._lock:
            event = self._events.get(result.end_to_end_id)

        # If we don't have the PaymentEvent cached yet, we can't forward; keep state updated.
        if event is None:
            print(
                f"[Orchestrator] No cached PaymentEvent for E2E={result.end_to_end_id}; "
                f"cannot forward to next step."
            )
            return snapshot

        svc = result.service_name.strip().lower()
        if svc == "account_validation":
            # Account validation publishes enriched PaymentEvent directly to routing_validation topic.
            # Orchestrator just waits for routing_validation ServiceResult.
            pass
        elif svc == "routing_validation":
            # Routing validation publishes routed PaymentEvent directly to sanctions_check INPUT topic
            # (like account_validation publishes to routing_validation INPUT).
            # Orchestrator just waits for sanctions_check ServiceResult.
            pass
        elif svc == "sanctions_check":
            self._publish_to_step(topics.TOPIC_BALANCE_CHECK_IN, event)
        elif svc == "balance_check":
            self._publish_to_step(topics.TOPIC_PAYMENT_POSTING_IN, event)
        elif svc == "payment_posting":
            self._emit_final_once(snapshot, event)

        return snapshot

    def run(
        self,
        *,
        poll_timeout_s: float = 1.0,
        max_messages: Optional[int] = None,
        on_error: Optional[Callable[[Exception], Any]] = None,
    ) -> tuple[int, int]:
        """
        Run ingress consumption and results consumption concurrently (two threads).

        Returns: (ingress_processed, results_processed) when max_messages is set for both,
        otherwise runs indefinitely.
        """
        
        ingress_count: list[int] = [0]
        results_count: list[int] = [0]
        err_holder: list[Exception] = []

        def _run_ingress() -> None:
            try:
                ingress_count[0] = self._ingress_consumer.run(
                    self._handle_ingress_payment,
                    deserializer=payment_event_from_json,
                    poll_timeout_s=poll_timeout_s,
                    max_messages=max_messages,
                    on_error=on_error,
                )
            except Exception as e:
                err_holder.append(e)

        def _run_results() -> None:
            try:
                results_count[0] = self._results_consumer.run(
                    self._handle_service_result,
                    deserializer=service_result_from_json,
                    poll_timeout_s=poll_timeout_s,
                    max_messages=max_messages,
                    on_error=on_error,
                )
            except Exception as e:
                err_holder.append(e)

        t1 = threading.Thread(target=_run_ingress, name="orchestrator-ingress", daemon=True)
        t2 = threading.Thread(target=_run_results, name="orchestrator-results", daemon=True)
        t1.start()
        t2.start()

        t1.join()
        t2.join()

        if err_holder and on_error is None:
            raise err_holder[0]

        return ingress_count[0], results_count[0]

    def close(self) -> None:
        self._ingress_consumer.close()
        self._results_consumer.close()
        self._producer.flush()


def main():
    print("Starting Payment Orchestrator...")

    ingress_consumer = KafkaConsumerWrapper(
        group_id="orchestrator-ingress",
        bootstrap_servers="localhost:9092",
        topics=["payments.orchestrator.in"],
        auto_offset_reset="earliest",
        
    )

    results_consumer = KafkaConsumerWrapper(
        group_id="orchestrator-results",
        bootstrap_servers="localhost:9092",
        topics=[
            "service.results.account_validation",
            "service.results.routing_validation",
            "service.results.sanctions_check",
            "service.results.balance_check",
            "service.results.payment_posting",
            "service.errors.account_validation",
            "service.errors.routing_validation",
            "service.errors.sanctions_check",
            "service.errors.balance_check",
            "service.errors.payment_posting",
        ],
        auto_offset_reset="earliest",
    )

    producer = KafkaProducerWrapper(
        bootstrap_servers="localhost:9092",
    )

    orchestrator = PaymentOrchestrator(
        ingress_consumer=ingress_consumer,
        results_consumer=results_consumer,
        producer=producer,
    )

    print("Payment Orchestrator started. Listening to Kafka...")
    orchestrator.run()


if __name__ == "__main__":
    main()

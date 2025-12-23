"""
Payment Egress Service.

Consumes posted payments from TOPIC_FINAL_STATUS and dispatches them to appropriate networks:
- INTERNAL (IBT): Internal notification only
- FED: pacs.008 (ISO 20022 Customer Credit Transfer)
- CHIPS: pacs.009 (ISO 20022 Financial Institution Transfer)
- SWIFT: MT103, MT202, or MT202COV based on payment characteristics
"""

from __future__ import annotations

import json
from typing import Any, Callable, Optional, Union

from canonical import PaymentEvent, RoutingNetwork
from egress import (
    canonical_to_mt103,
    canonical_to_mt202,
    canonical_to_mt202cov,
    canonical_to_mx,
    canonical_to_pacs009,
)
from ingress.mx_receiver import payment_event_to_json_bytes
from kafka_bus import KafkaConsumerWrapper, KafkaProducerWrapper
from kafka_bus.consumer import payment_event_from_json
from orchestrator import topics


SERVICE_NAME = "payment_egress"
DEFAULT_INPUT_TOPIC = topics.TOPIC_FINAL_STATUS


def _determine_swift_message_type(event: PaymentEvent) -> str:
    """
    Determine SWIFT message type: MT103, MT202, or MT202COV.
    
    Rules:
    - If intermediary bank exists (agent_chain) → Cover payment → MT202 or MT202COV
      - Domestic (US to US) → MT202
      - International (cross-border) → MT202COV
    - If no intermediary → Direct customer transfer → MT103
    """
    has_intermediary = event.agent_chain and len(event.agent_chain) > 0
    
    if has_intermediary:
        # Cover payment - determine domestic vs international
        debtor_country = event.debtor_agent.country or ""
        creditor_country = event.creditor_agent.country or ""
        
        is_domestic = (debtor_country == "US" and creditor_country == "US")
        
        if is_domestic:
            return "MT202"
        else:
            return "MT202COV"
    else:
        # Direct customer credit transfer
        return "MT103"


def _dispatch_payment(event: PaymentEvent) -> tuple[str, Union[bytes, str]]:
    """
    Dispatch payment to appropriate network and generate message format.
    
    Returns:
        Tuple of (network_name, message_bytes_or_string)
    """
    if not event.selected_network:
        raise ValueError(f"PaymentEvent {event.end_to_end_id} has no selected_network")
    
    network = event.selected_network
    
    if network == RoutingNetwork.INTERNAL:
        # IBT: Internal notification only (to be implemented later)
        notification = {
            "type": "INTERNAL_NOTIFICATION",
            "end_to_end_id": event.end_to_end_id,
            "msg_id": event.msg_id,
            "amount": str(event.amount),
            "currency": event.currency,
            "status": "POSTED",
        }
        return ("INTERNAL", json.dumps(notification, indent=2))
    
    elif network == RoutingNetwork.FED:
        # FED: pacs.008 (ISO 20022 Customer Credit Transfer)
        message = canonical_to_mx.payment_event_to_pacs008_xml(event)
        return ("FED", message)
    
    elif network == RoutingNetwork.CHIPS:
        # CHIPS: pacs.009 (ISO 20022 Financial Institution Transfer)
        message = canonical_to_pacs009.payment_event_to_pacs009_xml(event)
        return ("CHIPS", message)
    
    elif network == RoutingNetwork.SWIFT:
        # SWIFT: Determine message type (MT103, MT202, or MT202COV)
        message_type = _determine_swift_message_type(event)
        
        if message_type == "MT103":
            message = canonical_to_mt103.payment_event_to_mt103(event)
            return ("SWIFT_MT103", message)
        elif message_type == "MT202":
            message = canonical_to_mt202.payment_event_to_mt202(event)
            return ("SWIFT_MT202", message)
        else:  # MT202COV
            message = canonical_to_mt202cov.payment_event_to_mt202cov(event)
            return ("SWIFT_MT202COV", message)
    
    else:
        raise ValueError(f"Unsupported network: {network}")


class PaymentEgressService:
    """
    Egress service that consumes posted payments and dispatches to networks.
    
    Consumes PaymentEvent from TOPIC_FINAL_STATUS (published by orchestrator).
    Generates appropriate message format and dispatches to network.
    """

    def __init__(
        self,
        *,
        consumer: KafkaConsumerWrapper,
        input_topic: str = DEFAULT_INPUT_TOPIC,
        service_name: str = SERVICE_NAME,
        key_fn: Optional[Callable[[PaymentEvent], Optional[Union[str, bytes]]]] = None,
    ) -> None:
        self._consumer = consumer
        self._input_topic = input_topic
        self._service_name = service_name
        self._key_fn = key_fn

        self._consumer.subscribe([input_topic])

    def _handle_event(self, event: PaymentEvent) -> None:
        """Process a posted PaymentEvent and dispatch to network."""
        try:
            print(f"[Egress] Processing payment: E2E={event.end_to_end_id}, Network={event.selected_network}")
            
            network_name, message = _dispatch_payment(event)
            
            # Log the dispatch (in production, this would send to actual network)
            print(f"[Egress] Dispatched to {network_name}:")
            if isinstance(message, bytes):
                # For XML messages, decode to show content
                try:
                    message_str = message.decode("utf-8")
                    print(f"  Message (first 500 chars):\n{message_str[:500]}")
                except:
                    print(f"  Message (bytes, length={len(message)})")
            else:
                print(f"  Message:\n{message[:500]}")
            
            # In production, this would:
            # - Send to FED network adapter
            # - Send to CHIPS network adapter
            # - Send to SWIFT network adapter
            # For now, we just log the dispatch
            
        except Exception as e:
            print(f"[Egress] Error processing payment {event.end_to_end_id}: {e}")
            raise

    def run(
        self,
        *,
        poll_timeout_s: float = 1.0,
        max_messages: Optional[int] = None,
        on_error: Optional[Callable[[Exception], Any]] = None,
    ) -> int:
        """
        Run the egress service, consuming from TOPIC_FINAL_STATUS.
        
        Note: The orchestrator publishes PaymentEvent JSON to TOPIC_FINAL_STATUS
        when payment reaches POSTED state.
        """
        return self._consumer.run(
            self._handle_event,
            deserializer=payment_event_from_json,
            poll_timeout_s=poll_timeout_s,
            max_messages=max_messages,
            on_error=on_error,
        )

    def close(self) -> None:
        self._consumer.close()


def main():
    """Main entry point for payment egress service."""
    print("Starting Payment Egress Service...")
    
    consumer = KafkaConsumerWrapper(
        group_id="payment-egress",
        bootstrap_servers="localhost:9092",
        topics=[topics.TOPIC_FINAL_STATUS],
        auto_offset_reset="earliest",
    )
    
    service = PaymentEgressService(consumer=consumer)
    
    print(f"Payment Egress Service started. Listening to {topics.TOPIC_FINAL_STATUS}...")
    service.run()


if __name__ == "__main__":
    main()


from __future__ import annotations

import json
from dataclasses import asdict
from decimal import Decimal
from typing import Any, Callable, Optional, Union

from canonical import PaymentEvent
from ingress.mx_to_canonical import pacs008_xml_to_payment_event


INTERNAL_CREDITOR_BIC = "RKBKINBB"
# Internal routing now goes to the orchestrator ingress topic, which will
# sequentially feed satellites (account -> sanctions -> funds -> posting).
DEFAULT_INTERNAL_TOPIC = "payments.orchestrator.in"
DEFAULT_OUTBOUND_TOPIC = "payments.outbound"


def _payment_event_to_wire_dict(event: PaymentEvent) -> dict[str, Any]:
    """
    Convert PaymentEvent to a JSON-serializable dict.
    """

    d = asdict(event)

    # Decimal -> string to preserve precision; enums -> their value
    amt = d.get("amount")
    if isinstance(amt, Decimal):
        d["amount"] = str(amt)

    status = d.get("status")
    if hasattr(status, "value"):
        d["status"] = status.value

    # Handle optional account_validation enrichment
    av = d.get("account_validation")
    if av is not None:
        if isinstance(av, dict):
            av_status = av.get("status")
            if hasattr(av_status, "value"):
                av["status"] = av_status.value
            creditor_type = av.get("creditor_type")
            if hasattr(creditor_type, "value"):
                av["creditor_type"] = creditor_type.value

    # Handle optional routing fields
    selected_network = d.get("selected_network")
    if selected_network and hasattr(selected_network, "value"):
        d["selected_network"] = selected_network.value

    agent_chain = d.get("agent_chain")
    if agent_chain and isinstance(agent_chain, list):
        # agent_chain is already a list of dicts from asdict(), no conversion needed
        pass

    # Handle optional routing_decision
    routing_decision = d.get("routing_decision")
    if routing_decision is not None:
        if isinstance(routing_decision, dict):
            # Convert enums in routing_decision
            rd_selected_network = routing_decision.get("selected_network")
            if rd_selected_network and hasattr(rd_selected_network, "value"):
                routing_decision["selected_network"] = rd_selected_network.value
            
            rd_urgency = routing_decision.get("urgency")
            if rd_urgency and hasattr(rd_urgency, "value"):
                routing_decision["urgency"] = rd_urgency.value
            
            rd_customer_preference = routing_decision.get("customer_preference")
            if rd_customer_preference and hasattr(rd_customer_preference, "value"):
                routing_decision["customer_preference"] = rd_customer_preference.value
            
            # Handle account_validation_data in routing_decision
            rd_av = routing_decision.get("account_validation_data")
            if rd_av is not None and isinstance(rd_av, dict):
                rd_av_status = rd_av.get("status")
                if rd_av_status and hasattr(rd_av_status, "value"):
                    rd_av["status"] = rd_av_status.value
                rd_av_creditor_type = rd_av.get("creditor_type")
                if rd_av_creditor_type and hasattr(rd_av_creditor_type, "value"):
                    rd_av["creditor_type"] = rd_av_creditor_type.value

    return d


def payment_event_to_json_bytes(event: PaymentEvent) -> bytes:
    return json.dumps(_payment_event_to_wire_dict(event), separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def route_topic_for_payment_event(
    event: PaymentEvent,
    *,
    internal_creditor_bic: str = INTERNAL_CREDITOR_BIC,
    internal_topic: str = DEFAULT_INTERNAL_TOPIC,
    outbound_topic: str = DEFAULT_OUTBOUND_TOPIC,
) -> str:
    """
    Routing rule:
    - If creditor_agent == "RKBKINBB" -> internal Kafka topic
    - Else -> outbound topic
    """

    # Normalize to BIC8 so "RKBKINBBXXX" matches "RKBKINBB"
    creditor_bic8 = (event.creditor_agent.id_value or "").strip().upper()[:8]
    internal_bic8 = internal_creditor_bic.strip().upper()[:8]
    if creditor_bic8 == internal_bic8:
        return internal_topic
    return outbound_topic


def publish_payment_event(
    producer: Any,
    topic: str,
    event: PaymentEvent,
    *,
    key: Optional[Union[str, bytes]] = None,
) -> None:
    """
    Publish a PaymentEvent using a producer-like object.

    Supports common producer APIs:
    - kafka-python: producer.send(topic, value=b"...", key=b"...")
    - confluent-kafka: producer.produce(topic, value=b"...", key=b"...")
    - custom: producer.publish(topic, value=b"...", key=b"...")
    """

    value = payment_event_to_json_bytes(event)
    key_bytes: Optional[bytes]
    if key is None:
        key_bytes = None
    elif isinstance(key, bytes):
        key_bytes = key
    else:
        key_bytes = key.encode("utf-8")

    if hasattr(producer, "send"):
        producer.send(topic, value=value, key=key_bytes)
        return
    if hasattr(producer, "produce"):
        producer.produce(topic, value=value, key=key_bytes)
        return
    if hasattr(producer, "publish"):
        producer.publish(topic, value=value, key=key_bytes)
        return

    raise TypeError("Unsupported producer: expected .send(), .produce(), or .publish().")


def handle_pacs008_xml(
    xml: Union[str, bytes],
    *,
    producer: Any,
    internal_creditor_bic: str = INTERNAL_CREDITOR_BIC,
    internal_topic: str = DEFAULT_INTERNAL_TOPIC,
    outbound_topic: str = DEFAULT_OUTBOUND_TOPIC,
    key_fn: Optional[Callable[[PaymentEvent], Optional[Union[str, bytes]]]] = None,
) -> PaymentEvent:
    """
    End-to-end ingress helper:
    pacs.008 XML -> PaymentEvent -> route -> publish -> return PaymentEvent
    """

    event = pacs008_xml_to_payment_event(xml)
    topic = route_topic_for_payment_event(
        event,
        internal_creditor_bic=internal_creditor_bic,
        internal_topic=internal_topic,
        outbound_topic=outbound_topic,
    )
    key = key_fn(event) if key_fn else None
    publish_payment_event(producer, topic, event, key=key)
    return event



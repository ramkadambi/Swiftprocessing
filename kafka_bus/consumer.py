from __future__ import annotations

import importlib
import json
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Optional, Union

from canonical import (
    AccountValidationEnrichment,
    Agent,
    CreditorType,
    PaymentEvent,
    PaymentStatus,
    RoutingDecision,
    RoutingNetwork,
    ServiceResult,
    ServiceResultStatus,
    Urgency,
)


class PaymentEventDeserializeError(ValueError):
    """Raised when a Kafka message cannot be decoded into a PaymentEvent."""


def payment_event_from_json(value: Union[bytes, str]) -> PaymentEvent:
    """
    Deserialize a PaymentEvent from JSON produced by `payment_event_to_json_bytes`.
    """

    if isinstance(value, bytes):
        text = value.decode("utf-8")
    else:
        text = value

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise PaymentEventDeserializeError(f"Invalid JSON: {e}") from e

    try:
        debtor = data["debtor_agent"]
        creditor = data["creditor_agent"]
        amount = data["amount"]
        status = data["status"]
    except Exception as e:
        raise PaymentEventDeserializeError("Missing required PaymentEvent fields in JSON.") from e

    try:
        amt = Decimal(str(amount))
    except (InvalidOperation, TypeError) as e:
        raise PaymentEventDeserializeError(f"Invalid amount: {amount!r}") from e

    try:
        st = PaymentStatus(str(status))
    except Exception as e:
        raise PaymentEventDeserializeError(f"Invalid status: {status!r}") from e

    def _agent_from(d: Any) -> Agent:
        if not isinstance(d, dict):
            raise PaymentEventDeserializeError("Agent must be an object/dict.")
        return Agent(
            id_scheme=d.get("id_scheme"),
            id_value=d.get("id_value"),
            name=d.get("name"),
            country=d.get("country"),
        )

    # Handle optional account_validation enrichment
    account_validation = None
    av_data = data.get("account_validation")
    if av_data and isinstance(av_data, dict):
        try:
            av_status = ServiceResultStatus(str(av_data.get("status", "")))
            creditor_type = CreditorType(str(av_data.get("creditor_type", "")))
            account_validation = AccountValidationEnrichment(
                status=av_status,
                creditor_type=creditor_type,
                fed_member=bool(av_data.get("fed_member", False)),
                chips_member=bool(av_data.get("chips_member", False)),
                nostro_with_us=bool(av_data.get("nostro_with_us", False)),
                vostro_with_us=bool(av_data.get("vostro_with_us", False)),
                preferred_correspondent=av_data.get("preferred_correspondent"),
            )
        except Exception:
            # If enrichment data is malformed, ignore it (optional field)
            account_validation = None

    # Handle optional routing fields
    selected_network = None
    if "selected_network" in data:
        try:
            selected_network = RoutingNetwork(str(data["selected_network"]))
        except (ValueError, TypeError):
            selected_network = None

    agent_chain = None
    if "agent_chain" in data and data["agent_chain"]:
        try:
            agent_chain = [_agent_from(ag) for ag in data["agent_chain"]]
        except Exception:
            agent_chain = None

    routing_rule_applied = data.get("routing_rule_applied")

    # Handle optional routing_decision
    routing_decision = None
    rd_data = data.get("routing_decision")
    if rd_data and isinstance(rd_data, dict):
        try:
            rd_selected_network = RoutingNetwork(str(rd_data.get("selected_network", "")))
            rd_sender_bank = _agent_from(rd_data.get("sender_bank", {}))
            rd_creditor_bank = _agent_from(rd_data.get("creditor_bank", {}))
            rd_intermediary_bank = None
            if rd_data.get("intermediary_bank"):
                rd_intermediary_bank = _agent_from(rd_data["intermediary_bank"])
            
            rd_urgency = Urgency(str(rd_data.get("urgency", "NORMAL")))
            rd_customer_preference = None
            if rd_data.get("customer_preference"):
                rd_customer_preference = RoutingNetwork(str(rd_data["customer_preference"]))
            
            rd_rule_applied = rd_data.get("routing_rule_applied")
            rd_bic_lookup = rd_data.get("bic_lookup_data")
            
            rd_av_data = rd_data.get("account_validation_data")
            rd_account_validation = None
            if rd_av_data and isinstance(rd_av_data, dict):
                try:
                    rd_av_status = ServiceResultStatus(str(rd_av_data.get("status", "")))
                    rd_av_creditor_type = CreditorType(str(rd_av_data.get("creditor_type", "")))
                    rd_account_validation = AccountValidationEnrichment(
                        status=rd_av_status,
                        creditor_type=rd_av_creditor_type,
                        fed_member=bool(rd_av_data.get("fed_member", False)),
                        chips_member=bool(rd_av_data.get("chips_member", False)),
                        nostro_with_us=bool(rd_av_data.get("nostro_with_us", False)),
                        vostro_with_us=bool(rd_av_data.get("vostro_with_us", False)),
                        preferred_correspondent=rd_av_data.get("preferred_correspondent"),
                    )
                except Exception:
                    rd_account_validation = None
            
            routing_decision = RoutingDecision(
                selected_network=rd_selected_network,
                sender_bank=rd_sender_bank,
                creditor_bank=rd_creditor_bank,
                intermediary_bank=rd_intermediary_bank,
                urgency=rd_urgency,
                customer_preference=rd_customer_preference,
                routing_rule_applied=rd_rule_applied,
                bic_lookup_data=rd_bic_lookup,
                account_validation_data=rd_account_validation,
            )
        except Exception:
            # If routing_decision data is malformed, ignore it (optional field)
            routing_decision = None

    return PaymentEvent(
        msg_id=str(data["msg_id"]),
        end_to_end_id=str(data["end_to_end_id"]),
        amount=amt,
        currency=str(data["currency"]),
        debtor_agent=_agent_from(debtor),
        creditor_agent=_agent_from(creditor),
        status=st,
        account_validation=account_validation,
        selected_network=selected_network,
        agent_chain=agent_chain,
        routing_rule_applied=routing_rule_applied,
        routing_decision=routing_decision,
    )


class ServiceResultDeserializeError(ValueError):
    """Raised when a Kafka message cannot be decoded into a ServiceResult."""


def service_result_from_json(value: Union[bytes, str]) -> ServiceResult:
    """
    Deserialize a ServiceResult from JSON produced by satellites.
    """

    if isinstance(value, bytes):
        text = value.decode("utf-8")
    else:
        text = value

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ServiceResultDeserializeError(f"Invalid JSON: {e}") from e

    try:
        end_to_end_id = str(data["end_to_end_id"])
        service_name = str(data["service_name"])
        status_raw = data["status"]
    except Exception as e:
        raise ServiceResultDeserializeError("Missing required ServiceResult fields in JSON.") from e

    try:
        st = ServiceResultStatus(str(status_raw))
    except Exception as e:
        raise ServiceResultDeserializeError(f"Invalid status: {status_raw!r}") from e

    return ServiceResult(end_to_end_id=end_to_end_id, service_name=service_name, status=st)


class KafkaConsumerWrapper:
    """
    Simple Kafka consumer wrapper:
    - subscribes to a topic (or topics)
    - deserializes PaymentEvent from message value (JSON)
    - calls a handler(event)

    Supports either:
    - confluent-kafka
    - kafka-python
    """

    def __init__(
        self,
        *,
        consumer: Optional[Any] = None,
        bootstrap_servers: Optional[Union[str, list[str]]] = None,
        group_id: Optional[str] = None,
        topics: Optional[list[str]] = None,
        client_config: Optional[dict[str, Any]] = None,
        auto_offset_reset: str = "earliest",
    ) -> None:
        self._group_id = group_id
        self._consumer = consumer or self._create_consumer(
            bootstrap_servers=bootstrap_servers,
            group_id=group_id,
            client_config=client_config or {},
            auto_offset_reset=auto_offset_reset,
        )
        if topics:
            self.subscribe(topics)

    def _create_consumer(
        self,
        *,
        bootstrap_servers: Optional[Union[str, list[str]]],
        group_id: Optional[str],
        client_config: dict[str, Any],
        auto_offset_reset: str,
    ) -> Any:
        if not bootstrap_servers:
            raise ValueError("Provide either `consumer=` or `bootstrap_servers=`.")
        if not group_id:
            raise ValueError("group_id is required when creating a consumer.")

        # 1) Try confluent-kafka
        try:
            ck = importlib.import_module("confluent_kafka")
            conf: dict[str, Any] = {
                "bootstrap.servers": bootstrap_servers,
                "group.id": group_id,
                "auto.offset.reset": auto_offset_reset,
            }
            conf.update(client_config)
            return ck.Consumer(conf)
        except ModuleNotFoundError:
            pass

        # 2) Try kafka-python
        try:
            kp = importlib.import_module("kafka")
            conf: dict[str, Any] = {
                "bootstrap_servers": bootstrap_servers,
                "group_id": group_id,
                "auto_offset_reset": auto_offset_reset,
                "enable_auto_commit": True,
            }
            conf.update(client_config)
            return kp.KafkaConsumer(**conf)
        except ModuleNotFoundError as e:
            raise RuntimeError(
                "No supported Kafka client installed. Install `confluent-kafka` or `kafka-python`."
            ) from e

    def subscribe(self, topics: Union[str, list[str]]) -> None:
        if isinstance(topics, str):
            topics_list = [topics]
        else:
            topics_list = topics

        print(f"[KafkaConsumerWrapper] Subscribing to topics: {topics_list}")

        c = self._consumer
        if hasattr(c, "subscribe"):
            c.subscribe(topics_list)
            print(f"[KafkaConsumerWrapper] Subscribe() called successfully")
            return

        raise TypeError("Unsupported underlying consumer: expected .subscribe().")

    def run(
        self,
        handler: Callable[[Any], Any],
        *,
        deserializer: Callable[[Any], Any] = payment_event_from_json,
        poll_timeout_s: float = 1.0,
        max_messages: Optional[int] = None,
        on_error: Optional[Callable[[Exception], Any]] = None,
    ) -> int:
        """
        Poll loop. Calls handler(event) for each message.

        - max_messages: stop after N messages (useful for tests); None = forever
        """
        print(f"[KafkaConsumerWrapper] Starting poll loop (group_id={getattr(self, '_group_id', 'unknown')}, timeout={poll_timeout_s}s)")

        processed = 0
        c = self._consumer
        poll_count = 0

        while max_messages is None or processed < max_messages:
            poll_count += 1
            if poll_count % 10 == 0:
                print(f"[KafkaConsumerWrapper] Still polling... (processed={processed}, polls={poll_count})")
            
            # confluent-kafka style: poll() -> message or None
            if hasattr(c, "poll") and not hasattr(c, "__iter__"):
                msg = c.poll(poll_timeout_s)
                if msg is None:
                    continue
                print(f"[KafkaConsumerWrapper] Received message from confluent-kafka (topic={getattr(msg, 'topic', 'unknown')}, partition={getattr(msg, 'partition', 'unknown')})")
                if hasattr(msg, "error") and msg.error():
                    # msg.error() is truthy on errors; surface as an exception
                    err = RuntimeError(str(msg.error()))
                    if on_error:
                        on_error(err)
                        continue
                    raise err
                raw_val = msg.value() if hasattr(msg, "value") else None
            # kafka-python style: poll(timeout_ms=...) -> {tp: [msgs]}
            elif hasattr(c, "poll"):
                batch = c.poll(timeout_ms=int(poll_timeout_s * 1000))
                if not batch:
                    continue
                print(f"[KafkaConsumerWrapper] Received batch from kafka-python: {len(batch)} topic(s)")
                for _tp, msgs in batch.items():
                    print(f"[KafkaConsumerWrapper] Processing {len(msgs)} message(s) from topic={_tp}")
                    for m in msgs:
                        try:
                            print(f"[KafkaConsumerWrapper] Deserializing message (value_len={len(m.value) if m.value else 0})")
                            obj = deserializer(m.value)
                            print(f"[KafkaConsumerWrapper] Calling handler with deserialized object: {type(obj).__name__}")
                            handler(obj)
                            processed += 1
                            print(f"[KafkaConsumerWrapper] Handler completed successfully (processed={processed})")
                            if max_messages is not None and processed >= max_messages:
                                return processed
                        except Exception as e:
                            print(f"[KafkaConsumerWrapper] ERROR in handler/deserializer: {e}", exc_info=True)
                            if on_error:
                                on_error(e)
                                continue
                            raise
                continue
            else:
                raise TypeError("Unsupported underlying consumer: expected .poll().")

            try:
                print(f"[KafkaConsumerWrapper] Deserializing message (value_len={len(raw_val) if raw_val else 0})")
                obj = deserializer(raw_val)
                print(f"[KafkaConsumerWrapper] Calling handler with deserialized object: {type(obj).__name__}")
                handler(obj)
                processed += 1
                print(f"[KafkaConsumerWrapper] Handler completed successfully (processed={processed})")
            except Exception as e:
                print(f"[KafkaConsumerWrapper] ERROR in handler/deserializer: {e}", exc_info=True)
                if on_error:
                    on_error(e)
                    continue
                raise

        return processed

    def close(self) -> None:
        if hasattr(self._consumer, "close"):
            self._consumer.close()



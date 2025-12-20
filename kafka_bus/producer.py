from __future__ import annotations

import importlib
from typing import Any, Optional, Union

from canonical import PaymentEvent
from ingress.mx_receiver import payment_event_to_json_bytes


class KafkaProducerWrapper:
    """
    Simple Kafka producer wrapper.

    Requirement:
    - send(topic, key, value)
    - value is JSON-serialized PaymentEvent

    This wrapper supports either:
    - confluent-kafka (preferred for many production setups)
    - kafka-python

    If you already have an underlying producer instance, pass it via `producer=`.
    Otherwise, provide `bootstrap_servers` to auto-create one (if a supported
    library is installed).
    """

    def __init__(
        self,
        *,
        producer: Optional[Any] = None,
        bootstrap_servers: Optional[Union[str, list[str]]] = None,
        client_config: Optional[dict[str, Any]] = None,
    ) -> None:
        self._producer = producer or self._create_producer(
            bootstrap_servers=bootstrap_servers, client_config=client_config or {}
        )

    def _create_producer(
        self, *, bootstrap_servers: Optional[Union[str, list[str]]], client_config: dict[str, Any]
    ) -> Any:
        if not bootstrap_servers:
            raise ValueError("Provide either `producer=` or `bootstrap_servers=`.")

        # 1) Try confluent-kafka
        try:
            ck = importlib.import_module("confluent_kafka")
            conf: dict[str, Any] = {"bootstrap.servers": bootstrap_servers}
            conf.update(client_config)
            return ck.Producer(conf)
        except ModuleNotFoundError:
            pass

        # 2) Try kafka-python
        try:
            kp = importlib.import_module("kafka")
            # kafka-python uses bootstrap_servers, not bootstrap.servers
            conf = {"bootstrap_servers": bootstrap_servers}
            conf.update(client_config)
            return kp.KafkaProducer(**conf)
        except ModuleNotFoundError as e:
            raise RuntimeError(
                "No supported Kafka client installed. Install `confluent-kafka` or `kafka-python`."
            ) from e

    def send(self, topic: str, key: Optional[Union[str, bytes]], value: PaymentEvent) -> None:
        """
        Send a PaymentEvent to Kafka.

        - topic: Kafka topic
        - key: str/bytes/None
        - value: PaymentEvent (will be JSON-serialized)
        """

        if not isinstance(value, PaymentEvent):
            raise TypeError("value must be a canonical PaymentEvent.")

        payload = payment_event_to_json_bytes(value)
        self.send_bytes(topic, key, payload)

    def send_bytes(self, topic: str, key: Optional[Union[str, bytes]], value: bytes) -> None:
        """
        Send raw bytes to Kafka.
        """

        if not isinstance(value, (bytes, bytearray)):
            raise TypeError("value must be bytes.")

        key_bytes: Optional[bytes]
        if key is None:
            key_bytes = None
        elif isinstance(key, bytes):
            key_bytes = key
        else:
            key_bytes = key.encode("utf-8")

        print(f"[KafkaProducerWrapper] Sending message to topic='{topic}', key={key_bytes[:20] if key_bytes else None}, value_len={len(value)}")

        p = self._producer

        # kafka-python
        if hasattr(p, "send"):
            future = p.send(topic, value=bytes(value), key=key_bytes)
            print(f"[KafkaProducerWrapper] Message sent via kafka-python (future={future})")
            return

        # confluent-kafka
        if hasattr(p, "produce"):
            p.produce(topic, value=bytes(value), key=key_bytes)
            print(f"[KafkaProducerWrapper] Message queued via confluent-kafka")
            return

        # fallback for custom producer interface
        if hasattr(p, "publish"):
            p.publish(topic, value=bytes(value), key=key_bytes)
            print(f"[KafkaProducerWrapper] Message sent via custom publish()")
            return

        raise TypeError("Unsupported underlying producer: expected .send(), .produce(), or .publish().")

    def flush(self, timeout: Optional[float] = None) -> None:
        """
        Flush buffered messages if the underlying producer supports it.
        """

        if hasattr(self._producer, "flush"):
            if timeout is None:
                self._producer.flush()
            else:
                self._producer.flush(timeout)



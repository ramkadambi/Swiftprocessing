"""
Mock Kafka producer and consumer for testing without real Kafka.

These mocks simulate Kafka behavior by storing messages in memory,
allowing tests to verify message flow without requiring a running Kafka instance.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable, Optional, Union


class MockKafkaProducer:
    """Mock Kafka producer that stores messages in memory."""

    def __init__(self) -> None:
        self._messages: dict[str, list[tuple[Union[str, bytes], bytes]]] = defaultdict(list)
        self._flushed = False

    def send(self, topic: str, key: Union[str, bytes], value: Any) -> None:
        """Send a message (value is a PaymentEvent object, will be serialized by caller)."""
        # Store the object as-is (caller handles serialization)
        # This allows tests to access the PaymentEvent object directly
        self._messages[topic].append((key, value))

    def send_bytes(self, topic: str, key: Union[str, bytes], value: bytes) -> None:
        """Send a bytes message."""
        self._messages[topic].append((key, value))

    def flush(self) -> None:
        """Mark as flushed."""
        self._flushed = True

    def get_messages(self, topic: str) -> list[tuple[Union[str, bytes], Union[bytes, Any]]]:
        """Get all messages sent to a topic (returns bytes or PaymentEvent objects)."""
        return self._messages[topic].copy()

    def clear(self) -> None:
        """Clear all messages."""
        self._messages.clear()
        self._flushed = False

    def has_messages(self, topic: str) -> bool:
        """Check if any messages were sent to a topic."""
        return len(self._messages[topic]) > 0


class MockKafkaConsumer:
    """Mock Kafka consumer that reads from in-memory message queues."""

    def __init__(self) -> None:
        self._topics: list[str] = []
        self._messages: dict[str, list[tuple[Union[str, bytes], bytes]]] = defaultdict(list)
        self._consumed: dict[str, int] = defaultdict(int)

    def subscribe(self, topics: list[str]) -> None:
        """Subscribe to topics."""
        self._topics = topics

    def add_message(self, topic: str, key: Union[str, bytes], value: bytes) -> None:
        """Add a message to the consumer's queue (simulating Kafka message)."""
        self._messages[topic].append((key, value))

    def run(
        self,
        handler: Callable[[Any], Any],
        *,
        deserializer: Optional[Callable[[bytes], Any]] = None,
        poll_timeout_s: float = 1.0,
        max_messages: Optional[int] = None,
        on_error: Optional[Callable[[Exception], Any]] = None,
    ) -> int:
        """
        Run the consumer, processing messages from subscribed topics.
        
        Args:
            handler: Function to call with deserialized message
            deserializer: Function to deserialize bytes to object
            poll_timeout_s: Not used in mock (for compatibility)
            max_messages: Maximum number of messages to process
            on_error: Error handler callback
        
        Returns:
            Number of messages processed
        """
        processed = 0
        messages_to_process: list[tuple[str, Union[str, bytes], bytes]] = []

        # Collect all messages from subscribed topics
        for topic in self._topics:
            for key, value in self._messages[topic]:
                messages_to_process.append((topic, key, value))

        # Process messages
        for topic, key, value in messages_to_process:
            if max_messages and processed >= max_messages:
                break

            try:
                # Deserialize if deserializer provided
                if deserializer:
                    obj = deserializer(value)
                else:
                    obj = value

                # Call handler
                handler(obj)
                processed += 1
                self._consumed[topic] += 1

            except Exception as e:
                if on_error:
                    on_error(e)
                else:
                    raise

        return processed

    def close(self) -> None:
        """Close the consumer (no-op in mock)."""
        pass

    def clear(self) -> None:
        """Clear all messages."""
        self._messages.clear()
        self._consumed.clear()

    def get_consumed_count(self, topic: str) -> int:
        """Get number of messages consumed from a topic."""
        return self._consumed[topic]


class MockKafkaProducerWrapper:
    """Wrapper that matches KafkaProducerWrapper interface."""

    def __init__(self, *, bootstrap_servers: Optional[str] = None, **kwargs: Any) -> None:
        self._producer = MockKafkaProducer()
        self._bootstrap_servers = bootstrap_servers

    def send(self, topic: str, key: Union[str, bytes], value: Any) -> None:
        """Send a message (PaymentEvent object)."""
        self._producer.send(topic, key, value)

    def send_bytes(self, topic: str, key: Union[str, bytes], value: bytes) -> None:
        """Send a bytes message."""
        self._producer.send_bytes(topic, key, value)

    def flush(self) -> None:
        """Flush messages."""
        self._producer.flush()

    @property
    def producer(self) -> MockKafkaProducer:
        """Get the underlying mock producer."""
        return self._producer


class MockKafkaConsumerWrapper:
    """Wrapper that matches KafkaConsumerWrapper interface."""

    def __init__(
        self,
        *,
        bootstrap_servers: Optional[str] = None,
        group_id: Optional[str] = None,
        topics: Optional[list[str]] = None,
        auto_offset_reset: str = "earliest",
        **kwargs: Any,
    ) -> None:
        self._consumer = MockKafkaConsumer()
        self._bootstrap_servers = bootstrap_servers
        self._group_id = group_id
        if topics:
            self._consumer.subscribe(topics)

    def subscribe(self, topics: list[str]) -> None:
        """Subscribe to topics."""
        self._consumer.subscribe(topics)

    def run(
        self,
        handler: Callable[[Any], Any],
        *,
        deserializer: Optional[Callable[[bytes], Any]] = None,
        poll_timeout_s: float = 1.0,
        max_messages: Optional[int] = None,
        on_error: Optional[Callable[[Exception], Any]] = None,
    ) -> int:
        """Run the consumer."""
        return self._consumer.run(
            handler,
            deserializer=deserializer,
            poll_timeout_s=poll_timeout_s,
            max_messages=max_messages,
            on_error=on_error,
        )

    def close(self) -> None:
        """Close the consumer."""
        self._consumer.close()

    def add_message(self, topic: str, key: Union[str, bytes], value: bytes) -> None:
        """Add a message to the consumer's queue (for testing)."""
        self._consumer.add_message(topic, key, value)

    @property
    def consumer(self) -> MockKafkaConsumer:
        """Get the underlying mock consumer."""
        return self._consumer

